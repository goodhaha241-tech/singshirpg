"""User-raised guild boss training, storage, and Discord UI.

The active 70-turn run and account unlocks live in ``life_data`` so they use
the normal revision/rollback protection.  Completed bosses and battle records
are indexed in MySQL because they must be listed globally.
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiomysql
import discord
from discord.ui import Button, Modal, Select, TextInput

from cards import Dice, SkillCard
from data_manager import (
    add_guild_contribution,
    get_db_pool,
    get_user_data,
    mutate_user_data,
)
from monsters import Monster


KST = ZoneInfo("Asia/Seoul")
PURE_HOPE_ITEM = "순수한 희망"
START_MONEY = 300_000
START_PT = 3_000
START_HOPE = 2
MAX_TURNS = 70
MAX_SUPPORT_UPGRADE = 4
SUPPORT_UPGRADE_COSTS = (1, 2, 3, 4)
GROWTH_KEYS = ("hp", "attack", "defense", "mental", "tactics")
GROWTH_LABELS = {
    "hp": "HP",
    "attack": "공격",
    "defense": "방어",
    "mental": "정신",
    "tactics": "전술/SP",
}
MOOD_MULTIPLIERS = (0.90, 0.95, 1.00, 1.05, 1.10)

TRAINING_ACTIONS: dict[str, dict[str, Any]] = {
    "hp": {"label": "HP 훈련", "energy": -18, "gains": {"hp": 350, "sp": 8}},
    "attack": {"label": "공격 훈련", "energy": -20, "gains": {"attack": 3, "hp": 60, "sp": 8}},
    "defense": {"label": "방어 훈련", "energy": -18, "gains": {"defense": 3, "mental": 60, "sp": 8}},
    "mental": {"label": "정신 훈련", "energy": -16, "gains": {"mental": 220, "defense": 1, "sp": 8}},
    "tactics": {"label": "전술 훈련", "energy": -12, "gains": {"sp": 35, "mental": 50}},
    "rest": {"label": "휴식", "energy": 50},
    "outing": {"label": "외출", "energy": 20, "mood": 1},
    "infirmary": {"label": "치료", "energy": 15},
}

EVALUATION_TURNS = {
    14: ("Bronze", 40, 2_300),
    28: ("Silver", 70, 2_900),
    42: ("Gold", 100, 3_500),
    56: ("Platinum", 140, 4_100),
    70: ("Diamond", 200, 7_470),
}

SPECIAL_SUPPORTS = {
    "어즈렉": ("earthreg_faith", 250, "굳건한 믿음"),
    "루우데": ("luude_imprint", 300, "상냥한 악몽"),
    "영산": ("youngsan_gold", 350, "황금의 흐름"),
    "카이안": ("kaian_time", 400, "시간가속"),
    "샤일라": ("shayla_light", 400, "강한 빛"),
    "센쇼": ("sensho_star", 450, "별똥별의 가호"),
}

GENERAL_PASSIVES = {
    "hp_regen": ("생명 재생", 120, "매 턴 HP 2% 회복"),
    "mental_regen": ("정신 재생", 100, "매 턴 정신력 3% 회복"),
    "low_hp_attack": ("배수진", 160, "HP 50% 이하 공격 주사위 +20%"),
    "first_guard": ("초격 방어", 150, "전투 중 첫 피해 20% 감소"),
    "status_extend": ("오염 증폭", 180, "부여하는 상태이상 지속시간 +1"),
    "last_recovery": ("최후의 회복", 200, "최초 HP 25% 이하에서 HP·정신력 10% 회복"),
}

INNATE_PASSIVES = {
    "predator": ("포식자", 250_000, 250, "적 처치 시 턴당 1회 HP 5% 회복"),
    "regeneration_core": ("재생 코어", 300_000, 300, "5턴마다 HP·정신력 8% 회복"),
    "opening_pressure": ("개막 압박", 350_000, 350, "1~3턴 공격·반격 주사위 +15%"),
    "indomitable_shell": ("불굴의 외피", 400_000, 400, "최초 HP 30% 이하에서 정화·피해 감소"),
    "anomaly_circuit": ("변칙 회로", 450_000, 450, "턴 종료 시 25% 확률로 쿨다운 1 감소"),
    "domination": ("지배", 500_000, 500, "생존 공격자마다 공격 주사위 +3%"),
}

IMMUNITIES = {"bleed": ("출혈", 160), "paralysis": ("마비", 180), "stun": ("기절", 240)}
RESISTANCE_COSTS = {25: 40, 50: 100, 75: 190}
DICE_TIERS = {
    (5, 9): 25,
    (8, 14): 45,
    (12, 20): 75,
    (18, 30): 120,
}
EFFECT_COSTS = {
    "bleed": 30,
    "paralysis": 40,
    "stun": 80,
    "lifesteal": 90,
    "destroy": 120,
}
COOLDOWN_MULTIPLIERS = {1: 1.5, 2: 1.0, 3: 0.9, 4: 0.8}

GRADE_THRESHOLDS = (
    ("UF", 11_000),
    ("UG", 9_000),
    ("SS", 7_500),
    ("S", 6_000),
    ("A", 4_500),
    ("B", 3_500),
    ("C", 0),
)
SALE_REWARDS = {
    "C": {"money": 50_000, "pt": 500, "hope": 0},
    "B": {"money": 100_000, "pt": 1_000, "hope": 0},
    "A": {"money": 300_000, "pt": 3_000, "hope": 1},
    "S": {"money": 1_000_000, "pt": 10_000, "hope": 3},
    "SS": {"money": 3_000_000, "pt": 30_000, "hope": 6},
    "UG": {"money": 6_000_000, "pt": 60_000, "hope": 10},
    "UF": {"money": 12_000_000, "pt": 120_000, "hope": 20},
}


class BossTrainingError(ValueError):
    pass


def ensure_boss_training_data(user_data: dict[str, Any]) -> dict[str, Any]:
    life = user_data.setdefault("life_data", {})
    state = life.setdefault("boss_training", {})
    state.setdefault("active_run", None)
    state.setdefault("support_fragments", {})
    state.setdefault("support_upgrades", {})
    state.setdefault("public_support", None)
    state.setdefault("shop_unlocks", {})
    state.setdefault("rewarded_battle_ids", [])
    state.setdefault("sold_boss_ids", [])
    # Bound only the idempotency ledger, never the user's fragment inventory.
    state["rewarded_battle_ids"] = list(state["rewarded_battle_ids"])[-500:]
    state["sold_boss_ids"] = list(state["sold_boss_ids"])[-500:]
    return state


def support_character_names() -> list[str]:
    """Return the canonical, gacha-eligible support roster."""
    names: set[str] = {"카이안"}
    try:
        from recruitment import RECRUIT_REGISTRY

        for entry in RECRUIT_REGISTRY.values():
            name = str(entry.get("name") or entry.get("char_data", {}).get("name") or "").strip()
            if name:
                names.add(name)
    except Exception:
        names.update(SPECIAL_SUPPORTS)
    return sorted(names)


def add_support_fragment(
    user_data: dict[str, Any],
    character_name: str | None = None,
    rng: random.Random | Any = random,
) -> dict[str, Any]:
    roster = support_character_names()
    if not roster:
        raise BossTrainingError("서포트 캐릭터 풀이 비어 있습니다.")
    name = character_name or rng.choice(roster)
    if name not in roster:
        raise BossTrainingError(f"알 수 없는 서포트 캐릭터입니다: {name}")
    state = ensure_boss_training_data(user_data)
    fragments = state["support_fragments"]
    fragments[name] = int(fragments.get(name, 0)) + 1
    return {
        "kind": "support_fragment",
        "name": name,
        "count": 1,
        "total": int(fragments[name]),
        "upgrade": int(state["support_upgrades"].get(name, 0)),
    }


def upgrade_support(user_data: dict[str, Any], character_name: str) -> int:
    state = ensure_boss_training_data(user_data)
    level = int(state["support_upgrades"].get(character_name, 0))
    if level >= MAX_SUPPORT_UPGRADE:
        raise BossTrainingError("이미 4강인 서포트입니다. 남은 조각은 그대로 보관됩니다.")
    needed = SUPPORT_UPGRADE_COSTS[level]
    owned = int(state["support_fragments"].get(character_name, 0))
    if owned < needed:
        raise BossTrainingError(f"조각이 부족합니다. 필요 {needed}개 / 보유 {owned}개")
    state["support_fragments"][character_name] = owned - needed
    state["support_upgrades"][character_name] = level + 1
    return level + 1


def validate_growth_rates(rates: dict[str, int]) -> dict[str, int]:
    normalized = {key: int(rates.get(key, 0)) for key in GROWTH_KEYS}
    if any(value < 0 or value > 30 or value % 5 for value in normalized.values()):
        raise BossTrainingError("성장률은 항목별 0~30%, 5% 단위여야 합니다.")
    if sum(normalized.values()) != 30:
        raise BossTrainingError("다섯 성장률의 합은 정확히 30%여야 합니다.")
    return normalized


def _support_identity(name: str) -> str | None:
    for special_name in SPECIAL_SUPPORTS:
        if special_name in name:
            return special_name
    return None


def _support_specialty(character: dict[str, Any]) -> str:
    values = {
        "hp": float(character.get("hp", 0) or 0) / 5_000,
        "mental": float(character.get("max_mental", 0) or 0) / 2_000,
        "attack": float(character.get("attack", 0) or 0) / 25,
        "defense": float(character.get("defense", 0) or 0) / 25,
    }
    best = max(values, key=values.get) if any(values.values()) else "tactics"
    return best


def _snapshot_support(character: dict[str, Any], upgrade: int, owner_id: str) -> dict[str, Any]:
    return {
        "name": str(character.get("name", "이름 없음")),
        "owner_id": str(owner_id),
        "level": max(0, int(character.get("level", 0) or 0)),
        "upgrade": max(0, min(MAX_SUPPORT_UPGRADE, int(upgrade))),
        "specialty": _support_specialty(character),
        "bond": 0,
        "event_stage": 0,
    }


def _roll_support_placements(run: dict[str, Any], rng: random.Random | Any = random) -> None:
    placements: dict[str, list[int]] = {key: [] for key in GROWTH_KEYS}
    for index, support in enumerate(run.get("supports", [])):
        specialty = support.get("specialty", "tactics")
        action = specialty if rng.random() < 0.5 else rng.choice(GROWTH_KEYS)
        placements[action].append(index)
    run["support_placements"] = placements


def create_training_run(
    user_data: dict[str, Any],
    boss_name: str,
    growth_rates: dict[str, int],
    own_support_indices: list[int],
    guild_support: dict[str, Any] | None,
    *,
    base_tokens: dict[str, int] | None = None,
    innate_passive: str | None = None,
    rng: random.Random | Any = random,
) -> dict[str, Any]:
    state = ensure_boss_training_data(user_data)
    if state.get("active_run"):
        raise BossTrainingError("이미 진행 중인 보스 육성이 있습니다.")
    name = str(boss_name).strip()
    if not 2 <= len(name) <= 30:
        raise BossTrainingError("보스 이름은 2~30자로 입력해주세요.")
    growth = validate_growth_rates(growth_rates)
    if not state["shop_unlocks"].get("growth_license"):
        growth = {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5}

    characters = user_data.get("characters", [])
    indices = list(dict.fromkeys(int(value) for value in own_support_indices))
    if len(indices) != 3 or any(index < 0 or index >= len(characters) for index in indices):
        raise BossTrainingError("본인 서포트 캐릭터를 서로 다르게 3명 선택해주세요.")
    if not guild_support:
        raise BossTrainingError("길드 공개 서포트 1명을 선택해주세요.")

    inventory = user_data.setdefault("inventory", {})
    if int(inventory.get(PURE_HOPE_ITEM, 0)) < START_HOPE:
        raise BossTrainingError(f"순수한 희망이 부족합니다. 필요: {START_HOPE}개")
    if int(user_data.get("money", 0)) < START_MONEY:
        raise BossTrainingError(f"돈이 부족합니다. 필요: {START_MONEY:,}원")
    if int(user_data.get("pt", 0)) < START_PT:
        raise BossTrainingError(f"PT가 부족합니다. 필요: {START_PT:,} PT")

    tokens = {key: max(0, int((base_tokens or {}).get(key, 0))) for key in ("hp", "mental", "attack", "defense")}
    if not state["shop_unlocks"].get("base_stat_license"):
        tokens = {key: 0 for key in tokens}
    if (
        state["shop_unlocks"].get("base_stat_license")
        and sum(tokens.values()) != 5
    ) or any(value > 3 for value in tokens.values()):
        raise BossTrainingError("기본 스탯 토큰은 총 5개, 한 스탯 최대 3개입니다.")
    if innate_passive and not state["shop_unlocks"].get(innate_passive):
        raise BossTrainingError("구매하지 않은 고유 패시브입니다.")

    inventory[PURE_HOPE_ITEM] = int(inventory.get(PURE_HOPE_ITEM, 0)) - START_HOPE
    user_data["money"] = int(user_data.get("money", 0)) - START_MONEY
    user_data["pt"] = int(user_data.get("pt", 0)) - START_PT

    supports = [
        _snapshot_support(
            characters[index],
            state["support_upgrades"].get(str(characters[index].get("name", "")), 0),
            str(user_data.get("user_id", "self")),
        )
        for index in indices
    ]
    supports.append(deepcopy(guild_support))
    run = {
        "run_id": uuid.uuid4().hex,
        "name": name,
        "phase": "training",
        "turn": 0,
        "hp": 5_000 + tokens["hp"] * 1_000,
        "mental": 2_000 + tokens["mental"] * 1_000,
        "attack": 25 + tokens["attack"] * 2,
        "defense": 25 + tokens["defense"] * 2,
        "energy": 100,
        "mood": 3,
        "sp": 0,
        "spent_sp": 0,
        "injured": False,
        "growth_rates": growth,
        "base_tokens": tokens,
        "facility_successes": {key: 0 for key in GROWTH_KEYS},
        "facility_levels": {key: 1 for key in GROWTH_KEYS},
        "supports": supports,
        "pending_event_choice": None,
        "inheritance_candidates": [],
        "evaluation_results": [],
        "innate_passive": innate_passive,
        "build": {
            "skills": [],
            "immunity": None,
            "resistances": {},
            "passives": [],
            "inheritance": None,
            "ai_style": "balanced",
            "publish_scope": "guild",
        },
        "history": [],
        "created_at": datetime.now(KST).isoformat(),
    }
    _roll_support_placements(run, rng)
    state["active_run"] = run
    return run


def _support_event_chance(support: dict[str, Any]) -> float:
    bond = int(support.get("bond", 0))
    base = 0.20 if bond < 40 else 0.30 if bond < 80 else 0.45
    return min(1.0, base + int(support.get("upgrade", 0)) * 0.03)


def _apply_growth(
    run: dict[str, Any],
    action: str,
    gains: dict[str, int],
    support_bonus: float,
) -> dict[str, int]:
    mood = MOOD_MULTIPLIERS[max(1, min(5, int(run["mood"]))) - 1]
    facility = 1.0 + (max(1, int(run["facility_levels"].get(action, 1))) - 1) * 0.10
    growth = 1.0 + int(run["growth_rates"].get(action, 0)) / 100
    injury = 0.75 if run.get("injured") else 1.0
    multiplier = mood * facility * growth * injury * (1.0 + min(0.60, support_bonus))
    applied: dict[str, int] = {}
    for key, amount in gains.items():
        value = max(1, math.floor(int(amount) * multiplier))
        run[key] = int(run.get(key, 0)) + value
        applied[key] = value
    return applied


def _run_power_score(run: dict[str, Any], build: dict[str, Any] | None = None) -> int:
    build = build or run.get("build", {})
    innate = run.get("innate_passive")
    innate_value = INNATE_PASSIVES.get(innate, ("", 0, 0, ""))[2] if innate else 0
    return int(
        int(run.get("hp", 0)) / 20
        + int(run.get("mental", 0)) / 20
        + int(run.get("attack", 0)) * 25
        + int(run.get("defense", 0)) * 25
        + int(run.get("spent_sp", 0))
        + sum(250 for result in run.get("evaluation_results", []) if result.get("win"))
        + innate_value
    )


def _simulate_evaluation(
    run: dict[str, Any],
    turn: int,
    rng: random.Random | Any = random,
) -> dict[str, Any]:
    rank, reward, target = EVALUATION_TURNS[turn]
    # A compact 20-round AI mock: offense and effective durability contribute,
    # with a small seeded combat variance.  It is persisted immediately so
    # reconnecting cannot reroll the result.
    offense = int(run["attack"]) * 25 + int(run["sp"]) * 0.35
    durability = int(run["hp"]) / 20 + int(run["mental"]) / 20 + int(run["defense"]) * 25
    mock_score = int(offense + durability + rng.randint(-180, 180))
    win = mock_score >= target
    gained = reward if win else math.floor(reward * 0.40)
    run["sp"] = int(run["sp"]) + gained
    result = {
        "turn": turn,
        "rank": rank,
        "win": win,
        "score": mock_score,
        "target": target,
        "sp": gained,
    }
    run["evaluation_results"].append(result)
    return result


def perform_training_action(
    run: dict[str, Any],
    action: str,
    rng: random.Random | Any = random,
) -> dict[str, Any]:
    if run.get("phase") != "training" or int(run.get("turn", 0)) >= MAX_TURNS:
        raise BossTrainingError("훈련 단계가 아닙니다.")
    if run.get("pending_event_choice"):
        raise BossTrainingError("먼저 서포트 이벤트의 보상을 선택해주세요.")
    if action not in TRAINING_ACTIONS:
        raise BossTrainingError("알 수 없는 훈련 행동입니다.")

    spec = TRAINING_ACTIONS[action]
    before_energy = int(run["energy"])
    result: dict[str, Any] = {"action": action, "label": spec["label"], "success": True, "logs": []}
    run["turn"] = int(run["turn"]) + 1

    if action in GROWTH_KEYS:
        run["energy"] = max(0, min(100, before_energy + int(spec["energy"])))
        failure_rate = min(60, max(0, 50 - before_energy) + (15 if run.get("injured") else 0))
        result["failure_rate"] = failure_rate
        if rng.randint(1, 100) <= failure_rate:
            result["success"] = False
            run["mood"] = max(1, int(run["mood"]) - 1)
            injured_now = rng.random() < 0.35
            if injured_now:
                run["injured"] = True
            result["logs"].append(f"훈련 실패 · 기분 -1" + (" · 부상 발생" if injured_now else ""))
        else:
            placed = list(run.get("support_placements", {}).get(action, []))
            support_bonus = 0.0
            for index in placed:
                support = run["supports"][index]
                bond = int(support.get("bond", 0))
                support_bonus += min(0.10, int(support.get("level", 0)) * 0.002)
                support_bonus += int(support.get("upgrade", 0)) * 0.05
                if bond >= 80:
                    support_bonus += 0.20
                support["bond"] = min(100, bond + 7)
            applied = _apply_growth(run, action, spec["gains"], support_bonus)
            result["gains"] = applied
            run["facility_successes"][action] = int(run["facility_successes"].get(action, 0)) + 1
            run["facility_levels"][action] = min(5, 1 + run["facility_successes"][action] // 4)
            result["supports"] = [run["supports"][index]["name"] for index in placed]

            # One sequential special event at most per turn.
            for index in placed:
                support = run["supports"][index]
                identity = _support_identity(str(support.get("name", "")))
                stage = int(support.get("event_stage", 0))
                if not identity or stage >= 3 or rng.random() >= _support_event_chance(support):
                    continue
                stage += 1
                support["event_stage"] = stage
                if stage == 1:
                    support["bond"] = min(100, int(support["bond"]) + 10)
                    extra = {
                        key: max(1, math.floor(value * 0.50))
                        for key, value in spec["gains"].items()
                    }
                    for key, value in extra.items():
                        run[key] = int(run.get(key, 0)) + value
                    result["logs"].append(f"{identity} 연속 이벤트 1단계 · 유대 +10 · 추가 성장 {extra}")
                elif stage == 2:
                    run["pending_event_choice"] = {"support_index": index, "name": identity}
                    result["logs"].append(f"{identity} 연속 이벤트 2단계 · 보상을 선택하세요.")
                else:
                    if identity not in run["inheritance_candidates"]:
                        run["inheritance_candidates"].append(identity)
                    run["sp"] = int(run["sp"]) + 60
                    result["logs"].append(f"{identity} 연속 이벤트 완주 · 계승 후보 해금 · SP +60")
                break
    elif action == "rest":
        run["energy"] = min(100, before_energy + 50)
        if rng.random() < 0.25:
            run["mood"] = min(5, int(run["mood"]) + 1)
            result["logs"].append("충분히 쉬어 기분 +1")
    elif action == "outing":
        run["energy"] = min(100, before_energy + 20)
        run["mood"] = min(5, int(run["mood"]) + 1)
    elif action == "infirmary":
        run["energy"] = min(100, before_energy + 15)
        run["injured"] = False

    evaluation = None
    if int(run["turn"]) in EVALUATION_TURNS:
        evaluation = _simulate_evaluation(run, int(run["turn"]), rng)
        result["evaluation"] = evaluation
        result["logs"].append(
            f"{evaluation['rank']} 평가전 {'승리' if evaluation['win'] else '패배'} · SP +{evaluation['sp']}"
        )
    if int(run["turn"]) >= MAX_TURNS:
        run["phase"] = "build"
    else:
        _roll_support_placements(run, rng)

    run["history"] = (list(run.get("history", [])) + [{
        "turn": int(run["turn"]),
        "action": action,
        "success": bool(result["success"]),
        "logs": list(result["logs"]),
    }])[-20:]
    return result


def resolve_support_event_choice(run: dict[str, Any], choice: str) -> str:
    pending = run.get("pending_event_choice")
    if not pending:
        raise BossTrainingError("선택 대기 중인 서포트 이벤트가 없습니다.")
    name = pending["name"]
    if choice == "sp":
        run["sp"] = int(run["sp"]) + 40
        text = f"{name} 이벤트 · SP +40"
    elif choice == "recovery":
        run["energy"] = min(100, int(run["energy"]) + 25)
        run["mood"] = min(5, int(run["mood"]) + 1)
        text = f"{name} 이벤트 · 체력 +25 · 기분 +1"
    else:
        raise BossTrainingError("알 수 없는 이벤트 선택입니다.")
    run["pending_event_choice"] = None
    return text


def parse_dice_spec(text: str) -> list[dict[str, Any]]:
    dice: list[dict[str, Any]] = []
    aliases = {"공격": "attack", "방어": "defense", "반격": "counter", "회복": "heal", "정신": "mental_heal"}
    pattern = re.compile(r"^\s*([^:]+)\s*:\s*(\d+)\s*-\s*(\d+)\s*$")
    for raw in text.split(","):
        match = pattern.match(raw)
        if not match:
            raise BossTrainingError("주사위는 `공격:5-9, 방어:8-14` 형식으로 입력해주세요.")
        action = aliases.get(match.group(1).strip().lower(), match.group(1).strip().lower())
        if action not in {"attack", "defense", "counter", "heal", "mental_heal"}:
            raise BossTrainingError(f"지원하지 않는 주사위 종류입니다: {match.group(1)}")
        low, high = int(match.group(2)), int(match.group(3))
        tier_cost = DICE_TIERS.get((low, high))
        if tier_cost is None:
            raise BossTrainingError("주사위 범위는 5-9, 8-14, 12-20, 18-30 중 하나여야 합니다.")
        dice.append({"type": action, "min": low, "max": high})
    if not 1 <= len(dice) <= 3:
        raise BossTrainingError("스킬 하나에는 주사위가 1~3개 필요합니다.")
    return dice


def normalize_effects(text: str) -> list[str]:
    aliases = {
        "없음": "",
        "출혈": "bleed",
        "마비": "paralysis",
        "기절": "stun",
        "흡혈": "lifesteal",
        "파괴": "destroy",
    }
    effects: list[str] = []
    for raw in text.split(","):
        value = aliases.get(raw.strip(), raw.strip().lower())
        if not value:
            continue
        if value not in EFFECT_COSTS:
            raise BossTrainingError(f"지원하지 않는 부가효과입니다: {raw.strip()}")
        if value not in effects:
            effects.append(value)
    if len(effects) > 2:
        raise BossTrainingError("부가효과는 최대 2개입니다.")
    return effects


def skill_sp_cost(skill: dict[str, Any]) -> int:
    dice = skill.get("dice", [])
    if not 1 <= len(dice) <= 3:
        raise BossTrainingError("스킬 하나에는 주사위가 1~3개 필요합니다.")
    base = 0
    for item in dice:
        low, high = int(item["min"]), int(item["max"])
        if (low, high) not in DICE_TIERS:
            raise BossTrainingError("허용되지 않은 주사위 범위입니다.")
        base += DICE_TIERS[(low, high)]
        if item["type"] == "counter":
            base += 10
    effects = list(dict.fromkeys(skill.get("effects", [])))
    if len(effects) > 2 or any(effect not in EFFECT_COSTS for effect in effects):
        raise BossTrainingError("부가효과가 올바르지 않습니다.")
    base += sum(EFFECT_COSTS[effect] for effect in effects)
    cooldown = int(skill.get("cooldown", 2))
    if cooldown not in COOLDOWN_MULTIPLIERS:
        raise BossTrainingError("쿨다운은 1~4턴이어야 합니다.")
    if skill.get("is_aoe") and cooldown < 2:
        raise BossTrainingError("광역 스킬의 최소 쿨다운은 2턴입니다.")
    total = math.ceil(base * COOLDOWN_MULTIPLIERS[cooldown])
    if skill.get("is_aoe"):
        total *= 2
    return total


def _build_sp_cost(run: dict[str, Any], build: dict[str, Any]) -> int:
    total = sum(skill_sp_cost(skill) for skill in build.get("skills", []))
    immunity = build.get("immunity")
    if immunity:
        if immunity not in IMMUNITIES:
            raise BossTrainingError("알 수 없는 완전 면역입니다.")
        total += IMMUNITIES[immunity][1]
    resistances = build.get("resistances", {})
    for status, value in resistances.items():
        value = int(value)
        if status not in IMMUNITIES or value not in RESISTANCE_COSTS:
            raise BossTrainingError("상태이상 저항 설정이 올바르지 않습니다.")
        if status == immunity:
            raise BossTrainingError("완전 면역과 같은 상태이상에 저항을 구매할 수 없습니다.")
        total += RESISTANCE_COSTS[value]
    passives = list(dict.fromkeys(build.get("passives", [])))
    if len(passives) > 3 or any(key not in GENERAL_PASSIVES for key in passives):
        raise BossTrainingError("일반 패시브는 최대 3개입니다.")
    total += sum(GENERAL_PASSIVES[key][1] for key in passives)
    inheritance = build.get("inheritance")
    if inheritance:
        if inheritance not in run.get("inheritance_candidates", []):
            raise BossTrainingError("해금하지 않은 계승 능력입니다.")
        total += SPECIAL_SUPPORTS[inheritance][1]
    return total


def _require_build_budget(run: dict[str, Any]) -> int:
    cost = _build_sp_cost(run, run.get("build", {}))
    if cost > int(run.get("sp", 0)):
        raise BossTrainingError(f"SP가 부족합니다. 필요 {cost} / 보유 {int(run.get('sp', 0))}")
    return cost


def _default_skills() -> list[dict[str, Any]]:
    return [
        {
            "name": f"기본 기술 {index + 1}",
            "dice": [{"type": "attack" if index % 2 == 0 else "defense", "min": 5, "max": 9}],
            "effects": [],
            "cooldown": 2,
            "is_aoe": False,
            "free": True,
        }
        for index in range(5)
    ]


def grade_for_score(score: int) -> str:
    for grade, threshold in GRADE_THRESHOLDS:
        if int(score) >= threshold:
            return grade
    return "C"


def finalize_training_run(run: dict[str, Any]) -> dict[str, Any]:
    if run.get("phase") != "build" or int(run.get("turn", 0)) < MAX_TURNS:
        raise BossTrainingError("70턴 육성을 마친 뒤에만 보스를 완성할 수 있습니다.")
    build = deepcopy(run.get("build", {}))
    skills = list(build.get("skills", []))
    if len(skills) > 5:
        raise BossTrainingError("스킬은 최대 5개입니다.")
    if sum(1 for skill in skills if skill.get("is_aoe")) > 2:
        raise BossTrainingError("광역 스킬은 최대 2개입니다.")
    paid_cost = _build_sp_cost(run, build)
    if paid_cost > int(run.get("sp", 0)):
        raise BossTrainingError(f"SP가 부족합니다. 필요 {paid_cost} / 보유 {int(run.get('sp', 0))}")
    defaults = _default_skills()
    while len(skills) < 5:
        skills.append(defaults[len(skills)])
    build["skills"] = skills
    run["spent_sp"] = paid_cost
    score = _run_power_score(run, build)
    boss_id = uuid.uuid4().hex
    return {
        "boss_id": boss_id,
        "owner_id": None,
        "name": run["name"],
        "hp": int(run["hp"]),
        "mental": int(run["mental"]),
        "attack": int(run["attack"]),
        "defense": int(run["defense"]),
        "build": build,
        "innate_passive": run.get("innate_passive"),
        "spent_sp": paid_cost,
        "power_score": score,
        "grade": grade_for_score(score),
        "evaluation_results": deepcopy(run.get("evaluation_results", [])),
        "supports": deepcopy(run.get("supports", [])),
        "created_at": datetime.now(KST).isoformat(),
    }


def _effect_code(effect: str) -> str | None:
    return {
        "bleed": "bleed_1_on_win",
        "paralysis": "paralysis_1_on_win",
        "stun": "stun_1_prob_20",
        "lifesteal": "absorb_hp_25",
        "destroy": "destroy_next_on_hit",
    }.get(effect)


class BossSkillCard(SkillCard):
    def __init__(self, spec: dict[str, Any], inheritance: str | None = None):
        self.spec = deepcopy(spec)
        is_aoe = bool(spec.get("is_aoe"))
        effects = list(spec.get("effects", []))
        effect_codes = [_effect_code(effect) for effect in effects if _effect_code(effect)]
        dice_list = []
        forced_extras = []
        for index, item in enumerate(spec.get("dice", [])):
            low, high = int(item["min"]), int(item["max"])
            if is_aoe and item["type"] == "attack":
                low, high = max(1, math.floor(low * 0.75)), max(1, math.floor(high * 0.75))
            effect = effect_codes[index] if index < len(effect_codes) else None
            if inheritance == "카이안" and item["type"] == "counter":
                if effect:
                    forced_extras.append(effect)
                effect = "time_accel"
            dice_list.append(Dice(item["type"], low, high, effect=effect))
        super().__init__(str(spec.get("name", "보스 스킬")), dice_list, is_aoe=is_aoe)
        self.cooldown = int(spec.get("cooldown", 2))
        self.unassigned_effects = effect_codes[len(dice_list):] + forced_extras

    def use_card(self, attack_stat=0, defense_stat=0, current_mental=0, **kwargs):
        results = super().use_card(attack_stat, defense_stat, current_mental, **kwargs)
        if results and self.unassigned_effects:
            results[0]["extra_effects"] = list(self.unassigned_effects)
        return results

    @property
    def description(self):
        effects = {
            "bleed": "출혈 1",
            "paralysis": "마비 1",
            "stun": "기절 20%",
            "lifesteal": "흡혈 25%",
            "destroy": "다음 주사위 파괴",
        }
        suffix = ", ".join(effects[key] for key in self.spec.get("effects", []) if key in effects)
        details = f"\n쿨다운 {self.cooldown}턴" + (f" · {suffix}" if suffix else "")
        return super().description + details


class UserBossMonster(Monster):
    """Monster-compatible runtime object for one completed user boss."""

    def __init__(self, record: dict[str, Any]):
        data = record.get("boss_data", record)
        build = data.get("build", {})
        self.record = record
        self.skill_cards = [
            BossSkillCard(spec, build.get("inheritance"))
            for spec in build.get("skills", _default_skills())
        ]
        super().__init__(
            data.get("name", record.get("boss_name", "육성 보스")),
            int(data.get("hp", 5_000)),
            int(data.get("attack", 25)),
            int(data.get("defense", 25)),
            pattern_type=build.get("ai_style", "balanced"),
            card_deck=[],
        )
        self.max_mental = int(data.get("mental", 2_000))
        self.current_mental = self.max_mental
        self.card_deck = [card.name for card in self.skill_cards]
        self.status_immunity = build.get("immunity")
        self.status_resistances = {
            key: int(value) for key, value in build.get("resistances", {}).items()
        }
        self.general_passives = set(build.get("passives", []))
        self.innate_passive = data.get("innate_passive")
        self.inheritance = build.get("inheritance")
        special = SPECIAL_SUPPORTS.get(self.inheritance or "", (None,))[0]
        self.equipped_artifact = None
        self.equipped_engraved_artifact = {"special": special} if special else None
        self.defense_rate = 0
        self.runtime_cooldowns = {}
        self._first_damage_used = False
        self._last_recovery_used = False
        self._shell_used = False
        self._turn_kills = 0
        self._special_target_used = False

    def available_cards(self) -> list[BossSkillCard]:
        result = [
            card for card in self.skill_cards
            if int(self.runtime_cooldowns.get(f"skill:{card.name}", 0)) <= 0
        ]
        return result or list(self.skill_cards)

    def decide_action(self):
        cards = self.available_cards()
        weights = []
        for card in cards:
            primary = card.dice_list[0].action_type if card.dice_list else "attack"
            if self.pattern_type == "aggressive":
                weight = 70 if primary == "attack" else 15
            elif self.pattern_type == "defensive":
                weight = 70 if primary in {"defense", "counter", "heal", "mental_heal"} else 15
            else:
                weight = 33
            weights.append(weight)
        return random.choices(cards, weights=weights, k=1)[0]

    def commit_card(self, card: BossSkillCard) -> None:
        for key in list(self.runtime_cooldowns):
            if key.startswith("skill:"):
                self.runtime_cooldowns[key] = max(0, int(self.runtime_cooldowns[key]) - 1)
        self.runtime_cooldowns[f"skill:{card.name}"] = max(0, int(card.cooldown) - 1)
        self._special_target_used = False
        offensive = any(dice.action_type in {"attack", "counter"} for dice in card.dice_list)
        if self.inheritance == "영산" and offensive:
            count = int(self.runtime_cooldowns.get("youngsan_skill_count", 0)) + 1
            self.runtime_cooldowns["youngsan_skill_count"] = count
            self.runtime_cooldowns["youngsan_boost"] = count % 3 == 0
            self.runtime_cooldowns["youngsan_nuke_pending"] = count % 7 == 0
        if self.inheritance == "샤일라":
            self.runtime_cooldowns["shayla_destroy_this_turn"] = bool(
                self.runtime_cooldowns.pop("shayla_prime_next", False)
            )
            if any(dice.action_type == "mental_heal" for dice in card.dice_list):
                self.runtime_cooldowns["shayla_prime_next"] = True
        if self.inheritance == "센쇼" and any(
            dice.action_type == "defense" for dice in card.dice_list
        ):
            miracle = random.randint(1, 7) == 1
            self.runtime_cooldowns["sensho_miracle"] = miracle
            self.runtime_cooldowns["sensho_guard_boost"] = not miracle
            if miracle:
                hp = min(self.max_hp - self.current_hp, max(1, int(self.max_hp * 0.15)))
                mental = min(
                    self.max_mental - self.current_mental,
                    max(1, int(self.max_mental * 0.15)),
                )
                self.current_hp += hp
                self.current_mental += mental

    def on_turn_start(self, turn: int, alive_attackers: int) -> str:
        logs = []
        self._turn_kills = 0
        if "hp_regen" in self.general_passives:
            healed = min(self.max_hp - self.current_hp, max(1, int(self.max_hp * 0.02)))
            self.current_hp += healed
            if healed:
                logs.append(f"생명 재생 HP +{healed}")
        if "mental_regen" in self.general_passives:
            healed = min(self.max_mental - self.current_mental, max(1, int(self.max_mental * 0.03)))
            self.current_mental += healed
            if healed:
                logs.append(f"정신 재생 +{healed}")
        if self.innate_passive == "regeneration_core" and turn % 5 == 0:
            hp = min(self.max_hp - self.current_hp, max(1, int(self.max_hp * 0.08)))
            mental = min(self.max_mental - self.current_mental, max(1, int(self.max_mental * 0.08)))
            self.current_hp += hp
            self.current_mental += mental
            logs.append(f"재생 코어 HP +{hp}, 정신 +{mental}")
        self.runtime_cooldowns["alive_attackers"] = alive_attackers
        self.runtime_cooldowns["boss_turn"] = turn
        return " · ".join(logs)

    def modify_outgoing_dice(self, dice_results: list[dict[str, Any]], turn: int, alive_attackers: int) -> None:
        multiplier = 1.0
        if self.inheritance == "카이안":
            from battle_engine import apply_time_accel_power

            apply_time_accel_power(
                dice_results, int(self.runtime_cooldowns.get("kaian_stack", 0))
            )
        if "low_hp_attack" in self.general_passives and self.current_hp <= self.max_hp * 0.5:
            multiplier += 0.20
        if self.innate_passive == "opening_pressure" and turn <= 3:
            multiplier += 0.15
        if self.innate_passive == "domination":
            multiplier += min(0.12, max(0, alive_attackers) * 0.03)
        if self.inheritance == "영산" and self.runtime_cooldowns.get("youngsan_boost"):
            multiplier += 0.25
        if multiplier != 1.0:
            for dice in dice_results:
                if dice.get("type") in {"attack", "counter"}:
                    dice["value"] = max(0, math.floor(int(dice["value"]) * multiplier))
        if self.inheritance == "센쇼" and self.runtime_cooldowns.get("sensho_guard_boost"):
            for dice in dice_results:
                if dice.get("type") == "defense":
                    dice["value"] = max(0, math.floor(int(dice["value"]) * 1.5))

    def modify_opponent_dice(self, dice_results: list[dict[str, Any]], target) -> str:
        logs = []
        if self.inheritance == "샤일라" and self.runtime_cooldowns.get("shayla_destroy_this_turn"):
            valid = [index for index, dice in enumerate(dice_results) if dice.get("type") != "none"]
            count = min(len(valid), random.randint(1, 3))
            for index in random.sample(valid, count) if count else []:
                dice_results[index] = {"type": "none", "value": 0, "effect": None}
            stack = int(self.runtime_cooldowns.get("shayla_destroy_stack", 0)) + count
            if stack >= 10:
                stack = 0
                for index in range(len(dice_results)):
                    dice_results[index] = {"type": "none", "value": 0, "effect": None}
                logs.append("강한 빛 누적 10회로 상대 주사위 완전 무력화")
            elif count:
                logs.append(f"강한 빛으로 상대 주사위 {count}개 파괴 ({stack}/10)")
            self.runtime_cooldowns["shayla_destroy_stack"] = stack
        if not self._special_target_used and self.runtime_cooldowns.get("youngsan_nuke_pending"):
            self._special_target_used = True
            damage = max(1, math.floor(self.attack * 1.5))
            target.current_hp = max(0, target.current_hp - damage)
            logs.append(f"황금의 일격 고정 피해 {damage}")
        if not self._special_target_used and self.runtime_cooldowns.get("sensho_miracle"):
            self._special_target_used = True
            damage = max(1, math.floor(self.current_mental * 0.10))
            target.current_hp = max(0, target.current_hp - damage)
            logs.append(f"별똥별의 기적 고정 피해 {damage}")
        return " · ".join(logs)

    def on_attacker_defeated(self) -> str:
        if self.innate_passive != "predator" or self._turn_kills > 0:
            return ""
        self._turn_kills += 1
        healed = min(self.max_hp - self.current_hp, max(1, int(self.max_hp * 0.05)))
        self.current_hp += healed
        return f"포식자 HP +{healed}" if healed else ""

    def modify_incoming_damage(self, damage: int) -> int:
        damage = max(0, int(damage))
        if "first_guard" in self.general_passives and not self._first_damage_used and damage > 0:
            self._first_damage_used = True
            damage = math.floor(damage * 0.80)
        if self.runtime_cooldowns.get("shell_reduction_turns", 0) > 0:
            damage = math.floor(damage * 0.75)
        return damage

    def on_turn_end(self) -> str:
        logs = []
        if (
            "last_recovery" in self.general_passives
            and not self._last_recovery_used
            and self.current_hp <= self.max_hp * 0.25
        ):
            self._last_recovery_used = True
            hp = min(self.max_hp - self.current_hp, max(1, int(self.max_hp * 0.10)))
            mental = min(self.max_mental - self.current_mental, max(1, int(self.max_mental * 0.10)))
            self.current_hp += hp
            self.current_mental += mental
            logs.append(f"최후의 회복 HP +{hp}, 정신 +{mental}")
        if (
            self.innate_passive == "indomitable_shell"
            and not self._shell_used
            and self.current_hp <= self.max_hp * 0.30
        ):
            self._shell_used = True
            for key in self.status_effects:
                self.status_effects[key] = 0
            self.runtime_cooldowns["shell_reduction_turns"] = 2
            logs.append("불굴의 외피 발동")
        elif self.runtime_cooldowns.get("shell_reduction_turns", 0) > 0:
            self.runtime_cooldowns["shell_reduction_turns"] -= 1
        if self.innate_passive == "anomaly_circuit" and random.random() < 0.25:
            for key in list(self.runtime_cooldowns):
                if key.startswith("skill:"):
                    self.runtime_cooldowns[key] = max(0, int(self.runtime_cooldowns[key]) - 1)
            logs.append("변칙 회로로 쿨다운 감소")
        return " · ".join(logs)


def _row_to_dict(row: Any, columns: tuple[str, ...] = ()) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return {key: row[index] for index, key in enumerate(columns) if index < len(row)}


def _decode_boss_row(row: Any) -> dict[str, Any]:
    data = _row_to_dict(
        row,
        (
            "boss_id", "owner_id", "guild_id", "boss_name", "grade", "power_score",
            "boss_data", "is_published", "publish_scope", "active_battles",
            "weekly_key", "weekly_elo", "all_time_best_elo", "created_at", "updated_at",
        ),
    )
    raw = data.get("boss_data")
    if isinstance(raw, str):
        data["boss_data"] = json.loads(raw)
    return data


def weekly_key(now: datetime | None = None) -> str:
    current = (now or datetime.now(KST)).astimezone(KST)
    monday = (current - timedelta(days=current.weekday())).date()
    return monday.isoformat()


async def _reset_stale_weekly_ratings(cur) -> None:
    await cur.execute(
        """UPDATE user_bosses SET weekly_key=%s,weekly_elo=1500
           WHERE weekly_key IS NULL OR weekly_key<>%s""",
        (weekly_key(), weekly_key()),
    )


async def save_completed_boss(owner_id: int | str, guild_id: int, boss: dict[str, Any]) -> None:
    boss["owner_id"] = str(owner_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO user_bosses
                   (boss_id,owner_id,guild_id,boss_name,grade,power_score,boss_data,
                    weekly_key,weekly_elo,all_time_best_elo)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1500,1500)
                   ON DUPLICATE KEY UPDATE boss_data=VALUES(boss_data),
                    boss_name=VALUES(boss_name),grade=VALUES(grade),power_score=VALUES(power_score)""",
                (
                    boss["boss_id"], str(owner_id), int(guild_id), boss["name"], boss["grade"],
                    int(boss["power_score"]), json.dumps(boss, ensure_ascii=False), weekly_key(),
                ),
            )
            await conn.commit()


