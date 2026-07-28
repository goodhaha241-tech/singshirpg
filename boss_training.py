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

from cards import Dice, SkillCard, get_card
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
    "hp": {
        "label": "HP 훈련", "energy": -18,
        "gains": {"hp": 350, "defense": 2, "mental": 30, "sp": 8},
    },
    "attack": {
        "label": "공격 훈련", "energy": -20,
        "gains": {"attack": 3, "mental": 110, "sp": 12},
    },
    "defense": {
        "label": "방어 훈련", "energy": -18,
        "gains": {"defense": 3, "hp": 180, "mental": 30, "sp": 8},
    },
    "mental": {
        "label": "정신 훈련", "energy": -16,
        "gains": {"mental": 220, "attack": 2, "defense": 1, "sp": 8},
    },
    "tactics": {
        "label": "전술 훈련", "energy": 5,
        "gains": {"attack": 2, "mental": 30, "sp": 35},
    },
    "rest": {"label": "휴식", "energy": 50},
    "outing": {"label": "외출", "energy": 20, "mood": 1},
    "infirmary": {"label": "치료", "energy": 15},
}

EVALUATION_TURNS = {
    14: ("Bronze", 40, 2_300),
    28: ("Silver", 70, 2_900),
    42: ("Gold", 100, 3_500),
    56: ("Platinum", 140, 4_100),
    70: ("Diamond", 200, 8_750),
}

SPECIAL_SUPPORTS = {
    "어즈렉": ("earthreg_faith", 250, "굳건한 믿음"),
    "루우데": ("luude_imprint", 300, "상냥한 악몽"),
    "영산": ("youngsan_gold", 350, "황금의 흐름"),
    "카이안": ("kaian_time", 400, "시간가속"),
    "샤일라": ("shayla_light", 400, "강한 빛"),
    "센쇼": ("sensho_star", 450, "별똥별의 가호"),
    "영설": ("yeongseol_severe_cold", 550, "혹한"),
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

IMMUNITIES = {
    "bleed": ("출혈", 160),
    "paralysis": ("마비", 180),
    "stun": ("기절", 240),
    "freeze": ("빙결", 300),
}
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
    "freeze": 150,
}
COOLDOWN_MULTIPLIERS = {1: 1.5, 2: 1.0, 3: 0.9, 4: 0.8}

SCENARIOS = {
    "normal": {
        "name": "일반 시나리오",
        "description": "기존 70턴 육성 규칙을 그대로 사용합니다.",
        "facility_cap": 5,
        "training_multiplier": 1.0,
        "evaluation_sp_multiplier": 1.0,
    },
    "facility_expansion": {
        "name": "시설 확장 시나리오",
        "description": "시설 최대 레벨 6 · 모든 훈련 성장 +15% · 평가전 SP +20%",
        "facility_cap": 6,
        "training_multiplier": 1.15,
        "evaluation_sp_multiplier": 1.20,
        "shop_price": 600_000,
        "unlock_key": "scenario_facility_expansion",
    },
}

FACTOR_STAR_DISTRIBUTIONS = {
    "C": ((1, 1.0),),
    "B": ((1, 1.0),),
    "A": ((1, 0.70), (2, 0.30)),
    "S": ((1, 0.40), (2, 0.60)),
    "SS": ((1, 0.20), (2, 0.55), (3, 0.25)),
    "UG": ((1, 0.10), (2, 0.45), (3, 0.45)),
    "UF": ((2, 0.35), (3, 0.65)),
}
FACTOR_ACTIVATION_CHANCES = {1: 0.50, 2: 0.75, 3: 1.0}
FACTOR_STAT_VALUES = {
    "hp": {1: 150, 2: 300, 3: 500},
    "mental": {1: 80, 2: 160, 3: 260},
    "attack": {1: 1, 2: 2, 3: 3},
    "defense": {1: 1, 2: 2, 3: 3},
}
FACTOR_GROWTH_VALUES = {1: 3, 2: 6, 3: 10}
FACTOR_SKILL_ROLL = 0.45
FACTOR_HINT_ROLL = 0.25
FACTOR_PASSIVE_ROLL = 0.30
FACTOR_VERSION = 1
DUNGEON_VERSION = 1
DUNGEON_ROLE_LABELS = {
    "attack": "공격형",
    "defense": "방어형",
    "control": "제어형",
    "recovery": "회복형",
}
DUNGEON_ROLE_WEIGHTS = {
    # hp, mental, attack, defense, skill
    "attack": {"hp": 20, "mental": 10, "attack": 30, "defense": 10, "skill": 30},
    "defense": {"hp": 30, "mental": 15, "attack": 10, "defense": 25, "skill": 20},
    "control": {"hp": 20, "mental": 20, "attack": 15, "defense": 15, "skill": 30},
    "recovery": {"hp": 25, "mental": 25, "attack": 10, "defense": 20, "skill": 20},
}

USER_BOSS_REWARD_MULTIPLIERS = {
    "C": 1.0, "B": 1.2, "A": 1.5, "S": 2.0,
    "SS": 2.75, "UG": 3.75, "UF": 5.0,
}
USER_BOSS_HOPE_REWARDS = {
    "C": 1, "B": 1, "A": 1, "S": 1, "SS": 2, "UG": 3, "UF": 4,
}

BASE_SKILL_FAMILIES: dict[str, dict[str, dict[str, Any]]] = {
    "hp": {
        "default": {
            "name": "기본회복",
            "dice": [{"type": "heal", "min": 5, "max": 9}],
            "effects": [], "cooldown": 2, "is_aoe": False, "free": True,
        },
        "change": {
            "name": "숨고르기",
            "dice": [
                {"type": "attack", "min": 5, "max": 8},
                {"type": "heal", "min": 10, "max": 15},
            ],
            "effects": [], "cooldown": 2, "is_aoe": False, "base_cost": 80,
        },
        "upgrade": {
            "name": "중급회복",
            "dice": [
                {"type": "heal", "min": 15, "max": 20},
                {"type": "heal", "min": 8, "max": 10},
                {"type": "mental_heal", "min": 2, "max": 10},
            ],
            "effects": [], "cooldown": 3, "is_aoe": False, "base_cost": 120,
        },
    },
    "attack": {
        "default": {
            "name": "기본공격",
            "dice": [{"type": "attack", "min": 5, "max": 9}],
            "effects": [], "cooldown": 2, "is_aoe": False, "free": True,
        },
        "change": {
            "name": "복합공격",
            "dice": [
                {"type": "attack", "min": 3, "max": 5},
                {"type": "attack", "min": 2, "max": 4},
            ],
            "effects": [], "cooldown": 1, "is_aoe": False, "base_cost": 80,
        },
        "upgrade": {
            "name": "강한참격",
            "dice": [
                {"type": "attack", "min": 7, "max": 10},
                {"type": "attack", "min": 1, "max": 6},
            ],
            "effects": [], "cooldown": 2, "is_aoe": False, "base_cost": 120,
        },
    },
    "defense": {
        "default": {
            "name": "기본방어",
            "dice": [{"type": "defense", "min": 5, "max": 9}],
            "effects": [], "cooldown": 2, "is_aoe": False, "free": True,
        },
        "change": {
            "name": "복합반격",
            "dice": [
                {"type": "defense", "min": 3, "max": 5},
                {"type": "counter", "min": 3, "max": 5},
            ],
            "effects": [], "cooldown": 1, "is_aoe": False, "base_cost": 80,
        },
        "upgrade": {
            "name": "섬세한 방어",
            "dice": [{"type": "defense", "min": 8, "max": 12}],
            "effects": [], "cooldown": 2, "is_aoe": False, "base_cost": 120,
        },
    },
    "mental": {
        "default": {
            "name": "기본집중",
            "dice": [{"type": "mental_heal", "min": 5, "max": 9}],
            "effects": [], "cooldown": 2, "is_aoe": False, "free": True,
        },
        "change": {
            "name": "방어와 침착",
            "dice": [
                {"type": "defense", "min": 5, "max": 9},
                {"type": "mental_heal", "min": 10, "max": 12},
            ],
            "effects": [], "cooldown": 2, "is_aoe": False, "base_cost": 80,
        },
        "upgrade": {
            "name": "깊은집중",
            "dice": [
                {"type": "mental_heal", "min": 6, "max": 9},
                {"type": "heal", "min": 10, "max": 14},
            ],
            "effects": [], "cooldown": 2, "is_aoe": False, "base_cost": 120,
        },
    },
    "tactics": {
        "default": {
            "name": "기본반격",
            "dice": [{"type": "counter", "min": 5, "max": 9}],
            "effects": [], "cooldown": 2, "is_aoe": False, "free": True,
        },
        "change": {
            "name": "회전베기",
            "dice": [
                {"type": "attack", "min": 6, "max": 10},
                {"type": "counter", "min": 5, "max": 9},
            ],
            "effects": [], "cooldown": 2, "is_aoe": False, "base_cost": 80,
        },
        "upgrade": {
            "name": "집중반격",
            "dice": [
                {"type": "counter", "min": 5, "max": 9},
                {"type": "counter", "min": 5, "max": 9},
                {"type": "mental_heal", "min": 7, "max": 9},
            ],
            "effects": [], "cooldown": 3, "is_aoe": False, "base_cost": 120,
        },
    },
}

SPECIAL_SKILL_PRESETS: dict[str, dict[str, Any]] = {
    "어즈렉": {
        "name": "신앙의 성벽",
        "dice": [
            {"type": "defense", "min": 18, "max": 30},
            {"type": "defense", "min": 12, "max": 20},
            {"type": "heal", "min": 12, "max": 20},
        ],
        "effects": [], "cooldown": 3, "is_aoe": False, "base_cost": 260,
    },
    "루우데": {
        "name": "악몽 붕괴",
        "dice": [
            {"type": "attack", "min": 18, "max": 30, "effect": "destroy_next_on_hit"},
            {"type": "defense", "min": 12, "max": 20},
        ],
        "effects": [], "cooldown": 3, "is_aoe": False, "base_cost": 300,
    },
    "영산": {
        "name": "황금 폭류",
        "dice": [
            {"type": "attack", "min": 12, "max": 20},
            {"type": "attack", "min": 12, "max": 20},
            {"type": "attack", "min": 8, "max": 14},
        ],
        "effects": [], "cooldown": 3, "is_aoe": True, "base_cost": 320,
    },
    "카이안": {
        "name": "시간 단층",
        "dice": [
            {"type": "counter", "min": 18, "max": 30},
            {"type": "counter", "min": 12, "max": 20},
            {"type": "defense", "min": 12, "max": 20},
        ],
        "effects": [], "cooldown": 3, "is_aoe": False, "base_cost": 300,
    },
    "샤일라": {
        "name": "은하 섬광",
        "dice": [
            {"type": "mental_heal", "min": 12, "max": 20},
            {"type": "defense", "min": 12, "max": 20},
            {"type": "counter", "min": 8, "max": 14},
        ],
        "effects": [], "cooldown": 3, "is_aoe": False, "base_cost": 280,
    },
    "센쇼": {
        "name": "성좌의 심판",
        "dice": [
            {"type": "defense", "min": 12, "max": 20},
            {"type": "attack", "min": 18, "max": 30},
            {"type": "heal", "min": 12, "max": 20},
        ],
        "effects": [], "cooldown": 4, "is_aoe": False, "base_cost": 300,
    },
    "영설": {
        "name": "백야의 동결",
        "dice": [
            {"type": "attack", "min": 18, "max": 30, "effect": "freeze_2_on_win"},
            {"type": "attack", "min": 12, "max": 20},
            {"type": "defense", "min": 12, "max": 20},
        ],
        "effects": ["freeze"],
        "cooldown": 4,
        "is_aoe": True,
        "base_cost": 450,
        "purchase_cost": 450,
    },
}