async def list_owned_bosses(owner_id: int | str) -> list[dict[str, Any]]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await _reset_stale_weekly_ratings(cur)
            await cur.execute(
                "SELECT * FROM user_bosses WHERE owner_id=%s ORDER BY created_at DESC",
                (str(owner_id),),
            )
            return [_decode_boss_row(row) for row in await cur.fetchall()]


async def get_boss_record(boss_id: str) -> dict[str, Any] | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM user_bosses WHERE boss_id=%s", (boss_id,))
            row = await cur.fetchone()
            return _decode_boss_row(row) if row else None


async def list_published_bosses(
    guild_id: int,
    scope: str = "guild",
    limit: int = 25,
) -> list[dict[str, Any]]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await _reset_stale_weekly_ratings(cur)
            if scope == "world":
                await cur.execute(
                    """SELECT * FROM user_bosses
                       WHERE is_published=1 AND publish_scope='world'
                       ORDER BY weekly_elo DESC,power_score DESC LIMIT %s""",
                    (int(limit),),
                )
            else:
                await cur.execute(
                    """SELECT * FROM user_bosses WHERE is_published=1 AND guild_id=%s
                       ORDER BY weekly_elo DESC,power_score DESC LIMIT %s""",
                    (int(guild_id), int(limit)),
                )
            return [_decode_boss_row(row) for row in await cur.fetchall()]


async def get_boss_rankings(limit: int = 10) -> dict[str, list[dict[str, Any]]]:
    pool = await get_db_pool()
    queries = {
        "weekly": "weekly_elo DESC,power_score DESC",
        "all_time": "all_time_best_elo DESC,power_score DESC",
        "power": "power_score DESC,all_time_best_elo DESC",
    }
    result: dict[str, list[dict[str, Any]]] = {}
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await _reset_stale_weekly_ratings(cur)
            for key, ordering in queries.items():
                await cur.execute(
                    f"""SELECT * FROM user_bosses
                        WHERE is_published=1 AND publish_scope='world'
                        ORDER BY {ordering} LIMIT %s""",
                    (int(limit),),
                )
                result[key] = [_decode_boss_row(row) for row in await cur.fetchall()]
    return result


async def publish_boss(owner_id: int | str, boss_id: str, scope: str | None) -> None:
    if scope not in {None, "guild", "world"}:
        raise BossTrainingError("공개 범위는 길드 또는 월드여야 합니다.")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await conn.begin()
            await cur.execute(
                "SELECT owner_id,active_battles FROM user_bosses WHERE boss_id=%s FOR UPDATE",
                (boss_id,),
            )
            row = await cur.fetchone()
            if not row or str(row[0]) != str(owner_id):
                await conn.rollback()
                raise BossTrainingError("본인의 보스를 찾지 못했습니다.")
            if scope:
                await cur.execute(
                    "UPDATE user_bosses SET is_published=0 WHERE owner_id=%s",
                    (str(owner_id),),
                )
                await cur.execute(
                    """UPDATE user_bosses SET is_published=1,publish_scope=%s
                       WHERE boss_id=%s""",
                    (scope, boss_id),
                )
            else:
                await cur.execute(
                    "UPDATE user_bosses SET is_published=0 WHERE boss_id=%s",
                    (boss_id,),
                )
            await conn.commit()