GRADE_THRESHOLDS = (
    ("UF", 13_000),
    ("UG", 11_000),
    ("SS", 9_000),
    ("S", 7_500),
    ("A", 6_000),
    ("B", 4_500),
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
    state.setdefault("challenger_rewarded_battle_ids", [])
    state.setdefault("sold_boss_ids", [])
    # Bound only the idempotency ledger, never the user's fragment inventory.
    state["rewarded_battle_ids"] = list(state["rewarded_battle_ids"])[-500:]
    state["challenger_rewarded_battle_ids"] = list(
        state["challenger_rewarded_battle_ids"]
    )[-500:]
    state["sold_boss_ids"] = list(state["sold_boss_ids"])[-500:]
    run = state.get("active_run")
    if isinstance(run, dict):
        run.setdefault("inherited_growth_bonus", {})
        run.setdefault("passive_factor_discounts", {})
        run.setdefault("inherited_skill_offers", {})
        run.setdefault("inheritance_parents", [])
        run.setdefault("inheritance_events_done", [])
        run.setdefault("inheritance_log", [])
        run.setdefault("inheritance_totals", {"stats": {}})
        run.setdefault("scenario_id", "normal")
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
    if "영설" in str(character.get("name", "")):
        return "attack"
    # 캐릭터 스탯과 현재 장착 카드의 주사위 구성을 함께 본다.
    # 반격 카드는 전술 성향에 강하게 반영해 다섯 훈련 모두 실제로
    # 서포트 주력이 될 수 있도록 한다.
    values = {
        "hp": float(character.get("hp", 0) or 0) / 300,
        "mental": float(character.get("max_mental", 0) or 0) / 240,
        "attack": float(character.get("attack", 0) or 0) / 30,
        "defense": float(character.get("defense", 0) or 0) / 30,
        "tactics": 0.45 + float(character.get("level", 0) or 0) / 100,
    }
    action_to_specialty = {
        "heal": "hp",
        "mental_heal": "mental",
        "attack": "attack",
        "defense": "defense",
        "counter": "tactics",
    }
    for card_name in character.get("equipped_cards", []) or []:
        card = get_card(str(card_name))
        if card is None:
            continue
        if getattr(card, "is_aoe", False):
            values["tactics"] += 0.40
        for dice in getattr(card, "dice_list", []) or []:
            specialty = action_to_specialty.get(getattr(dice, "action_type", ""))
            if specialty:
                values[specialty] += 2.50 if specialty == "tactics" else 0.80
    best = max(values, key=values.get)
    return best


def _snapshot_support(character: dict[str, Any], upgrade: int, owner_id: str) -> dict[str, Any]:
    return {
        "name": str(character.get("name", "이름 없음")),
        "owner_id": str(owner_id),
        "level": max(0, int(character.get("level", 0) or 0)),
        "upgrade": max(0, min(MAX_SUPPORT_UPGRADE, int(upgrade))),
        "specialty": _support_specialty(character),
        "specialty_version": 2,
        "equipped_cards": list(character.get("equipped_cards", []) or []),
        "bond": 0,
        "event_stage": 0,
    }


def _refresh_support_specialties(run: dict[str, Any]) -> None:
    """Migrate active runs created before card-aware support specialties."""
    for support in run.get("supports", []):
        if int(support.get("specialty_version", 0)) >= 2:
            continue
        equipped_cards = list(support.get("equipped_cards", []) or [])
        if equipped_cards:
            inferred = _support_specialty({
                "level": support.get("level", 0),
                "equipped_cards": equipped_cards,
            })
            support["specialty"] = inferred
        support["specialty_version"] = 2


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
    parent_records: list[dict[str, Any]] | None = None,
    scenario_id: str = "normal",
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
    if scenario_id not in SCENARIOS:
        raise BossTrainingError("알 수 없는 육성 시나리오입니다.")
    scenario = SCENARIOS[scenario_id]
    unlock_key = scenario.get("unlock_key")
    if unlock_key and not state["shop_unlocks"].get(unlock_key):
        raise BossTrainingError("해금하지 않은 육성 시나리오입니다.")

    parents = list(parent_records or [])
    parent_ids = [str(record.get("boss_id", "")) for record in parents]
    if len(parents) > 2 or len(set(parent_ids)) != len(parent_ids) or any(not value for value in parent_ids):
        raise BossTrainingError("계승 부모는 서로 다른 완성 보스 0~2체여야 합니다.")
    parent_snapshots = []
    for record in parents:
        normalized, _ = ensure_completed_boss_factors(record)
        parent_data = normalized.get("boss_data", normalized)
        parent_snapshots.append({
            "boss_id": str(normalized.get("boss_id") or parent_data.get("boss_id")),
            "name": str(normalized.get("boss_name") or parent_data.get("name", "부모 보스")),
            "grade": str(normalized.get("grade") or parent_data.get("grade", "C")),
            "factors": deepcopy(parent_data.get("factors", [])),
        })

    inventory[PURE_HOPE_ITEM] = int(inventory.get(PURE_HOPE_ITEM, 0)) - START_HOPE
    user_data["money"] = int(user_data.get("money", 0)) - START_MONEY
    user_data["pt"] = int(user_data.get("pt", 0)) - START_PT

    supports = [
        _snapshot_support(
            characters[index],
            state["support_upgrades"].get(str(characters[index].get("name", "")), 0),
            "self",
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
        "inherited_growth_bonus": {},
        "passive_factor_discounts": {},
        "inherited_skill_offers": {},
        "inheritance_parents": parent_snapshots,
        "inheritance_events_done": [],
        "inheritance_log": [],
        "inheritance_totals": {"stats": {}},
        "scenario_id": scenario_id,
        "base_tokens": tokens,
        "facility_successes": {key: 0 for key in GROWTH_KEYS},
        "facility_levels": {key: 1 for key in GROWTH_KEYS},
        "supports": supports,
        "pending_event_choice": None,
        "inheritance_candidates": [],
        "skill_hints": {},
        "base_skill_hints": {},
        "base_upgrade_hints": {},
        "special_preset_hints": {},
        "hint_history": [],
        "evaluation_results": [],
        "innate_passive": innate_passive,
        "build": {
            "skills": _default_skills(),
            "skill_slots_initialized": True,
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
    _apply_inheritance_event(run, "start", rng)
    state["active_run"] = run
    return run


def _support_event_chance(support: dict[str, Any]) -> float:
    bond = int(support.get("bond", 0))
    base = 0.20 if bond < 40 else 0.30 if bond < 80 else 0.45
    return min(1.0, base + int(support.get("upgrade", 0)) * 0.03)


def _skill_hint_chance(support: dict[str, Any]) -> float:
    bond = int(support.get("bond", 0))
    base = 0.10 if bond < 40 else 0.20 if bond < 80 else 0.30
    return min(1.0, base + int(support.get("upgrade", 0)) * 0.02)


def _add_hint(run: dict[str, Any], bucket: str, key: str, source: str) -> int:
    hints = run.setdefault(bucket, {})
    hints[key] = min(4, int(hints.get(key, 0)) + 1)
    history = run.setdefault("hint_history", [])
    history.append({
        "turn": int(run.get("turn", 0)),
        "bucket": bucket,
        "key": key,
        "source": source,
    })
    run["hint_history"] = history[-30:]
    return int(hints[key])


def _grant_equipped_card_hint(
    run: dict[str, Any],
    support: dict[str, Any],
    rng: random.Random | Any = random,
) -> str | None:
    cards = [
        name for name in support.get("equipped_cards", [])
        if get_card(str(name)) is not None
    ]
    if not cards:
        return None
    card_name = str(rng.choice(cards))
    count = _add_hint(run, "skill_hints", card_name, str(support.get("name", "")))
    return f"{card_name} 힌트 Lv.{count} (SP {count * 10}% 할인)"


def _grant_stage_three_hints(
    run: dict[str, Any],
    support: dict[str, Any],
    rng: random.Random | Any = random,
) -> list[str]:
    specialty = str(support.get("specialty", "tactics"))
    source = str(support.get("name", "서포트"))
    base_count = _add_hint(run, "base_skill_hints", specialty, source)
    upgrade_count = _add_hint(run, "base_upgrade_hints", specialty, source)
    logs = [
        f"{GROWTH_LABELS[specialty]} 기본기 변경 힌트 Lv.{base_count}",
        f"{GROWTH_LABELS[specialty]} 기본기 강화 힌트 Lv.{upgrade_count}",
    ]
    identity = _support_identity(source)
    if identity == "영설":
        for card_name in support.get("equipped_cards", []):
            if get_card(str(card_name)) is None:
                continue
            count = _add_hint(run, "skill_hints", str(card_name), source)
            logs.append(f"{card_name} 변경·강화 힌트 Lv.{count} (SP {count * 10}% 할인)")
    else:
        card_hint = _grant_equipped_card_hint(run, support, rng)
        if card_hint:
            logs.append(card_hint)
    if identity:
        preset_count = _add_hint(run, "special_preset_hints", identity, source)
        logs.append(
            f"{identity} 강력 프리셋 힌트 Lv.{preset_count} "
            f"(SP {preset_count * 10}% 할인)"
        )
    return logs


def training_failure_rate(run: dict[str, Any], energy: int | None = None) -> int:
    current_energy = int(run.get("energy", 0)) if energy is None else int(energy)
    return min(
        60,
        max(0, 50 - current_energy)
        + (15 if run.get("injured") else 0),
    )


def _apply_growth(
    run: dict[str, Any],
    action: str,
    gains: dict[str, int],
    support_bonus: float,
    sp_support_bonus: float = 0.0,
) -> dict[str, int]:
    mood = MOOD_MULTIPLIERS[max(1, min(5, int(run["mood"]))) - 1]
    facility = 1.0 + (max(1, int(run["facility_levels"].get(action, 1))) - 1) * 0.10
    growth_rate = (
        int(run["growth_rates"].get(action, 0))
        + int(run.get("inherited_growth_bonus", {}).get(action, 0))
    )
    growth = 1.0 + growth_rate / 100
    injury = 0.75 if run.get("injured") else 1.0
    scenario = SCENARIOS.get(run.get("scenario_id", "normal"), SCENARIOS["normal"])
    multiplier = (
        mood * facility * growth * injury
        * (1.0 + min(0.60, support_bonus))
        * float(scenario["training_multiplier"])
    )
    applied: dict[str, int] = {}
    for key, amount in gains.items():
        key_multiplier = multiplier * (1.0 + sp_support_bonus if key == "sp" else 1.0)
        value = max(1, math.floor(int(amount) * key_multiplier))
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
    base_gained = reward if win else math.floor(reward * 0.40)
    scenario = SCENARIOS.get(run.get("scenario_id", "normal"), SCENARIOS["normal"])
    gained = math.floor(base_gained * float(scenario["evaluation_sp_multiplier"]))
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
    _refresh_support_specialties(run)
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
        failure_rate = training_failure_rate(run, before_energy)
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
            yeongseol_count = 0
            friendship_supports = []
            for index in placed:
                support = run["supports"][index]
                bond = int(support.get("bond", 0))
                support_bonus += min(0.10, int(support.get("level", 0)) * 0.002)
                support_bonus += int(support.get("upgrade", 0)) * 0.05
                if bond >= 80 and support.get("specialty") == action:
                    support_bonus += 0.20
                    friendship_supports.append(str(support.get("name", "서포트")))
                support["bond"] = min(100, bond + 7)
                if _support_identity(str(support.get("name", ""))) == "영설":
                    yeongseol_count += 1
            yeongseol_sp_bonus = min(0.50, yeongseol_count * 0.25)
            applied = _apply_growth(
                run,
                action,
                spec["gains"],
                support_bonus,
                sp_support_bonus=yeongseol_sp_bonus,
            )
            result["gains"] = applied
            gain_labels = {
                "hp": "HP",
                "mental": "정신",
                "attack": "공격",
                "defense": "방어",
                "sp": "SP",
            }
            result["logs"].append(
                "성장 · " + " · ".join(
                    f"{gain_labels.get(key, key)} +{value}"
                    for key, value in applied.items()
                )
            )
            run["facility_successes"][action] = int(run["facility_successes"].get(action, 0)) + 1
            scenario = SCENARIOS.get(run.get("scenario_id", "normal"), SCENARIOS["normal"])
            run["facility_levels"][action] = min(
                int(scenario["facility_cap"]),
                1 + run["facility_successes"][action] // 4,
            )
            result["supports"] = [run["supports"][index]["name"] for index in placed]
            result["friendship_supports"] = friendship_supports
            if friendship_supports:
                result["logs"].append(
                    f"💞 우정 트레이닝: {', '.join(friendship_supports)} · 성장 +20%"
                )
            if yeongseol_count:
                result["logs"].append(
                    f"🌨️ 영설 서포트 {yeongseol_count}명 · 훈련 SP +{int(yeongseol_sp_bonus * 100)}%"
                )

            # Only the borrowed public support can drop an equipped-card hint
            # outside its event chain.
            for index in placed:
                support = run["supports"][index]
                if str(support.get("owner_id")) == "self":
                    continue
                if rng.random() < _skill_hint_chance(support):
                    hint_log = _grant_equipped_card_hint(run, support, rng)
                    if hint_log:
                        result["logs"].append(f"💡 공개 서포트 힌트: {hint_log}")

            # One sequential special event at most per turn.
            for index in placed:
                support = run["supports"][index]
                identity = _support_identity(str(support.get("name", "")))
                stage = int(support.get("event_stage", 0))
                if stage >= 3 or rng.random() >= _support_event_chance(support):
                    continue
                stage += 1
                support["event_stage"] = stage
                support_name = str(support.get("name", "서포트"))
                if stage == 1:
                    support["bond"] = min(100, int(support["bond"]) + 10)
                    extra = {
                        key: max(1, math.floor(value * 0.50))
                        for key, value in spec["gains"].items()
                    }
                    for key, value in extra.items():
                        run[key] = int(run.get(key, 0)) + value
                    result["logs"].append(
                        f"{support_name} 연속 이벤트 1단계 · 유대 +10 · 추가 성장 {extra}"
                    )
                elif stage == 2:
                    run["pending_event_choice"] = {
                        "support_index": index,
                        "name": support_name,
                    }
                    result["logs"].append(
                        f"{support_name} 연속 이벤트 2단계 · 보상을 선택하세요."
                    )
                else:
                    if identity and identity not in run["inheritance_candidates"]:
                        run["inheritance_candidates"].append(identity)
                    run["sp"] = int(run["sp"]) + 60
                    hint_logs = _grant_stage_three_hints(run, support, rng)
                    completion = (
                        f"{support_name} 연속 이벤트 완주 · SP +60"
                        + (f" · {identity} 계승 후보 해금" if identity else "")
                    )
                    result["logs"].append(completion)
                    result["logs"].extend(f"💡 {text}" for text in hint_logs)
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
    inheritance_key = {35: "mid", 60: "late"}.get(int(run["turn"]))
    if inheritance_key:
        inheritance_logs = _apply_inheritance_event(run, inheritance_key, rng)
        result["logs"].extend(inheritance_logs)
    if int(run["turn"]) >= MAX_TURNS:
        run["phase"] = "build"
    else:
        _roll_support_placements(run, rng)

    run["history"] = (list(run.get("history", [])) + [{
        "turn": int(run["turn"]),
        "action": action,
        "success": bool(result["success"]),
        "logs": list(result["logs"]),
    }])[-3:]
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
        "빙결": "freeze",
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
    if skill.get("free"):
        return 0
    if "purchase_cost" in skill:
        return max(0, int(skill["purchase_cost"]))
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
    skills = ensure_skill_slots(run)
    total = sum(skill_sp_cost(skill) for skill in skills)
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
    passive_discounts = run.get("passive_factor_discounts", {})
    for key in passives:
        discount = min(50, max(0, int(passive_discounts.get(key, 0))))
        total += math.ceil(GENERAL_PASSIVES[key][1] * (100 - discount) / 100)
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


def _sp_summary(run: dict[str, Any]) -> tuple[int, int, int]:
    allocated = _build_sp_cost(run, run.get("build", {}))
    owned = int(run.get("sp", 0))
    return owned, allocated, owned - allocated


def _default_skills() -> list[dict[str, Any]]:
    return [
        deepcopy(BASE_SKILL_FAMILIES[key]["default"])
        for key in GROWTH_KEYS
    ]


def ensure_skill_slots(run: dict[str, Any]) -> list[dict[str, Any]]:
    build = run.setdefault("build", {})
    skills = list(build.get("skills", []))
    if not build.get("skill_slots_initialized"):
        defaults = _default_skills()
        for index, skill in enumerate(skills[:5]):
            defaults[index] = skill
        skills = defaults
        build["skills"] = skills
        build["skill_slots_initialized"] = True
    while len(skills) < 5:
        skills.append(deepcopy(_default_skills()[len(skills)]))
    del skills[5:]
    build["skills"] = skills
    return skills


def _hint_discount(count: int) -> int:
    return min(40, max(0, int(count)) * 10)


def _discounted_cost(base_cost: int, hint_count: int) -> int:
    return max(0, math.ceil(int(base_cost) * (100 - _hint_discount(hint_count)) / 100))


def _estimate_card_cost(card) -> int:
    total = 0
    for dice in getattr(card, "dice_list", []) or []:
        maximum = int(getattr(dice, "d_max", 0))
        total += 25 if maximum <= 9 else 45 if maximum <= 14 else 75 if maximum <= 20 else 120
        if getattr(dice, "action_type", "") == "counter":
            total += 10
        effect = str(getattr(dice, "effect", "") or "")
        if "bleed" in effect:
            total += 30
        elif "paralysis" in effect:
            total += 40
        elif "stun" in effect:
            total += 80
        elif "freeze" in effect:
            total += 150
        elif "absorb_hp" in effect:
            total += 90
        elif "destroy_next" in effect:
            total += 120
    if getattr(card, "is_aoe", False):
        total *= 2
    return max(25, total)


def _card_offer_spec(card_name: str) -> dict[str, Any] | None:
    card = get_card(card_name)
    if card is None:
        return None
    dice = []
    for item in getattr(card, "dice_list", []) or []:
        dice.append({
            "type": str(getattr(item, "action_type", "attack")),
            "min": int(getattr(item, "d_min", 1)),
            "max": int(getattr(item, "d_max", 1)),
            "effect": getattr(item, "effect", None),
        })
    if not dice:
        return None
    return {
        "name": str(card_name),
        "dice": dice,
        "effects": [],
        "cooldown": 2,
        "is_aoe": bool(getattr(card, "is_aoe", False)),
        "base_cost": _estimate_card_cost(card),
        "catalog_kind": "equipped",
    }


def available_skill_offers(run: dict[str, Any]) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for card_name, count in sorted(run.get("skill_hints", {}).items()):
        if int(count) <= 0:
            continue
        spec = _card_offer_spec(str(card_name))
        if not spec:
            continue
        spec["offer_id"] = f"card:{card_name}"
        spec["hint_count"] = int(count)
        offers.append(spec)
    for specialty in GROWTH_KEYS:
        change_count = int(run.get("base_skill_hints", {}).get(specialty, 0))
        if change_count:
            spec = deepcopy(BASE_SKILL_FAMILIES[specialty]["change"])
            spec.update({
                "offer_id": f"base:{specialty}:change",
                "hint_count": change_count,
                "catalog_kind": "base_change",
            })
            offers.append(spec)
        upgrade_count = int(run.get("base_upgrade_hints", {}).get(specialty, 0))
        if upgrade_count:
            spec = deepcopy(BASE_SKILL_FAMILIES[specialty]["upgrade"])
            spec.update({
                "offer_id": f"base:{specialty}:upgrade",
                "hint_count": upgrade_count,
                "catalog_kind": "base_upgrade",
            })
            offers.append(spec)
    for identity, count in sorted(run.get("special_preset_hints", {}).items()):
        if int(count) <= 0 or identity not in SPECIAL_SKILL_PRESETS:
            continue
        spec = deepcopy(SPECIAL_SKILL_PRESETS[identity])
        spec.update({
            "offer_id": f"special:{identity}",
            "hint_count": int(count),
            "catalog_kind": "special",
            "special_identity": identity,
        })
        offers.append(spec)
    for factor_id, inherited in sorted(run.get("inherited_skill_offers", {}).items()):
        count = int(inherited.get("hint_count", 0))
        if count <= 0:
            continue
        spec = deepcopy(inherited.get("spec", {}))
        if not spec.get("name") or not spec.get("dice"):
            continue
        spec.update({
            "offer_id": f"factor:{factor_id}",
            "hint_count": min(4, count),
            "catalog_kind": "inherited",
        })
        offers.append(spec)
    return offers


def _roll_factor_star(grade: str, rng: random.Random) -> int:
    roll = rng.random()
    cumulative = 0.0
    for stars, chance in FACTOR_STAR_DISTRIBUTIONS.get(
        str(grade), FACTOR_STAR_DISTRIBUTIONS["C"]
    ):
        cumulative += chance
        if roll <= cumulative:
            return int(stars)
    return int(
        FACTOR_STAR_DISTRIBUTIONS.get(str(grade), FACTOR_STAR_DISTRIBUTIONS["C"])[-1][0]
    )


def _factor_skill_spec(skill: dict[str, Any]) -> dict[str, Any]:
    spec = deepcopy(skill)
    for metadata_key in (
        "offer_id", "hint_count", "hint_discount", "special_identity",
    ):
        spec.pop(metadata_key, None)
    purchase_cost = spec.pop("purchase_cost", None)
    was_free = bool(spec.pop("free", False))
    base_cost = spec.pop("base_cost", None)
    if base_cost is None:
        try:
            base_cost = skill_sp_cost(spec)
        except BossTrainingError:
            base_cost = purchase_cost if purchase_cost is not None else 25
    if was_free:
        base_cost = 0
    spec["base_cost"] = max(0, int(base_cost))
    spec["catalog_kind"] = "inherited"
    return spec


def _factor_skill_id(spec: dict[str, Any]) -> str:
    payload = json.dumps(spec, ensure_ascii=False, sort_keys=True)
    return uuid.uuid5(uuid.NAMESPACE_URL, payload).hex


def factor_display_text(factor: dict[str, Any]) -> str:
    stars = max(1, min(3, int(factor.get("stars", 1))))
    star_text = "★" * stars
    kind = factor.get("kind")
    if kind == "stat":
        stat = str(factor.get("stat", ""))
        labels = {"hp": "HP", "mental": "정신", "attack": "공격", "defense": "방어"}
        amount = FACTOR_STAT_VALUES.get(stat, {}).get(stars, 0)
        return f"{star_text} {labels.get(stat, stat)} 인자 · 발동 시 +{amount}"
    if kind == "growth":
        specialty = str(factor.get("specialty", ""))
        amount = FACTOR_GROWTH_VALUES.get(stars, 0)
        return (
            f"{star_text} {GROWTH_LABELS.get(specialty, specialty)} 성장률 인자 "
            f"· 발동 시 +{amount}%"
        )
    if kind == "skill":
        name = str(factor.get("skill", {}).get("name", "스킬"))
        source = "장착" if factor.get("source") == "registered" else "미장착 힌트"
        return f"{star_text} {name} 스킬 인자 · 힌트 Lv.+{stars} ({source})"
    if kind == "passive_discount":
        key = str(factor.get("passive", ""))
        name = GENERAL_PASSIVES.get(key, (key,))[0]
        return f"{star_text} {name} 할인 인자 · 비용 -{stars * 10}%p"
    return f"{star_text} 알 수 없는 인자"


def _generate_boss_factors(boss: dict[str, Any], seed: str) -> list[dict[str, Any]]:
    rng = random.Random(f"{seed}:boss-factors-v{FACTOR_VERSION}")
    grade = str(boss.get("grade", "C"))
    factors: list[dict[str, Any]] = []

    vital_scores = {
        "hp": int(boss.get("hp", 0)) / 20,
        "mental": int(boss.get("mental", 0)) / 20,
    }
    vital_max = max(vital_scores.values())
    vital_candidates = [key for key, value in vital_scores.items() if value == vital_max]
    factors.append({
        "kind": "stat",
        "stat": rng.choice(vital_candidates),
        "stars": _roll_factor_star(grade, rng),
    })

    combat_scores = {
        "attack": int(boss.get("attack", 0)) * 25,
        "defense": int(boss.get("defense", 0)) * 25,
    }
    combat_max = max(combat_scores.values())
    combat_candidates = [key for key, value in combat_scores.items() if value == combat_max]
    factors.append({
        "kind": "stat",
        "stat": rng.choice(combat_candidates),
        "stars": _roll_factor_star(grade, rng),
    })

    base_growth = dict(
        boss.get("growth_rates")
        or {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5}
    )
    inherited_growth = dict(boss.get("inherited_growth_bonus", {}))
    effective_growth = {
        key: int(base_growth.get(key, 0)) + int(inherited_growth.get(key, 0))
        for key in GROWTH_KEYS
    }
    growth_max = max(effective_growth.values())
    growth_candidates = [
        key for key, value in effective_growth.items() if value == growth_max
    ]
    factors.append({
        "kind": "growth",
        "specialty": rng.choice(growth_candidates),
        "stars": _roll_factor_star(grade, rng),
    })

    registered_names = set()
    for skill in boss.get("build", {}).get("skills", []):
        spec = _factor_skill_spec(skill)
        registered_names.add(str(spec.get("name", "")))
        if rng.random() < FACTOR_SKILL_ROLL:
            factors.append({
                "kind": "skill",
                "factor_id": _factor_skill_id(spec),
                "skill": spec,
                "stars": _roll_factor_star(grade, rng),
                "source": "registered",
            })

    for offer in boss.get("hint_catalog", []):
        if str(offer.get("name", "")) in registered_names:
            continue
        spec = _factor_skill_spec(offer)
        if rng.random() < FACTOR_HINT_ROLL:
            factors.append({
                "kind": "skill",
                "factor_id": _factor_skill_id(spec),
                "skill": spec,
                "stars": _roll_factor_star(grade, rng),
                "source": "hint",
            })

    for passive in boss.get("build", {}).get("passives", []):
        if passive in GENERAL_PASSIVES and rng.random() < FACTOR_PASSIVE_ROLL:
            factors.append({
                "kind": "passive_discount",
                "passive": passive,
                "stars": _roll_factor_star(grade, rng),
            })
    return factors


def ensure_completed_boss_factors(
    record: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    normalized = deepcopy(record)
    wrapped = isinstance(normalized.get("boss_data"), dict)
    data = normalized["boss_data"] if wrapped else normalized
    changed = False
    if not data.get("boss_id") and normalized.get("boss_id"):
        data["boss_id"] = normalized["boss_id"]
        changed = True
    if not data.get("grade") and normalized.get("grade"):
        data["grade"] = normalized["grade"]
        changed = True
    if not data.get("growth_rates"):
        data["growth_rates"] = {
            "hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5
        }
        changed = True
    if "inherited_growth_bonus" not in data:
        data["inherited_growth_bonus"] = {}
        changed = True
    if "hint_catalog" not in data:
        data["hint_catalog"] = []
        changed = True
    if "scenario_id" not in data:
        data["scenario_id"] = "normal"
        changed = True
    if int(data.get("factors_version", 0)) < FACTOR_VERSION or not data.get("factors"):
        data["factors"] = _generate_boss_factors(
            data,
            str(normalized.get("boss_id") or data.get("boss_id") or data.get("name", "")),
        )
        data["factors_version"] = FACTOR_VERSION
        changed = True
    if wrapped:
        normalized["boss_data"] = data
    return normalized, changed


def _apply_inheritance_event(
    run: dict[str, Any],
    event_key: str,
    rng: random.Random | Any = random,
) -> list[str]:
    completed = run.setdefault("inheritance_events_done", [])
    if event_key in completed:
        return []
    completed.append(event_key)
    labels = {"start": "시작", "mid": "35턴", "late": "60턴"}
    event_logs = [f"🧬 {labels.get(event_key, event_key)} 인자 계승"]
    activations = 0
    for parent in run.get("inheritance_parents", []):
        parent_name = str(parent.get("name", "부모 보스"))
        for factor in parent.get("factors", []):
            stars = max(1, min(3, int(factor.get("stars", 1))))
            if rng.random() >= FACTOR_ACTIVATION_CHANCES[stars]:
                continue
            kind = factor.get("kind")
            if kind == "stat":
                stat = str(factor.get("stat"))
                amount = FACTOR_STAT_VALUES.get(stat, {}).get(stars, 0)
                if not amount:
                    continue
                run[stat] = int(run.get(stat, 0)) + amount
                stat_totals = run.setdefault(
                    "inheritance_totals", {"stats": {}}
                ).setdefault("stats", {})
                stat_totals[stat] = int(stat_totals.get(stat, 0)) + amount
                text = f"{stat} +{amount}"
            elif kind == "growth":
                specialty = str(factor.get("specialty"))
                if specialty not in GROWTH_KEYS:
                    continue
                amount = FACTOR_GROWTH_VALUES[stars]
                bonuses = run.setdefault("inherited_growth_bonus", {})
                bonuses[specialty] = int(bonuses.get(specialty, 0)) + amount
                text = f"{GROWTH_LABELS[specialty]} 성장률 +{amount}%"
            elif kind == "skill":
                spec = deepcopy(factor.get("skill", {}))
                if not spec.get("name"):
                    continue
                factor_id = str(factor.get("factor_id") or _factor_skill_id(spec))
                offers = run.setdefault("inherited_skill_offers", {})
                entry = offers.setdefault(factor_id, {"spec": spec, "hint_count": 0})
                entry["hint_count"] = min(
                    4, int(entry.get("hint_count", 0)) + stars
                )
                text = f"{spec['name']} 힌트 Lv.{entry['hint_count']}"
            elif kind == "passive_discount":
                passive = str(factor.get("passive"))
                if passive not in GENERAL_PASSIVES:
                    continue
                discounts = run.setdefault("passive_factor_discounts", {})
                discounts[passive] = min(
                    50, int(discounts.get(passive, 0)) + stars * 10
                )
                text = (
                    f"{GENERAL_PASSIVES[passive][0]} 할인 "
                    f"{discounts[passive]}%"
                )
            else:
                continue
            activations += 1
            event_logs.append(f"• {parent_name} {'★' * stars} · {text}")
    if not activations:
        event_logs.append("• 발동한 인자가 없습니다.")
    history = run.setdefault("inheritance_log", [])
    history.extend(event_logs)
    run["inheritance_log"] = history[-60:]
    return event_logs


def purchase_skill_offer(run: dict[str, Any], offer_id: str, slot_index: int) -> dict[str, Any]:
    if not 0 <= int(slot_index) < 5:
        raise BossTrainingError("스킬 슬롯은 1~5번이어야 합니다.")
    offer = next(
        (item for item in available_skill_offers(run) if item["offer_id"] == offer_id),
        None,
    )
    if not offer:
        raise BossTrainingError("아직 발견하지 못한 스킬 힌트입니다.")
    skill = deepcopy(offer)
    base_cost = int(skill.pop("base_cost"))
    hint_count = int(skill.pop("hint_count"))
    skill.pop("offer_id", None)
    skill["purchase_cost"] = _discounted_cost(base_cost, hint_count)
    skill["hint_discount"] = _hint_discount(hint_count)
    skills = ensure_skill_slots(run)
    previous = skills[int(slot_index)]
    skills[int(slot_index)] = skill
    try:
        _require_build_budget(run)
    except Exception:
        skills[int(slot_index)] = previous
        raise
    return skill


def restore_default_skill(run: dict[str, Any], slot_index: int) -> dict[str, Any]:
    if not 0 <= int(slot_index) < 5:
        raise BossTrainingError("스킬 슬롯은 1~5번이어야 합니다.")
    skills = ensure_skill_slots(run)
    skills[int(slot_index)] = deepcopy(_default_skills()[int(slot_index)])
    return skills[int(slot_index)]


def grade_for_score(score: int) -> str:
    for grade, threshold in GRADE_THRESHOLDS:
        if int(score) >= threshold:
            return grade
    return "C"


def finalize_training_run(run: dict[str, Any]) -> dict[str, Any]:
    if run.get("phase") != "build" or int(run.get("turn", 0)) < MAX_TURNS:
        raise BossTrainingError("70턴 육성을 마친 뒤에만 보스를 완성할 수 있습니다.")
    build = deepcopy(run.get("build", {}))
    skills = list(ensure_skill_slots(run))
    if sum(1 for skill in skills if skill.get("is_aoe")) > 2:
        raise BossTrainingError("광역 스킬은 최대 2개입니다.")
    paid_cost = _build_sp_cost(run, build)
    if paid_cost > int(run.get("sp", 0)):
        raise BossTrainingError(f"SP가 부족합니다. 필요 {paid_cost} / 보유 {int(run.get('sp', 0))}")
    build["skills"] = skills
    run["spent_sp"] = paid_cost
    score = _run_power_score(run, build)
    boss_id = uuid.uuid4().hex
    boss = {
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
        "growth_rates": deepcopy(run.get("growth_rates", {})),
        "inherited_growth_bonus": deepcopy(run.get("inherited_growth_bonus", {})),
        "hint_catalog": deepcopy(available_skill_offers(run)),
        "scenario_id": run.get("scenario_id", "normal"),
        "factors_version": FACTOR_VERSION,
        "created_at": datetime.now(KST).isoformat(),
    }
    boss["factors"] = _generate_boss_factors(
        boss, str(run.get("run_id") or boss_id)
    )
    return boss


def dungeon_is_ready(data: dict[str, Any] | None) -> bool:
    dungeon = (data or {}).get("dungeon", {})
    return bool(
        isinstance(dungeon, dict)
        and int(dungeon.get("version", 0)) >= DUNGEON_VERSION
        and dungeon.get("locked")
        and len(dungeon.get("monsters", [])) == 3
        and isinstance(dungeon.get("elite"), dict)
    )


def dungeon_factor_key(factor: dict[str, Any]) -> str:
    return json.dumps(factor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dungeon_factor_token(factor: dict[str, Any]) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, dungeon_factor_key(factor)).hex


def eligible_dungeon_factors(boss: dict[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic, unique raid factors and guarantee at least three."""
    allowed = {"stat", "skill", "passive_discount"}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for factor in boss.get("factors", []):
        if factor.get("kind") not in allowed:
            continue
        copied = deepcopy(factor)
        key = dungeon_factor_key(copied)
        if key in seen:
            continue
        seen.add(key)
        result.append(copied)

    represented_stats = {
        str(factor.get("stat"))
        for factor in result
        if factor.get("kind") == "stat"
    }
    stat_scores = {
        "hp": int(boss.get("hp", 0)) / 20,
        "mental": int(boss.get("mental", 0)) / 20,
        "attack": int(boss.get("attack", 0)) * 25,
        "defense": int(boss.get("defense", 0)) * 25,
    }
    for stat, _score in sorted(
        stat_scores.items(), key=lambda item: (-item[1], item[0])
    ):
        if len(result) >= 3:
            break
        if stat in represented_stats:
            continue
        factor = {
            "kind": "stat",
            "stat": stat,
            "stars": 1,
            "dungeon_supplement": True,
        }
        result.append(factor)
        represented_stats.add(stat)
    while len(result) < 3:
        # Extremely old/corrupt bosses can have every stat absent or zero.
        stat = ("hp", "mental", "attack", "defense")[len(result) % 4]
        factor = {
            "kind": "stat",
            "stat": stat,
            "stars": 1,
            "dungeon_supplement": True,
            "supplement_index": len(result),
        }
        result.append(factor)
    return result


def validate_dungeon_shares(shares: list[int]) -> list[int]:
    values = [int(value) for value in shares]
    if len(values) != 3:
        raise BossTrainingError("몬스터 점수 배분은 정확히 3개여야 합니다.")
    if any(value < 20 or value > 60 or value % 5 for value in values):
        raise BossTrainingError("점수 배분은 종마다 20~60%, 5% 단위여야 합니다.")
    if sum(values) != 100:
        raise BossTrainingError("세 몬스터의 점수 배분 합계는 정확히 100%여야 합니다.")
    return values


def _dungeon_tier(score: int, slot: int = 0) -> tuple[int, int]:
    thresholds = (
        ((18, 30), 4_500),
        ((12, 20), 2_500),
        ((8, 14), 1_300),
    )
    adjusted = max(0, int(score) - slot * 650)
    for dice_range, threshold in thresholds:
        if adjusted >= threshold:
            return dice_range
    return (5, 9)


def _dungeon_role_skills(
    name: str,
    role: str,
    target_score: int,
) -> list[dict[str, Any]]:
    first = _dungeon_tier(target_score, 0)
    second = _dungeon_tier(target_score, 1)
    third = _dungeon_tier(target_score, 2)

    def die(action: str, values: tuple[int, int], effect: str | None = None):
        item = {"type": action, "min": values[0], "max": values[1]}
        if effect:
            item["effect"] = effect
        return item

    if role == "attack":
        return [
            {"name": f"{name}의 강습", "dice": [die("attack", first)], "effects": [], "cooldown": 2, "is_aoe": False},
            {"name": f"{name}의 난격", "dice": [die("attack", second), die("attack", third)], "effects": ["bleed"], "cooldown": 3, "is_aoe": False},
            {"name": f"{name}의 포식", "dice": [die("attack", second)], "effects": ["lifesteal"], "cooldown": 3, "is_aoe": False},
        ]
    if role == "defense":
        return [
            {"name": f"{name}의 방벽", "dice": [die("defense", first), die("counter", second)], "effects": [], "cooldown": 2, "is_aoe": False},
            {"name": f"{name}의 응수", "dice": [die("attack", second), die("defense", second)], "effects": [], "cooldown": 2, "is_aoe": False},
            {"name": f"{name}의 수복", "dice": [die("defense", second), die("heal", third)], "effects": [], "cooldown": 3, "is_aoe": False},
        ]
    if role == "control":
        return [
            {"name": f"{name}의 동결", "dice": [die("attack", first, "freeze_2_on_win")], "effects": ["freeze"], "cooldown": 3, "is_aoe": False},
            {"name": f"{name}의 마비", "dice": [die("attack", second, "paralysis_1_on_win"), die("defense", third)], "effects": ["paralysis"], "cooldown": 3, "is_aoe": False},
            {"name": f"{name}의 봉쇄", "dice": [die("attack", second)], "effects": ["stun"], "cooldown": 4, "is_aoe": False},
        ]
    return [
        {"name": f"{name}의 흡수", "dice": [die("attack", second)], "effects": ["lifesteal"], "cooldown": 3, "is_aoe": False},
        {"name": f"{name}의 치유", "dice": [die("defense", second), die("heal", first)], "effects": [], "cooldown": 3, "is_aoe": False},
        {"name": f"{name}의 명상", "dice": [die("mental_heal", first), die("heal", third)], "effects": [], "cooldown": 3, "is_aoe": False},
    ]


def generate_dungeon_monster(
    boss: dict[str, Any],
    *,
    slot: int,
    name: str,
    role: str,
    share: int,
    factors: list[dict[str, Any]],
) -> dict[str, Any]:
    if role not in DUNGEON_ROLE_WEIGHTS:
        raise BossTrainingError("알 수 없는 던전 몬스터 역할입니다.")
    if not 0 <= int(slot) < 3:
        raise BossTrainingError("던전 몬스터 슬롯이 올바르지 않습니다.")
    clean_name = str(name).strip()
    if not 2 <= len(clean_name) <= 30:
        raise BossTrainingError("몬스터 이름은 2~30자로 입력해주세요.")
    share = int(share)
    if share < 20 or share > 60 or share % 5:
        raise BossTrainingError("몬스터 점수는 20~60%, 5% 단위여야 합니다.")
    if not 1 <= len(factors) <= 2:
        raise BossTrainingError("몬스터마다 인자를 1~2개 배정해야 합니다.")

    target = max(1, math.floor(int(boss["power_score"]) * share / 100))
    weights = DUNGEON_ROLE_WEIGHTS[role]
    skills = _dungeon_role_skills(clean_name, role, target)
    skill_score = sum(skill_sp_cost(skill) for skill in skills)
    stat_budget = max(1, target - skill_score)
    stat_weight_total = sum(weights[key] for key in ("hp", "mental", "attack", "defense"))
    hp = max(100, math.floor(stat_budget * weights["hp"] / stat_weight_total) * 20)
    mental = max(100, math.floor(stat_budget * weights["mental"] / stat_weight_total) * 20)
    attack = max(1, math.floor(stat_budget * weights["attack"] / stat_weight_total / 25))
    defense = max(1, math.floor(stat_budget * weights["defense"] / stat_weight_total / 25))
    actual = hp // 20 + mental // 20 + attack * 25 + defense * 25 + skill_score
    if actual < target:
        hp += (target - actual) * 20
    seed_payload = (
        f"{boss.get('boss_id')}:{DUNGEON_VERSION}:{slot}:{clean_name}:"
        f"{role}:{share}:{','.join(dungeon_factor_key(f) for f in factors)}"
    )
    return {
        "slot": int(slot),
        "name": clean_name,
        "role": role,
        "role_label": DUNGEON_ROLE_LABELS[role],
        "share": share,
        "target_score": target,
        "hp": hp,
        "mental": mental,
        "attack": attack,
        "defense": defense,
        "skills": skills,
        "skill_score": skill_score,
        "factors": deepcopy(factors),
        "seed": uuid.uuid5(uuid.NAMESPACE_URL, seed_payload).hex,
    }


def generate_dungeon_elite(
    boss: dict[str, Any],
    monsters: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(monsters) != 3:
        raise BossTrainingError("혼합 엘리트 생성에는 몬스터 3종이 필요합니다.")
    target = max(1, math.floor(int(boss["power_score"]) * 0.80))
    roles = [str(monster["role"]) for monster in monsters]
    averaged = {
        key: sum(DUNGEON_ROLE_WEIGHTS[role][key] for role in roles) / 3
        for key in ("hp", "mental", "attack", "defense")
    }
    signatures = [deepcopy(monster["skills"][0]) for monster in monsters]
    elite_name = f"{boss.get('name', '보스')}의 융합체"
    fusion_range = _dungeon_tier(target, 0)
    fusion = {
        "name": f"{elite_name}의 혼합 폭주",
        "dice": [
            {"type": "attack", "min": fusion_range[0], "max": fusion_range[1]},
            {"type": "defense", "min": fusion_range[0], "max": fusion_range[1]},
        ],
        "effects": [],
        "cooldown": 3,
        "is_aoe": True,
    }
    skills = [*signatures, fusion]
    skill_score = sum(skill_sp_cost(skill) for skill in skills)
    stat_total = max(1.0, sum(averaged.values()))
    stat_budget = max(1, target - skill_score)
    hp = max(100, math.floor(stat_budget * averaged["hp"] / stat_total) * 20)
    mental = max(100, math.floor(stat_budget * averaged["mental"] / stat_total) * 20)
    attack = max(1, math.floor(stat_budget * averaged["attack"] / stat_total / 25))
    defense = max(1, math.floor(stat_budget * averaged["defense"] / stat_total / 25))
    actual = hp // 20 + mental // 20 + attack * 25 + defense * 25 + skill_score
    if actual < target:
        hp += (target - actual) * 20
    return {
        "slot": 3,
        "name": elite_name,
        "role": "elite",
        "role_label": "혼합 엘리트",
        "target_score": target,
        "hp": hp,
        "mental": mental,
        "attack": attack,
        "defense": defense,
        "skills": skills,
        "skill_score": skill_score,
        "factors": [],
    }


def build_dungeon_spec(
    boss: dict[str, Any],
    configs: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(configs) != 3:
        raise BossTrainingError("던전 몬스터 3종을 모두 설정해주세요.")
    names = [str(item.get("name", "")).strip() for item in configs]
    if len(set(names)) != 3:
        raise BossTrainingError("세 던전 몬스터의 이름은 서로 달라야 합니다.")
    shares = validate_dungeon_shares([int(item.get("share", 0)) for item in configs])
    available = {
        dungeon_factor_key(factor): factor
        for factor in eligible_dungeon_factors(boss)
    }
    used: set[str] = set()
    monsters = []
    for slot, (config, share) in enumerate(zip(configs, shares)):
        selected = []
        for raw_factor in config.get("factors", []):
            key = dungeon_factor_key(raw_factor)
            if key not in available:
                raise BossTrainingError("보스가 보유하지 않은 인자가 포함되어 있습니다.")
            if key in used:
                raise BossTrainingError("같은 인자를 여러 몬스터에게 배정할 수 없습니다.")
            used.add(key)
            selected.append(available[key])
        monsters.append(
            generate_dungeon_monster(
                boss,
                slot=slot,
                name=config.get("name", ""),
                role=str(config.get("role", "")),
                share=share,
                factors=selected,
            )
        )
    if not 3 <= len(used) <= 6:
        raise BossTrainingError("던전에는 서로 다른 인자를 총 3~6개 배정해야 합니다.")
    return {
        "version": DUNGEON_VERSION,
        "locked": True,
        "locked_at": str(boss.get("created_at") or datetime.now(KST).isoformat()),
        "budget_total": int(boss["power_score"]),
        "monsters": monsters,
        "elite": generate_dungeon_elite(boss, monsters),
    }


def default_dungeon_builder_state(boss: dict[str, Any]) -> dict[str, Any]:
    factors = eligible_dungeon_factors(boss)
    return {
        "boss": deepcopy(boss),
        "shares": [35, 35, 30],
        "names": ["첫 번째 수문장", "두 번째 수문장", "세 번째 수문장"],
        "roles": ["attack", "defense", "control"],
        "factor_keys": [
            [dungeon_factor_token(factors[0])],
            [dungeon_factor_token(factors[1])],
            [dungeon_factor_token(factors[2])],
        ],
    }


def dungeon_builder_configs(state: dict[str, Any]) -> list[dict[str, Any]]:
    boss = state["boss"]
    factors = {
        dungeon_factor_token(factor): factor
        for factor in eligible_dungeon_factors(boss)
    }
    return [
        {
            "name": state["names"][index],
            "role": state["roles"][index],
            "share": int(state["shares"][index]),
            "factors": [
                factors[key]
                for key in state["factor_keys"][index]
                if key in factors
            ],
        }
        for index in range(3)
    ]


def _effect_code(effect: str) -> str | None:
    return {
        "bleed": "bleed_1_on_win",
        "paralysis": "paralysis_1_on_win",
        "stun": "stun_1_prob_20",
        "lifesteal": "absorb_hp_25",
        "destroy": "destroy_next_on_hit",
        "freeze": "freeze_2_on_win",
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
            effect = item.get("effect")
            if effect is None:
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
            "freeze": "빙결 2턴",
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


class DungeonRaidMonster(UserBossMonster):
    """Runtime monster generated from a locked user-dungeon floor spec."""

    def __init__(self, spec: dict[str, Any]):
        self.dungeon_spec = deepcopy(spec)
        role = str(spec.get("role", "control"))
        ai_style = {
            "attack": "aggressive",
            "defense": "defensive",
            "control": "balanced",
            "recovery": "defensive",
            "elite": "balanced",
        }.get(role, "balanced")
        data = {
            "name": spec.get("name", "던전 몬스터"),
            "hp": int(spec.get("hp", 100)),
            "mental": int(spec.get("mental", 100)),
            "attack": int(spec.get("attack", 1)),
            "defense": int(spec.get("defense", 1)),
            "build": {
                "skills": deepcopy(spec.get("skills", _default_skills()[:3])),
                "ai_style": ai_style,
                "passives": [],
                "resistances": {},
            },
        }
        super().__init__({"boss_data": data, "boss_name": data["name"]})
        self.role = role
        self.reward_factors = deepcopy(spec.get("factors", []))


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


async def _normalize_boss_rows(conn, cur, rows: list[Any]) -> list[dict[str, Any]]:
    """레거시 보스 인자를 최초 조회 시 결정적으로 생성해 영구 저장한다."""
    normalized_rows: list[dict[str, Any]] = []
    changed_any = False
    for row in rows:
        decoded = _decode_boss_row(row)
        normalized, changed = ensure_completed_boss_factors(decoded)
        normalized_rows.append(normalized)
        if changed:
            await cur.execute(
                "UPDATE user_bosses SET boss_data=%s WHERE boss_id=%s",
                (
                    json.dumps(normalized["boss_data"], ensure_ascii=False),
                    normalized["boss_id"],
                ),
            )
            changed_any = True
    if changed_any:
        await conn.commit()
    return normalized_rows


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


async def save_legacy_boss_dungeon(
    owner_id: int | str,
    boss_id: str,
    dungeon: dict[str, Any],
) -> None:
    if not dungeon_is_ready({"dungeon": dungeon}):
        raise BossTrainingError("완성되지 않은 던전 명세는 저장할 수 없습니다.")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await conn.begin()
            await cur.execute(
                "SELECT owner_id,boss_data,active_battles FROM user_bosses WHERE boss_id=%s FOR UPDATE",
                (boss_id,),
            )
            row = await cur.fetchone()
            if not row or str(row["owner_id"]) != str(owner_id):
                await conn.rollback()
                raise BossTrainingError("본인의 보스를 찾지 못했습니다.")
            data = row["boss_data"]
            if isinstance(data, str):
                data = json.loads(data)
            if dungeon_is_ready(data):
                await conn.rollback()
                raise BossTrainingError("이미 확정된 던전은 다시 편집할 수 없습니다.")
            if int(row.get("active_battles", 0) or 0) > 0:
                await conn.rollback()
                raise BossTrainingError("진행 중인 원정이 있어 던전을 확정할 수 없습니다.")
            data["dungeon"] = deepcopy(dungeon)
            await cur.execute(
                """UPDATE user_bosses
                   SET boss_data=%s,is_published=0
                   WHERE boss_id=%s AND owner_id=%s""",
                (json.dumps(data, ensure_ascii=False), boss_id, str(owner_id)),
            )
            await conn.commit()


async def list_owned_bosses(owner_id: int | str) -> list[dict[str, Any]]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await _reset_stale_weekly_ratings(cur)
            await conn.commit()
            await cur.execute(
                "SELECT * FROM user_bosses WHERE owner_id=%s ORDER BY created_at DESC",
                (str(owner_id),),
            )
            return await _normalize_boss_rows(conn, cur, list(await cur.fetchall()))


async def get_boss_record(boss_id: str) -> dict[str, Any] | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM user_bosses WHERE boss_id=%s", (boss_id,))
            row = await cur.fetchone()
            if not row:
                return None
            return (await _normalize_boss_rows(conn, cur, [row]))[0]


async def list_published_bosses(
    guild_id: int,
    scope: str = "guild",
    limit: int = 25,
) -> list[dict[str, Any]]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await _reset_stale_weekly_ratings(cur)
            await conn.commit()
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
            rows = await _normalize_boss_rows(conn, cur, list(await cur.fetchall()))
            return [
                row for row in rows
                if dungeon_is_ready(row.get("boss_data", {}))
            ]


async def list_inheritance_parent_bosses(
    owner_id: int | str,
    guild_id: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return private owned bosses plus guild/world bosses currently published."""
    owned, guild_public, world_public = await asyncio.gather(
        list_owned_bosses(owner_id),
        list_published_bosses(guild_id, "guild", limit=limit),
        list_published_bosses(guild_id, "world", limit=limit),
    )
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, rows in (
        ("owned", owned),
        ("guild", guild_public),
        ("world", world_public),
    ):
        for original in rows:
            boss_id = str(original.get("boss_id", ""))
            if not boss_id or boss_id in seen:
                continue
            seen.add(boss_id)
            row = dict(original)
            if str(row.get("owner_id")) == str(owner_id):
                row["inheritance_source"] = "owned"
            elif str(row.get("publish_scope")) == "world":
                row["inheritance_source"] = "world"
            else:
                row["inheritance_source"] = source
            merged.append(row)
    return merged


def inheritance_source_label(record: dict[str, Any]) -> str:
    return {
        "owned": "내 보스",
        "guild": "길드 공개",
        "world": "월드 공개",
    }.get(str(record.get("inheritance_source", "")), "공개")


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
            await conn.commit()
            for key, ordering in queries.items():
                await cur.execute(
                    f"""SELECT * FROM user_bosses
                        WHERE is_published=1 AND publish_scope='world'
                        ORDER BY {ordering} LIMIT %s""",
                    (int(limit),),
                )
                normalized = await _normalize_boss_rows(
                    conn, cur, list(await cur.fetchall())
                )
                result[key] = [
                    row for row in normalized
                    if dungeon_is_ready(row.get("boss_data", {}))
                ]
    return result


async def publish_boss(owner_id: int | str, boss_id: str, scope: str | None) -> None:
    if scope not in {None, "guild", "world"}:
        raise BossTrainingError("공개 범위는 길드 또는 월드여야 합니다.")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await conn.begin()
            await cur.execute(
                "SELECT owner_id,active_battles,boss_data FROM user_bosses WHERE boss_id=%s FOR UPDATE",
                (boss_id,),
            )
            row = await cur.fetchone()
            if not row or str(row[0]) != str(owner_id):
                await conn.rollback()
                raise BossTrainingError("본인의 보스를 찾지 못했습니다.")
            if scope:
                raw_data = row[2]
                if isinstance(raw_data, str):
                    raw_data = json.loads(raw_data)
                if not dungeon_is_ready(raw_data):
                    await conn.rollback()
                    raise BossTrainingError(
                        "던전 몬스터 3종을 제작·확정한 뒤 공개할 수 있습니다."
                    )
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


def user_boss_grade_reward(
    grade: str,
    *,
    factor: float = 1.0,
) -> dict[str, int]:
    multiplier = USER_BOSS_REWARD_MULTIPLIERS.get(str(grade), 1.0)
    return {
        "money": math.floor(5_000 * multiplier * factor),
        "pt": math.floor(1_000 * multiplier * factor),
        "contribution": math.floor(100 * multiplier * factor),
    }


async def finish_boss_battle(
    record: dict[str, Any],
    battle_id: str,
    challenger_id: int | str,
    attackers_won: bool,
    owner_name: str | None = None,
    *,
    self_challenge: bool = False,
    battle_data: dict[str, Any] | None = None,
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
            # 자기 보스 도전은 전투 이력만 남기고 Elo에는 반영하지 않는다.
            expected = 1.0 / (1.0 + 10 ** ((1500 - current) / 400))
            actual = 0.0 if attackers_won else 1.0
            updated = (
                current
                if self_challenge
                else max(0, round(current + 32 * (actual - expected)))
            )
            best = max(int(row.get("all_time_best_elo", 1500)), updated)
            await cur.execute(
                """INSERT IGNORE INTO user_boss_battles
                   (battle_id,boss_id,challenger_id,result,weekly_key,elo_before,elo_after,battle_data)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    battle_id, boss_id, str(challenger_id),
                    "attacker_win" if attackers_won else "boss_win",
                    key, current, updated,
                    json.dumps({
                        "attackers_won": attackers_won,
                        "self_challenge": bool(self_challenge),
                        **deepcopy(battle_data or {}),
                    }, ensure_ascii=False),
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
    reward = (
        {"money": 0, "pt": 0, "contribution": 0}
        if self_challenge
        else user_boss_grade_reward(
            str(record.get("grade", "C")),
            factor=0.4 if attackers_won else 1.0,
        )
    )
    if self_challenge:
        return {
            "elo_before": current,
            "elo_after": updated,
            "owner_reward": reward,
            "granted": False,
            "self_challenge": True,
        }
    owner_id = str(record["owner_id"])
    granted = {"value": False}

    def grant(latest):
        state = ensure_boss_training_data(latest)
        ledger = state["rewarded_battle_ids"]
        if battle_id in ledger or not inserted or self_challenge:
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
    return {
        "elo_before": current,
        "elo_after": updated,
        "owner_reward": reward,
        "granted": granted["value"],
        "self_challenge": bool(self_challenge),
    }


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
    prices = {
        "base_stat_license": 100_000,
        "growth_license": 200_000,
        "scenario_facility_expansion": 600_000,
    }
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
            title="🏰 유저 던전 육성",
            description=message or (
                "70턴 보스 육성 → 최종 빌드 → 던전 몬스터 3종 제작을 마친 뒤 "
                "5층 길드·월드 원정으로 공개합니다."
            ),
            color=discord.Color.dark_purple(),
        )
        if run:
            phase = {
                "build": "최종 빌드",
                "dungeon_build": "던전 제작",
            }.get(run.get("phase"), "육성")
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
            if run.get("phase") == "dungeon_build":
                view = BossDungeonBuilderView(
                    self.author,
                    self.guild_info,
                    active_run=True,
                )
                await view.setup()
                return await interaction.response.edit_message(
                    embed=view.get_embed(), view=view
                )
            if run.get("phase") == "build":
                view = BossBuildView(self.author, self.guild_info)
                return await interaction.response.edit_message(
                    embed=await view.get_embed(), view=view
                )
            view = BossTrainingRunView(self.author, self.guild_info)
            return await interaction.response.edit_message(
                embeds=await view.get_embeds(), view=view
            )
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
        self.inheritance_bosses: list[dict[str, Any]] = []
        self.parent_ids: list[str] = []
        self.scenario_id = "normal"

    async def setup(self, user_data):
        self.user_data = user_data
        self.guild_supports = await get_public_supports(self.guild_info["guild_id"], self.author.id)
        self.inheritance_bosses = await list_inheritance_parent_bosses(
            self.author.id,
            self.guild_info["guild_id"],
        )
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
                    discord.SelectOption(
                        label=str(char.get("name", "이름 없음"))[:100],
                        value=str(index),
                        description=(
                            f"주력 {GROWTH_LABELS[_support_specialty(char)]} · "
                            f"장착 {', '.join(char.get('equipped_cards', []) or ['없음'])}"
                        )[:100],
                    )
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
                        description=(
                            f"주력 {GROWTH_LABELS.get(support['specialty'], support['specialty'])} · "
                            f"장착 {', '.join(support.get('equipped_cards', []) or ['없음'])}"
                        )[:100],
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
        advanced = Button(label="🧬 계승·시나리오", style=discord.ButtonStyle.primary, row=3)

        async def open_advanced(interaction):
            view = BossAdvancedSetupView(self)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)

        advanced.callback = open_advanced
        self.add_item(advanced)
        start = Button(label="🌱 70턴 육성 시작", style=discord.ButtonStyle.success, row=3)
        start.callback = self.start
        self.add_item(start)
        back = Button(label="뒤로", style=discord.ButtonStyle.secondary, row=4)
        back.callback = self.back
        self.add_item(back)

    def get_embed(self, message: str | None = None) -> discord.Embed:
        state = ensure_boss_training_data(self.user_data)
        own_lines = []
        for index in self.own_indices:
            if index >= len(self.user_data.get("characters", [])):
                continue
            character = self.user_data["characters"][index]
            cards = ", ".join(character.get("equipped_cards", []) or ["없음"])
            own_lines.append(
                f"• **{character.get('name', '이름 없음')}** · "
                f"주력 {GROWTH_LABELS[_support_specialty(character)]} · 장착 {cards}"
            )
        if self.guild_index is not None:
            support = self.guild_supports[self.guild_index]
            cards = ", ".join(support.get("equipped_cards", []) or ["없음"])
            borrowed = (
                f"• **{support['name']}** (+{support['upgrade']}강) · "
                f"주력 {GROWTH_LABELS.get(support['specialty'], support['specialty'])} · 장착 {cards}"
            )
        else:
            borrowed = "• 미선택"
        growth_text = " · ".join(f"{GROWTH_LABELS[key]} +{value}%" for key, value in self.growth_rates.items())
        embed = discord.Embed(
            title="🌱 새 보스 육성 설정",
            description=message or "서포트와 성장 설정을 확정하면 비용이 차감되고 1턴부터 시작합니다.",
            color=discord.Color.green(),
        )
        embed.add_field(name="이름", value=self.boss_name or "미설정", inline=False)
        embed.add_field(
            name="서포트 편성 · 주력/장착 카드 스냅샷",
            value=(
                f"**본인**\n{chr(10).join(own_lines) or '• 미선택'}\n"
                f"**길드 공개**\n{borrowed}"
            )[:1024],
            inline=False,
        )
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
        selected_parents = [
            row for row in self.inheritance_bosses
            if str(row.get("boss_id")) in self.parent_ids
        ]
        scenario = SCENARIOS.get(self.scenario_id, SCENARIOS["normal"])
        parent_text = ", ".join(
            f"{row.get('boss_name')} [{row.get('grade')}] · "
            f"{inheritance_source_label(row)}"
            for row in selected_parents
        ) or "없음"
        embed.add_field(
            name="🧬 계승·시나리오",
            value=(
                f"부모: {parent_text}\n"
                f"시나리오: **{scenario['name']}**"
            ),
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
            current_bosses = await list_inheritance_parent_bosses(
                self.author.id,
                self.guild_info["guild_id"],
            )
            current_ids = {str(row.get("boss_id")) for row in current_bosses}
            if any(parent_id not in current_ids for parent_id in self.parent_ids):
                raise BossTrainingError(
                    "선택한 부모 보스가 판매·비공개되었거나 더 이상 존재하지 않습니다. 고급 설정에서 다시 선택해주세요."
                )
            self.inheritance_bosses = current_bosses

            def create(latest):
                create_training_run(
                    latest, self.boss_name, self.growth_rates, self.own_indices,
                    self.guild_supports[self.guild_index],
                    base_tokens=self.base_tokens, innate_passive=self.innate_passive,
                    parent_records=[
                        row for row in self.inheritance_bosses
                        if str(row.get("boss_id")) in self.parent_ids
                    ],
                    scenario_id=self.scenario_id,
                )

            await mutate_user_data(self.author.id, create, self.author.display_name)
            view = BossTrainingRunView(self.author, self.guild_info)
            await interaction.response.edit_message(
                embeds=await view.get_embeds("육성을 시작했습니다."),
                view=view,
            )
        except Exception as exc:
            await _reply_error(interaction, exc)

    async def back(self, interaction: discord.Interaction):
        view = BossTrainingHubView(self.author, self.guild_info)
        await interaction.response.edit_message(embed=await view.get_embed(), view=view)


class BossAdvancedSetupView(_OwnerView):
    PER_PAGE = 4

    def __init__(self, setup_view: BossSetupView):
        super().__init__(setup_view.author, timeout=300)
        self.setup_view = setup_view
        self.page = 0
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        bosses = self.setup_view.inheritance_bosses
        total_pages = max(1, math.ceil(len(bosses) / self.PER_PAGE))
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * self.PER_PAGE
        for offset, row in enumerate(bosses[start:start + self.PER_PAGE]):
            boss_id = str(row["boss_id"])
            selected = boss_id in self.setup_view.parent_ids
            button = Button(
                label=(
                    f"{'✅ ' if selected else ''}{row['boss_name']} [{row['grade']}] "
                    f"· {inheritance_source_label(row)}"
                )[:80],
                style=discord.ButtonStyle.success if selected else discord.ButtonStyle.secondary,
                row=offset // 2,
            )

            async def toggle(interaction, selected_id=boss_id):
                if selected_id in self.setup_view.parent_ids:
                    self.setup_view.parent_ids.remove(selected_id)
                elif len(self.setup_view.parent_ids) >= 2:
                    return await interaction.response.send_message(
                        "계승 부모는 최대 2체입니다.", ephemeral=True
                    )
                else:
                    self.setup_view.parent_ids.append(selected_id)
                self.rebuild()
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            button.callback = toggle
            self.add_item(button)

        previous = Button(label="이전", disabled=self.page == 0, row=2)
        following = Button(
            label="다음", disabled=self.page >= total_pages - 1, row=2
        )

        async def move(interaction, delta):
            self.page += delta
            self.rebuild()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

        previous.callback = lambda interaction: move(interaction, -1)
        following.callback = lambda interaction: move(interaction, 1)
        self.add_item(previous)
        self.add_item(following)

        state = ensure_boss_training_data(self.setup_view.user_data)
        scenario_options = [
            discord.SelectOption(
                label="일반 시나리오",
                value="normal",
                default=self.setup_view.scenario_id == "normal",
            )
        ]
        if state["shop_unlocks"].get("scenario_facility_expansion"):
            scenario_options.append(
                discord.SelectOption(
                    label="시설 확장 시나리오",
                    value="facility_expansion",
                    description="시설 최대 6 · 훈련 +15% · 평가전 SP +20%",
                    default=self.setup_view.scenario_id == "facility_expansion",
                )
            )
        scenario = Select(
            placeholder="육성 시나리오 선택",
            options=scenario_options,
            row=3,
        )

        async def choose_scenario(interaction):
            self.setup_view.scenario_id = interaction.data["values"][0]
            self.rebuild()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

        scenario.callback = choose_scenario
        self.add_item(scenario)
        back = Button(label="설정으로 돌아가기", style=discord.ButtonStyle.primary, row=4)

        async def go_back(interaction):
            self.setup_view.rebuild()
            await interaction.response.edit_message(
                embed=self.setup_view.get_embed("고급 설정을 저장했습니다."),
                view=self.setup_view,
            )

        back.callback = go_back
        self.add_item(back)

    def get_embed(self) -> discord.Embed:
        bosses = self.setup_view.inheritance_bosses
        total_pages = max(1, math.ceil(len(bosses) / self.PER_PAGE))
        selected = [
            row for row in bosses
            if str(row.get("boss_id")) in self.setup_view.parent_ids
        ]
        factor_lines = []
        for row in selected:
            factors = row.get("boss_data", {}).get("factors", [])
            factor_lines.append(
                f"• **{row['boss_name']} [{row['grade']}]** · "
                f"{inheritance_source_label(row)} · 인자 {len(factors)}개"
            )
        scenario = SCENARIOS.get(
            self.setup_view.scenario_id, SCENARIOS["normal"]
        )
        embed = discord.Embed(
            title="🧬 계승 부모·시나리오 설정",
            description=(
                "내 완성 보스 또는 현재 공개 중인 길드·월드 보스에서 0~2체를 선택합니다. "
                "인자는 시작·35턴·60턴에 각각 판정되며, "
                "육성을 시작하면 부모 정보가 스냅샷으로 고정됩니다."
            ),
            color=discord.Color.purple(),
        )
        embed.add_field(
            name=f"부모 선택 ({len(selected)}/2) · {self.page + 1}/{total_pages}쪽",
            value="\n".join(factor_lines) or "선택하지 않음",
            inline=False,
        )
        embed.add_field(
            name=f"시나리오 · {scenario['name']}",
            value=scenario["description"],
            inline=False,
        )
        for row in selected:
            factors = row.get("boss_data", {}).get("factors", [])
            embed.add_field(
                name=f"🔎 {row['boss_name']} 인자",
                value=(
                    "\n".join(f"• {factor_display_text(factor)}" for factor in factors)
                    or "인자 없음"
                )[:1024],
                inline=False,
            )
        return embed


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
            success_rate = 100 - training_failure_rate(run or {})
            action_buttons = [
                (f"❤️ HP {success_rate}%", "hp", 0),
                (f"⚔️ 공격 {success_rate}%", "attack", 0),
                (f"🛡️ 방어 {success_rate}%", "defense", 0),
                (f"🔮 정신 {success_rate}%", "mental", 0),
                (f"📘 전술 {success_rate}%", "tactics", 0),
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
        factors = Button(label="🧬 인자 확인", style=discord.ButtonStyle.secondary, row=2)

        async def show_factors(interaction):
            data = await get_user_data(self.author.id, self.author.display_name)
            active = ensure_boss_training_data(data).get("active_run")
            if not active:
                return await interaction.response.send_message(
                    "진행 중인 육성이 없습니다.",
                    ephemeral=True,
                )
            await interaction.response.send_message(
                embed=self.make_inheritance_embed(active),
                ephemeral=True,
            )

        factors.callback = show_factors
        self.add_item(factors)
        back = Button(label="허브로", style=discord.ButtonStyle.secondary, row=2)

        async def back_to_hub(interaction):
            hub = BossTrainingHubView(self.author, self.guild_info)
            await interaction.response.edit_message(embed=await hub.get_embed(), view=hub)

        back.callback = back_to_hub
        self.add_item(back)

    @staticmethod
    def make_inheritance_embed(run: dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title="🧬 계승 인자 상세",
            description=(
                "부모 인자는 시작·35턴·60턴에 독립 판정됩니다.\n"
                f"완료 시점: {', '.join(run.get('inheritance_events_done', [])) or '없음'}"
            ),
            color=discord.Color.purple(),
        )
        for parent in run.get("inheritance_parents", []):
            factors = parent.get("factors", [])
            embed.add_field(
                name=f"{parent.get('name', '부모')} [{parent.get('grade', 'C')}]",
                value=(
                    "\n".join(
                        f"• {factor_display_text(factor)}"
                        for factor in factors
                    )
                    or "인자 없음"
                )[:1024],
                inline=False,
            )
        inherited_stats = " · ".join(
            f"{key} +{value}"
            for key, value in run.get("inheritance_totals", {}).get("stats", {}).items()
            if int(value)
        ) or "없음"
        growth_bonus = " · ".join(
            f"{GROWTH_LABELS.get(key, key)} +{value}%"
            for key, value in run.get("inherited_growth_bonus", {}).items()
            if int(value)
        ) or "없음"
        passive_discounts = " · ".join(
            f"{GENERAL_PASSIVES[key][0]} {value}%"
            for key, value in run.get("passive_factor_discounts", {}).items()
            if key in GENERAL_PASSIVES and int(value)
        ) or "없음"
        inherited_hints = sum(
            int(value.get("hint_count", 0))
            for value in run.get("inherited_skill_offers", {}).values()
        )
        embed.add_field(
            name="현재까지 적용된 계승",
            value=(
                f"스탯: {inherited_stats}\n"
                f"성장률: {growth_bonus}\n"
                f"패시브 할인: {passive_discounts}\n"
                f"스킬 힌트 Lv. 합계: {inherited_hints}"
            )[:1024],
            inline=False,
        )
        if not run.get("inheritance_parents"):
            embed.description += "\n선택한 부모 보스가 없습니다."
        return embed

    async def get_embeds(self, message: str | None = None) -> list[discord.Embed]:
        data = await get_user_data(self.author.id, self.author.display_name)
        run = ensure_boss_training_data(data).get("active_run")
        if not run:
            return [discord.Embed(title="육성 정보 없음", color=discord.Color.red())]
        _refresh_support_specialties(run)
        self.rebuild(run)
        energy = max(0, min(100, int(run["energy"])))
        main_embed = discord.Embed(
            title=f"👑 {run['name']} · {int(run['turn'])}/70턴",
            description=message or "훈련을 선택해주세요.",
            color=discord.Color.dark_purple(),
        )
        main_embed.add_field(
            name="현재 능력",
            value=(
                f"HP **{int(run['hp']):,}** · 정신 **{int(run['mental']):,}** · "
                f"공격 **{int(run['attack'])}** · 방어 **{int(run['defense'])}** · "
                f"SP **{int(run['sp'])}**" + (" · 🤕 부상" if run.get("injured") else "")
            ),
            inline=False,
        )
        success_rate = 100 - training_failure_rate(run)
        main_embed.add_field(
            name="훈련 성공률",
            value=(
                f"모든 훈련 **{success_rate}%**"
                + (" · 🤕 부상 페널티 적용 중" if run.get("injured") else "")
            ),
            inline=False,
        )
        if run.get("pending_event_choice"):
            main_embed.add_field(
                name="✨ 연속 이벤트 2단계",
                value=f"{run['pending_event_choice']['name']}의 보상을 선택해주세요.",
                inline=False,
            )
        if run.get("evaluation_results"):
            last = run["evaluation_results"][-1]
            main_embed.add_field(
                name="최근 평가전",
                value=f"{last['rank']} · {'승리' if last['win'] else '패배'} · SP +{last['sp']}",
                inline=False,
            )
        main_embed.add_field(
            name="현재 컨디션",
            value=(
                f"체력 {'🟩' * (energy // 10)}{'⬜' * (10 - energy // 10)} "
                f"**{energy}/100**\n"
                f"기분 {'★' * int(run['mood'])}{'☆' * (5 - int(run['mood']))}"
            ),
            inline=False,
        )

        placement_lines = []
        placements = run.get("support_placements", {})
        for action in GROWTH_KEYS:
            names = []
            for index in placements.get(action, []):
                if not 0 <= int(index) < len(run.get("supports", [])):
                    continue
                support = run["supports"][int(index)]
                friendship = (
                    int(support.get("bond", 0)) >= 80
                    and support.get("specialty") == action
                )
                names.append(
                    f"{'✨💞 ' if friendship else ''}{support.get('name', '서포트')}"
                )
            placement_lines.append(
                f"**{GROWTH_LABELS[action]} 훈련** · {', '.join(names) or '참가 서포트 없음'}"
            )
        bond_lines = []
        for index, support in enumerate(run.get("supports", [])):
            specialty = str(support.get("specialty", "tactics"))
            bond_lines.append(
                f"**{support.get('name', '서포트')}** · "
                f"인연 {int(support.get('bond', 0))}/100 · "
                f"연속 이벤트 {int(support.get('event_stage', 0))}/3 · "
                f"+{int(support.get('upgrade', 0))}강 · "
                f"주력 {GROWTH_LABELS.get(specialty, specialty)}"
            )
        support_embed = discord.Embed(
            title="🤝 훈련별 참가 서포트",
            description="\n".join(placement_lines),
            color=discord.Color.teal(),
        )
        support_embed.add_field(
            name="💞 인연 정보",
            value="\n".join(bond_lines) or "편성된 서포트가 없습니다.",
            inline=False,
        )
        support_embed.set_footer(
            text="✨💞 표시는 해당 주력 분야에서 우정 트레이닝이 가능한 서포트입니다."
        )

        history_lines = []
        for entry in run.get("history", [])[-3:]:
            action_label = TRAINING_ACTIONS.get(
                entry.get("action"), {"label": entry.get("action", "행동")}
            )["label"]
            details = " · ".join(entry.get("logs", [])) or "완료"
            history_lines.append(
                f"**{int(entry.get('turn', 0))}턴 · {action_label}**\n{details}"
            )
        log_text = "\n\n".join(history_lines) or "아직 육성 로그가 없습니다."
        if len(log_text) > 3900:
            log_text = "…(이전 로그 생략)\n" + log_text[-3870:]
        log_embed = discord.Embed(
            title="📜 최근 3턴 육성 로그",
            description=log_text,
            color=discord.Color.orange(),
        )
        return [main_embed, support_embed, log_embed]

    async def get_embed(self, message: str | None = None) -> discord.Embed:
        return (await self.get_embeds(message))[0]

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
                await interaction.edit_original_response(
                    embeds=await self.get_embeds(message),
                    view=self,
                )
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
            await interaction.response.edit_message(
                embeds=await self.get_embeds(result["text"]),
                view=self,
            )
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossSkillNameModal(Modal, title="커스텀 스킬 이름"):
    skill_name = TextInput(label="스킬 이름", min_length=1, max_length=30)

    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        try:
            skill = {
                "name": self.skill_name.value.strip(),
                "dice": deepcopy(self.wizard.dice),
                "effects": list(self.wizard.effects),
                "cooldown": int(self.wizard.cooldown),
                "is_aoe": bool(self.wizard.is_aoe),
                "catalog_kind": "custom",
            }
            cost = skill_sp_cost(skill)
            slot_index = self.wizard.slot_index

            def save(latest):
                run = ensure_boss_training_data(latest).get("active_run")
                if not run or run.get("phase") != "build":
                    raise BossTrainingError("최종 빌드 단계가 아닙니다.")
                skills = ensure_skill_slots(run)
                if (
                    skill["is_aoe"]
                    and sum(
                        1 for index, item in enumerate(skills)
                        if index != slot_index and item.get("is_aoe")
                    ) >= 2
                ):
                    raise BossTrainingError("광역 스킬은 최대 2개입니다.")
                previous = skills[slot_index]
                skills[slot_index] = skill
                try:
                    _require_build_budget(run)
                except Exception:
                    skills[slot_index] = previous
                    raise

            await mutate_user_data(
                self.wizard.author.id, save, self.wizard.author.display_name
            )
            view = BossSkillManagementView(
                self.wizard.author,
                self.wizard.guild_info,
                selected_slot=slot_index,
            )
            await interaction.response.edit_message(
                embed=await view.get_embed(
                    f"{slot_index + 1}번 슬롯에 **{skill['name']}** 저장 · {cost} SP"
                ),
                view=view,
            )
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossSkillWizardView(_OwnerView):
    ACTIONS = (
        ("⚔️ 공격", "attack"),
        ("🛡️ 방어", "defense"),
        ("⚡ 반격", "counter"),
        ("💚 회복", "heal"),
        ("🔮 정신", "mental_heal"),
    )
    TIERS = ((5, 9), (8, 14), (12, 20), (18, 30))
    EFFECTS = (
        ("🩸 출혈", "bleed"),
        ("⚡ 마비", "paralysis"),
        ("💫 기절", "stun"),
        ("❄️ 빙결 2턴", "freeze"),
        ("🧛 흡혈", "lifesteal"),
        ("💥 파괴", "destroy"),
    )

    def __init__(
        self,
        author,
        guild_info,
        slot_index,
        *,
        total_sp: int = 0,
        other_allocated_cost: int = 0,
    ):
        super().__init__(author, timeout=600)
        self.guild_info = guild_info
        self.slot_index = int(slot_index)
        self.stage = "count"
        self.target_dice_count = 0
        self.pending_action: str | None = None
        self.dice: list[dict[str, Any]] = []
        self.effects: list[str] = []
        self.cooldown = 2
        self.is_aoe = False
        self.total_sp = int(total_sp)
        self.other_allocated_cost = int(other_allocated_cost)
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        if self.stage == "count":
            for count in (1, 2, 3):
                button = Button(
                    label=f"주사위 {count}개",
                    style=discord.ButtonStyle.primary,
                    row=0,
                )

                async def choose(interaction, selected=count):
                    self.target_dice_count = selected
                    self.stage = "type"
                    self.rebuild()
                    await interaction.response.edit_message(
                        embed=self.get_embed(), view=self
                    )

                button.callback = choose
                self.add_item(button)
        elif self.stage == "type":
            for label, action in self.ACTIONS:
                button = Button(label=label, style=discord.ButtonStyle.primary, row=0)

                async def choose(interaction, selected=action):
                    self.pending_action = selected
                    self.stage = "tier"
                    self.rebuild()
                    await interaction.response.edit_message(
                        embed=self.get_embed(), view=self
                    )

                button.callback = choose
                self.add_item(button)
        elif self.stage == "tier":
            for low, high in self.TIERS:
                button = Button(
                    label=f"{low}~{high}",
                    style=discord.ButtonStyle.primary,
                    row=0,
                )

                async def choose(interaction, selected_low=low, selected_high=high):
                    self.dice.append({
                        "type": self.pending_action,
                        "min": selected_low,
                        "max": selected_high,
                    })
                    self.pending_action = None
                    self.stage = (
                        "type"
                        if len(self.dice) < self.target_dice_count
                        else "effects"
                    )
                    self.rebuild()
                    await interaction.response.edit_message(
                        embed=self.get_embed(), view=self
                    )

                button.callback = choose
                self.add_item(button)
        elif self.stage == "effects":
            for effect_index, (label, effect) in enumerate(self.EFFECTS):
                button = Button(
                    label=("✅ " if effect in self.effects else "") + label,
                    style=(
                        discord.ButtonStyle.success
                        if effect in self.effects
                        else discord.ButtonStyle.secondary
                    ),
                    row=effect_index // 5,
                )

                async def toggle(interaction, selected=effect):
                    if selected in self.effects:
                        self.effects.remove(selected)
                    elif len(self.effects) < 2:
                        self.effects.append(selected)
                    else:
                        return await interaction.response.send_message(
                            "부가효과는 최대 2개입니다.", ephemeral=True
                        )
                    self.rebuild()
                    await interaction.response.edit_message(
                        embed=self.get_embed(), view=self
                    )

                button.callback = toggle
                self.add_item(button)
            next_button = Button(
                label="효과 선택 완료",
                style=discord.ButtonStyle.primary,
                row=2,
            )

            async def next_stage(interaction):
                self.stage = "cooldown"
                self.rebuild()
                await interaction.response.edit_message(
                    embed=self.get_embed(), view=self
                )

            next_button.callback = next_stage
            self.add_item(next_button)
        elif self.stage == "cooldown":
            for value in (1, 2, 3, 4):
                button = Button(
                    label=f"쿨다운 {value}턴",
                    style=discord.ButtonStyle.primary,
                    row=0,
                )

                async def choose(interaction, selected=value):
                    self.cooldown = selected
                    self.stage = "area"
                    self.rebuild()
                    await interaction.response.edit_message(
                        embed=self.get_embed(), view=self
                    )

                button.callback = choose
                self.add_item(button)
        elif self.stage == "area":
            for label, aoe in (("🗡️ 단일", False), ("☄️ 광역", True)):
                button = Button(label=label, style=discord.ButtonStyle.danger, row=0)

                async def choose(interaction, selected=aoe):
                    if selected and self.cooldown < 2:
                        return await interaction.response.send_message(
                            "광역 스킬의 최소 쿨다운은 2턴입니다.",
                            ephemeral=True,
                        )
                    self.is_aoe = selected
                    self.stage = "name"
                    self.rebuild()
                    await interaction.response.edit_message(
                        embed=self.get_embed(), view=self
                    )

                button.callback = choose
                self.add_item(button)
        elif self.stage == "name":
            name_button = Button(
                label="✍️ 스킬 이름 입력",
                style=discord.ButtonStyle.success,
                row=0,
            )
            name_button.callback = (
                lambda interaction: interaction.response.send_modal(
                    BossSkillNameModal(self)
                )
            )
            self.add_item(name_button)
        cancel = Button(label="취소", style=discord.ButtonStyle.secondary, row=4)

        async def cancel_build(interaction):
            view = BossSkillManagementView(
                self.author, self.guild_info, selected_slot=self.slot_index
            )
            await interaction.response.edit_message(
                embed=await view.get_embed("커스텀 제작을 취소했습니다."),
                view=view,
            )

        cancel.callback = cancel_build
        self.add_item(cancel)

    def get_embed(self) -> discord.Embed:
        action_labels = dict((value, label) for label, value in self.ACTIONS)
        dice_text = " ➜ ".join(
            f"{action_labels.get(item['type'], item['type'])} {item['min']}~{item['max']}"
            for item in self.dice
        ) or "미선택"
        stage_labels = {
            "count": "주사위 개수를 선택하세요.",
            "type": f"{len(self.dice) + 1}번째 주사위 종류를 선택하세요.",
            "tier": f"{len(self.dice) + 1}번째 주사위 위력 구간을 선택하세요.",
            "effects": "부가효과를 최대 2개 선택하세요.",
            "cooldown": "재사용 대기시간을 선택하세요.",
            "area": "단일 또는 광역을 선택하면 마지막으로 이름만 입력합니다.",
            "name": "최종 SP 비용을 확인한 뒤 스킬 이름만 입력하세요.",
        }
        effects = ", ".join(self.effects) or "없음"
        current_cost = 0
        if self.dice:
            current_cost = skill_sp_cost({
                "name": "설계 중",
                "dice": self.dice,
                "effects": self.effects,
                "cooldown": self.cooldown,
                "is_aoe": self.is_aoe,
            })
        projected_remaining = self.total_sp - self.other_allocated_cost - current_cost
        estimate_note = (
            "\n※ 쿨다운과 범위를 고르기 전에는 **쿨다운 2턴·단일** 기준 예상값입니다."
            if self.stage in {"count", "type", "tier", "effects", "cooldown"}
            else ""
        )
        embed = discord.Embed(
            title=f"🧰 커스텀 스킬 제작 · 슬롯 {self.slot_index + 1}",
            description=stage_labels[self.stage],
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="현재 설계",
            value=(
                f"주사위: {dice_text}\n효과: {effects}\n"
                f"쿨다운: {self.cooldown}턴 · 범위: {'광역' if self.is_aoe else '단일'}"
            ),
            inline=False,
        )
        embed.add_field(
            name="SP 예상",
            value=(
                f"보유 **{self.total_sp:,}** · 다른 배정 **{self.other_allocated_cost:,}**\n"
                f"현재 설계 비용 **{current_cost:,}** · 전체 배정 예상 "
                f"**{self.other_allocated_cost + current_cost:,}**\n"
                f"저장 후 남은 SP "
                f"**{projected_remaining:,}**{estimate_note}"
            ),
            inline=False,
        )
        return embed


class BossSkillManagementView(_OwnerView):
    def __init__(self, author, guild_info, selected_slot=0):
        super().__init__(author, timeout=600)
        self.guild_info = guild_info
        self.selected_slot = max(0, min(4, int(selected_slot)))
        self.run: dict[str, Any] | None = None
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        for index in range(5):
            button = Button(
                label=f"{'✅ ' if index == self.selected_slot else ''}{index + 1}번",
                style=(
                    discord.ButtonStyle.success
                    if index == self.selected_slot
                    else discord.ButtonStyle.secondary
                ),
                row=0,
            )

            async def choose(interaction, selected=index):
                self.selected_slot = selected
                self.rebuild()
                await interaction.response.edit_message(
                    embed=await self.get_embed(), view=self
                )

            button.callback = choose
            self.add_item(button)
        custom = Button(label="🧰 커스텀 제작", style=discord.ButtonStyle.primary, row=1)

        async def open_custom(interaction):
            data = await get_user_data(self.author.id, self.author.display_name)
            run = ensure_boss_training_data(data).get("active_run")
            if not run:
                return await _reply_error(
                    interaction, BossTrainingError("진행 중인 최종 빌드가 없습니다.")
                )
            skills = ensure_skill_slots(run)
            allocated = _build_sp_cost(run, run.get("build", {}))
            old_cost = skill_sp_cost(skills[self.selected_slot])
            view = BossSkillWizardView(
                self.author,
                self.guild_info,
                self.selected_slot,
                total_sp=int(run.get("sp", 0)),
                other_allocated_cost=max(0, allocated - old_cost),
            )
            await interaction.response.edit_message(embed=view.get_embed(), view=view)

        custom.callback = open_custom
        self.add_item(custom)
        hints = Button(label="💡 힌트 프리셋", style=discord.ButtonStyle.success, row=1)

        async def open_hints(interaction):
            view = BossHintCatalogView(
                self.author, self.guild_info, self.selected_slot
            )
            await interaction.response.edit_message(
                embed=await view.get_embed(), view=view
            )

        hints.callback = open_hints
        self.add_item(hints)
        restore = Button(label="↩️ 기본기 복원", style=discord.ButtonStyle.secondary, row=1)
        restore.callback = self.restore
        self.add_item(restore)
        back = Button(label="최종 빌드로", style=discord.ButtonStyle.secondary, row=2)

        async def back_to_build(interaction):
            view = BossBuildView(self.author, self.guild_info)
            await interaction.response.edit_message(
                embed=await view.get_embed(), view=view
            )

        back.callback = back_to_build
        self.add_item(back)

    async def get_embed(self, message: str | None = None) -> discord.Embed:
        data = await get_user_data(self.author.id, self.author.display_name)
        run = ensure_boss_training_data(data).get("active_run")
        if not run:
            return discord.Embed(title="스킬 편집 정보 없음", color=discord.Color.red())
        skills = ensure_skill_slots(run)
        self.run = run
        lines = [
            f"{'▶' if index == self.selected_slot else '•'} **{index + 1}. {skill['name']}**"
            f" · {skill_sp_cost(skill)} SP"
            f"{' · 광역' if skill.get('is_aoe') else ''}"
            for index, skill in enumerate(skills)
        ]
        owned, allocated, remaining = _sp_summary(run)
        embed = discord.Embed(
            title="🎴 보스 스킬 슬롯 편집",
            description=message or (
                "슬롯을 고른 뒤 커스텀 제작, 발견한 힌트 프리셋 구매, "
                "기본기 복원 중 하나를 선택하세요."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="SP 현황",
            value=(
                f"보유 **{owned:,}** · 전체 배정 **{allocated:,}** · "
                f"남은 **{remaining:,} SP**"
            ),
            inline=False,
        )
        embed.add_field(name="현재 5개 슬롯", value="\n".join(lines), inline=False)
        return embed

    async def restore(self, interaction):
        try:
            slot = self.selected_slot

            def apply(latest):
                run = ensure_boss_training_data(latest).get("active_run")
                if not run or run.get("phase") != "build":
                    raise BossTrainingError("최종 빌드 단계가 아닙니다.")
                restore_default_skill(run, slot)

            await mutate_user_data(
                self.author.id, apply, self.author.display_name
            )
            await interaction.response.edit_message(
                embed=await self.get_embed(
                    f"{slot + 1}번 슬롯을 무료 기본기로 복원했습니다."
                ),
                view=self,
            )
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossHintCatalogView(_OwnerView):
    PER_PAGE = 4

    def __init__(self, author, guild_info, slot_index):
        super().__init__(author, timeout=600)
        self.guild_info = guild_info
        self.slot_index = int(slot_index)
        self.page = 0
        self.offers: list[dict[str, Any]] = []

    def rebuild(self):
        self.clear_items()
        total_pages = max(1, math.ceil(len(self.offers) / self.PER_PAGE))
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * self.PER_PAGE
        for offer in self.offers[start:start + self.PER_PAGE]:
            cost = _discounted_cost(offer["base_cost"], offer["hint_count"])
            button = Button(
                label=f"{offer['name']} · {cost}SP"[:80],
                style=discord.ButtonStyle.success,
                row=0,
            )

            async def purchase(interaction, offer_id=offer["offer_id"]):
                await self.purchase(interaction, offer_id)

            button.callback = purchase
            self.add_item(button)
        previous = Button(
            label="이전",
            disabled=self.page == 0,
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        following = Button(
            label="다음",
            disabled=self.page >= total_pages - 1,
            style=discord.ButtonStyle.secondary,
            row=1,
        )

        async def move(interaction, delta):
            self.page += delta
            self.rebuild()
            await interaction.response.edit_message(
                embed=await self.get_embed(), view=self
            )

        previous.callback = lambda interaction: move(interaction, -1)
        following.callback = lambda interaction: move(interaction, 1)
        self.add_item(previous)
        self.add_item(following)
        back = Button(label="스킬 슬롯으로", style=discord.ButtonStyle.secondary, row=1)

        async def go_back(interaction):
            view = BossSkillManagementView(
                self.author, self.guild_info, selected_slot=self.slot_index
            )
            await interaction.response.edit_message(
                embed=await view.get_embed(), view=view
            )

        back.callback = go_back
        self.add_item(back)

    async def get_embed(self) -> discord.Embed:
        data = await get_user_data(self.author.id, self.author.display_name)
        run = ensure_boss_training_data(data).get("active_run")
        if not run:
            return discord.Embed(title="힌트 정보 없음", color=discord.Color.red())
        self.offers = available_skill_offers(run)
        self.rebuild()
        owned, allocated, remaining = _sp_summary(run)
        start = self.page * self.PER_PAGE
        lines = []
        for offer in self.offers[start:start + self.PER_PAGE]:
            discount = _hint_discount(offer["hint_count"])
            cost = _discounted_cost(offer["base_cost"], offer["hint_count"])
            kind = {
                "equipped": "장착 카드",
                "base_change": "기본기 변경",
                "base_upgrade": "기본기 강화",
                "special": "특수능력 프리셋",
            }.get(offer.get("catalog_kind"), "프리셋")
            lines.append(
                f"**{offer['name']}** · {kind}\n"
                f"힌트 Lv.{offer['hint_count']} · {discount}% 할인 · "
                f"{offer['base_cost']} → **{cost} SP**"
            )
        embed = discord.Embed(
            title=f"💡 발견한 스킬 힌트 · 슬롯 {self.slot_index + 1}",
            description=(
                "\n\n".join(lines)
                if lines
                else "아직 발견한 힌트가 없습니다. 서포트 연속 이벤트와 공개 서포트 훈련에서 얻을 수 있습니다."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="SP 현황",
            value=(
                f"보유 **{owned:,}** · 전체 배정 **{allocated:,}** · "
                f"남은 **{remaining:,} SP**\n"
                "구매 시 선택 슬롯의 기존 스킬 비용을 먼저 제외합니다."
            ),
            inline=False,
        )
        return embed

    async def purchase(self, interaction, offer_id):
        try:
            slot = self.slot_index
            result: dict[str, Any] = {}

            def apply(latest):
                run = ensure_boss_training_data(latest).get("active_run")
                if not run or run.get("phase") != "build":
                    raise BossTrainingError("최종 빌드 단계가 아닙니다.")
                result.update(purchase_skill_offer(run, offer_id, slot))

            await mutate_user_data(
                self.author.id, apply, self.author.display_name
            )
            view = BossSkillManagementView(
                self.author, self.guild_info, selected_slot=slot
            )
            await interaction.response.edit_message(
                embed=await view.get_embed(
                    f"{slot + 1}번 슬롯에 **{result['name']}** 구매 · "
                    f"{result['purchase_cost']} SP ({result['hint_discount']}% 할인)"
                ),
                view=view,
            )
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossResistanceModal(Modal, title="상태이상 저항 설정"):
    resistances = TextInput(
        label="각 상태 0/25/50/75",
        default="bleed:0, paralysis:0, stun:0, freeze:0",
        max_length=100,
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
                    raise BossTrainingError(
                        "저항은 bleed/paralysis/stun/freeze에 0/25/50/75만 설정할 수 있습니다."
                    )
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
                discord.SelectOption(
                    label=(
                        f"{label} · "
                        f"{math.ceil(cost * (100 - min(50, int((run or {}).get('passive_factor_discounts', {}).get(key, 0)))) / 100)} SP"
                    ),
                    value=key,
                    description=(
                        (
                            f"계승 할인 {int((run or {}).get('passive_factor_discounts', {}).get(key, 0))}% · "
                            if int((run or {}).get("passive_factor_discounts", {}).get(key, 0))
                            else ""
                        )
                        + desc
                    )[:100],
                )
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
        skill_editor = Button(label="🎴 스킬 편집", style=discord.ButtonStyle.primary, row=3)

        async def open_skill_editor(interaction):
            view = BossSkillManagementView(self.author, self.guild_info)
            await interaction.response.edit_message(
                embed=await view.get_embed(),
                view=view,
            )

        skill_editor.callback = open_skill_editor
        self.add_item(skill_editor)
        reset = Button(label="↩️ 기본기 전체 복원", style=discord.ButtonStyle.secondary, row=3)
        reset.callback = self.reset_skills
        self.add_item(reset)
        resistance = Button(label="🧪 저항", style=discord.ButtonStyle.secondary, row=3)
        resistance.callback = lambda interaction: interaction.response.send_modal(BossResistanceModal(self))
        self.add_item(resistance)
        ai = Button(label="🤖 AI 변경", style=discord.ButtonStyle.secondary, row=3)
        ai.callback = self.rotate_ai
        self.add_item(ai)
        finish = Button(label="✅ 던전 제작으로", style=discord.ButtonStyle.success, row=4)
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
        def reset(run):
            run["build"]["skills"] = _default_skills()
            run["build"]["skill_slots_initialized"] = True

        await self._update(interaction, reset, "5개 슬롯을 무료 기본기로 모두 복원했습니다.")

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
        skill_slots = ensure_skill_slots(run)
        try:
            cost = _build_sp_cost(run, build)
            cost_text = (
                f"보유 **{int(run['sp']):,}** · 전체 배정 **{cost:,}** · "
                f"남은 **{int(run['sp']) - cost:,} SP**"
            )
        except BossTrainingError as exc:
            cost_text = f"오류: {exc}"
        skills = [
            f"{index}. **{skill['name']}** · {skill_sp_cost(skill)} SP"
            f"{' · 광역' if skill.get('is_aoe') else ''}"
            for index, skill in enumerate(skill_slots, 1)
        ]
        hint_levels = (
            sum(int(value) for value in run.get("skill_hints", {}).values())
            + sum(int(value) for value in run.get("base_skill_hints", {}).values())
            + sum(int(value) for value in run.get("base_upgrade_hints", {}).values())
            + sum(int(value) for value in run.get("special_preset_hints", {}).values())
            + sum(
                int(value.get("hint_count", 0))
                for value in run.get("inherited_skill_offers", {}).values()
            )
        )
        offer_count = len(available_skill_offers(run))
        immunity = IMMUNITIES.get(build.get("immunity"), ("없음", 0))[0]
        resistance = ", ".join(f"{IMMUNITIES[key][0]} {value}%" for key, value in build.get("resistances", {}).items()) or "없음"
        passive_names = [
            (
                f"{GENERAL_PASSIVES[key][0]}"
                f"(-{int(run.get('passive_factor_discounts', {}).get(key, 0))}%)"
                if int(run.get("passive_factor_discounts", {}).get(key, 0))
                else GENERAL_PASSIVES[key][0]
            )
            for key in build.get("passives", [])
        ]
        embed = discord.Embed(
            title=f"🧩 {run['name']} 최종 빌드",
            description=message or (
                "스킬 편집에서 슬롯을 고른 뒤 버튼으로 커스텀 기술을 만들거나, "
                "육성 중 발견한 힌트 프리셋을 구매할 수 있습니다."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="SP", value=cost_text, inline=False)
        embed.add_field(name="스킬 슬롯", value="\n".join(skills), inline=False)
        embed.add_field(
            name="발견한 힌트",
            value=f"구매 가능 프리셋 **{offer_count}개** · 누적 힌트 Lv. **{hint_levels}**",
            inline=False,
        )
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
        embed.add_field(
            name="상향된 평가 등급컷",
            value=(
                "B 4,500 · A 6,000 · S 7,500 · SS 9,000 · "
                "UG 11,000 · UF 13,000"
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
                builder_state = default_dungeon_builder_state(boss)

                def advance(current):
                    state = ensure_boss_training_data(current)
                    active = state.get("active_run")
                    if active and active.get("run_id") == run.get("run_id"):
                        active["phase"] = "dungeon_build"
                        active["dungeon_builder"] = builder_state

                await mutate_user_data(self.author.id, advance, self.author.display_name)
                view = BossDungeonBuilderView(
                    self.author,
                    self.guild_info,
                    active_run=True,
                )
                await view.setup()
                await interaction.edit_original_response(
                    embed=view.get_embed(
                        f"보스 빌드를 잠갔습니다. 평가 {boss['power_score']:,}점을 "
                        "세 몬스터에게 배분해주세요."
                    ),
                    view=view,
                )
            except Exception as exc:
                await _reply_error(interaction, exc)

    async def back(self, interaction):
        hub = BossTrainingHubView(self.author, self.guild_info)
        await interaction.response.edit_message(embed=await hub.get_embed(), view=hub)


class DungeonMonsterNameModal(Modal, title="던전 몬스터 이름"):
    monster_name = TextInput(label="몬스터 이름", min_length=2, max_length=30)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.monster_name.default = parent.state["names"][parent.selected_slot]

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.parent.update_state(
                interaction,
                lambda state: state["names"].__setitem__(
                    self.parent.selected_slot, self.monster_name.value.strip()
                ),
                "몬스터 이름을 변경했습니다.",
            )
        except Exception as exc:
            await _reply_error(interaction, exc)


class BossDungeonBuilderView(_OwnerView):
    """One-time, deterministic three-monster dungeon builder."""

    def __init__(
        self,
        author,
        guild_info,
        *,
        active_run: bool,
        record: dict[str, Any] | None = None,
    ):
        super().__init__(author, timeout=600)
        self.guild_info = guild_info
        self.active_run = active_run
        self.record = record
        self.state: dict[str, Any] = {}
        self.selected_slot = 0
        self.confirm_lock = asyncio.Lock()

    async def setup(self):
        if self.active_run:
            data = await get_user_data(self.author.id, self.author.display_name)
            run = ensure_boss_training_data(data).get("active_run")
            if not run or run.get("phase") != "dungeon_build":
                raise BossTrainingError("진행 중인 던전 제작이 없습니다.")
            if not run.get("dungeon_builder"):
                raise BossTrainingError("던전 제작 초안이 없습니다.")
            self.state = deepcopy(run["dungeon_builder"])
        else:
            if not self.record:
                raise BossTrainingError("제작할 기존 보스를 찾지 못했습니다.")
            boss = deepcopy(self.record.get("boss_data", {}))
            boss.setdefault("boss_id", self.record.get("boss_id"))
            boss.setdefault("name", self.record.get("boss_name", "육성 보스"))
            boss.setdefault("grade", self.record.get("grade", "C"))
            boss.setdefault("power_score", int(self.record.get("power_score", 0)))
            if dungeon_is_ready(boss):
                raise BossTrainingError("이미 확정된 던전은 다시 편집할 수 없습니다.")
            self.state = default_dungeon_builder_state(boss)
        self.rebuild()

    @property
    def boss(self) -> dict[str, Any]:
        return self.state["boss"]

    def rebuild(self):
        self.clear_items()
        slot_select = Select(
            placeholder=f"{self.selected_slot + 1}번 몬스터 편집 중",
            options=[
                discord.SelectOption(
                    label=f"{index + 1}층 · {self.state['names'][index]}"[:100],
                    value=str(index),
                    default=index == self.selected_slot,
                )
                for index in range(3)
            ],
            row=0,
        )

        async def choose_slot(interaction):
            self.selected_slot = int(interaction.data["values"][0])
            self.rebuild()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

        slot_select.callback = choose_slot
        self.add_item(slot_select)

        role_select = Select(
            placeholder="전투 역할 선택",
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    default=self.state["roles"][self.selected_slot] == key,
                )
                for key, label in DUNGEON_ROLE_LABELS.items()
            ],
            row=1,
        )

        async def choose_role(interaction):
            value = interaction.data["values"][0]
            await self.update_state(
                interaction,
                lambda state: state["roles"].__setitem__(self.selected_slot, value),
                "몬스터 역할을 변경했습니다.",
            )

        role_select.callback = choose_role
        self.add_item(role_select)

        share_select = Select(
            placeholder="평가점 배분 선택",
            options=[
                discord.SelectOption(
                    label=f"{value}% · {math.floor(int(self.boss['power_score']) * value / 100):,}점",
                    value=str(value),
                    default=int(self.state["shares"][self.selected_slot]) == value,
                )
                for value in range(20, 61, 5)
            ],
            row=2,
        )

        async def choose_share(interaction):
            value = int(interaction.data["values"][0])
            await self.update_state(
                interaction,
                lambda state: state["shares"].__setitem__(self.selected_slot, value),
                "점수 배분을 변경했습니다.",
            )

        share_select.callback = choose_share
        self.add_item(share_select)

        all_factors = eligible_dungeon_factors(self.boss)
        selected_keys = set(self.state["factor_keys"][self.selected_slot])
        assigned_elsewhere = {
            key: index
            for index, keys in enumerate(self.state["factor_keys"])
            if index != self.selected_slot
            for key in keys
        }
        factor_select = Select(
            placeholder="계승 인자 1~2개 선택",
            min_values=1,
            max_values=min(2, len(all_factors)),
            options=[
                discord.SelectOption(
                    label=factor_display_text(factor)[:100],
                    value=dungeon_factor_token(factor),
                    description=(
                        f"{assigned_elsewhere[dungeon_factor_token(factor)] + 1}층에 배정됨 · 선택 시 이동"
                        if dungeon_factor_token(factor) in assigned_elsewhere
                        else "처치 시 공격대가 원정 동안 계승"
                    )[:100],
                    default=dungeon_factor_token(factor) in selected_keys,
                )
                for factor in all_factors[:25]
            ],
            row=3,
        )

        async def choose_factors(interaction):
            values = list(interaction.data.get("values", []))

            def assign(state):
                for index, keys in enumerate(state["factor_keys"]):
                    if index != self.selected_slot:
                        state["factor_keys"][index] = [
                            key for key in keys if key not in values
                        ]
                state["factor_keys"][self.selected_slot] = values

            await self.update_state(interaction, assign, "계승 인자를 배정했습니다.")

        factor_select.callback = choose_factors
        self.add_item(factor_select)

        rename = Button(label="✏️ 이름", style=discord.ButtonStyle.secondary, row=4)
        rename.callback = lambda interaction: interaction.response.send_modal(
            DungeonMonsterNameModal(self)
        )
        self.add_item(rename)
        confirm = Button(label="🔒 최종 확정", style=discord.ButtonStyle.success, row=4)
        confirm.callback = self.confirm
        self.add_item(confirm)
        back = Button(label="허브로", style=discord.ButtonStyle.secondary, row=4)
        back.callback = self.back
        self.add_item(back)

    async def update_state(self, interaction, updater, message: str):
        updater(self.state)
        if self.active_run:
            snapshot = deepcopy(self.state)

            def save(latest):
                run = ensure_boss_training_data(latest).get("active_run")
                if not run or run.get("phase") != "dungeon_build":
                    raise BossTrainingError("진행 중인 던전 제작이 없습니다.")
                run["dungeon_builder"] = snapshot

            await mutate_user_data(self.author.id, save, self.author.display_name)
        self.rebuild()
        await interaction.response.edit_message(
            embed=self.get_embed(message),
            view=self,
        )

    def get_embed(self, message: str | None = None) -> discord.Embed:
        shares = [int(value) for value in self.state.get("shares", [])]
        total = sum(shares)
        embed = discord.Embed(
            title=f"🏰 {self.boss.get('name', '보스')} 던전 제작",
            description=message or (
                "몬스터 이름만 입력하고 역할·점수·인자를 선택하면 "
                "스탯과 기술이 고정 시드로 자동 생성됩니다."
            ),
            color=discord.Color.dark_purple(),
        )
        embed.add_field(
            name="제작 예산",
            value=(
                f"보스 평가 **{int(self.boss['power_score']):,}점** · "
                f"현재 배분 **{total}%**\n"
                "각 20~60%, 5% 단위 · 합계 100%"
            ),
            inline=False,
        )
        configs = dungeon_builder_configs(self.state)
        for index, config in enumerate(configs):
            try:
                monster = generate_dungeon_monster(
                    self.boss,
                    slot=index,
                    name=config["name"],
                    role=config["role"],
                    share=config["share"],
                    factors=config["factors"],
                )
                skills = ", ".join(skill["name"] for skill in monster["skills"])
                factors = "\n".join(
                    f"• {factor_display_text(factor)}"
                    for factor in monster["factors"]
                )
                value = (
                    f"{monster['role_label']} · {monster['share']}% · "
                    f"목표 {monster['target_score']:,}점\n"
                    f"HP {monster['hp']:,} · 정신 {monster['mental']:,} · "
                    f"공격 {monster['attack']} · 방어 {monster['defense']}\n"
                    f"기술: {skills}\n{factors}"
                )
            except BossTrainingError as exc:
                value = f"⚠️ {exc}"
            embed.add_field(
                name=f"{'➡️ ' if index == self.selected_slot else ''}{index + 1}층 · {config['name']}",
                value=value[:1024],
                inline=False,
            )
        embed.add_field(
            name="4층 · 혼합 엘리트",
            value=(
                f"세 종의 대표 기술 + 혼합 광역기 · "
                f"목표 {math.floor(int(self.boss['power_score']) * 0.8):,}점\n"
                "처치 시 추가 인자는 지급하지 않습니다."
            ),
            inline=False,
        )
        return embed

    async def confirm(self, interaction):
        async with self.confirm_lock:
            try:
                dungeon = build_dungeon_spec(
                    self.boss,
                    dungeon_builder_configs(self.state),
                )
                await interaction.response.defer()
                if self.active_run:
                    boss = deepcopy(self.boss)
                    boss["dungeon"] = dungeon
                    await save_completed_boss(
                        self.author.id,
                        self.guild_info["guild_id"],
                        boss,
                    )

                    def clear(latest):
                        state = ensure_boss_training_data(latest)
                        active = state.get("active_run")
                        if active and active.get("phase") == "dungeon_build":
                            state["active_run"] = None

                    await mutate_user_data(
                        self.author.id, clear, self.author.display_name
                    )
                    message = (
                        f"🎉 **{boss['name']}** 던전 완성 · {boss['grade']} 등급 · "
                        f"평가 {boss['power_score']:,}"
                    )
                else:
                    await save_legacy_boss_dungeon(
                        self.author.id,
                        self.record["boss_id"],
                        dungeon,
                    )
                    message = "기존 보스의 5층 던전을 확정했습니다. 이제 다시 공개할 수 있습니다."
                hub = BossTrainingHubView(self.author, self.guild_info)
                await interaction.edit_original_response(
                    embed=await hub.get_embed(message),
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
        dungeon = Button(label="🏰 던전 제작", style=discord.ButtonStyle.primary, row=2)
        dungeon.callback = self.build_dungeon
        self.add_item(dungeon)
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
            factors = data.get("factors", [])
            embed.add_field(
                name="🧬 보유 인자",
                value=(
                    "\n".join(f"• {factor_display_text(factor)}" for factor in factors)
                    or "인자 없음"
                )[:1024],
                inline=False,
            )
            dungeon = data.get("dungeon", {})
            if dungeon_is_ready(data):
                floor_lines = [
                    f"{index}. **{monster['name']}** · {monster.get('role_label', monster.get('role'))} "
                    f"· {int(monster.get('target_score', 0)):,}점"
                    for index, monster in enumerate(dungeon.get("monsters", []), 1)
                ]
                floor_lines.append(
                    f"4. **{dungeon.get('elite', {}).get('name', '혼합 엘리트')}** · "
                    f"{int(dungeon.get('elite', {}).get('target_score', 0)):,}점"
                )
                floor_lines.append(f"5. **{row['boss_name']}**")
                dungeon_text = "\n".join(floor_lines)
            else:
                dungeon_text = (
                    "⚠️ 던전 미제작 · 공개하려면 몬스터 3종을 한 번 확정해야 합니다."
                )
            embed.add_field(
                name="🏰 5층 던전",
                value=dungeon_text[:1024],
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

    async def build_dungeon(self, interaction):
        row = self.selected()
        if not row:
            return await _reply_error(
                interaction, BossTrainingError("던전을 제작할 보스를 선택해주세요.")
            )
        if dungeon_is_ready(row.get("boss_data", {})):
            return await _reply_error(
                interaction, BossTrainingError("이미 확정된 던전은 다시 편집할 수 없습니다.")
            )
        view = BossDungeonBuilderView(
            self.author,
            self.guild_info,
            active_run=False,
            record=row,
        )
        await view.setup()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

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
        embed = discord.Embed(
            title=f"⚔️ {'월드' if self.scope == 'world' else '길드'} 유저 보스",
            description="\n".join(lines) or "현재 공개된 보스가 없습니다.",
            color=discord.Color.red(),
        )
        selected = next(
            (row for row in self.records if row["boss_id"] == self.selected_id),
            None,
        )
        if selected and dungeon_is_ready(selected.get("boss_data", {})):
            dungeon = selected["boss_data"]["dungeon"]
            floor_lines = []
            for index, monster in enumerate(dungeon["monsters"], 1):
                factors = ", ".join(
                    factor_display_text(factor)
                    for factor in monster.get("factors", [])
                )
                floor_lines.append(
                    f"{index}. **{monster['name']}** · {monster.get('role_label')} "
                    f"· {factors or '인자 없음'}"
                )
            floor_lines.append(f"4. **{dungeon['elite']['name']}** · 혼합 엘리트")
            floor_lines.append(f"5. **{selected['boss_name']}** · 최종 보스")
            embed.add_field(
                name="🏰 5층 구성·계승 인자",
                value="\n".join(floor_lines)[:1024],
                inline=False,
            )
        return embed

    async def toggle_scope(self, interaction):
        self.scope = "world" if self.scope == "guild" else "guild"
        await self.setup()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def challenge(self, interaction):
        try:
            record = next((row for row in self.records if row["boss_id"] == self.selected_id), None)
            if not record:
                raise BossTrainingError("도전할 보스를 선택해주세요.")
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
            discord.SelectOption(
                label="시설 확장 시나리오 적용권 · 600,000 PT",
                value="scenario_facility_expansion",
                description="시설 최대 6 · 훈련 +15% · 평가전 SP +20%",
            ),
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
        prices = {
            "base_stat_license": 100_000,
            "growth_license": 200_000,
            "scenario_facility_expansion": 600_000,
        }
        prices.update({key: data[1] for key, data in INNATE_PASSIVES.items()})
        names = {
            "base_stat_license": "기본 스탯 설정권",
            "growth_license": "성장률 설정권",
            "scenario_facility_expansion": "시설 확장 시나리오 적용권",
        }
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