async def sell_boss(owner_id: int | str, boss_id: str, typed_name: str, user_name: str) -> dict[str, int]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM user_bosses WHERE boss_id=%s", (boss_id,))
            row = await cur.fetchone()
            if not row or str(row["owner_id"]) != str(owner_id):
                raise BossTrainingError("본인의 보스를 찾지 못했습니다.")
            if str(row["boss_name"]) != str(typed_name).strip():
                raise BossTrainingError("입력한 보스 이름이 일치하지 않습니다.")
            if int(row["active_battles"] or 0) > 0:
                raise BossTrainingError("진행 중인 레이드가 있어 판매할 수 없습니다.")
            reward = dict(SALE_REWARDS[str(row["grade"])])

    def grant(latest):
        state = ensure_boss_training_data(latest)
        if boss_id in state["sold_boss_ids"]:
            return
        latest["money"] = int(latest.get("money", 0)) + reward["money"]
        latest["pt"] = int(latest.get("pt", 0)) + reward["pt"]
        if reward["hope"]:
            inv = latest.setdefault("inventory", {})
            inv[PURE_HOPE_ITEM] = int(inv.get(PURE_HOPE_ITEM, 0)) + reward["hope"]
        state["sold_boss_ids"].append(boss_id)

    await mutate_user_data(owner_id, grant, user_name)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM user_bosses WHERE boss_id=%s AND owner_id=%s AND active_battles=0",
                (boss_id, str(owner_id)),
            )
            await conn.commit()
            if cur.rowcount != 1:
                raise BossTrainingError(
                    "판매 보상은 안전하게 기록했지만 보스 삭제를 마치지 못했습니다. 다시 시도해주세요."
                )
    return reward


async def begin_boss_battle(boss_id: str) -> str:
    battle_id = uuid.uuid4().hex
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE user_bosses SET active_battles=active_battles+1 WHERE boss_id=%s",
                (boss_id,),
            )
            if cur.rowcount != 1:
                raise BossTrainingError("공개 보스를 찾지 못했습니다.")
            await conn.commit()
    return battle_id


async def finish_boss_battle(
    record: dict[str, Any],
    battle_id: str,
    challenger_id: int | str,
    attackers_won: bool,
    owner_name: str | None = None,
) -> dict[str, Any]:
    boss_id = record["boss_id"]
    key = weekly_key()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await conn.begin()
            await cur.execute("SELECT * FROM user_bosses WHERE boss_id=%s FOR UPDATE", (boss_id,))
            row = await cur.fetchone()
            if not row:
                await conn.rollback()
                raise BossTrainingError("전투 결과를 기록할 보스가 없습니다.")
            current = 1500 if row.get("weekly_key") != key else int(row.get("weekly_elo", 1500))
            # Boss expectation against a 1500 challenger, K=32.
            expected = 1.0 / (1.0 + 10 ** ((1500 - current) / 400))
            actual = 0.0 if attackers_won else 1.0
            updated = max(0, round(current + 32 * (actual - expected)))
            best = max(int(row.get("all_time_best_elo", 1500)), updated)
            await cur.execute(
                """INSERT IGNORE INTO user_boss_battles
                   (battle_id,boss_id,challenger_id,result,weekly_key,elo_before,elo_after,battle_data)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    battle_id, boss_id, str(challenger_id),
                    "attacker_win" if attackers_won else "boss_win",
                    key, current, updated,
                    json.dumps({"attackers_won": attackers_won}, ensure_ascii=False),
                ),
            )
            inserted = cur.rowcount == 1
            if inserted:
                await cur.execute(
                    """UPDATE user_bosses SET weekly_key=%s,weekly_elo=%s,
                       all_time_best_elo=%s,active_battles=GREATEST(0,active_battles-1)
                       WHERE boss_id=%s""",
                    (key, updated, best, boss_id),
                )
            await conn.commit()
    reward = {"money": 1_000 if attackers_won else 2_500, "pt": 200 if attackers_won else 500,
              "contribution": 20 if attackers_won else 50}
    owner_id = str(record["owner_id"])
    granted = {"value": False}

    def grant(latest):
        state = ensure_boss_training_data(latest)
        ledger = state["rewarded_battle_ids"]
        if battle_id in ledger or not inserted:
            return
        latest["money"] = int(latest.get("money", 0)) + reward["money"]
        latest["pt"] = int(latest.get("pt", 0)) + reward["pt"]
        ledger.append(battle_id)
        granted["value"] = True

    await mutate_user_data(owner_id, grant, owner_name)
    if granted["value"]:
        await add_guild_contribution(
            owner_id, reward["contribution"], "user_boss_defense",
            record.get("boss_name", "육성 보스"), owner_name,
        )
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE user_boss_battles SET owner_rewarded=1 WHERE battle_id=%s",
                    (battle_id,),
                )
                await conn.commit()
    return {"elo_before": current, "elo_after": updated, "owner_reward": reward, "granted": granted["value"]}


async def get_public_supports(guild_id: int, exclude_user_id: int | str) -> list[dict[str, Any]]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT gm.user_id,uld.data,u.characters
                   FROM guild_members gm
                   JOIN user_life_data uld ON uld.user_id=gm.user_id
                   JOIN users u ON u.user_id=gm.user_id
                   WHERE gm.guild_id=%s AND gm.user_id<>%s""",
                (int(guild_id), str(exclude_user_id)),
            )
            result = []
            for row in await cur.fetchall():
                life = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
                public = (life or {}).get("boss_training", {}).get("public_support")
                if not isinstance(public, dict):
                    continue
                chars = json.loads(row["characters"]) if isinstance(row["characters"], str) else row["characters"]
                char = next(
                    (item for item in (chars or []) if item.get("name") == public.get("name")),
                    public.get("character"),
                )
                if not isinstance(char, dict):
                    continue
                upgrades = (life or {}).get("boss_training", {}).get("support_upgrades", {})
                result.append(_snapshot_support(
                    char, int(upgrades.get(char.get("name"), 0)), str(row["user_id"])
                ))
            return result


async def buy_training_shop_item(
    user_id: int | str,
    user_name: str,
    item_key: str,
) -> str:
    prices = {"base_stat_license": 100_000, "growth_license": 200_000}
    prices.update({key: data[1] for key, data in INNATE_PASSIVES.items()})
    if item_key not in prices:
        raise BossTrainingError("알 수 없는 상점 상품입니다.")
    outcome = {"message": ""}

    def buy(latest):
        state = ensure_boss_training_data(latest)
        if state["shop_unlocks"].get(item_key):
            raise BossTrainingError("이미 영구 해금한 상품입니다.")
        price = prices[item_key]
        if int(latest.get("pt", 0)) < price:
            raise BossTrainingError(f"PT가 부족합니다. 필요: {price:,} PT")
        latest["pt"] = int(latest.get("pt", 0)) - price
        state["shop_unlocks"][item_key] = True
        outcome["message"] = f"{price:,} PT를 사용해 영구 해금했습니다."

    await mutate_user_data(user_id, buy, user_name)
    return outcome["message"]


# ---------------------------------------------------------------------------
# Discord UI
# ---------------------------------------------------------------------------


async def _reply_error(interaction: discord.Interaction, error: Exception) -> None:
    message = f"❌ {error}"
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class _OwnerView(discord.ui.View):
    def __init__(self, author, *, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 보스 육성 메뉴만 조작할 수 있습니다.", ephemeral=True)
        return False


class BossTrainingHubView(_OwnerView):
    def __init__(self, author, guild_info, parent_view=None):
        super().__init__(author, timeout=240)
        self.guild_info = guild_info
        self.parent_view = parent_view

    async def get_embed(self, message: str | None = None) -> discord.Embed:
        data = await get_user_data(self.author.id, self.author.display_name)
        state = ensure_boss_training_data(data)
        run = state.get("active_run")
        bosses = await list_owned_bosses(self.author.id)
        published = next((row for row in bosses if row.get("is_published")), None)
        embed = discord.Embed(
            title="👑 유저 보스 육성",
            description=message or (
                "70턴 동안 보스를 육성하고 스킬·면역·패시브를 설계한 뒤 "
                "길드 또는 월드 레이드에 공개합니다."
            ),
            color=discord.Color.dark_purple(),
        )
        if run:
            phase = "최종 빌드" if run.get("phase") == "build" else "육성"
            embed.add_field(
                name="진행 중",
                value=(
                    f"**{run['name']}** · {phase} · {int(run.get('turn', 0))}/70턴\n"
                    f"HP {int(run['hp']):,} · 정신 {int(run['mental']):,} · "
                    f"공격 {int(run['attack'])} · 방어 {int(run['defense'])} · SP {int(run['sp'])}"
                ),
                inline=False,
            )
        else:
            inv = data.get("inventory", {})
            embed.add_field(
                name="새 육성 비용",
                value=(
                    f"순수한 희망 {START_HOPE}개 · {START_MONEY:,}원 · {START_PT:,} PT\n"
                    f"현재 보유: 희망 {int(inv.get(PURE_HOPE_ITEM, 0))} · "
                    f"{int(data.get('money', 0)):,}원 · {int(data.get('pt', 0)):,} PT"
                ),
                inline=False,
            )
        embed.add_field(
            name="완성 보스",
            value=(
                f"보관 **{len(bosses)}체** · 공개 "
                + (f"**{published['boss_name']}** ({published['publish_scope']})" if published else "없음")
            ),
            inline=False,
        )
        return embed

    @discord.ui.button(label="🌱 시작/계속", style=discord.ButtonStyle.success, row=0)
    async def open_run(self, interaction: discord.Interaction, button: Button):
        data = await get_user_data(self.author.id, self.author.display_name)
        run = ensure_boss_training_data(data).get("active_run")
        if run:
            view = BossBuildView(self.author, self.guild_info) if run.get("phase") == "build" else BossTrainingRunView(self.author, self.guild_info)
            return await interaction.response.edit_message(embed=await view.get_embed(), view=view)
        view = BossSetupView(self.author, self.guild_info)
        await view.setup(data)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="🤝 서포트", style=discord.ButtonStyle.primary, row=0)
    async def open_supports(self, interaction: discord.Interaction, button: Button):
        data = await get_user_data(self.author.id, self.author.display_name)
        view = BossSupportView(self.author, self.guild_info, data)
        view.rebuild()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="📚 보스 보관함", style=discord.ButtonStyle.secondary, row=0)
    async def open_archive(self, interaction: discord.Interaction, button: Button):
        view = BossArchiveView(self.author, self.guild_info)
        await view.setup()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="⚔️ 도전", style=discord.ButtonStyle.danger, row=0)
    async def open_challenges(self, interaction: discord.Interaction, button: Button):
        view = BossChallengeView(self.author, self.guild_info)
        await view.setup()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="🛒 육성 상점", style=discord.ButtonStyle.primary, row=1)
    async def open_shop(self, interaction: discord.Interaction, button: Button):
        data = await get_user_data(self.author.id, self.author.display_name)
        view = BossTrainingShopView(self.author, self.guild_info, data)
        view.rebuild()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="🏆 순위", style=discord.ButtonStyle.secondary, row=1)
    async def open_ranking(self, interaction: discord.Interaction, button: Button):
        rankings = await get_boss_rankings(10)
        embed = discord.Embed(
            title=f"🏆 유저 보스 순위 · {weekly_key()}",
            description="주간 방어 Elo, 역대 최고 Elo, 정적 평가점을 서로 분리해 집계합니다.",
            color=discord.Color.gold(),
        )
        for title, key, score_key, label in (
            ("주간 방어 Elo", "weekly", "weekly_elo", "Elo"),
            ("역대 최고 Elo", "all_time", "all_time_best_elo", "최고"),
            ("정적 평가점", "power", "power_score", "평가"),
        ):
            lines = [
                f"{index}. **{row['boss_name']}** [{row['grade']}] · "
                f"{label} {int(row[score_key]):,}"
                for index, row in enumerate(rankings[key], 1)
            ]
            embed.add_field(name=title, value="\n".join(lines) or "기록 없음", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="수련장으로", style=discord.ButtonStyle.secondary, row=1)
    async def go_back(self, interaction: discord.Interaction, button: Button):
        if self.parent_view:
            return await interaction.response.edit_message(
                embed=await self.parent_view.get_embed(), view=self.parent_view
            )
        from guild import GuildTrainingView

        view = GuildTrainingView(self.author, self.guild_info)
        await interaction.response.edit_message(embed=await view.get_embed(), view=view)


class BossSetupModal(Modal, title="보스 육성 설정"):
    boss_name = TextInput(label="보스 이름", min_length=2, max_length=30)
    growth = TextInput(
        label="성장률 HP,공격,방어,정신,전술 (합 30)",
        default="10,5,5,5,5",
        max_length=30,
    )
    base_tokens = TextInput(
        label="기본 토큰 HP,정신,공격,방어 (합 5)",
        default="2,1,1,1",
        max_length=20,
        required=False,
    )

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        try:
            growth_values = [int(value.strip()) for value in self.growth.value.split(",")]
            token_values = [int(value.strip()) for value in (self.base_tokens.value or "0,0,0,0").split(",")]
            if len(growth_values) != 5 or len(token_values) != 4:
                raise BossTrainingError("성장률은 5개, 기본 토큰은 4개 숫자를 쉼표로 구분해주세요.")
            self.parent.boss_name = self.boss_name.value.strip()
            self.parent.growth_rates = dict(zip(GROWTH_KEYS, growth_values))
            self.parent.base_tokens = dict(zip(("hp", "mental", "attack", "defense"), token_values))
            validate_growth_rates(self.parent.growth_rates)
            state = ensure_boss_training_data(self.parent.user_data)
            required_total = 5 if state["shop_unlocks"].get("base_stat_license") else 0
            if (
                required_total and sum(token_values) != required_total
            ) or any(value < 0 or value > 3 for value in token_values):
                raise BossTrainingError("설정권 사용 시 기본 토큰 5개를 모두 배분하고 항목별 0~3개로 설정하세요.")
            await interaction.response.edit_message(embed=self.parent.get_embed("설정을 저장했습니다."), view=self.parent)
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossSetupView(_OwnerView):
    def __init__(self, author, guild_info):
        super().__init__(author, timeout=300)
        self.guild_info = guild_info
        self.user_data: dict[str, Any] = {}
        self.guild_supports: list[dict[str, Any]] = []
        self.own_indices: list[int] = []
        self.guild_index: int | None = None
        self.boss_name = ""
        self.growth_rates = {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5}
        self.base_tokens = {key: 0 for key in ("hp", "mental", "attack", "defense")}
        self.innate_passive: str | None = None

    async def setup(self, user_data):
        self.user_data = user_data
        self.guild_supports = await get_public_supports(self.guild_info["guild_id"], self.author.id)
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        characters = self.user_data.get("characters", [])
        if characters:
            own = Select(
                placeholder="본인 서포트 3명 선택",
                min_values=min(3, len(characters)),
                max_values=min(3, len(characters)),
                options=[
                    discord.SelectOption(label=str(char.get("name", "이름 없음"))[:100], value=str(index))
                    for index, char in enumerate(characters[:25])
                ],
                row=0,
            )

            async def choose_own(interaction):
                self.own_indices = [int(value) for value in interaction.data["values"]]
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            own.callback = choose_own
            self.add_item(own)
        if self.guild_supports:
            borrowed = Select(
                placeholder="길드 공개 서포트 1명 선택",
                options=[
                    discord.SelectOption(
                        label=f"{support['name']} (+{support['upgrade']}강)"[:100],
                        description=f"특기 {GROWTH_LABELS.get(support['specialty'], support['specialty'])}",
                        value=str(index),
                    )
                    for index, support in enumerate(self.guild_supports[:25])
                ],
                row=1,
            )

            async def choose_borrowed(interaction):
                self.guild_index = int(interaction.data["values"][0])
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            borrowed.callback = choose_borrowed
            self.add_item(borrowed)
        state = ensure_boss_training_data(self.user_data)
        unlocked = [
            (key, data) for key, data in INNATE_PASSIVES.items()
            if state["shop_unlocks"].get(key)
        ]
        if unlocked:
            innate = Select(
                placeholder="고유 패시브 선택 (선택 사항)",
                options=[discord.SelectOption(label="사용 안 함", value="none")] + [
                    discord.SelectOption(label=data[0], value=key, description=data[3][:100])
                    for key, data in unlocked[:24]
                ],
                row=2,
            )

            async def choose_innate(interaction):
                value = interaction.data["values"][0]
                self.innate_passive = None if value == "none" else value
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            innate.callback = choose_innate
            self.add_item(innate)
        configure = Button(label="📝 이름·성장률·기본 스탯", style=discord.ButtonStyle.primary, row=3)
        configure.callback = lambda interaction: interaction.response.send_modal(BossSetupModal(self))
        self.add_item(configure)
        start = Button(label="🌱 70턴 육성 시작", style=discord.ButtonStyle.success, row=3)
        start.callback = self.start
        self.add_item(start)
        back = Button(label="뒤로", style=discord.ButtonStyle.secondary, row=4)
        back.callback = self.back
        self.add_item(back)

    def get_embed(self, message: str | None = None) -> discord.Embed:
        state = ensure_boss_training_data(self.user_data)
        own_names = [
            self.user_data["characters"][index].get("name", "이름 없음")
            for index in self.own_indices if index < len(self.user_data.get("characters", []))
        ]
        borrowed = self.guild_supports[self.guild_index]["name"] if self.guild_index is not None else "미선택"
        growth_text = " · ".join(f"{GROWTH_LABELS[key]} +{value}%" for key, value in self.growth_rates.items())
        embed = discord.Embed(
            title="🌱 새 보스 육성 설정",
            description=message or "서포트와 성장 설정을 확정하면 비용이 차감되고 1턴부터 시작합니다.",
            color=discord.Color.green(),
        )
        embed.add_field(name="이름", value=self.boss_name or "미설정", inline=False)
        embed.add_field(name="서포트", value=f"본인: {', '.join(own_names) or '미선택'}\n길드: {borrowed}", inline=False)
        embed.add_field(
            name="성장률",
            value=growth_text + ("" if state["shop_unlocks"].get("growth_license") else "\n설정권 미보유: 기본 배분 적용"),
            inline=False,
        )
        embed.add_field(
            name="기본 토큰",
            value=", ".join(f"{key} {value}" for key, value in self.base_tokens.items())
            + ("" if state["shop_unlocks"].get("base_stat_license") else "\n설정권 미보유: 적용 안 됨"),
            inline=False,
        )
        if not self.guild_supports:
            embed.add_field(name="길드 서포트 없음", value="길드원이 서포트를 공개 등록해야 시작할 수 있습니다.", inline=False)
        return embed

    async def start(self, interaction: discord.Interaction):
        try:
            if not self.boss_name:
                raise BossTrainingError("먼저 이름과 성장률을 설정해주세요.")
            if len(self.own_indices) != 3:
                raise BossTrainingError("본인 서포트 3명을 선택해주세요.")
            if self.guild_index is None:
                raise BossTrainingError("길드 공개 서포트 1명을 선택해주세요.")

            def create(latest):
                create_training_run(
                    latest, self.boss_name, self.growth_rates, self.own_indices,
                    self.guild_supports[self.guild_index],
                    base_tokens=self.base_tokens, innate_passive=self.innate_passive,
                )

            await mutate_user_data(self.author.id, create, self.author.display_name)
            view = BossTrainingRunView(self.author, self.guild_info)
            await interaction.response.edit_message(embed=await view.get_embed("육성을 시작했습니다."), view=view)
        except Exception as exc:
            await _reply_error(interaction, exc)

    async def back(self, interaction: discord.Interaction):
        view = BossTrainingHubView(self.author, self.guild_info)
        await interaction.response.edit_message(embed=await view.get_embed(), view=view)


class AbortBossModal(Modal, title="보스 육성 포기"):
    confirmation = TextInput(label="보스 이름을 정확히 입력", max_length=30)

    def __init__(self, parent, expected_name):
        super().__init__()
        self.parent = parent
        self.expected_name = expected_name

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if self.confirmation.value.strip() != self.expected_name:
                raise BossTrainingError("보스 이름이 일치하지 않습니다.")

            def abort(latest):
                state = ensure_boss_training_data(latest)
                run = state.get("active_run")
                if not run or run.get("name") != self.expected_name:
                    raise BossTrainingError("진행 중인 육성 정보가 변경되었습니다.")
                state["active_run"] = None

            await mutate_user_data(self.parent.author.id, abort, self.parent.author.display_name)
            hub = BossTrainingHubView(self.parent.author, self.parent.guild_info)
            await interaction.response.edit_message(embed=await hub.get_embed("육성을 포기했습니다. 시작 비용은 반환되지 않습니다."), view=hub)
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossTrainingRunView(_OwnerView):
    def __init__(self, author, guild_info):
        super().__init__(author, timeout=600)
        self.guild_info = guild_info
        self.rebuild()

    def rebuild(self, run: dict[str, Any] | None = None):
        self.clear_items()
        if run and run.get("pending_event_choice"):
            for label, choice in (("SP +40", "sp"), ("체력 +25·기분 +1", "recovery")):
                button = Button(label=label, style=discord.ButtonStyle.success, row=0)

                async def pick(interaction, selected=choice):
                    await self.choose_event(interaction, selected)

                button.callback = pick
                self.add_item(button)
        else:
            action_buttons = [
                ("❤️ HP", "hp", 0), ("⚔️ 공격", "attack", 0), ("🛡️ 방어", "defense", 0),
                ("🔮 정신", "mental", 0), ("📘 전술", "tactics", 0),
                ("🛌 휴식", "rest", 1), ("🎡 외출", "outing", 1), ("🏥 치료", "infirmary", 1),
            ]
            for label, action, row in action_buttons:
                button = Button(label=label, style=discord.ButtonStyle.primary if row == 0 else discord.ButtonStyle.secondary, row=row)

                async def act(interaction, selected=action):
                    await self.run_action(interaction, selected)

                button.callback = act
                self.add_item(button)
        abort = Button(label="육성 포기", style=discord.ButtonStyle.danger, row=2)

        async def abort_run(interaction):
            data = await get_user_data(self.author.id, self.author.display_name)
            active = ensure_boss_training_data(data).get("active_run")
            if not active:
                return await _reply_error(interaction, BossTrainingError("진행 중인 육성이 없습니다."))
            await interaction.response.send_modal(AbortBossModal(self, active["name"]))

        abort.callback = abort_run
        self.add_item(abort)
        back = Button(label="허브로", style=discord.ButtonStyle.secondary, row=2)

        async def back_to_hub(interaction):
            hub = BossTrainingHubView(self.author, self.guild_info)
            await interaction.response.edit_message(embed=await hub.get_embed(), view=hub)

        back.callback = back_to_hub
        self.add_item(back)

    async def get_embed(self, message: str | None = None) -> discord.Embed:
        data = await get_user_data(self.author.id, self.author.display_name)
        run = ensure_boss_training_data(data).get("active_run")
        if not run:
            return discord.Embed(title="육성 정보 없음", color=discord.Color.red())
        self.rebuild(run)
        energy = max(0, min(100, int(run["energy"])))
        embed = discord.Embed(
            title=f"👑 {run['name']} · {int(run['turn'])}/70턴",
            description=message or (
                f"체력 {'🟩' * (energy // 10)}{'⬜' * (10 - energy // 10)} {energy}/100 · "
                f"기분 {'★' * int(run['mood'])}{'☆' * (5 - int(run['mood']))}"
            ),
            color=discord.Color.dark_purple(),
        )
        embed.add_field(
            name="현재 능력",
            value=(
                f"HP **{int(run['hp']):,}** · 정신 **{int(run['mental']):,}** · "
                f"공격 **{int(run['attack'])}** · 방어 **{int(run['defense'])}** · "
                f"SP **{int(run['sp'])}**" + (" · 🤕 부상" if run.get("injured") else "")
            ),
            inline=False,
        )
        placement_lines = []
        for action in GROWTH_KEYS:
            names = [
                run["supports"][index]["name"]
                for index in run.get("support_placements", {}).get(action, [])
            ]
            if names:
                placement_lines.append(f"**{GROWTH_LABELS[action]}:** {', '.join(names)}")
        embed.add_field(name="이번 턴 서포트", value="\n".join(placement_lines) or "배치 없음", inline=False)
        if run.get("pending_event_choice"):
            embed.add_field(
                name="✨ 연속 이벤트 2단계",
                value=f"{run['pending_event_choice']['name']}의 보상을 선택해주세요.",
                inline=False,
            )
        if run.get("evaluation_results"):
            last = run["evaluation_results"][-1]
            embed.add_field(
                name="최근 평가전",
                value=f"{last['rank']} · {'승리' if last['win'] else '패배'} · SP +{last['sp']}",
                inline=False,
            )
        if run.get("history"):
            latest = run["history"][-1]
            logs = "\n".join(latest.get("logs", []))
            embed.add_field(name="최근 행동", value=f"{latest['turn']}턴 {latest['action']}\n{logs or '완료'}"[:1024], inline=False)
        return embed

    async def run_action(self, interaction: discord.Interaction, action: str):
        try:
            await interaction.response.defer()
            from guild import advance_guild_world_turn

            await advance_guild_world_turn(self.author, 1)
            outcome: dict[str, Any] = {}

            def mutate(latest):
                run = ensure_boss_training_data(latest).get("active_run")
                if not run:
                    raise BossTrainingError("진행 중인 육성이 없습니다.")
                outcome.update(perform_training_action(run, action))

            latest = await mutate_user_data(self.author.id, mutate, self.author.display_name)
            run = ensure_boss_training_data(latest).get("active_run")
            message = " · ".join(outcome.get("logs", [])) or f"{outcome['label']}을 마쳤습니다."
            if run.get("phase") == "build":
                view = BossBuildView(self.author, self.guild_info)
                await interaction.edit_original_response(embed=await view.get_embed("70턴 육성을 마쳤습니다. 최종 빌드를 확정해주세요."), view=view)
            else:
                self.rebuild(run)
                await interaction.edit_original_response(embed=await self.get_embed(message), view=self)
        except Exception as exc:
            await _reply_error(interaction, exc)

    async def choose_event(self, interaction: discord.Interaction, choice: str):
        try:
            result = {"text": ""}

            def mutate(latest):
                run = ensure_boss_training_data(latest).get("active_run")
                if not run:
                    raise BossTrainingError("진행 중인 육성이 없습니다.")
                result["text"] = resolve_support_event_choice(run, choice)

            await mutate_user_data(self.author.id, mutate, self.author.display_name)
            await interaction.response.edit_message(embed=await self.get_embed(result["text"]), view=self)
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossSkillModal(Modal, title="커스텀 보스 스킬"):
    skill_name = TextInput(label="스킬 이름", min_length=1, max_length=30)
    dice = TextInput(label="주사위", placeholder="공격:8-14, 반격:5-9", max_length=100)
    effects = TextInput(label="효과 (최대 2개)", placeholder="출혈, 파괴 또는 없음", required=False, max_length=40)
    cooldown = TextInput(label="쿨다운 1~4", default="2", max_length=1)
    aoe = TextInput(label="광역 여부 (예/아니오)", default="아니오", max_length=5)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        try:
            skill = {
                "name": self.skill_name.value.strip(),
                "dice": parse_dice_spec(self.dice.value),
                "effects": normalize_effects(self.effects.value or ""),
                "cooldown": int(self.cooldown.value),
                "is_aoe": self.aoe.value.strip().lower() in {"예", "yes", "y", "true", "1"},
            }
            cost = skill_sp_cost(skill)

            def add(latest):
                run = ensure_boss_training_data(latest).get("active_run")
                if not run or run.get("phase") != "build":
                    raise BossTrainingError("최종 빌드 단계가 아닙니다.")
                skills = run["build"].setdefault("skills", [])
                if len(skills) >= 5:
                    raise BossTrainingError("이미 스킬 5개를 구성했습니다.")
                if skill["is_aoe"] and sum(1 for item in skills if item.get("is_aoe")) >= 2:
                    raise BossTrainingError("광역 스킬은 최대 2개입니다.")
                skills.append(skill)
                _require_build_budget(run)

            await mutate_user_data(self.parent.author.id, add, self.parent.author.display_name)
            self.parent.rebuild()
            await interaction.response.edit_message(embed=await self.parent.get_embed(f"{skill['name']} 추가 · {cost} SP"), view=self.parent)
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossResistanceModal(Modal, title="상태이상 저항 설정"):
    resistances = TextInput(
        label="bleed,paralysis,stun 각각 0/25/50/75",
        default="bleed:0, paralysis:0, stun:0",
        max_length=80,
    )

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        try:
            parsed: dict[str, int] = {}
            for part in self.resistances.value.split(","):
                key, value = part.split(":", 1)
                key, amount = key.strip().lower(), int(value.strip())
                if key not in IMMUNITIES or amount not in {0, 25, 50, 75}:
                    raise BossTrainingError("저항은 bleed/paralysis/stun에 0/25/50/75만 설정할 수 있습니다.")
                if amount:
                    parsed[key] = amount

            def update(latest):
                run = ensure_boss_training_data(latest).get("active_run")
                if not run or run.get("phase") != "build":
                    raise BossTrainingError("최종 빌드 단계가 아닙니다.")
                run["build"]["resistances"] = parsed
                _require_build_budget(run)

            await mutate_user_data(self.parent.author.id, update, self.parent.author.display_name)
            await interaction.response.edit_message(embed=await self.parent.get_embed("상태이상 저항을 저장했습니다."), view=self.parent)
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossBuildView(_OwnerView):
    def __init__(self, author, guild_info):
        super().__init__(author, timeout=600)
        self.guild_info = guild_info
        self.finalize_lock = asyncio.Lock()
        self.rebuild()

    def rebuild(self, run: dict[str, Any] | None = None):
        self.clear_items()
        immunity = Select(
            placeholder="완전 면역 선택",
            options=[discord.SelectOption(label="면역 없음", value="none")] + [
                discord.SelectOption(label=f"{label} 면역 · {cost} SP", value=key)
                for key, (label, cost) in IMMUNITIES.items()
            ],
            row=0,
        )
        immunity.callback = self.choose_immunity
        self.add_item(immunity)
        passives = Select(
            placeholder="일반 패시브 최대 3개",
            min_values=0,
            max_values=3,
            options=[
                discord.SelectOption(label=f"{label} · {cost} SP", value=key, description=desc[:100])
                for key, (label, cost, desc) in GENERAL_PASSIVES.items()
            ],
            row=1,
        )
        passives.callback = self.choose_passives
        self.add_item(passives)
        candidates = (run or {}).get("inheritance_candidates", [])
        if candidates:
            inheritance = Select(
                placeholder="계승 능력 최대 1개",
                options=[discord.SelectOption(label="계승 안 함", value="none")] + [
                    discord.SelectOption(
                        label=f"{name} · {SPECIAL_SUPPORTS[name][1]} SP",
                        value=name,
                        description=SPECIAL_SUPPORTS[name][2],
                    )
                    for name in candidates[:24]
                ],
                row=2,
            )
            inheritance.callback = self.choose_inheritance
            self.add_item(inheritance)
        add_skill = Button(label="➕ 스킬", style=discord.ButtonStyle.primary, row=3)
        add_skill.callback = lambda interaction: interaction.response.send_modal(BossSkillModal(self))
        self.add_item(add_skill)
        reset = Button(label="🗑️ 스킬 초기화", style=discord.ButtonStyle.secondary, row=3)
        reset.callback = self.reset_skills
        self.add_item(reset)
        resistance = Button(label="🧪 저항", style=discord.ButtonStyle.secondary, row=3)
        resistance.callback = lambda interaction: interaction.response.send_modal(BossResistanceModal(self))
        self.add_item(resistance)
        ai = Button(label="🤖 AI 변경", style=discord.ButtonStyle.secondary, row=3)
        ai.callback = self.rotate_ai
        self.add_item(ai)
        finish = Button(label="✅ 보스 완성", style=discord.ButtonStyle.success, row=4)
        finish.callback = self.finalize
        self.add_item(finish)
        back = Button(label="허브로", style=discord.ButtonStyle.secondary, row=4)
        back.callback = self.back
        self.add_item(back)

    async def _update(self, interaction, updater, message):
        try:
            def mutate(latest):
                run = ensure_boss_training_data(latest).get("active_run")
                if not run or run.get("phase") != "build":
                    raise BossTrainingError("최종 빌드 단계가 아닙니다.")
                updater(run)
                _require_build_budget(run)

            latest = await mutate_user_data(self.author.id, mutate, self.author.display_name)
            run = ensure_boss_training_data(latest).get("active_run")
            self.rebuild(run)
            await interaction.response.edit_message(embed=await self.get_embed(message), view=self)
        except Exception as exc:
            await _reply_error(interaction, exc)

    async def choose_immunity(self, interaction):
        value = interaction.data["values"][0]
        await self._update(
            interaction,
            lambda run: run["build"].update(immunity=None if value == "none" else value),
            "완전 면역을 변경했습니다.",
        )

    async def choose_passives(self, interaction):
        values = list(interaction.data.get("values", []))
        await self._update(interaction, lambda run: run["build"].update(passives=values), "일반 패시브를 변경했습니다.")

    async def choose_inheritance(self, interaction):
        value = interaction.data["values"][0]
        await self._update(
            interaction,
            lambda run: run["build"].update(inheritance=None if value == "none" else value),
            "계승 능력을 변경했습니다.",
        )

    async def reset_skills(self, interaction):
        await self._update(interaction, lambda run: run["build"].update(skills=[]), "커스텀 스킬을 모두 제거했습니다.")

    async def rotate_ai(self, interaction):
        order = ["aggressive", "balanced", "defensive"]

        def rotate(run):
            current = run["build"].get("ai_style", "balanced")
            run["build"]["ai_style"] = order[(order.index(current) + 1) % len(order)]

        await self._update(interaction, rotate, "AI 성향을 변경했습니다.")

    async def get_embed(self, message: str | None = None) -> discord.Embed:
        data = await get_user_data(self.author.id, self.author.display_name)
        run = ensure_boss_training_data(data).get("active_run")
        if not run:
            return discord.Embed(title="최종 빌드 정보 없음", color=discord.Color.red())
        self.rebuild(run)
        build = run["build"]
        try:
            cost = _build_sp_cost(run, build)
            cost_text = f"{cost}/{int(run['sp'])} SP"
        except BossTrainingError as exc:
            cost_text = f"오류: {exc}"
        skills = [
            f"{index}. **{skill['name']}** · {skill_sp_cost(skill)} SP"
            f"{' · 광역' if skill.get('is_aoe') else ''}"
            for index, skill in enumerate(build.get("skills", []), 1)
        ]
        immunity = IMMUNITIES.get(build.get("immunity"), ("없음", 0))[0]
        resistance = ", ".join(f"{IMMUNITIES[key][0]} {value}%" for key, value in build.get("resistances", {}).items()) or "없음"
        passive_names = [GENERAL_PASSIVES[key][0] for key in build.get("passives", [])]
        embed = discord.Embed(
            title=f"🧩 {run['name']} 최종 빌드",
            description=message or "커스텀 스킬이 5개 미만이면 남은 칸은 무료 기본 기술로 채워집니다.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="SP", value=cost_text, inline=False)
        embed.add_field(name="커스텀 스킬", value="\n".join(skills) or "없음 · 기본 기술 5개 사용", inline=False)
        embed.add_field(name="상태이상", value=f"면역: {immunity}\n저항: {resistance}", inline=False)
        embed.add_field(
            name="패시브",
            value=(
                f"일반: {', '.join(passive_names) or '없음'}\n"
                f"계승: {build.get('inheritance') or '없음'}\n"
                f"고유: {INNATE_PASSIVES.get(run.get('innate_passive'), ('없음',))[0]}"
            ),
            inline=False,
        )
        embed.add_field(name="AI", value=build.get("ai_style", "balanced"), inline=True)
        return embed

    async def finalize(self, interaction: discord.Interaction):
        async with self.finalize_lock:
            try:
                await interaction.response.defer()
                latest = await get_user_data(self.author.id, self.author.display_name)
                run = ensure_boss_training_data(latest).get("active_run")
                if not run:
                    raise BossTrainingError("진행 중인 육성이 없습니다.")
                boss = finalize_training_run(run)
                await save_completed_boss(self.author.id, self.guild_info["guild_id"], boss)

                def clear(current):
                    state = ensure_boss_training_data(current)
                    active = state.get("active_run")
                    if active and active.get("run_id") == run.get("run_id"):
                        state["active_run"] = None

                await mutate_user_data(self.author.id, clear, self.author.display_name)
                hub = BossTrainingHubView(self.author, self.guild_info)
                await interaction.edit_original_response(
                    embed=await hub.get_embed(
                        f"🎉 **{boss['name']}** 완성 · {boss['grade']} 등급 · 평가 {boss['power_score']:,}"
                    ),
                    view=hub,
                )
            except Exception as exc:
                await _reply_error(interaction, exc)

    async def back(self, interaction):
        hub = BossTrainingHubView(self.author, self.guild_info)
        await interaction.response.edit_message(embed=await hub.get_embed(), view=hub)


class BossSupportView(_OwnerView):
    def __init__(self, author, guild_info, user_data):
        super().__init__(author, timeout=240)
        self.guild_info = guild_info
        self.user_data = user_data
        self.selected_name: str | None = None
        self.selected_character_index: int | None = None

    def rebuild(self):
        self.clear_items()
        roster = support_character_names()
        support_select = Select(
            placeholder="강화할 서포트 선택",
            options=[
                discord.SelectOption(label=name, value=name)
                for name in roster[:25]
            ],
            row=0,
        )

        async def select_support(interaction):
            self.selected_name = interaction.data["values"][0]
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

        support_select.callback = select_support
        self.add_item(support_select)
        chars = self.user_data.get("characters", [])
        if chars:
            public_select = Select(
                placeholder="공개 등록할 보유 캐릭터",
                options=[
                    discord.SelectOption(label=str(char.get("name", "이름 없음"))[:100], value=str(index))
                    for index, char in enumerate(chars[:25])
                ],
                row=1,
            )

            async def select_public(interaction):
                self.selected_character_index = int(interaction.data["values"][0])
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            public_select.callback = select_public
            self.add_item(public_select)
        upgrade = Button(label="⬆️ 강화", style=discord.ButtonStyle.success, row=2)
        upgrade.callback = self.upgrade
        self.add_item(upgrade)
        register = Button(label="📣 공개 등록", style=discord.ButtonStyle.primary, row=2)
        register.callback = self.register
        self.add_item(register)
        back = Button(label="허브로", style=discord.ButtonStyle.secondary, row=2)
        back.callback = self.back
        self.add_item(back)

    def get_embed(self, message: str | None = None) -> discord.Embed:
        state = ensure_boss_training_data(self.user_data)
        lines = []
        for name in support_character_names():
            fragment = int(state["support_fragments"].get(name, 0))
            level = int(state["support_upgrades"].get(name, 0))
            if fragment or level or name == self.selected_name:
                needed = SUPPORT_UPGRADE_COSTS[level] if level < 4 else 0
                lines.append(f"**{name}** +{level}강 · 조각 {fragment}" + (f"/{needed}" if needed else " · 최고 강화"))
        public = state.get("public_support")
        embed = discord.Embed(
            title="🤝 캐릭터 서포트 관리",
            description=message or (
                "순수한 희망 뽑기에서 5% 확률로 캐릭터별 조각을 얻습니다. "
                "4강 이후 조각도 계속 보관됩니다."
            ),
            color=discord.Color.teal(),
        )
        embed.add_field(name="조각·강화", value="\n".join(lines) or "아직 획득한 조각이 없습니다.", inline=False)
        embed.add_field(
            name="길드 공개 서포트",
            value=(public.get("name") if isinstance(public, dict) else "미등록"),
            inline=False,
        )
        return embed

    async def _reload(self):
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        self.rebuild()

    async def upgrade(self, interaction):
        try:
            if not self.selected_name:
                raise BossTrainingError("강화할 서포트를 선택해주세요.")
            result = {"level": 0}

            def apply(latest):
                result["level"] = upgrade_support(latest, self.selected_name)

            await mutate_user_data(self.author.id, apply, self.author.display_name)
            await self._reload()
            await interaction.response.edit_message(
                embed=self.get_embed(f"{self.selected_name} 서포트가 +{result['level']}강이 되었습니다."),
                view=self,
            )
        except Exception as exc:
            await _reply_error(interaction, exc)

    async def register(self, interaction):
        try:
            if self.selected_character_index is None:
                raise BossTrainingError("공개 등록할 보유 캐릭터를 선택해주세요.")
            index = self.selected_character_index

            def apply(latest):
                chars = latest.get("characters", [])
                if not 0 <= index < len(chars):
                    raise BossTrainingError("캐릭터 정보가 변경되었습니다.")
                ensure_boss_training_data(latest)["public_support"] = {
                    "name": chars[index].get("name", "이름 없음"),
                    "character": deepcopy(chars[index]),
                }

            await mutate_user_data(self.author.id, apply, self.author.display_name)
            await self._reload()
            await interaction.response.edit_message(embed=self.get_embed("길드 공개 서포트를 등록했습니다."), view=self)
        except Exception as exc:
            await _reply_error(interaction, exc)

    async def back(self, interaction):
        hub = BossTrainingHubView(self.author, self.guild_info)
        await interaction.response.edit_message(embed=await hub.get_embed(), view=hub)


class SellBossModal(Modal, title="보스 판매"):
    confirmation = TextInput(label="보스 이름을 정확히 입력", max_length=80)

    def __init__(self, parent, record):
        super().__init__()
        self.parent = parent
        self.record = record

    async def on_submit(self, interaction):
        try:
            reward = await sell_boss(
                self.parent.author.id, self.record["boss_id"],
                self.confirmation.value, self.parent.author.display_name,
            )
            await self.parent.setup()
            await interaction.response.edit_message(
                embed=self.parent.get_embed(
                    f"판매 완료 · {reward['money']:,}원 · {reward['pt']:,} PT"
                    + (f" · 순수한 희망 {reward['hope']}개" if reward["hope"] else "")
                ),
                view=self.parent,
            )
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossArchiveView(_OwnerView):
    def __init__(self, author, guild_info):
        super().__init__(author, timeout=240)
        self.guild_info = guild_info
        self.records: list[dict[str, Any]] = []
        self.selected_id: str | None = None

    async def setup(self):
        self.records = await list_owned_bosses(self.author.id)
        if self.selected_id and not any(row["boss_id"] == self.selected_id for row in self.records):
            self.selected_id = None
        self.rebuild()

    def selected(self):
        return next((row for row in self.records if row["boss_id"] == self.selected_id), None)

    def rebuild(self):
        self.clear_items()
        if self.records:
            select = Select(
                placeholder="완성 보스 선택",
                options=[
                    discord.SelectOption(
                        label=f"[{row['grade']}] {row['boss_name']}"[:100],
                        description=f"평가 {int(row['power_score']):,} · Elo {int(row['weekly_elo'])}",
                        value=row["boss_id"],
                    )
                    for row in self.records[:25]
                ],
                row=0,
            )

            async def choose(interaction):
                self.selected_id = interaction.data["values"][0]
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            select.callback = choose
            self.add_item(select)
        for label, scope, style in (
            ("길드 공개", "guild", discord.ButtonStyle.success),
            ("월드 공개", "world", discord.ButtonStyle.primary),
            ("공개 해제", None, discord.ButtonStyle.secondary),
        ):
            button = Button(label=label, style=style, row=1)

            async def change(interaction, selected_scope=scope):
                await self.publish(interaction, selected_scope)

            button.callback = change
            self.add_item(button)
        sell = Button(label="판매", style=discord.ButtonStyle.danger, row=2)
        sell.callback = self.sell
        self.add_item(sell)
        back = Button(label="허브로", style=discord.ButtonStyle.secondary, row=2)
        back.callback = self.back
        self.add_item(back)

    def get_embed(self, message: str | None = None) -> discord.Embed:
        embed = discord.Embed(
            title="📚 완성 보스 보관함",
            description=message or f"완성 보스 {len(self.records)}체 · 동시에 하나만 공개할 수 있습니다.",
            color=discord.Color.dark_gold(),
        )
        row = self.selected()
        if row:
            data = row["boss_data"]
            reward = SALE_REWARDS[row["grade"]]
            embed.add_field(
                name=f"[{row['grade']}] {row['boss_name']}",
                value=(
                    f"평가 {int(row['power_score']):,} · 주간 Elo {int(row['weekly_elo'])} · "
                    f"역대 최고 {int(row['all_time_best_elo'])}\n"
                    f"HP {int(data['hp']):,} · 정신 {int(data['mental']):,} · "
                    f"공격 {int(data['attack'])} · 방어 {int(data['defense'])}\n"
                    f"공개: {'예 · ' + row['publish_scope'] if row['is_published'] else '아니오'}\n"
                    f"판매: {reward['money']:,}원 · {reward['pt']:,} PT · 희망 {reward['hope']}"
                ),
                inline=False,
            )
        return embed

    async def publish(self, interaction, scope):
        try:
            if not self.selected_id:
                raise BossTrainingError("보스를 선택해주세요.")
            await publish_boss(self.author.id, self.selected_id, scope)
            await self.setup()
            await interaction.response.edit_message(
                embed=self.get_embed("공개 설정을 변경했습니다."), view=self
            )
        except Exception as exc:
            await _reply_error(interaction, exc)

    async def sell(self, interaction):
        row = self.selected()
        if not row:
            return await _reply_error(interaction, BossTrainingError("판매할 보스를 선택해주세요."))
        await interaction.response.send_modal(SellBossModal(self, row))

    async def back(self, interaction):
        hub = BossTrainingHubView(self.author, self.guild_info)
        await interaction.response.edit_message(embed=await hub.get_embed(), view=hub)


class BossChallengeView(_OwnerView):
    def __init__(self, author, guild_info):
        super().__init__(author, timeout=240)
        self.guild_info = guild_info
        self.scope = "guild"
        self.records: list[dict[str, Any]] = []
        self.selected_id: str | None = None

    async def setup(self):
        self.records = await list_published_bosses(self.guild_info["guild_id"], self.scope)
        self.selected_id = None
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        if self.records:
            select = Select(
                placeholder="도전할 보스 선택",
                options=[
                    discord.SelectOption(
                        label=f"[{row['grade']}] {row['boss_name']}"[:100],
                        description=f"Elo {int(row['weekly_elo'])} · 평가 {int(row['power_score']):,}",
                        value=row["boss_id"],
                    )
                    for row in self.records[:25]
                ],
                row=0,
            )

            async def choose(interaction):
                self.selected_id = interaction.data["values"][0]
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            select.callback = choose
            self.add_item(select)
        toggle = Button(
            label="🌍 월드 목록" if self.scope == "guild" else "🏰 길드 목록",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        toggle.callback = self.toggle_scope
        self.add_item(toggle)
        challenge = Button(label="⚔️ 모집 시작", style=discord.ButtonStyle.danger, row=1)
        challenge.callback = self.challenge
        self.add_item(challenge)
        back = Button(label="허브로", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self.back
        self.add_item(back)

    def get_embed(self) -> discord.Embed:
        lines = [
            f"**[{row['grade']}] {row['boss_name']}** · Elo {int(row['weekly_elo'])} · "
            f"평가 {int(row['power_score']):,}"
            for row in self.records
        ]
        return discord.Embed(
            title=f"⚔️ {'월드' if self.scope == 'world' else '길드'} 유저 보스",
            description="\n".join(lines) or "현재 공개된 보스가 없습니다.",
            color=discord.Color.red(),
        )

    async def toggle_scope(self, interaction):
        self.scope = "world" if self.scope == "guild" else "guild"
        await self.setup()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def challenge(self, interaction):
        try:
            record = next((row for row in self.records if row["boss_id"] == self.selected_id), None)
            if not record:
                raise BossTrainingError("도전할 보스를 선택해주세요.")
            if str(record["owner_id"]) == str(self.author.id):
                raise BossTrainingError("본인이 만든 보스에는 도전할 수 없습니다.")
            from guild import RaidLobbyView

            lobby = RaidLobbyView(
                self.author, self.guild_info, None,
                user_boss_record=record, scope=self.scope,
            )
            await lobby.add_participant(self.author)
            await interaction.response.edit_message(embed=lobby.get_embed(), view=lobby)
            lobby.public_message = interaction.message
        except Exception as exc:
            await _reply_error(interaction, exc)

    async def back(self, interaction):
        hub = BossTrainingHubView(self.author, self.guild_info)
        await interaction.response.edit_message(embed=await hub.get_embed(), view=hub)


class BossTrainingShopView(_OwnerView):
    def __init__(self, author, guild_info, user_data):
        super().__init__(author, timeout=240)
        self.guild_info = guild_info
        self.user_data = user_data
        self.selected_key: str | None = None

    def rebuild(self):
        self.clear_items()
        options = [
            discord.SelectOption(label="기본 스탯 설정권 · 100,000 PT", value="base_stat_license"),
            discord.SelectOption(label="성장률 설정권 · 200,000 PT", value="growth_license"),
        ] + [
            discord.SelectOption(label=f"{data[0]} · {data[1]:,} PT"[:100], value=key, description=data[3][:100])
            for key, data in INNATE_PASSIVES.items()
        ]
        select = Select(placeholder="영구 해금 상품 선택", options=options, row=0)

        async def choose(interaction):
            self.selected_key = interaction.data["values"][0]
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

        select.callback = choose
        self.add_item(select)
        buy = Button(label="구매", style=discord.ButtonStyle.success, row=1)
        buy.callback = self.buy
        self.add_item(buy)
        back = Button(label="허브로", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self.back
        self.add_item(back)

    def get_embed(self, message: str | None = None) -> discord.Embed:
        state = ensure_boss_training_data(self.user_data)
        prices = {"base_stat_license": 100_000, "growth_license": 200_000}
        prices.update({key: data[1] for key, data in INNATE_PASSIVES.items()})
        names = {"base_stat_license": "기본 스탯 설정권", "growth_license": "성장률 설정권"}
        names.update({key: data[0] for key, data in INNATE_PASSIVES.items()})
        lines = [
            f"{'✅' if state['shop_unlocks'].get(key) else '🔒'} **{names[key]}** · {price:,} PT"
            for key, price in prices.items()
        ]
        embed = discord.Embed(
            title="🛒 보스 육성 상점",
            description=message or "구매한 설정권과 고유 패시브는 계정에 영구 적용되며 환불되지 않습니다.",
            color=discord.Color.gold(),
        )
        embed.add_field(name=f"보유 PT {int(self.user_data.get('pt', 0)):,}", value="\n".join(lines), inline=False)
        return embed

    async def buy(self, interaction):
        try:
            if not self.selected_key:
                raise BossTrainingError("상품을 선택해주세요.")
            message = await buy_training_shop_item(self.author.id, self.author.display_name, self.selected_key)
            self.user_data = await get_user_data(self.author.id, self.author.display_name)
            self.rebuild()
            await interaction.response.edit_message(embed=self.get_embed(message), view=self)
        except Exception as exc:
            await _reply_error(interaction, exc)

    async def back(self, interaction):
        hub = BossTrainingHubView(self.author, self.guild_info)
        await interaction.response.edit_message(embed=await hub.get_embed(), view=hub)
