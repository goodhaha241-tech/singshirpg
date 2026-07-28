# economy-exchange-v9.4
# fish-quality-v9.3.1
# cafe-tycoon-v9.2
# ripple-artifact-v8.7
# cumulative-v3-life-system
# rollback-guard-appraisal-gems-v8
# appraisal-gem-affixes-v8.1
# pve-gem-runtime-v8.2
# gem-visibility-tools-v8.3
# comparison-select-ui-v8.6.6
# life-button-ui-v8.5
from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any

import discord

from character import (
    GEM_MAIN_STAT_LABELS,
    ensure_gem_stat_affixes,
    gem_main_stat_text,
    roll_gem_stat_affixes,
)
from data_manager import StaleUserDataError, advance_world_turn, get_user_data
from gem_effects import (
    gem_final_aux_value,
    gem_final_effect_value,
)
from navigation_v7 import attach_navigation

# guild-pvp-stability-v7.2


PURE_HOPE_ITEM = "순수한 희망"
PURE_HOPE_PRICE = 1_000_000
RAW_STONE_ITEM = "원석"
TOOL_TOKEN_ITEM = "도구 증표"
TOOL_TOKEN_PRICE = 50

TOOL_GACHA_STONE_WEIGHT = 60
TOOL_GACHA_TOOL_WEIGHT = 35
TOOL_GACHA_SUPPORT_WEIGHT = 5
APPRAISAL_TURNS = 30
CRAFT_TURNS = 20
MAX_TOOL_BREAKTHROUGH = 3
MAX_EQUIPPED_TOOLS = 3

_APPRAISAL_OPERATION_LOCKS: dict[str, asyncio.Lock] = {}


# category:
# - dedicated: only the matching common artifact special can equip it later.
# - combat_common: any artifact can equip it later.
# - life: any artifact can equip it later, but it acts through a selected worker.
STONE_GEMS = {
    "회상의 원석": [
        {"name": "복기의 젬", "category": "dedicated", "target_special": "reuse_last_dice", "range": (1, 3), "summary": "재사용 주사위의 위력을 높인다."},
        {"name": "교정의 젬", "category": "dedicated", "target_special": "reuse_last_dice", "range": (1, 2), "summary": "재사용 실패를 다음 재사용 보너스로 바꾼다."},
        {"name": "여백의 젬", "category": "dedicated", "target_special": "reuse_last_dice", "range": (3, 6), "summary": "주사위가 빈 구간에서 방어적인 보조 효과를 얻는다."},
    ],
    "맹화의 원석": [
        {"name": "격화의 젬", "category": "dedicated", "target_special": "fierce_attack", "range": (3, 7), "summary": "맹렬한 추가 위력을 강화한다."},
        {"name": "도화선의 젬", "category": "dedicated", "target_special": "fierce_attack", "range": (2, 5), "summary": "맹렬한 효과의 첫 발동과 다음 발동을 보조한다."},
        {"name": "잔불의 젬", "category": "dedicated", "target_special": "fierce_attack", "range": (20, 35), "summary": "맹렬한 위력 일부를 후속 잔불 피해로 남긴다."},
    ],
    "성벽의 원석": [
        {"name": "맥박의 젬", "category": "dedicated", "target_special": "sturdy_defense", "range": (3, 8), "summary": "견고한 회복 효과를 강화한다."},
        {"name": "축성의 젬", "category": "dedicated", "target_special": "sturdy_defense", "range": (20, 40), "summary": "초과 회복을 보호 효과로 바꾼다."},
        {"name": "인내의 젬", "category": "dedicated", "target_special": "sturdy_defense", "range": (3, 6), "summary": "견고한 발동 턴의 생존력을 높인다."},
    ],
    "업보의 원석": [
        {"name": "가시의 젬", "category": "dedicated", "target_special": "reflection", "range": (2, 5), "summary": "반사 비율을 높인다."},
        {"name": "원한의 젬", "category": "dedicated", "target_special": "reflection", "range": (1, 3), "summary": "피격을 누적해 다음 반사를 강화한다."},
        {"name": "응보의 젬", "category": "dedicated", "target_special": "reflection", "range": (2, 5), "summary": "반사 발동과 함께 피해 경감 및 후속 보너스를 얻는다."},
    ],
    "격정의 원석": [
        {"name": "고양의 젬", "category": "dedicated", "target_special": "escalation", "range": (1, 4), "summary": "모든 주사위에 적용되는 고조 보정의 최솟값을 올린다."},
        {"name": "폭주의 젬", "category": "dedicated", "target_special": "escalation", "range": (3, 8), "summary": "각 주사위의 고조 보정을 다시 굴려 높은 결과를 선택한다."},
        {"name": "연쇄의 젬", "category": "dedicated", "target_special": "escalation", "range": (15, 25), "summary": "양수인 고조 보정 일부를 다음 유효 주사위에 전달한다."},
    ],
    "파문의 원석": [
        {"name": "증폭의 젬", "category": "dedicated", "target_special": "ripple", "range": (5, 10), "summary": "무작위 주사위 유형의 파문 전이율을 높인다."},
        {"name": "맥동의 젬", "category": "dedicated", "target_special": "ripple", "range": (1, 3), "summary": "파문의 발동 주기를 매 턴으로 바꾸고 전이값을 보강한다."},
        {"name": "환류의 젬", "category": "dedicated", "target_special": "ripple", "range": (5, 15), "summary": "파문으로 전이한 수치에 비례해 체력과 정신력을 회복한다."},
    ],
    "윤회의 원석": [
        {"name": "회귀의 젬", "category": "dedicated", "target_special": "immortality", "range": (5, 10), "summary": "부활 직후의 생존력과 행동을 강화한다."},
        {"name": "정화의 젬", "category": "dedicated", "target_special": "immortality", "range": (30, 50), "summary": "부활할 때 상태이상을 정리한다."},
        {"name": "여명의 젬", "category": "dedicated", "target_special": "immortality", "range": (3, 7), "summary": "전투 종료 후 회복을 보조한다."},
    ],
    "공명의 원석": [
        {"name": "선봉의 젬", "category": "combat_common", "target_special": None, "range": (2, 4), "summary": "매 턴 첫 유효 주사위를 강화한다."},
        {"name": "균형의 젬", "category": "combat_common", "target_special": None, "range": (2, 4), "summary": "합 패배를 다음 주사위 보너스로 바꾼다."},
        {"name": "수호의 젬", "category": "combat_common", "target_special": None, "range": (5, 8), "summary": "매 턴 처음 받는 실피해를 감소시킨다."},
        {"name": "정화의 젬", "category": "combat_common", "target_special": None, "range": (25, 40), "summary": "상태이상 지속시간을 줄이고 5성에서 전투당 한 번 모두 제거한다."},
        {"name": "집중의 젬", "category": "combat_common", "target_special": None, "range": (5, 9), "summary": "유효 주사위가 하나인 카드를 크게 강화한다."},
        {"name": "연격의 젬", "category": "combat_common", "target_special": None, "range": (3, 5), "summary": "같은 카드의 두 번째 이후 공격 주사위를 강화한다."},
        {"name": "결의의 젬", "category": "combat_common", "target_special": None, "range": (3, 6), "summary": "정신력이 낮을 때 모든 유효 주사위를 강화한다."},
        {"name": "순환의 젬", "category": "combat_common", "target_special": None, "range": (2, 4), "summary": "서로 다른 카드를 번갈아 쓰면 정신력을 회복한다."},
    ],
    "생장의 원석": [
        {"name": "풍요의 젬", "category": "life", "target_special": None, "range": (5, 10), "summary": "채소와 양식 수확량에 추가 획득 판정을 준다."},
        {"name": "경작의 젬", "category": "life", "target_special": None, "range": (3, 6), "summary": "채소의 건강과 최종 품질을 높인다."},
        {"name": "관개의 젬", "category": "life", "target_special": None, "range": (5, 10), "summary": "물주기 효율과 과습 위험을 보조한다."},
        {"name": "청류의 젬", "category": "life", "target_special": None, "range": (6, 12), "summary": "양어장의 수질 관리 효과를 높인다."},
        {"name": "양식의 젬", "category": "life", "target_special": None, "range": (2, 3), "summary": "적정 환경에서 물고기 성장도를 더 얻는다."},
        {"name": "장인의 젬", "category": "life", "target_special": None, "range": (3, 7), "summary": "젬 세공 행동의 성공률을 보조한다."},
        {"name": "조리의 젬", "category": "life", "target_special": None, "range": (3, 7), "summary": "생산 재료로 만든 요리의 품질을 높인다."},
    ],
}

STONE_NAMES = tuple(STONE_GEMS)


TOOL_DEFS = {
    "정령 화로": {
        "rarity": "일반",
        "description": "달구기 직후의 다음 성공을 크게 키우는 연계형 화로입니다. 실패하면 효과가 사라지지 않습니다.",
        "effects": [
            "달구기 후 다음 마법부여·불순물 제거 성공 효과 +10%",
            "달구기 후 다음 마법부여·불순물 제거 성공 효과 +15%",
            "달구기 후 다음 마법부여·불순물 제거 성공 효과 +20%",
            "달구기 후 다음 마법부여·불순물 제거 성공 효과 +30%",
        ],
    },
    "흑철 화로": {
        "rarity": "고급",
        "description": "초반 달구기를 두 배로 올려 고열 구간에 빠르게 진입합니다. 높은 실패율도 함께 감수해야 합니다.",
        "effects": [
            "세공 중 첫 달구기는 달굼 +2",
            "처음 2회의 달구기가 달굼 +2",
            "처음 3회의 달구기가 달굼 +2",
            "처음 4회의 달구기가 달굼 +2",
        ],
    },
    "서리 집게": {
        "rarity": "일반",
        "description": "한 번의 식히기로 더 많은 달굼을 내리고, 돌파 시 다음 가공의 성공률도 보조합니다.",
        "effects": [
            "식히기 시 달굼 -3",
            "달굼 -3, 다음 가공 성공률 +5%p",
            "달굼 -4, 다음 가공 성공률 +5%p",
            "달굼 -4, 다음 가공 성공률 +10%p",
        ],
    },
    "빙정 냉각판": {
        "rarity": "희귀",
        "description": "식히기 전 달굼을 다음 행동의 효과량에만 남겨, 낮아진 위험도로 고열 효과를 사용합니다.",
        "effects": [
            "세공당 1회, 식히기 전 달굼을 다음 행동 효과량 계산에 사용",
            "세공당 2회 발동",
            "세공당 3회 발동",
            "세공당 4회 발동",
        ],
    },
    "마력 붓": {
        "rarity": "일반",
        "description": "마법부여로 오르는 고유 효과와 주 능력을 함께 강화하는 안정적인 도구입니다.",
        "effects": [
            "마법부여 강화량 +10%",
            "마법부여 강화량 +15%",
            "강화량 +20%, 동반 주 능력 상승량 +1",
            "강화량 +30%, 동반 주 능력 상승량 +2",
        ],
    },
    "폭주 촉매": {
        "rarity": "희귀",
        "description": "마법부여 성공률을 낮추는 대신 고유 효과와 주 능력의 상승량을 크게 증폭합니다.",
        "effects": [
            "마법부여 강화량 +50%, 성공률 -15%p",
            "강화량 +55%, 성공률 -13%p",
            "강화량 +65%, 성공률 -10%p",
            "강화량 +80%, 성공률 -8%p",
        ],
    },
    "별무늬 세공망치": {
        "rarity": "일반",
        "description": "현재 성급과 달굼에 관계없이 모양 내기 성공률을 고정 수치로 올립니다.",
        "effects": [
            "모양 내기 성공률 +5%p",
            "성공률 +8%p",
            "성공률 +12%p",
            "성공률 +15%p",
        ],
    },
    "유성 망치": {
        "rarity": "고급",
        "description": "모양 내기 실패가 이어질수록 다음 시도의 성공률을 누적해 보완합니다. 성공하면 누적이 초기화됩니다.",
        "effects": [
            "모양 내기 실패 시 다음 성공률 +8%p, 최대 1중첩",
            "실패당 +8%p, 최대 2중첩",
            "실패당 +10%p, 최대 2중첩",
            "실패당 +10%p, 최대 3중첩",
        ],
    },
    "순백의 체": {
        "rarity": "일반",
        "description": "불순물 제거 성공 시 아티팩트 주 능력치를 보조하는 상수 상승량을 키웁니다.",
        "effects": [
            "불순물 제거 상승량 +15%",
            "상승량 +20%",
            "상승량 +30%",
            "상승량 +40%",
        ],
    },
    "결정 추출기": {
        "rarity": "고급",
        "description": "불순물 제거에 성공한 뒤 추가 판정으로 해당 상승량을 두 배로 만듭니다.",
        "effects": [
            "불순물 제거 성공 시 10% 확률로 상승량 2배",
            "2배 확률 15%",
            "2배 확률 20%",
            "2배 확률 25%",
        ],
    },
    "장인의 확대경": {
        "rarity": "고급",
        "description": "현재 성공률과 예상 상승량을 보여주며, 돌파할수록 세 가지 가공 행동의 성공률도 직접 높입니다.",
        "effects": [
            "각 행동의 정확한 성공률 표시",
            "정확한 성공률 표시, 모든 가공 성공률 +3%p",
            "성공률·현재 예상 상승량 표시, 모든 가공 성공률 +5%p",
            "성공률·현재 예상 상승량 표시, 모든 가공 성공률 +8%p",
        ],
    },
    "안정의 균형추": {
        "rarity": "희귀",
        "description": "달굼이 발생시키는 실패율 페널티만 완화합니다. 달굼으로 높아진 행동 효과는 그대로 유지됩니다.",
        "effects": [
            "달굼 성공률 페널티 5%p 완화",
            "페널티 7%p 완화",
            "페널티 10%p 완화",
            "페널티 12%p 완화",
        ],
    },
    "예열 코일": {
        "rarity": "고급",
        "description": "세공 시작부터 달굼을 확보합니다. 높은 돌파에서는 첫 가공 행동의 성공률도 보조합니다.",
        "effects": [
            "세공 시작 시 달굼 +1",
            "시작 달굼 +1, 첫 가공 행동 성공률 +5%p",
            "세공 시작 시 달굼 +2",
            "시작 달굼 +2, 첫 가공 행동 성공률 +10%p",
        ],
    },
    "안정 룬펜": {
        "rarity": "고급",
        "description": "상승량을 바꾸지 않고 마법부여 성공률만 안정적으로 높이는 정밀 도구입니다.",
        "effects": [
            "마법부여 성공률 +6%p",
            "마법부여 성공률 +9%p",
            "마법부여 성공률 +12%p",
            "마법부여 성공률 +15%p",
        ],
    },
    "별자리 자": {
        "rarity": "희귀",
        "description": "낮은 성급의 형태를 빠르게 잡아 줍니다. 3성 이상에서는 성공률 보너스가 절반만 적용됩니다.",
        "effects": [
            "모양 내기 성공률 +10%p, 3성 이상 +5%p",
            "성공률 +14%p, 3성 이상 +7%p",
            "성공률 +18%p, 3성 이상 +9%p",
            "성공률 +24%p, 3성 이상 +12%p",
        ],
    },
    "결점 표본함": {
        "rarity": "고급",
        "description": "불순물 제거 실패 원인을 보존해 다음 불순물 제거 성공률을 누적합니다. 성공하면 누적이 초기화됩니다.",
        "effects": [
            "실패당 다음 불순물 제거 성공률 +8%p, 최대 1중첩",
            "실패당 +8%p, 최대 2중첩",
            "실패당 +10%p, 최대 2중첩",
            "실패당 +10%p, 최대 3중첩",
        ],
    },
}

# Rarity is selected first, then one tool in that rarity is selected uniformly.
TOOL_RARITY_WEIGHT = {"일반": 60, "고급": 30, "희귀": 10}

TOOL_CATEGORIES = {
    "heating": {"label": "달구기", "tools": ("정령 화로", "흑철 화로", "예열 코일")},
    "cooling": {"label": "식히기", "tools": ("서리 집게", "빙정 냉각판")},
    "enchanting": {"label": "마법부여", "tools": ("마력 붓", "폭주 촉매", "안정 룬펜")},
    "shaping": {"label": "모양 내기", "tools": ("별무늬 세공망치", "유성 망치", "별자리 자")},
    "purifying": {"label": "불순물 제거", "tools": ("순백의 체", "결정 추출기", "결점 표본함")},
    "general": {"label": "범용", "tools": ("장인의 확대경", "안정의 균형추")},
}


CROPS = {
    "새벽 감자": {"turns": 12, "yield": (3, 6), "water": (25, 80)},
    "별빛 토마토": {"turns": 15, "yield": (2, 5), "water": (45, 65)},
    "꿈양배추": {"turns": 18, "yield": (2, 4), "water": (35, 70)},
    "구름 양파": {"turns": 14, "yield": (3, 5), "water": (20, 65)},
    "무지개 당근": {"turns": 20, "yield": (1, 4), "water": (35, 60)},
    "시간 호박": {"turns": 24, "yield": (1, 3), "water": (30, 70)},
    "달빛 버섯": {"turns": 16, "yield": (2, 5), "water": (55, 85)},
    "악몽 고추": {"turns": 20, "yield": (1, 3), "water": (30, 60)},
    "은하 무": {"turns": 17, "yield": (2, 5), "water": (40, 70)},
}

FISH_SPECIES = {
    "빵잉어": {"turns": 12, "yield": (2, 5), "water": (35, 90)},
    "빵붕어": {"turns": 13, "yield": (2, 5), "water": (35, 85)},
    "민물배스": {"turns": 16, "yield": (2, 4), "water": (45, 80)},
    "피라미": {"turns": 11, "yield": (3, 6), "water": (40, 85)},
    "버들치": {"turns": 16, "yield": (2, 4), "water": (65, 100)},
    "모래무지": {"turns": 15, "yield": (2, 4), "water": (45, 85)},
    "쉬리": {"turns": 19, "yield": (2, 4), "water": (60, 90)},
    "각시붕어": {"turns": 18, "yield": (2, 4), "water": (50, 85)},
    "구름송어": {"turns": 18, "yield": (2, 4), "water": (55, 85)},
    "어름치": {"turns": 24, "yield": (1, 3), "water": (75, 100)},
    "동사리": {"turns": 23, "yield": (1, 3), "water": (45, 75)},
    "송사리": {"turns": 20, "yield": (2, 5), "water": (50, 85)},
    "버들매치": {"turns": 25, "yield": (1, 3), "water": (60, 90)},
    "가는돌고기": {"turns": 26, "yield": (1, 3), "water": (65, 95)},
    "별비늘돔": {"turns": 28, "yield": (1, 2), "water": (70, 100)},
    "악몽 메기": {"turns": 22, "yield": (1, 4), "water": (35, 60)},
    "메롱물고기": {"turns": 16, "yield": (2, 4), "water": (45, 80)},
    "꽁다리치": {"turns": 17, "yield": (2, 4), "water": (50, 85)},
    "쵸비고기": {"turns": 15, "yield": (2, 5), "water": (40, 80)},
    "밭갱어": {"turns": 18, "yield": (2, 4), "water": (45, 75)},
    "등불오징어": {"turns": 20, "yield": (1, 3), "water": (60, 100)},
    "명이태": {"turns": 23, "yield": (1, 3), "water": (70, 100)},
    "로운새우": {"turns": 14, "yield": (3, 7), "water": (45, 90)},
    "돔돌치": {"turns": 24, "yield": (1, 3), "water": (65, 95)},
}

SEED_ITEMS = {name: ("달빛 버섯 종균" if name == "달빛 버섯" else f"{name} 씨앗") for name in CROPS}
FINGERLING_ITEMS = {
    name: (
        f"{name} 유생" if name == "등불오징어"
        else f"{name} 치하" if name == "로운새우"
        else f"{name} 치어"
    )
    for name in FISH_SPECIES
}


def ensure_life_data(user_data: dict[str, Any]) -> dict[str, Any]:
    life = user_data.setdefault("life_data", {})
    if not isinstance(life, dict):
        life = {}
        user_data["life_data"] = life
    legacy_appraisal = life.get("appraisal")
    appraisal_slots = life.get("appraisal_slots")
    if not isinstance(appraisal_slots, list):
        appraisal_slots = [legacy_appraisal if isinstance(legacy_appraisal, dict) else None]
    # Keep the list object stable. Claim code may hold a reference to it while
    # collection/achievement helpers call ensure_life_data again.
    while len(appraisal_slots) < 3:
        appraisal_slots.append(None)
    del appraisal_slots[3:]
    for index, task in enumerate(appraisal_slots):
        if not isinstance(task, dict):
            appraisal_slots[index] = None
            continue
        task.setdefault("task_id", uuid.uuid4().hex)
    life["appraisal_slots"] = appraisal_slots
    # Compatibility field for older views; v8 uses appraisal_slots exclusively.
    life["appraisal"] = None
    life.setdefault("claimed_appraisal_ids", [])
    life.setdefault("stones", {})
    life.setdefault("gems", [])
    for gem in life["gems"]:
        if isinstance(gem, dict):
            ensure_gem_stat_affixes(gem)
    life.setdefault("tools", {})
    life.setdefault("tool_overflow_duplicates", 0)
    life.setdefault("gem_crafting", None)
    active_craft = life.get("gem_crafting")
    if isinstance(active_craft, dict):
        craft_affixes = {
            "id": active_craft.get("id"),
            "name": (active_craft.get("gem_def") or {}).get("name"),
            "stone": active_craft.get("stone"),
            "crafted_by": active_craft.get("worker_name"),
            "stat_value": active_craft.get("stat_value", 1),
            "aux_stat_value": active_craft.get(
                "aux_stat_value",
                active_craft.get("stat_value", 1),
            ),
            "main_stat": active_craft.get("main_stat"),
            "main_stat_mode": active_craft.get("main_stat_mode"),
            "main_stat_value": active_craft.get("main_stat_value"),
        }
        ensure_gem_stat_affixes(craft_affixes)
        for key in (
            "main_stat",
            "main_stat_mode",
            "main_stat_value",
            "aux_stat_value",
            "stat_value",
        ):
            active_craft[key] = craft_affixes[key]
    life.setdefault("vegetable_garden", {"plot": None, "produce": {}})
    life.setdefault("fish_farm", {"tank": None, "produce": {}})
    life.setdefault("starter_supply_claimed", {"garden": False, "fish_farm": False})
    return life


def _inventory(user_data: dict[str, Any]) -> dict[str, int]:
    inventory = user_data.setdefault("inventory", {})
    if not isinstance(inventory, dict):
        inventory = {}
        user_data["inventory"] = inventory
    return inventory


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(value)))


def _tool_level(craft: dict[str, Any], name: str) -> int | None:
    tools = craft.get("tools", {})
    if name not in tools:
        return None
    return max(0, min(MAX_TOOL_BREAKTHROUGH, int(tools[name])))


def _worker_life_gems(user_data: dict[str, Any], worker_index: int) -> list[dict[str, Any]]:
    chars = user_data.get("characters", [])
    if not (0 <= worker_index < len(chars)):
        return []
    result = []
    character = chars[worker_index]
    for key in ("equipped_artifact", "equipped_engraved_artifact"):
        artifact = character.get(key)
        if not isinstance(artifact, dict):
            continue
        result.extend(
            gem for gem in artifact.get("gems", [])
            if isinstance(gem, dict) and gem.get("category") == "life"
        )
    return result


def _worker_busy(life: dict[str, Any], worker_index: int) -> bool:
    plot = life.get("vegetable_garden", {}).get("plot")
    tank = life.get("fish_farm", {}).get("tank")
    craft = life.get("gem_crafting")
    return any(
        isinstance(task, dict) and int(task.get("worker_index", -1)) == worker_index
        for task in (plot, tank, craft)
    )


def _life_gem(user_data: dict[str, Any], worker_index: int, name: str) -> dict[str, Any] | None:
    for gem in _worker_life_gems(user_data, worker_index):
        if gem.get("name") == name:
            return gem
    return None


def _life_gem_value(user_data: dict[str, Any], worker_index: int, name: str, default: int = 0) -> int:
    matches = [
        gem for gem in _worker_life_gems(user_data, worker_index)
        if gem.get("name") == name
    ]
    if not matches:
        return default
    return sum(gem_final_effect_value(gem) for gem in matches)


def _life_gem_star(user_data: dict[str, Any], worker_index: int, name: str) -> int:
    matches = [
        gem for gem in _worker_life_gems(user_data, worker_index)
        if gem.get("name") == name
    ]
    return max(
        (max(0, min(5, int(gem.get("star", 0) or 0))) for gem in matches),
        default=-1,
    )


def _choose_tool_name() -> str:
    rarity = random.choices(
        list(TOOL_RARITY_WEIGHT),
        weights=list(TOOL_RARITY_WEIGHT.values()),
        k=1,
    )[0]
    pool = [name for name, data in TOOL_DEFS.items() if data["rarity"] == rarity]
    return random.choice(pool)


def draw_crafting_tool(
    user_data: dict[str, Any],
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Draw one reusable tool; every duplicate automatically breaks through."""
    life = ensure_life_data(user_data)
    name = tool_name or _choose_tool_name()
    if name not in TOOL_DEFS:
        raise ValueError(f"unknown crafting tool: {name}")
    tools = life["tools"]
    old_level = tools.get(name)

    if old_level is None:
        tools[name] = 0
        result = "new"
    elif int(old_level) < MAX_TOOL_BREAKTHROUGH:
        tools[name] = int(old_level) + 1
        result = "breakthrough"
    else:
        tools[name] = MAX_TOOL_BREAKTHROUGH
        life["tool_overflow_duplicates"] = int(life.get("tool_overflow_duplicates", 0)) + 1
        inventory = _inventory(user_data)
        inventory[TOOL_TOKEN_ITEM] = int(inventory.get(TOOL_TOKEN_ITEM, 0)) + 1
        result = "overflow"

    try:
        from progression_system_v6 import add_collection, ensure_progression
        add_collection(user_data, "tools", name)
        progression = ensure_progression(user_data)
        if old_level is not None and "first_tool_breakthrough" not in progression["achievements"]:
            progression["achievements"].append("first_tool_breakthrough")
        if int(tools[name]) >= MAX_TOOL_BREAKTHROUGH and "max_tool" not in progression["achievements"]:
            progression["achievements"].append("max_tool")
    except ImportError:
        pass

    return {
        "kind": "tool",
        "name": name,
        "rarity": TOOL_DEFS[name]["rarity"],
        "result": result,
        "old_level": old_level,
        "level": int(tools[name]),
        "tool_tokens": int(_inventory(user_data).get(TOOL_TOKEN_ITEM, 0)),
    }


def draw_tool_gacha_result(user_data: dict[str, Any]) -> dict[str, Any]:
    """Draw a raw stone, reusable crafting tool, or character support fragment."""
    result_kind = random.choices(
        ["stone", "tool", "support_fragment"],
        weights=[
            TOOL_GACHA_STONE_WEIGHT,
            TOOL_GACHA_TOOL_WEIGHT,
            TOOL_GACHA_SUPPORT_WEIGHT,
        ],
        k=1,
    )[0]
    if result_kind == "stone":
        inventory = _inventory(user_data)
        inventory[RAW_STONE_ITEM] = int(inventory.get(RAW_STONE_ITEM, 0)) + 1
        return {"kind": "stone", "name": RAW_STONE_ITEM, "count": 1}
    if result_kind == "support_fragment":
        # Lazy import avoids coupling the life-system module import graph to
        # the Discord guild views.
        from boss_training import add_support_fragment

        return add_support_fragment(user_data)
    return draw_crafting_tool(user_data)


def draw_crafting_tools(user_data: dict[str, Any], count: int) -> list[dict[str, Any]]:
    count = int(count)
    if count not in (1, 10):
        raise ValueError("tool gacha count must be 1 or 10")
    return [draw_tool_gacha_result(user_data) for _ in range(count)]


def format_tool_result(result: dict[str, Any], index: int | None = None) -> str:
    prefix = f"`{index:02d}` " if index is not None else ""
    if result.get("kind") == "stone":
        return f"{prefix}💎 **원석 ×{int(result.get('count', 1))}**"
    if result.get("kind") == "support_fragment":
        return (
            f"{prefix}🤝 **{result['name']} 서포트 조각 ×1** "
            f"· 보유 {int(result.get('total', 1))}개 · +{int(result.get('upgrade', 0))}강"
        )
    name = result["name"]
    rarity = result["rarity"]
    if result["result"] == "new":
        status = "신규 획득 · 0돌파"
    elif result["result"] == "breakthrough":
        status = f"자동 돌파 {result['old_level']}→{result['level']}"
    else:
        status = "이미 3돌파 · 도구 증표 +1"
    return f"{prefix}🛠️ **[{rarity}] {name}** — {status}"


def buy_tool_token_offer(
    user_data: dict[str, Any],
    offer_key: str,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Exchange 50 tool tokens for one deterministic shop offer."""
    inventory = _inventory(user_data)
    tokens = int(inventory.get(TOOL_TOKEN_ITEM, 0))
    if tokens < TOOL_TOKEN_PRICE:
        return False, f"도구 증표가 부족합니다. 필요: {TOOL_TOKEN_PRICE}개 / 보유: {tokens}개", None

    life = ensure_life_data(user_data)
    if offer_key == "tool":
        eligible = [
            name
            for name in TOOL_DEFS
            if int(life["tools"].get(name, -1)) < MAX_TOOL_BREAKTHROUGH
        ]
        if not eligible:
            return False, "모든 세공 도구가 최고 돌파라서 이 상품을 구매할 수 없습니다.", None
        name = random.choices(
            eligible,
            weights=[TOOL_RARITY_WEIGHT[TOOL_DEFS[name]["rarity"]] for name in eligible],
            k=1,
        )[0]
        inventory[TOOL_TOKEN_ITEM] = tokens - TOOL_TOKEN_PRICE
        result = draw_crafting_tool(user_data, name)
        return True, f"🎟️ {format_tool_result(result)}", result

    rewards = {
        "stone": (RAW_STONE_ITEM, 5),
        "hope": (PURE_HOPE_ITEM, 3),
        "money": ("money", 3_000_000),
    }
    if offer_key not in rewards:
        return False, "알 수 없는 교환 상품입니다.", None
    item, count = rewards[offer_key]
    inventory[TOOL_TOKEN_ITEM] = tokens - TOOL_TOKEN_PRICE
    if item == "money":
        user_data["money"] = int(user_data.get("money", 0)) + count
        return True, f"💰 머니 {count:,}원을 받았습니다.", {"kind": "money", "count": count}
    inventory[item] = int(inventory.get(item, 0)) + count
    return True, f"✅ {item} ×{count}을(를) 받았습니다.", {"kind": "item", "name": item, "count": count}


def _appraisal_slots(user_data: dict[str, Any]) -> list[dict[str, Any] | None]:
    return ensure_life_data(user_data)["appraisal_slots"]


def start_appraisal(
    user_data: dict[str, Any],
    slot_index: int | None = None,
) -> tuple[bool, str]:
    slots = _appraisal_slots(user_data)
    if slot_index is None:
        slot_index = next((idx for idx, task in enumerate(slots) if task is None), -1)
    slot_index = int(slot_index)
    if not 0 <= slot_index < len(slots):
        return False, "빈 감정 슬롯이 없습니다."
    if slots[slot_index] is not None:
        return False, f"{slot_index + 1}번 슬롯은 이미 감정 중입니다."
    inv = _inventory(user_data)
    if int(inv.get(RAW_STONE_ITEM, 0)) <= 0:
        return False, "미감정 원석이 없습니다."
    inv[RAW_STONE_ITEM] = int(inv.get(RAW_STONE_ITEM, 0)) - 1
    now = int(user_data.get("myhome", {}).get("total_turns", 0) or 0)
    slots[slot_index] = {
        "task_id": uuid.uuid4().hex,
        "start_turn": now,
        "required_turns": APPRAISAL_TURNS,
    }
    return True, (
        f"{slot_index + 1}번 슬롯에서 원석 감정을 시작했습니다. "
        f"공용 활동 {APPRAISAL_TURNS}턴이 필요합니다."
    )


def appraisal_progress(
    user_data: dict[str, Any],
    slot_index: int = 0,
) -> tuple[int, int]:
    slots = _appraisal_slots(user_data)
    slot_index = int(slot_index)
    if not 0 <= slot_index < len(slots):
        return 0, 0
    task = slots[slot_index]
    if not task:
        return 0, 0
    now = int(user_data.get("myhome", {}).get("total_turns", 0) or 0)
    required = int(task.get("required_turns", APPRAISAL_TURNS))
    progress = max(0, now - int(task.get("start_turn", now)))
    return min(progress, required), required


def claim_appraisal(
    user_data: dict[str, Any],
    slot_index: int = 0,
) -> tuple[bool, str]:
    life = ensure_life_data(user_data)
    slots = _appraisal_slots(user_data)
    slot_index = int(slot_index)
    if not 0 <= slot_index < len(slots):
        return False, "잘못된 감정 슬롯입니다."
    task = slots[slot_index]
    if not task:
        return False, "감정 중인 원석이 없습니다."
    progress, required = appraisal_progress(user_data, slot_index)
    if progress < required:
        return False, f"감정 진행 중입니다. ({progress}/{required})"
    task_id = str(task.setdefault("task_id", uuid.uuid4().hex))
    claimed_ids = life.setdefault("claimed_appraisal_ids", [])
    if task_id in claimed_ids:
        slots[slot_index] = None
        return False, "이미 수령한 감정 결과입니다."
    stone = str(task.setdefault("result_stone", random.choice(STONE_NAMES)))
    stones = life["stones"]
    stones[stone] = int(stones.get(stone, 0)) + 1
    claimed_ids.append(task_id)
    del claimed_ids[:-100]
    slots[slot_index] = None
    try:
        from progression_system_v6 import add_collection, ensure_progression
        add_collection(user_data, "stones", stone)
        progression = ensure_progression(user_data)
        if "first_appraisal" not in progression["achievements"]:
            progression["achievements"].append("first_appraisal")
        notification_key = f"appraisal_ready_{slot_index}"
        if notification_key in progression.get("notification_keys", []):
            progression["notification_keys"].remove(notification_key)
    except ImportError:
        pass
    return True, stone


def claim_all_appraisals(user_data: dict[str, Any]) -> tuple[bool, list[str]]:
    results = []
    for slot_index in range(3):
        progress, required = appraisal_progress(user_data, slot_index)
        if required and progress >= required:
            ok, stone = claim_appraisal(user_data, slot_index)
            if ok:
                results.append(f"{slot_index + 1}번: {stone}")
    if not results:
        return False, ["수령 가능한 감정 결과가 없습니다."]
    return True, results


def start_gem_crafting(
    user_data: dict[str, Any],
    stone_name: str,
    gem_index: int,
    worker_index: int,
    tool_names: list[str],
) -> tuple[bool, str]:
    life = ensure_life_data(user_data)
    if life.get("gem_crafting"):
        return False, "이미 세공 중인 젬이 있습니다."
    if stone_name not in STONE_GEMS:
        return False, "알 수 없는 원석입니다."
    if int(life["stones"].get(stone_name, 0)) <= 0:
        return False, f"{stone_name}을(를) 보유하고 있지 않습니다."
    gems = STONE_GEMS[stone_name]
    if not (0 <= gem_index < len(gems)):
        return False, "알 수 없는 젬입니다."
    chars = user_data.get("characters", [])
    if not (0 <= worker_index < len(chars)):
        return False, "담당 캐릭터를 선택해주세요."
    if _worker_busy(life, worker_index):
        return False, "해당 캐릭터는 이미 다른 장기 생활 작업을 담당하고 있습니다."

    unique_tools = list(dict.fromkeys(tool_names))
    if len(unique_tools) > MAX_EQUIPPED_TOOLS:
        return False, "세공 도구는 최대 3종까지 선택할 수 있습니다."
    owned_tools = life["tools"]
    for name in unique_tools:
        if name not in TOOL_DEFS or name not in owned_tools:
            return False, f"보유하지 않은 도구입니다: {name}"

    gem_def = gems[gem_index]
    low, high = gem_def["range"]
    life["stones"][stone_name] = int(life["stones"][stone_name]) - 1
    craft_id = str(uuid.uuid4())
    rolled_affixes = {"id": craft_id, "name": gem_def["name"], "stone": stone_name}
    roll_gem_stat_affixes(rolled_affixes, random)
    craft = {
        "id": craft_id,
        "stone": stone_name,
        "gem_def": gem_def,
        "worker_index": worker_index,
        "worker_name": chars[worker_index].get("name", f"캐릭터 {worker_index + 1}"),
        "tools": {name: int(owned_tools[name]) for name in unique_tools},
        "turn": 0,
        "star": 0,
        "heat": 0,
        "max_heat": 0,
        "used_cool": False,
        "effect_value": random.randint(int(low), int(high)),
        "main_stat": rolled_affixes["main_stat"],
        "main_stat_mode": rolled_affixes["main_stat_mode"],
        "main_stat_value": int(rolled_affixes["main_stat_value"]),
        "aux_stat_value": int(rolled_affixes["aux_stat_value"]),
        "stat_value": int(rolled_affixes["aux_stat_value"]),
        "meteor_stacks": 0,
        "heat_uses": 0,
        "spirit_furnace_pending": False,
        "frost_success_bonus": 0,
        "effect_heat_override": None,
        "ice_plate_uses": 0,
        "preheat_action_bonus": 0,
        "specimen_stacks": 0,
        "last_log": (
            f"0성 젬 세공을 시작했습니다. "
            f"주 능력: {gem_main_stat_text(rolled_affixes)} · "
            f"보조 능력: 아티팩트 주 능력치 +{rolled_affixes['aux_stat_value']}"
        ),
    }
    coil_level = _tool_level(craft, "예열 코일")
    if coil_level is not None:
        craft["heat"] = 2 if coil_level >= 2 else 1
        craft["max_heat"] = craft["heat"]
        if coil_level in (1, 3):
            craft["preheat_action_bonus"] = 5 if coil_level == 1 else 10
        craft["last_log"] += (
            f" · 예열 코일: 시작 달굼 {craft['heat']}"
            + (
                f", 첫 가공 성공률 +{craft['preheat_action_bonus']}%p"
                if craft["preheat_action_bonus"] else ""
            )
        )
    life["gem_crafting"] = craft
    return True, f"{gem_def['name']} 세공을 시작했습니다."


def _craft_worker_bonus(user_data: dict[str, Any], craft: dict[str, Any]) -> int:
    gem = _life_gem(user_data, int(craft.get("worker_index", -1)), "장인의 젬")
    if not gem:
        return 0
    value = max(1, gem_final_effect_value(gem))
    star = max(0, int(gem.get("star", 0) or 0))
    if star >= 5:
        value += 7
    elif star >= 3:
        value += 3
    return value


def _balance_relief(craft: dict[str, Any]) -> int:
    level = _tool_level(craft, "안정의 균형추")
    return [5, 7, 10, 12][level] if level is not None else 0


def _frost_bonus(craft: dict[str, Any]) -> int:
    return int(craft.get("frost_success_bonus", 0) or 0)


def _shape_tool_bonus(craft: dict[str, Any]) -> int:
    level = _tool_level(craft, "별무늬 세공망치")
    return [5, 8, 12, 15][level] if level is not None else 0


def _meteor_rule(craft: dict[str, Any]) -> tuple[int, int]:
    level = _tool_level(craft, "유성 망치")
    if level is None:
        return 0, 0
    per_stack = [8, 8, 10, 10][level]
    max_stack = [1, 2, 2, 3][level]
    return per_stack, max_stack


def _magnifier_success_bonus(craft: dict[str, Any]) -> int:
    level = _tool_level(craft, "장인의 확대경")
    return [0, 3, 5, 8][level] if level is not None else 0


def _rune_pen_bonus(craft: dict[str, Any]) -> int:
    level = _tool_level(craft, "안정 룬펜")
    return [6, 9, 12, 15][level] if level is not None else 0


def _constellation_bonus(craft: dict[str, Any]) -> int:
    level = _tool_level(craft, "별자리 자")
    if level is None:
        return 0
    value = [10, 14, 18, 24][level]
    return value // 2 if int(craft.get("star", 0)) >= 3 else value


def _specimen_rule(craft: dict[str, Any]) -> tuple[int, int]:
    level = _tool_level(craft, "결점 표본함")
    if level is None:
        return 0, 0
    return [8, 8, 10, 10][level], [1, 2, 2, 3][level]


def _craft_chances(user_data: dict[str, Any], craft: dict[str, Any]) -> dict[str, int]:
    heat = int(craft.get("heat", 0))
    worker = _craft_worker_bonus(user_data, craft)
    relief = _balance_relief(craft)
    regular_relief = min(relief, heat * 4)
    shape_relief = min(relief, heat * 5)
    frost = _frost_bonus(craft)
    magnifier = _magnifier_success_bonus(craft)
    first_action = int(craft.get("preheat_action_bonus", 0) or 0)

    enchant = 75 - heat * 4 + regular_relief + frost + worker + magnifier + first_action
    catalyst = _tool_level(craft, "폭주 촉매")
    if catalyst is not None:
        enchant -= [15, 13, 10, 8][catalyst]
    enchant += _rune_pen_bonus(craft)

    shape = 82 - int(craft.get("star", 0)) * 11 - heat * 5 + shape_relief + frost + worker + magnifier + first_action
    shape += _shape_tool_bonus(craft)
    shape += _constellation_bonus(craft)
    per_stack, _ = _meteor_rule(craft)
    shape += per_stack * int(craft.get("meteor_stacks", 0))

    purify = 78 - heat * 4 + regular_relief + frost + worker + magnifier + first_action
    specimen_per_stack, _ = _specimen_rule(craft)
    purify += specimen_per_stack * int(craft.get("specimen_stacks", 0))
    return {
        "enchant": max(5, min(95, enchant)),
        "shape": max(5, min(95, shape)),
        "purify": max(5, min(95, purify)),
    }


def _consume_next_action_bonuses(craft: dict[str, Any]) -> None:
    craft["frost_success_bonus"] = 0
    craft["effect_heat_override"] = None
    craft["preheat_action_bonus"] = 0


def _main_stat_craft_gain(craft: dict[str, Any], heat: int) -> int:
    """Make heat meaningfully affect the character-stat side of enchanting."""
    stat = craft.get("main_stat")
    mode = craft.get("main_stat_mode")
    heat = max(0, int(heat))
    if mode == "percentage_point":
        return 1 + int(heat >= 6)
    if mode == "percent":
        return 1 + heat // 3
    if stat in ("max_hp", "max_mental"):
        return 2 + heat
    return 1 + heat // 2


def _craft_gain_preview(craft: dict[str, Any]) -> str:
    """Return the exact non-random gain used if each current action succeeds."""
    heat = int(craft.get("heat", 0))
    effect_heat = craft.get("effect_heat_override")
    effect_heat = heat if effect_heat is None else int(effect_heat)

    enchant = 1 + (effect_heat * 3 + 3) // 4
    main = _main_stat_craft_gain(craft, effect_heat)
    spirit = _tool_level(craft, "정령 화로")
    if craft.get("spirit_furnace_pending") and spirit is not None:
        enchant = max(1, round(enchant * [1.10, 1.15, 1.20, 1.30][spirit]))
        main = max(1, round(main * [1.10, 1.15, 1.20, 1.30][spirit]))
    brush = _tool_level(craft, "마력 붓")
    if brush is not None:
        enchant = max(1, round(enchant * [1.10, 1.15, 1.20, 1.30][brush]))
        if brush >= 2:
            main += 1 if brush == 2 else 2
    catalyst = _tool_level(craft, "폭주 촉매")
    if catalyst is not None:
        enchant = max(1, round(enchant * [1.50, 1.55, 1.65, 1.80][catalyst]))
        main = max(1, round(main * [1.25, 1.30, 1.40, 1.50][catalyst]))

    purify = 1 + (effect_heat * 2 + 2) // 3
    if craft.get("spirit_furnace_pending") and spirit is not None:
        purify = max(1, round(purify * [1.10, 1.15, 1.20, 1.30][spirit]))
    sieve = _tool_level(craft, "순백의 체")
    if sieve is not None:
        purify = max(1, round(purify * [1.15, 1.20, 1.30, 1.40][sieve]))

    shape = 1 + effect_heat // 2
    extractor = _tool_level(craft, "결정 추출기")
    extractor_text = (
        f" · 추출기 { [10, 15, 20, 25][extractor] }%로 ×2"
        if extractor is not None else ""
    )
    return (
        f"마법부여: 고유 +{enchant}, 주 능력 +{main}\n"
        f"모양 내기: +{shape}성(최대 5성)\n"
        f"불순물 제거: 보조 +{purify}{extractor_text}"
    )


def _finish_craft_if_needed(user_data: dict[str, Any]) -> dict[str, Any] | None:
    life = ensure_life_data(user_data)
    craft = life.get("gem_crafting")
    if not craft or int(craft.get("turn", 0)) < CRAFT_TURNS:
        return None
    gem_def = craft["gem_def"]
    result = {
        "id": craft["id"],
        "name": gem_def["name"],
        "stone": craft["stone"],
        "category": gem_def["category"],
        "target_special": gem_def["target_special"],
        "summary": gem_def["summary"],
        "star": int(craft["star"]),
        "effect_value": int(craft["effect_value"]),
        "main_stat": craft["main_stat"],
        "main_stat_mode": craft["main_stat_mode"],
        "main_stat_value": int(craft["main_stat_value"]),
        "aux_stat_value": int(craft["aux_stat_value"]),
        "stat_value": int(craft["aux_stat_value"]),
        "crafted_by": craft.get("worker_name"),
    }
    life["gems"].append(result)
    life["gem_crafting"] = None
    try:
        from progression_system_v6 import add_collection, ensure_progression
        add_collection(user_data, "gems", result["name"])
        progression = ensure_progression(user_data)
        if "first_gem" not in progression["achievements"]:
            progression["achievements"].append("first_gem")
        if result["star"] >= 5 and "five_star_gem" not in progression["achievements"]:
            progression["achievements"].append("five_star_gem")
        if result["star"] == 0 and "zero_star_finish" not in progression["secret_achievements"]:
            progression["secret_achievements"].append("zero_star_finish")
        if not craft.get("used_cool") and "no_cooling_finish" not in progression["secret_achievements"]:
            progression["secret_achievements"].append("no_cooling_finish")
        if (
            result["star"] >= 5
            and int(craft.get("max_heat", 0)) >= 8
            and "overheated_five_star" not in progression["secret_achievements"]
        ):
            progression["secret_achievements"].append("overheated_five_star")
    except ImportError:
        pass
    return result


def perform_craft_action(user_data: dict[str, Any], action: str) -> tuple[bool, str, dict[str, Any] | None]:
    life = ensure_life_data(user_data)
    craft = life.get("gem_crafting")
    if not craft:
        return False, "세공 중인 젬이 없습니다.", None
    if int(craft.get("turn", 0)) >= CRAFT_TURNS:
        result = _finish_craft_if_needed(user_data)
        return True, "세공이 완료되었습니다.", result

    heat = int(craft.get("heat", 0))
    chances = _craft_chances(user_data, craft)
    log = ""
    valid = True

    if action == "heat":
        amount = 1
        level = _tool_level(craft, "흑철 화로")
        if level is not None and int(craft.get("heat_uses", 0)) < level + 1:
            amount = 2
        craft["heat_uses"] = int(craft.get("heat_uses", 0)) + 1
        craft["heat"] = heat + amount
        craft["max_heat"] = max(int(craft.get("max_heat", 0)), int(craft["heat"]))
        if _tool_level(craft, "정령 화로") is not None:
            craft["spirit_furnace_pending"] = True
        log = f"🔥 달구기: 달굼 +{amount} → {craft['heat']}"

    elif action == "cool":
        if heat <= 0:
            valid = False
            log = "달굼이 0이라 식힐 수 없습니다."
        else:
            craft["used_cool"] = True
            amount = 2
            frost_level = _tool_level(craft, "서리 집게")
            if frost_level is not None:
                amount = 3 if frost_level <= 1 else 4
                craft["frost_success_bonus"] = 0 if frost_level == 0 else (5 if frost_level <= 2 else 10)

            plate_level = _tool_level(craft, "빙정 냉각판")
            if plate_level is not None and int(craft.get("ice_plate_uses", 0)) < plate_level + 1:
                craft["effect_heat_override"] = heat
                craft["ice_plate_uses"] = int(craft.get("ice_plate_uses", 0)) + 1

            craft["heat"] = max(0, heat - amount)
            log = f"❄️ 식히기: 달굼 -{amount} → {craft['heat']}"

    elif action == "enchant":
        success = random.randint(1, 100) <= chances["enchant"]
        effect_heat = craft.get("effect_heat_override")
        effect_heat = heat if effect_heat is None else int(effect_heat)
        if success:
            # v8.1: 달굼이 마법부여 결과에도 분명히 체감되도록 상향한다.
            gain = 1 + (effect_heat * 3 + 3) // 4
            main_gain = _main_stat_craft_gain(craft, effect_heat)
            spirit = _tool_level(craft, "정령 화로")
            if craft.get("spirit_furnace_pending") and spirit is not None:
                gain = max(1, round(gain * [1.10, 1.15, 1.20, 1.30][spirit]))
                main_gain = max(1, round(main_gain * [1.10, 1.15, 1.20, 1.30][spirit]))
                craft["spirit_furnace_pending"] = False

            brush = _tool_level(craft, "마력 붓")
            if brush is not None:
                gain = max(1, round(gain * [1.10, 1.15, 1.20, 1.30][brush]))
                if brush >= 2:
                    main_gain += 1 if brush == 2 else 2

            catalyst = _tool_level(craft, "폭주 촉매")
            if catalyst is not None:
                gain = max(1, round(gain * [1.50, 1.55, 1.65, 1.80][catalyst]))
                main_gain = max(1, round(main_gain * [1.25, 1.30, 1.40, 1.50][catalyst]))

            craft["effect_value"] = int(craft["effect_value"]) + gain
            craft["main_stat_value"] = int(craft["main_stat_value"]) + main_gain
            log = (
                f"✨ 마법부여 성공: 고유 효과 +{gain} · "
                f"{GEM_MAIN_STAT_LABELS.get(craft.get('main_stat'), '주 능력')} +{main_gain}"
            )
        else:
            log = "✨ 마법부여 실패: 수치 변화 없음"
        _consume_next_action_bonuses(craft)

    elif action == "shape":
        success = random.randint(1, 100) <= chances["shape"]
        effect_heat = craft.get("effect_heat_override")
        effect_heat = heat if effect_heat is None else int(effect_heat)
        if success:
            up = 1 + effect_heat // 2
            old = int(craft["star"])
            craft["star"] = min(5, old + up)
            craft["meteor_stacks"] = 0
            log = f"💎 모양 내기 성공: {old}성 → {craft['star']}성"
        else:
            per_stack, max_stack = _meteor_rule(craft)
            if per_stack > 0:
                craft["meteor_stacks"] = min(max_stack, int(craft.get("meteor_stacks", 0)) + 1)
                log = f"💎 모양 내기 실패: 유성 보정 {craft['meteor_stacks']}중첩"
            else:
                log = "💎 모양 내기 실패: 성급 변화 없음"
        _consume_next_action_bonuses(craft)

    elif action == "purify":
        success = random.randint(1, 100) <= chances["purify"]
        effect_heat = craft.get("effect_heat_override")
        effect_heat = heat if effect_heat is None else int(effect_heat)
        if success:
            # 보조 능력도 달굼에 따라 눈에 띄게 성장하지만 성공률은 함께 낮아진다.
            gain = 1 + (effect_heat * 2 + 2) // 3
            spirit = _tool_level(craft, "정령 화로")
            if craft.get("spirit_furnace_pending") and spirit is not None:
                gain = max(1, round(gain * [1.10, 1.15, 1.20, 1.30][spirit]))
                craft["spirit_furnace_pending"] = False

            sieve = _tool_level(craft, "순백의 체")
            if sieve is not None:
                gain = max(1, round(gain * [1.15, 1.20, 1.30, 1.40][sieve]))

            extractor = _tool_level(craft, "결정 추출기")
            if extractor is not None and random.randint(1, 100) <= [10, 15, 20, 25][extractor]:
                gain *= 2
                log = "🔷 불순물 제거 대성공"
            else:
                log = "🔷 불순물 제거 성공"

            craft["aux_stat_value"] = int(craft["aux_stat_value"]) + gain
            craft["stat_value"] = int(craft["aux_stat_value"])
            if int(craft.get("specimen_stacks", 0)) > 0:
                log += f" · 결점 보정 {craft['specimen_stacks']}중첩 소모"
            craft["specimen_stacks"] = 0
            log += f": 아티팩트 주 능력치 보조 +{gain}"
        else:
            per_stack, max_stack = _specimen_rule(craft)
            if per_stack > 0:
                craft["specimen_stacks"] = min(
                    max_stack,
                    int(craft.get("specimen_stacks", 0)) + 1,
                )
                log = (
                    "🔷 불순물 제거 실패: 수치 변화 없음 · "
                    f"결점 보정 {craft['specimen_stacks']}중첩"
                )
            else:
                log = "🔷 불순물 제거 실패: 수치 변화 없음"
        _consume_next_action_bonuses(craft)

    else:
        return False, "알 수 없는 세공 행동입니다.", None

    if not valid:
        return False, log, None
    if action in {"enchant", "shape", "purify"}:
        worker_bonus = _craft_worker_bonus(user_data, craft)
        if worker_bonus:
            log += f" · 💎 장인의 젬 성공률 +{worker_bonus}%p 적용"

    craft["turn"] = int(craft.get("turn", 0)) + 1
    craft["last_log"] = log
    advance_world_turn(user_data, 1)
    try:
        from progression_system_v6 import weekly_progress
        weekly_progress(user_data, "gem_craft_actions", 1)
    except ImportError:
        pass
    result = _finish_craft_if_needed(user_data)
    return True, log, result


def start_crop(user_data: dict[str, Any], crop_name: str, worker_index: int) -> tuple[bool, str]:
    life = ensure_life_data(user_data)
    garden = life["vegetable_garden"]
    if garden.get("plot"):
        return False, "이미 채소를 재배 중입니다."
    if crop_name not in CROPS:
        return False, "알 수 없는 작물입니다."
    chars = user_data.get("characters", [])
    if not (0 <= worker_index < len(chars)):
        return False, "담당 캐릭터를 선택해주세요."
    if _worker_busy(life, worker_index):
        return False, "해당 캐릭터는 이미 다른 장기 생활 작업을 담당하고 있습니다."
    inv = _inventory(user_data)
    seed = SEED_ITEMS[crop_name]
    if int(inv.get(seed, 0)) <= 0:
        return False, f"{seed}이(가) 필요합니다."
    inv[seed] -= 1
    garden["plot"] = {
        "crop": crop_name,
        "worker_index": worker_index,
        "worker_name": chars[worker_index].get("name", f"캐릭터 {worker_index + 1}"),
        "turn": 0,
        "growth": 0,
        "water": 55,
        "nutrition": 45,
        "health": 100,
        "stress": 0,
        "quality": 50,
        "complete": False,
        "last_log": "파종을 마쳤습니다.",
    }
    return True, f"{crop_name} 재배를 시작했습니다."


def perform_crop_action(user_data: dict[str, Any], action: str) -> tuple[bool, str]:
    life = ensure_life_data(user_data)
    plot = life["vegetable_garden"].get("plot")
    if not plot:
        return False, "재배 중인 작물이 없습니다."
    if plot.get("complete"):
        return False, "이미 수확할 수 있는 상태입니다."

    worker = int(plot.get("worker_index", -1))
    log = ""
    if action == "water":
        if int(plot["water"]) >= 90:
            return False, "수분이 너무 높아 물을 더 줄 수 없습니다."
        bonus = _life_gem_value(user_data, worker, "관개의 젬", 0)
        plot["water"] = _clamp(int(plot["water"]) + 25 + bonus)
        if int(plot["water"]) > 90:
            star = _life_gem_star(user_data, worker, "관개의 젬")
            if star < 3:
                plot["health"] = _clamp(int(plot["health"]) - 5)
        if _life_gem_star(user_data, worker, "관개의 젬") >= 5:
            plot["health"] = _clamp(int(plot["health"]) + 2)
        log = "💧 물을 주었습니다."
        if bonus:
            log += f" · 💎 관개의 젬 수분 +{bonus}"
    elif action == "fertilize":
        plot["nutrition"] = _clamp(int(plot["nutrition"]) + 20)
        plot["stress"] = _clamp(int(plot["stress"]) + 5)
        log = "🌱 비료를 주었습니다."
    elif action == "soil":
        plot["health"] = _clamp(int(plot["health"]) + 8)
        plot["stress"] = _clamp(int(plot["stress"]) - 8)
        plot["nutrition"] = _clamp(int(plot["nutrition"]) - 3)
        log = "🪴 흙을 골랐습니다."
    elif action == "prune":
        plot["growth"] = _clamp(int(plot["growth"]) + 3)
        if int(plot["health"]) >= 50:
            plot["quality"] = _clamp(int(plot["quality"]) + 4)
        else:
            plot["health"] = _clamp(int(plot["health"]) - 3)
        log = "✂️ 가지를 다듬었습니다."
    elif action == "sunlight":
        plot["water"] = _clamp(int(plot["water"]) - 10)
        plot["health"] = _clamp(int(plot["health"]) + 5)
        plot["quality"] = _clamp(int(plot["quality"]) + 1)
        log = "☀️ 햇빛을 조절했습니다."
    elif action == "wait":
        log = "⏳ 한 턴 지켜보았습니다."
    else:
        return False, "알 수 없는 재배 행동입니다."

    crop = CROPS[plot["crop"]]
    low, high = crop["water"]
    plot["water"] = _clamp(int(plot["water"]) - 5)
    plot["nutrition"] = _clamp(int(plot["nutrition"]) - 3)
    plot["stress"] = _clamp(int(plot["stress"]) - 1)

    growth = 2
    if low <= int(plot["water"]) <= high:
        growth += 6
    elif int(plot["water"]) < 15:
        plot["health"] = _clamp(int(plot["health"]) - 10)
    elif int(plot["water"]) > 90:
        plot["health"] = _clamp(int(plot["health"]) - 7)
    if int(plot["nutrition"]) >= 25:
        growth += 3
    if int(plot["health"]) >= 80:
        plot["quality"] = _clamp(int(plot["quality"]) + 2)
    if int(plot["stress"]) >= 70:
        plot["quality"] = _clamp(int(plot["quality"]) - 5)

    plot["growth"] = _clamp(int(plot["growth"]) + growth)
    plot["turn"] = int(plot["turn"]) + 1
    plot["complete"] = int(plot["turn"]) >= int(crop["turns"]) or int(plot["growth"]) >= 100
    plot["last_log"] = log
    advance_world_turn(user_data, 1)
    return True, log


def _quality_name(score: int) -> str:
    if score >= 95:
        return "환상적인"
    if score >= 85:
        return "최상급"
    if score >= 70:
        return "우수한"
    if score >= 50:
        return "싱싱한"
    if score >= 30:
        return "보통"
    return "시든"


def claim_crop(user_data: dict[str, Any]) -> tuple[bool, str]:
    life = ensure_life_data(user_data)
    garden = life["vegetable_garden"]
    plot = garden.get("plot")
    if not plot or not plot.get("complete"):
        return False, "아직 수확할 수 없습니다."
    worker = int(plot.get("worker_index", -1))
    crop = CROPS[plot["crop"]]
    farming_star = _life_gem_star(user_data, worker, "경작의 젬")
    farming_unlock = 10 if farming_star >= 5 else (5 if farming_star >= 3 else 0)
    score = _clamp(
        int(plot["quality"])
        + _life_gem_value(user_data, worker, "경작의 젬", 0)
        + farming_unlock
    )
    amount = random.randint(*crop["yield"])
    base_amount = amount
    abundance = _life_gem_value(user_data, worker, "풍요의 젬", 0)
    for _ in range(amount):
        if random.randint(1, 100) <= abundance:
            amount += 1
    abundance_star = _life_gem_star(user_data, worker, "풍요의 젬")
    if abundance_star >= 3 and score >= 70:
        amount += 1
    if abundance_star >= 5 and score >= 85:
        amount += 1
    item = f"{_quality_name(score)} {plot['crop']}"
    produce = garden["produce"]
    produce[item] = int(produce.get(item, 0)) + amount
    inv = _inventory(user_data)
    inv[plot["crop"]] = int(inv.get(plot["crop"], 0)) + amount
    try:
        from progression_system_v6 import add_collection, ensure_progression
        add_collection(user_data, "crops", plot["crop"])
        progression = ensure_progression(user_data)
        if "first_crop" not in progression["achievements"]:
            progression["achievements"].append("first_crop")
        from progression_system_v6 import weekly_progress
        weekly_progress(user_data, "crop_harvests", 1)
    except ImportError:
        pass
    garden["plot"] = None
    gem_notes = []
    farming = _life_gem_value(user_data, worker, "경작의 젬", 0)
    if farming or farming_unlock:
        gem_notes.append(f"경작 품질 +{farming + farming_unlock}")
    if amount > base_amount:
        gem_notes.append(f"풍요 추가 수확 +{amount - base_amount}")
    suffix = f"\n💎 젬 적용: {' · '.join(gem_notes)}" if gem_notes else ""
    return True, f"{item} ×{amount}{suffix}"


def start_fish_farm(user_data: dict[str, Any], species: str, worker_index: int) -> tuple[bool, str]:
    life = ensure_life_data(user_data)
    farm = life["fish_farm"]
    if farm.get("tank"):
        return False, "이미 양식 중인 어종이 있습니다."
    if species not in FISH_SPECIES:
        return False, "알 수 없는 어종입니다."
    chars = user_data.get("characters", [])
    if not (0 <= worker_index < len(chars)):
        return False, "담당 캐릭터를 선택해주세요."
    if _worker_busy(life, worker_index):
        return False, "해당 캐릭터는 이미 다른 장기 생활 작업을 담당하고 있습니다."
    inv = _inventory(user_data)
    juvenile = FINGERLING_ITEMS[species]
    if int(inv.get(juvenile, 0)) > 0:
        stocking_item = juvenile
        stocking_kind = "치어 입식"
    elif int(inv.get(species, 0)) > 0:
        stocking_item = species
        stocking_kind = "친어 입식"
    else:
        return False, f"{juvenile} 또는 {species} 1마리가 필요합니다."
    inv[stocking_item] -= 1
    if int(inv.get(stocking_item, 0)) <= 0:
        inv.pop(stocking_item, None)
    farm["tank"] = {
        "species": species,
        "stocking_item": stocking_item,
        "stocking_kind": stocking_kind,
        "worker_index": worker_index,
        "worker_name": chars[worker_index].get("name", f"캐릭터 {worker_index + 1}"),
        "turn": 0,
        "growth": 0,
        "water_quality": 75,
        "satiety": 60,
        "stress": 10,
        "disease": 0,
        "quality": 50,
        "complete": False,
        "last_log": f"{stocking_kind}을 마쳤습니다.",
        "first_feed": True,
    }
    return True, f"{species} 양식을 시작했습니다. ({stocking_item} ×1 소비)"


def perform_fish_action(user_data: dict[str, Any], action: str) -> tuple[bool, str]:
    life = ensure_life_data(user_data)
    tank = life["fish_farm"].get("tank")
    if not tank:
        return False, "양식 중인 어종이 없습니다."
    if tank.get("complete"):
        return False, "이미 출하할 수 있는 상태입니다."

    worker = int(tank.get("worker_index", -1))
    log = ""
    if action == "feed":
        tank["satiety"] = _clamp(int(tank["satiety"]) + 30)
        water_loss = 8
        if _life_gem_star(user_data, worker, "양식의 젬") >= 3 and tank.get("first_feed"):
            water_loss = 0
            gem_note = " · 💎 양식의 젬 첫 먹이 수질 감소 방지"
        elif _life_gem_star(user_data, worker, "양식의 젬") >= 3:
            water_loss = 6
            gem_note = " · 💎 양식의 젬 수질 감소 완화"
        else:
            gem_note = ""
        tank["first_feed"] = False
        tank["water_quality"] = _clamp(int(tank["water_quality"]) - water_loss)
        if int(tank["satiety"]) > 90:
            tank["stress"] = _clamp(int(tank["stress"]) + 5)
        log = "🍽️ 먹이를 주었습니다." + gem_note
    elif action == "water":
        bonus = _life_gem_value(user_data, worker, "청류의 젬", 0)
        tank["water_quality"] = _clamp(int(tank["water_quality"]) + 30 + bonus)
        tank["stress"] = _clamp(int(tank["stress"]) + 5)
        log = "💧 물갈이를 했습니다."
        if bonus:
            log += f" · 💎 청류의 젬 수질 +{bonus}"
    elif action == "oxygen":
        tank["water_quality"] = _clamp(int(tank["water_quality"]) + 10)
        tank["stress"] = _clamp(int(tank["stress"]) - 8)
        log = "🫧 산소를 공급했습니다."
    elif action == "clean":
        bonus = _life_gem_value(user_data, worker, "청류의 젬", 0)
        tank["disease"] = _clamp(int(tank["disease"]) - 15)
        tank["water_quality"] = _clamp(int(tank["water_quality"]) + 15 + bonus)
        tank["satiety"] = _clamp(int(tank["satiety"]) - 5)
        log = "🧹 수조를 청소했습니다."
        if bonus:
            log += f" · 💎 청류의 젬 수질 +{bonus}"
    elif action == "observe":
        tank["quality"] = _clamp(int(tank["quality"]) + 4)
        log = "👀 상태를 세심하게 관찰했습니다. · 품질 +4"
    elif action == "wait":
        log = "⏳ 한 턴 지켜보았습니다."
    else:
        return False, "알 수 없는 양식 행동입니다."

    species = FISH_SPECIES[tank["species"]]
    low, high = species["water"]
    tank["satiety"] = _clamp(int(tank["satiety"]) - 8)
    water_decay = 4
    if _life_gem_star(user_data, worker, "청류의 젬") >= 3:
        water_decay = max(1, water_decay - 1)
    tank["water_quality"] = _clamp(int(tank["water_quality"]) - water_decay)

    growth = 2
    satiety_stable = 30 <= int(tank["satiety"]) <= 85
    water_stable = low <= int(tank["water_quality"]) <= high
    if satiety_stable:
        growth += 7
    if water_stable:
        growth += 3
        growth_bonus = _life_gem_value(user_data, worker, "양식의 젬", 0)
        growth += growth_bonus
        if growth_bonus:
            log += f" · 💎 양식의 젬 성장 +{growth_bonus}"
    if int(tank["disease"]) < 50:
        if satiety_stable and water_stable:
            tank["quality"] = _clamp(int(tank["quality"]) + 2)
            log += " · 🌊 안정된 환경 품질 +2"
        elif (
            (satiety_stable or water_stable)
            and int(tank["stress"]) < 70
        ):
            tank["quality"] = _clamp(int(tank["quality"]) + 1)
            log += " · 🌊 양호한 환경 품질 +1"
    if int(tank["water_quality"]) < 20:
        if _life_gem_star(user_data, worker, "청류의 젬") >= 3 and not tank.get("disease_guard_used"):
            tank["disease_guard_used"] = True
        else:
            tank["disease"] = _clamp(int(tank["disease"]) + 10)
    if int(tank["stress"]) >= 70:
        tank["quality"] = _clamp(int(tank["quality"]) - 5)
    if int(tank["disease"]) >= 100:
        tank["quality"] = 0

    tank["growth"] = _clamp(int(tank["growth"]) + growth)
    tank["turn"] = int(tank["turn"]) + 1
    tank["complete"] = int(tank["turn"]) >= int(species["turns"]) or int(tank["growth"]) >= 100
    tank["last_log"] = log
    advance_world_turn(user_data, 1)
    return True, log


def claim_fish(user_data: dict[str, Any]) -> tuple[bool, str]:
    life = ensure_life_data(user_data)
    farm = life["fish_farm"]
    tank = farm.get("tank")
    if not tank or not tank.get("complete"):
        return False, "아직 출하할 수 없습니다."
    worker = int(tank.get("worker_index", -1))
    species = FISH_SPECIES[tank["species"]]
    score = _clamp(int(tank["quality"]) - int(tank["disease"]) // 5)
    clearwater_quality_bonus = (
        _life_gem_star(user_data, worker, "청류의 젬") >= 5
        and int(tank["water_quality"]) >= 75
    )
    if clearwater_quality_bonus:
        score = _clamp(score + 6)
    amount = random.randint(*species["yield"])
    base_amount = amount
    abundance = _life_gem_value(user_data, worker, "풍요의 젬", 0)
    for _ in range(amount):
        if random.randint(1, 100) <= abundance:
            amount += 1
    abundance_star = _life_gem_star(user_data, worker, "풍요의 젬")
    if abundance_star >= 3 and score >= 70:
        amount += 1
    if abundance_star >= 5 and score >= 85:
        amount += 1
    if _life_gem_star(user_data, worker, "양식의 젬") >= 5 and random.randint(1, 100) <= 25:
        amount += 1
    item = f"{_quality_name(score)} {tank['species']}"
    produce = farm["produce"]
    produce[item] = int(produce.get(item, 0)) + amount
    inv = _inventory(user_data)
    inv[tank["species"]] = int(inv.get(tank["species"], 0)) + amount
    try:
        from progression_system_v6 import add_collection, ensure_progression
        add_collection(user_data, "fish", tank["species"])
        progression = ensure_progression(user_data)
        if "first_fish" not in progression["achievements"]:
            progression["achievements"].append("first_fish")
        from progression_system_v6 import weekly_progress
        weekly_progress(user_data, "fish_harvests", 1)
    except ImportError:
        pass
    farm["tank"] = None
    gem_notes = []
    if clearwater_quality_bonus:
        gem_notes.append("청류 출하 품질 +6")
    if amount > base_amount:
        gem_notes.append(f"풍요·양식 추가 출하 +{amount - base_amount}")
    suffix = f"\n💎 젬 적용: {' · '.join(gem_notes)}" if gem_notes else ""
    return True, f"{item} ×{amount}{suffix}"


async def _defer(interaction: discord.Interaction) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()


async def _save(save_func, author, user_data) -> None:
    await save_func(author.id, user_data)


def _replace_user_snapshot(target: dict[str, Any], fresh: dict[str, Any]) -> None:
    target.clear()
    target.update(fresh)


async def _run_latest_appraisal_operation(author, save_func, current_data, operation):
    """
    Reload, mutate and persist appraisal state as one per-user UI operation.

    A completed slot is never reported as claimed until its cleared state has
    committed. Old Discord messages therefore cannot replay a completed slot.
    """
    user_key = str(author.id)
    lock = _APPRAISAL_OPERATION_LOCKS.setdefault(user_key, asyncio.Lock())
    async with lock:
        fresh = await get_user_data(author.id, getattr(author, "display_name", None))
        ok, payload = operation(fresh)
        if ok:
            try:
                await _save(save_func, author, fresh)
            except StaleUserDataError:
                newest = await get_user_data(author.id, getattr(author, "display_name", None))
                _replace_user_snapshot(current_data, newest)
                return False, "다른 화면에서 감정 상태가 먼저 변경되었습니다. 최신 상태를 다시 확인해주세요."
        _replace_user_snapshot(current_data, fresh)
        return ok, payload


# owner-isolated-ui-v8.6.4
async def _life_owner_only(view, interaction):
    if interaction.user.id == view.author.id:
        return True
    await interaction.response.send_message("❌ 본인의 생활 화면만 조작할 수 있습니다.", ephemeral=True)
    return False


class PureHopeShopView(discord.ui.View):
    """Money shop for Pure Hope. One item always costs exactly 1,000,000 won."""

    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=120)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _life_owner_only(self, interaction)

    def get_embed(self, message: str | None = None) -> discord.Embed:
        inv = _inventory(self.user_data)
        embed = discord.Embed(
            title="✨ 순수한 희망 상점",
            description=message or "세공 도구 뽑기에 사용하는 재화입니다.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="가격", value=f"1개당 {PURE_HOPE_PRICE:,}원", inline=True)
        embed.add_field(name="보유", value=f"{inv.get(PURE_HOPE_ITEM, 0):,}개", inline=True)
        embed.add_field(name="보유 머니", value=f"{self.user_data.get('money', 0):,}원", inline=False)
        return embed

    async def _buy(self, interaction: discord.Interaction, count: int):
        await _defer(interaction)
        cost = PURE_HOPE_PRICE * count
        if int(self.user_data.get("money", 0)) < cost:
            return await interaction.followup.send(
                f"❌ 머니가 부족합니다. 필요: {cost:,}원", ephemeral=True
            )
        self.user_data["money"] = int(self.user_data.get("money", 0)) - cost
        inv = _inventory(self.user_data)
        inv[PURE_HOPE_ITEM] = int(inv.get(PURE_HOPE_ITEM, 0)) + count
        await _save(self.save_func, self.author, self.user_data)
        await interaction.edit_original_response(
            content=None,
            embed=self.get_embed(f"✅ 순수한 희망 {count}개를 구매했습니다."),
            view=self,
        )

    @discord.ui.button(label="1개 구매", style=discord.ButtonStyle.success)
    async def buy_one(self, interaction, button):
        await self._buy(interaction, 1)

    @discord.ui.button(label="10개 구매", style=discord.ButtonStyle.primary)
    async def buy_ten(self, interaction, button):
        await self._buy(interaction, 10)

    @discord.ui.button(label="상점으로", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button):
        await _defer(interaction)
        from shop import ShopView
        view = ShopView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(content=None, embed=view.get_embed(), view=view)


class LifeSystemView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=180)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        ensure_life_data(self.user_data)
        self.page = 0
        self._rebuild_menu()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _life_owner_only(self, interaction)

    def _rebuild_menu(self):
        self.clear_items()
        entries = [self.garden, self.fish, self.appraisal, self.crafting, self.tools]
        start = self.page * 3
        for item in entries[start:start + 3]:
            self.add_item(item)
        if self.page:
            prev = discord.ui.Button(label="이전 메뉴", style=discord.ButtonStyle.secondary, row=3)
            prev.callback = self._previous_menu
            self.add_item(prev)
        elif len(entries) > 3:
            nxt = discord.ui.Button(label="다음 메뉴", style=discord.ButtonStyle.secondary, row=3)
            nxt.callback = self._next_menu
            self.add_item(nxt)

    async def _next_menu(self, interaction):
        self.page = 1
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _previous_menu(self, interaction):
        self.page = 0
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    def get_embed(self) -> discord.Embed:
        life = ensure_life_data(self.user_data)
        inv = _inventory(self.user_data)
        embed = discord.Embed(
            title="🌿 생활·세공",
            description="채소밭과 양어장은 자체 턴을 사용하며, 유효 행동마다 공용 활동 턴도 1 진행됩니다.",
            color=discord.Color.green(),
        )
        embed.add_field(name="원석", value=f"미감정 {inv.get(RAW_STONE_ITEM, 0)}개", inline=True)
        embed.add_field(name="순수한 희망", value=f"{inv.get(PURE_HOPE_ITEM, 0)}개", inline=True)
        embed.add_field(name="세공 도구", value=f"{len(life['tools'])}/{len(TOOL_DEFS)}종", inline=True)
        embed.add_field(name="완성 젬", value=f"{len(life['gems'])}개", inline=True)
        embed.set_footer(text=f"메뉴 {self.page + 1}/2 · 한 화면에 최대 4개 버튼")
        return embed

    @discord.ui.button(label="채소밭", emoji="🥕", style=discord.ButtonStyle.success)
    async def garden(self, interaction, button):
        await _defer(interaction)
        view = VegetableGardenView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    @discord.ui.button(label="양어장", emoji="🐟", style=discord.ButtonStyle.primary)
    async def fish(self, interaction, button):
        await _defer(interaction)
        view = FishFarmView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    @discord.ui.button(label="원석 감정", emoji="🔍", style=discord.ButtonStyle.secondary)
    async def appraisal(self, interaction, button):
        await _defer(interaction)
        view = AppraisalView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    @discord.ui.button(label="젬 세공", emoji="💎", style=discord.ButtonStyle.danger)
    async def crafting(self, interaction, button):
        await _defer(interaction)
        view = GemCraftingView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    @discord.ui.button(label="세공 도구", emoji="🛠️", style=discord.ButtonStyle.secondary)
    async def tools(self, interaction, button):
        await _defer(interaction)
        view = ToolGachaView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)


class _LifeChildView(discord.ui.View):
    def __init__(self, author, user_data, save_func, timeout=180):
        super().__init__(timeout=timeout)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        ensure_life_data(self.user_data)
        attach_navigation(
            self,
            self.author,
            self._life_hub_factory,
            back_label="생활 관리로",
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await _life_owner_only(self, interaction)

    def _life_hub_factory(self):
        from life_overhaul_v5 import LifeHubView
        return LifeHubView(self.author, self.user_data, self.save_func)

    async def go_back(self, interaction):
        await _defer(interaction)
        view = self._life_hub_factory()
        await interaction.edit_original_response(embed=view.get_embed(), view=view)


class _PagedButtonMixin:
    """Render action choices as buttons and comparison choices as lists."""

    BUTTON_PAGE_SIZE = 4
    SELECT_PAGE_SIZE = 8
    _DYNAMIC_PREFIX = "life_page:"

    def _clear_paged_buttons(self):
        for item in list(self.children):
            custom_id = getattr(item, "custom_id", "") or ""
            if custom_id.startswith(self._DYNAMIC_PREFIX):
                self.remove_item(item)

    def _add_paged_buttons(
        self,
        entries,
        *,
        page_attr,
        label_func,
        select_callback,
        namespace,
        selected_func=None,
    ):
        self._clear_paged_buttons()
        entries = list(entries)
        total_pages = max(1, (len(entries) + self.BUTTON_PAGE_SIZE - 1) // self.BUTTON_PAGE_SIZE)
        page = max(0, min(int(getattr(self, page_attr, 0)), total_pages - 1))
        setattr(self, page_attr, page)
        start = page * self.BUTTON_PAGE_SIZE

        for offset, entry in enumerate(entries[start:start + self.BUTTON_PAGE_SIZE]):
            absolute_index = start + offset
            selected = bool(selected_func(entry)) if selected_func else False
            button = discord.ui.Button(
                label=str(label_func(entry))[:80],
                style=discord.ButtonStyle.success if selected else discord.ButtonStyle.primary,
                row=0,
                custom_id=f"{self._DYNAMIC_PREFIX}{namespace}:pick:{absolute_index}",
            )

            async def choose(interaction, value=entry):
                await select_callback(interaction, value)

            button.callback = choose
            self.add_item(button)

        if total_pages > 1:
            previous = discord.ui.Button(
                label="이전",
                emoji="◀️",
                style=discord.ButtonStyle.secondary,
                row=1,
                disabled=page <= 0,
                custom_id=f"{self._DYNAMIC_PREFIX}{namespace}:previous",
            )
            counter = discord.ui.Button(
                label=f"{page + 1}/{total_pages}",
                style=discord.ButtonStyle.secondary,
                row=1,
                disabled=True,
                custom_id=f"{self._DYNAMIC_PREFIX}{namespace}:counter",
            )
            following = discord.ui.Button(
                label="다음",
                emoji="▶️",
                style=discord.ButtonStyle.secondary,
                row=1,
                disabled=page >= total_pages - 1,
                custom_id=f"{self._DYNAMIC_PREFIX}{namespace}:next",
            )

            async def move(interaction, delta):
                await _defer(interaction)
                setattr(self, page_attr, max(0, min(page + delta, total_pages - 1)))
                self._render_buttons()
                await interaction.edit_original_response(embed=self.get_embed(), view=self)

            async def previous_callback(interaction):
                await move(interaction, -1)

            async def next_callback(interaction):
                await move(interaction, 1)

            previous.callback = previous_callback
            following.callback = next_callback
            self.add_item(previous)
            self.add_item(counter)
            self.add_item(following)

    def _add_paged_select(
        self,
        entries,
        *,
        page_attr,
        label_func,
        description_func,
        select_callback,
        namespace,
        placeholder,
        selected_func=None,
    ):
        self._clear_paged_buttons()
        entries = list(entries)
        total_pages = max(1, (len(entries) + self.SELECT_PAGE_SIZE - 1) // self.SELECT_PAGE_SIZE)
        page = max(0, min(int(getattr(self, page_attr, 0)), total_pages - 1))
        setattr(self, page_attr, page)
        start = page * self.SELECT_PAGE_SIZE
        visible = entries[start:start + self.SELECT_PAGE_SIZE]

        if visible:
            options = []
            for offset, entry in enumerate(visible):
                selected = bool(selected_func(entry)) if selected_func else False
                label = str(label_func(entry))
                if selected:
                    label = f"✓ {label}"
                options.append(
                    discord.SelectOption(
                        label=label[:100],
                        value=str(start + offset),
                        description=str(description_func(entry))[:100],
                    )
                )
            select = discord.ui.Select(
                placeholder=f"{placeholder} ({page + 1}/{total_pages})",
                options=options,
                row=0,
                custom_id=f"{self._DYNAMIC_PREFIX}{namespace}:select",
            )

            async def choose(interaction):
                index = int(interaction.data["values"][0])
                await select_callback(interaction, entries[index])

            select.callback = choose
            self.add_item(select)

        if total_pages > 1:
            previous = discord.ui.Button(
                label="이전",
                emoji="◀️",
                style=discord.ButtonStyle.secondary,
                row=1,
                disabled=page <= 0,
                custom_id=f"{self._DYNAMIC_PREFIX}{namespace}:previous",
            )
            counter = discord.ui.Button(
                label=f"{page + 1}/{total_pages}",
                style=discord.ButtonStyle.secondary,
                row=1,
                disabled=True,
                custom_id=f"{self._DYNAMIC_PREFIX}{namespace}:counter",
            )
            following = discord.ui.Button(
                label="다음",
                emoji="▶️",
                style=discord.ButtonStyle.secondary,
                row=1,
                disabled=page >= total_pages - 1,
                custom_id=f"{self._DYNAMIC_PREFIX}{namespace}:next",
            )

            async def move(interaction, delta):
                await _defer(interaction)
                setattr(self, page_attr, max(0, min(page + delta, total_pages - 1)))
                self._render_buttons()
                await interaction.edit_original_response(embed=self.get_embed(), view=self)

            async def previous_callback(interaction):
                await move(interaction, -1)

            async def next_callback(interaction):
                await move(interaction, 1)

            previous.callback = previous_callback
            following.callback = next_callback
            self.add_item(previous)
            self.add_item(counter)
            self.add_item(following)


class ToolTokenShopView(_LifeChildView):
    """Exchange overflow-duplicate tokens for useful crafting resources."""

    OFFERS = (
        ("tool", "미완성 도구 랜덤권", "최고 돌파가 아닌 도구 1개를 무작위 획득·돌파"),
        ("stone", "원석 ×5", "감정할 수 있는 원석 5개"),
        ("hope", "순수한 희망 ×3", "세공 도구 뽑기 재화 3개"),
        ("money", "머니 3,000,000원", "머니 300만 원"),
    )

    def __init__(self, author, user_data, save_func):
        super().__init__(author, user_data, save_func, timeout=180)
        self.selected_offer = "tool"
        self.last_message = None
        self._rebuild_components()

    def _rebuild_components(self):
        self.clear_items()
        options = []
        life = ensure_life_data(self.user_data)
        all_maxed = all(
            int(life["tools"].get(name, -1)) >= MAX_TOOL_BREAKTHROUGH
            for name in TOOL_DEFS
        )
        for key, label, description in self.OFFERS:
            disabled_note = " · 모두 최고 돌파" if key == "tool" and all_maxed else ""
            options.append(discord.SelectOption(
                label=label,
                value=key,
                description=f"{description}{disabled_note}"[:100],
                default=key == self.selected_offer,
            ))
        select = discord.ui.Select(
            placeholder="도구 증표 교환 상품",
            row=0,
            options=options,
        )
        select.callback = self._select_offer
        self.add_item(select)
        buy = discord.ui.Button(
            label=f"{TOOL_TOKEN_PRICE}개로 교환",
            style=discord.ButtonStyle.success,
            row=1,
        )
        buy.callback = self._buy
        self.add_item(buy)
        back = discord.ui.Button(label="세공 도구로", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back_to_tools
        self.add_item(back)
        attach_navigation(
            self,
            self.author,
            self._life_hub_factory,
            back_label="생활 관리로",
        )

    async def _select_offer(self, interaction):
        await _defer(interaction)
        self.selected_offer = interaction.data["values"][0]
        self.last_message = None
        self._rebuild_components()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def _buy(self, interaction):
        await _defer(interaction)
        ok, message, _ = buy_tool_token_offer(self.user_data, self.selected_offer)
        if ok:
            await _save(self.save_func, self.author, self.user_data)
        self.last_message = message
        self._rebuild_components()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def _back_to_tools(self, interaction):
        await _defer(interaction)
        view = ToolGachaView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    def get_embed(self):
        inventory = _inventory(self.user_data)
        selected = next(
            (offer for offer in self.OFFERS if offer[0] == self.selected_offer),
            self.OFFERS[0],
        )
        embed = discord.Embed(
            title="🎟️ 도구 증표 상점",
            description=(
                self.last_message
                or "최고 돌파 도구가 다시 나오면 도구 증표를 1개 받습니다."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="보유 도구 증표",
            value=f"{int(inventory.get(TOOL_TOKEN_ITEM, 0)):,}개",
            inline=True,
        )
        embed.add_field(name="모든 상품 가격", value=f"{TOOL_TOKEN_PRICE}개", inline=True)
        embed.add_field(
            name=selected[1],
            value=selected[2],
            inline=False,
        )
        embed.set_footer(text="랜덤권은 최고 돌파가 아닌 도구만 후보에 포함합니다.")
        return embed


class ToolGachaView(_LifeChildView):
    """Crafting-tool collection and gacha, categorized with eight tools per page."""

    ITEMS_PER_PAGE = 8

    def __init__(self, author, user_data, save_func):
        super().__init__(author, user_data, save_func, timeout=300)
        self.category = "all"
        self.page = 0
        self.selected_tool = next(iter(TOOL_DEFS), None)
        self.last_result = None
        self._rebuild_components()

    def _category_options(self):
        return (
            ("all", "전체"),
            ("owned", "보유 도구"),
            *((key, data["label"]) for key, data in TOOL_CATEGORIES.items()),
        )

    def _filtered_tools(self):
        names = list(TOOL_DEFS)
        owned = ensure_life_data(self.user_data)["tools"]
        if self.category == "owned":
            names = [name for name in names if name in owned]
        elif self.category in TOOL_CATEGORIES:
            allowed = set(TOOL_CATEGORIES[self.category]["tools"])
            names = [name for name in names if name in allowed]
        return sorted(
            names,
            key=lambda name: (
                0 if name in owned else 1,
                TOOL_DEFS[name]["rarity"],
                name,
            ),
        )

    def _sync_selection(self):
        names = self._filtered_tools()
        total_pages = max(1, (len(names) + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE)
        self.page = min(max(0, self.page), total_pages - 1)
        page_names = names[self.page * self.ITEMS_PER_PAGE:(self.page + 1) * self.ITEMS_PER_PAGE]
        if self.selected_tool not in page_names:
            self.selected_tool = page_names[0] if page_names else None
        return names, page_names, total_pages

    def _rebuild_components(self):
        self.clear_items()
        names, page_names, total_pages = self._sync_selection()
        owned = ensure_life_data(self.user_data)["tools"]

        category_select = discord.ui.Select(
            placeholder="세공 도구 종류",
            row=0,
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    description=f"{self._category_count(key)}종",
                    default=key == self.category,
                )
                for key, label in self._category_options()
            ],
        )
        category_select.callback = self._select_category
        self.add_item(category_select)

        if page_names:
            tool_select = discord.ui.Select(
                placeholder=f"세공 도구 선택 · 페이지당 {self.ITEMS_PER_PAGE}개",
                row=1,
                options=[
                    discord.SelectOption(
                        label=(
                            f"{name} · {owned[name]}돌파"
                            if name in owned else f"{name} · 미보유"
                        )[:100],
                        value=name,
                        description=(
                            f"{TOOL_DEFS[name]['rarity']} · "
                            f"{TOOL_DEFS[name]['effects'][int(owned.get(name, 0)) if name in owned else 0]}"
                        )[:100],
                        default=name == self.selected_tool,
                    )
                    for name in page_names
                ],
            )
            tool_select.callback = self._select_tool
            self.add_item(tool_select)

        previous = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=2, disabled=self.page == 0)
        previous.callback = self._previous_page
        self.add_item(previous)
        self.add_item(discord.ui.Button(
            label=f"{self.page + 1}/{total_pages} · 총 {len(names)}종",
            style=discord.ButtonStyle.secondary,
            row=2,
            disabled=True,
        ))
        following = discord.ui.Button(
            label="▶",
            style=discord.ButtonStyle.secondary,
            row=2,
            disabled=self.page >= total_pages - 1,
        )
        following.callback = self._next_page
        self.add_item(following)

        draw_one = discord.ui.Button(label="1회 뽑기", style=discord.ButtonStyle.primary, row=3)
        draw_one.callback = lambda interaction: self._draw(interaction, 1)
        self.add_item(draw_one)
        draw_ten = discord.ui.Button(label="10회 뽑기", style=discord.ButtonStyle.danger, row=3)
        draw_ten.callback = lambda interaction: self._draw(interaction, 10)
        self.add_item(draw_ten)
        token_shop = discord.ui.Button(label="도구 증표 상점", emoji="🎟️", style=discord.ButtonStyle.success, row=3)
        token_shop.callback = self._open_token_shop
        self.add_item(token_shop)
        attach_navigation(
            self,
            self.author,
            self._life_hub_factory,
            back_label="생활 관리로",
        )

    async def _open_token_shop(self, interaction):
        await _defer(interaction)
        view = ToolTokenShopView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    def _category_count(self, key):
        old = self.category
        self.category = key
        count = len(self._filtered_tools())
        self.category = old
        return count

    async def _select_category(self, interaction):
        await _defer(interaction)
        self.category = interaction.data["values"][0]
        self.page = 0
        self.selected_tool = None
        self.last_result = None
        self._rebuild_components()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def _select_tool(self, interaction):
        await _defer(interaction)
        self.selected_tool = interaction.data["values"][0]
        self.last_result = None
        self._rebuild_components()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def _previous_page(self, interaction):
        await _defer(interaction)
        self.page = max(0, self.page - 1)
        self.selected_tool = None
        self.last_result = None
        self._rebuild_components()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def _next_page(self, interaction):
        await _defer(interaction)
        self.page += 1
        self.selected_tool = None
        self.last_result = None
        self._rebuild_components()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def _draw(self, interaction, count: int):
        await _defer(interaction)
        inv = _inventory(self.user_data)
        hope = int(inv.get(PURE_HOPE_ITEM, 0))
        if hope < count:
            return await interaction.followup.send(
                f"❌ 순수한 희망이 부족합니다. 필요: {count}개 / 보유: {hope}개",
                ephemeral=True,
            )
        inv[PURE_HOPE_ITEM] = hope - count
        results = draw_crafting_tools(self.user_data, count)
        await _save(self.save_func, self.author, self.user_data)
        self.last_result = "\n".join(
            format_tool_result(result, index + 1 if count == 10 else None)
            for index, result in enumerate(results)
        )
        tool_results = [result for result in results if result.get("kind") == "tool"]
        if tool_results:
            self.selected_tool = tool_results[-1]["name"]
            self.category = "owned"
            owned_names = self._filtered_tools()
            if self.selected_tool in owned_names:
                self.page = owned_names.index(self.selected_tool) // self.ITEMS_PER_PAGE
        self._rebuild_components()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    def get_embed(self, message: str | None = None) -> discord.Embed:
        inv = _inventory(self.user_data)
        life = ensure_life_data(self.user_data)
        label = dict(self._category_options()).get(self.category, self.category)
        embed = discord.Embed(
            title="🛠️ 세공 도구 관리",
            description=(
                f"분류: **{label}** · 페이지당 {self.ITEMS_PER_PAGE}종\n"
                "도구는 영구 재사용되며, 중복 획득 시 즉시 자동 돌파됩니다."
            ),
            color=discord.Color.purple(),
        )
        embed.add_field(
            name="보유 현황",
            value=(
                f"도구 {len(life['tools'])}/{len(TOOL_DEFS)}종 · "
                f"순수한 희망 {inv.get(PURE_HOPE_ITEM, 0)}개 · "
                f"도구 증표 {inv.get(TOOL_TOKEN_ITEM, 0)}개\n"
                f"등장: 원석 {TOOL_GACHA_STONE_WEIGHT}% · "
                f"도구 {TOOL_GACHA_TOOL_WEIGHT}% · "
                f"서포트 조각 {TOOL_GACHA_SUPPORT_WEIGHT}%"
            ),
            inline=False,
        )
        if self.selected_tool:
            level = life["tools"].get(self.selected_tool)
            effect_level = int(level) if level is not None else 0
            definition = TOOL_DEFS[self.selected_tool]
            progression = "\n".join(
                f"{'▶' if index == effect_level else '•'} {index}돌파: {effect}"
                for index, effect in enumerate(definition["effects"])
            )
            embed.add_field(
                name=self.selected_tool,
                value=(
                    f"분류: {next((data['label'] for data in TOOL_CATEGORIES.values() if self.selected_tool in data['tools']), '범용')}\n"
                    f"희귀도: {definition['rarity']}\n"
                    f"보유: {f'{level}돌파' if level is not None else '미보유'}\n"
                    f"설명: {definition.get('description', '세공을 보조하는 영구 도구입니다.')}\n\n"
                    f"**돌파별 효과**\n{progression}"
                )[:1024],
                inline=False,
            )
        result_text = message or self.last_result
        if result_text:
            embed.add_field(name="방금 획득", value=result_text[:1024], inline=False)
        return embed


class AppraisalView(_LifeChildView):
    def __init__(self, author, user_data, save_func):
        super().__init__(author, user_data, save_func)
        self.selected_slot = 0

    def get_embed(self, message: str | None = None) -> discord.Embed:
        life = ensure_life_data(self.user_data)
        inv = _inventory(self.user_data)
        embed = discord.Embed(
            title="🔍 원석 감정",
            description=message or "감정에는 캐릭터·도구·비용이 필요하지 않습니다.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="미감정 원석", value=f"{inv.get(RAW_STONE_ITEM, 0)}개", inline=True)
        slot_lines = []
        for slot_index in range(3):
            progress, required = appraisal_progress(self.user_data, slot_index)
            marker = "▶ " if slot_index == self.selected_slot else ""
            state = "비어 있음" if required == 0 else (
                "완료 · 수령 가능" if progress >= required else f"{progress}/{required} 활동 턴"
            )
            slot_lines.append(f"{marker}**{slot_index + 1}번 슬롯** · {state}")
        embed.add_field(name="감정 슬롯", value="\n".join(slot_lines), inline=False)
        stones = [f"{k} ×{v}" for k, v in life["stones"].items() if int(v) > 0]
        embed.add_field(name="감정된 원석", value="\n".join(stones) or "없음", inline=False)
        return embed

    @discord.ui.select(
        placeholder="관리할 감정 슬롯 선택",
        options=[
            discord.SelectOption(label="1번 감정 슬롯", value="0"),
            discord.SelectOption(label="2번 감정 슬롯", value="1"),
            discord.SelectOption(label="3번 감정 슬롯", value="2"),
        ],
        row=0,
    )
    async def select_slot(self, interaction, select):
        self.selected_slot = int(select.values[0])
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="선택 슬롯 감정 시작", style=discord.ButtonStyle.primary, row=1)
    async def start(self, interaction, button):
        await _defer(interaction)
        ok, msg = await _run_latest_appraisal_operation(
            self.author,
            self.save_func,
            self.user_data,
            lambda latest: start_appraisal(latest, self.selected_slot),
        )
        await interaction.edit_original_response(embed=self.get_embed(msg), view=self)

    @discord.ui.button(label="선택 슬롯 결과 수령", style=discord.ButtonStyle.success, row=1)
    async def claim(self, interaction, button):
        await _defer(interaction)
        ok, msg = await _run_latest_appraisal_operation(
            self.author,
            self.save_func,
            self.user_data,
            lambda latest: claim_appraisal(latest, self.selected_slot),
        )
        if ok:
            msg = f"✅ 감정 완료: **{msg}**"
        await interaction.edit_original_response(embed=self.get_embed(msg), view=self)

    @discord.ui.button(label="완료 결과 모두 수령", style=discord.ButtonStyle.success, row=2)
    async def claim_all(self, interaction, button):
        await _defer(interaction)
        ok, results = await _run_latest_appraisal_operation(
            self.author,
            self.save_func,
            self.user_data,
            claim_all_appraisals,
        )
        if isinstance(results, str):
            results = [results]
        await interaction.edit_original_response(
            embed=self.get_embed("\n".join(results)),
            view=self,
        )

    @discord.ui.button(label="뒤로", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction, button):
        await self.go_back(interaction)


class VegetableGardenView(_LifeChildView):
    _ACTION_LABELS = {"파종", "물주기", "비료", "흙 고르기", "가지치기", "햇빛", "방치", "수확"}

    def __init__(self, author, user_data, save_func):
        super().__init__(author, user_data, save_func)
        self._sync_action_buttons()

    def _sync_action_buttons(self):
        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label in self._ACTION_LABELS:
                self.remove_item(item)
        plot = ensure_life_data(self.user_data)["vegetable_garden"].get("plot")
        if not plot:
            self.add_item(self.start)
        elif plot.get("complete"):
            self.add_item(self.claim)
        else:
            for action_button in (
                self.water,
                self.fertilize,
                self.soil,
                self.prune,
                self.sunlight,
                self.wait,
            ):
                self.add_item(action_button)

    def get_embed(self, message: str | None = None) -> discord.Embed:
        garden = ensure_life_data(self.user_data)["vegetable_garden"]
        plot = garden.get("plot")
        embed = discord.Embed(title="🥕 채소밭", description=message or "작물별 자체 재배 턴을 관리합니다.", color=discord.Color.green())
        if plot:
            crop = CROPS[plot["crop"]]
            embed.add_field(name="작물", value=f"{plot['crop']} · 담당 {plot['worker_name']}", inline=False)
            embed.add_field(name="진행", value=f"{plot['turn']}/{crop['turns']}턴 · 성장 {plot['growth']}%", inline=True)
            embed.add_field(name="환경", value=f"수분 {plot['water']} · 영양 {plot['nutrition']}\n건강 {plot['health']} · 스트레스 {plot['stress']}", inline=True)
            embed.add_field(name="품질", value=f"{plot['quality']} · {'수확 가능' if plot['complete'] else plot['last_log']}", inline=False)
        else:
            embed.add_field(name="재배 상태", value="비어 있음", inline=False)
        produce = garden.get("produce", {})
        if produce:
            embed.add_field(name="생산품", value="\n".join(f"{k} ×{v}" for k, v in produce.items()), inline=False)
        return embed

    @discord.ui.button(label="파종", style=discord.ButtonStyle.success)
    async def start(self, interaction, button):
        await _defer(interaction)
        view = CropSetupView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    async def _act(self, interaction, action):
        await _defer(interaction)
        ok, msg = perform_crop_action(self.user_data, action)
        if ok:
            await _save(self.save_func, self.author, self.user_data)
        self._sync_action_buttons()
        await interaction.edit_original_response(embed=self.get_embed(msg), view=self)

    @discord.ui.button(label="물주기", emoji="💧", style=discord.ButtonStyle.primary)
    async def water(self, interaction, button): await self._act(interaction, "water")

    @discord.ui.button(label="비료", emoji="🌱", style=discord.ButtonStyle.primary)
    async def fertilize(self, interaction, button): await self._act(interaction, "fertilize")

    @discord.ui.button(label="흙 고르기", emoji="🪴", style=discord.ButtonStyle.secondary)
    async def soil(self, interaction, button): await self._act(interaction, "soil")

    @discord.ui.button(label="가지치기", emoji="✂️", style=discord.ButtonStyle.secondary)
    async def prune(self, interaction, button): await self._act(interaction, "prune")

    @discord.ui.button(label="햇빛", emoji="☀️", style=discord.ButtonStyle.secondary)
    async def sunlight(self, interaction, button): await self._act(interaction, "sunlight")

    @discord.ui.button(label="방치", emoji="⏳", style=discord.ButtonStyle.secondary)
    async def wait(self, interaction, button): await self._act(interaction, "wait")

    @discord.ui.button(label="수확", emoji="🧺", style=discord.ButtonStyle.success)
    async def claim(self, interaction, button):
        await _defer(interaction)
        ok, msg = claim_crop(self.user_data)
        if ok:
            await _save(self.save_func, self.author, self.user_data)
        self._sync_action_buttons()
        await interaction.edit_original_response(embed=self.get_embed(msg), view=self)

    @discord.ui.button(label="뒤로", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button): await self.go_back(interaction)


class CropSetupView(_PagedButtonMixin, _LifeChildView):
    def __init__(self, author, user_data, save_func):
        super().__init__(author, user_data, save_func)
        self.crop_name = None
        self.worker_index = None
        self.stage = "crop"
        self.choice_page = 0
        inventory = _inventory(user_data)
        self.stocked = [
            (name, data, int(inventory.get(SEED_ITEMS[name], 0)))
            for name, data in CROPS.items()
            if int(inventory.get(SEED_ITEMS[name], 0)) > 0
        ]
        self.characters = list(user_data.get("characters", []))
        self._render_buttons()

    def _render_buttons(self):
        self._clear_paged_buttons()
        if self.confirm in self.children:
            self.remove_item(self.confirm)

        if self.stage == "crop":
            self._add_paged_select(
                self.stocked,
                page_attr="choice_page",
                label_func=lambda entry: f"{entry[0]} ×{entry[2]}",
                description_func=lambda entry: (
                    f"보유 {entry[2]}개 · {entry[1]['turns']}턴 · "
                    f"수확 {entry[1]['yield'][0]}~{entry[1]['yield'][1]} · "
                    f"적정 수분 {entry[1]['water'][0]}~{entry[1]['water'][1]}"
                ),
                select_callback=self._select_crop,
                namespace="crop",
                placeholder="심을 작물 선택",
            )
        elif self.stage == "worker":
            indexed_characters = list(enumerate(self.characters))
            self._add_paged_buttons(
                indexed_characters,
                page_attr="choice_page",
                label_func=lambda entry: entry[1].get("name", f"캐릭터 {entry[0] + 1}"),
                select_callback=self._select_worker,
                namespace="crop_worker",
            )
            self._add_step_back_button("작물 다시 선택", "crop")
        else:
            self._add_step_back_button("담당 다시 선택", "worker")
            if self.crop_name is not None and self.worker_index is not None:
                self.add_item(self.confirm)

    def _add_step_back_button(self, label, target_stage):
        button = discord.ui.Button(
            label=label,
            emoji="↩️",
            style=discord.ButtonStyle.secondary,
            row=2,
            custom_id=f"{self._DYNAMIC_PREFIX}crop:step_back",
        )

        async def callback(interaction):
            await _defer(interaction)
            self.stage = target_stage
            self.choice_page = 0
            self._render_buttons()
            await interaction.edit_original_response(embed=self.get_embed(), view=self)

        button.callback = callback
        self.add_item(button)

    async def _select_crop(self, interaction, entry):
        await _defer(interaction)
        self.crop_name = entry[0]
        self.stage = "worker"
        self.choice_page = 0
        self._render_buttons()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def _select_worker(self, interaction, entry):
        await _defer(interaction)
        self.worker_index = int(entry[0])
        self.stage = "confirm"
        self.choice_page = 0
        self._render_buttons()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    def get_embed(self):
        inventory = _inventory(self.user_data)
        stocks = [
            f"• {name}: {int(inventory.get(SEED_ITEMS[name], 0))}개"
            for name in CROPS
            if int(inventory.get(SEED_ITEMS[name], 0)) > 0
        ]
        worker_name = "미선택"
        if self.worker_index is not None:
            characters = self.user_data.get("characters", [])
            if 0 <= self.worker_index < len(characters):
                worker_name = characters[self.worker_index].get("name", f"캐릭터 {self.worker_index + 1}")
        return discord.Embed(
            title="🥕 파종 준비",
            description=(
                f"작물: **{self.crop_name or '미선택'}**\n"
                f"담당: **{worker_name}**\n\n"
                f"현재 단계: **{'작물 선택' if self.stage == 'crop' else '담당 선택' if self.stage == 'worker' else '시작 확인'}**\n\n"
                f"**현재 보유 씨앗·종균**\n"
                f"{chr(10).join(stocks) if stocks else '보유 재고가 없습니다. 생활 상점에서 먼저 구매하세요.'}"
            ),
            color=discord.Color.green(),
        )

    @discord.ui.button(label="재배 시작", style=discord.ButtonStyle.success, row=2)
    async def confirm(self, interaction, button):
        await _defer(interaction)
        if self.crop_name is None or self.worker_index is None:
            return await interaction.followup.send("작물과 담당 캐릭터를 모두 선택해주세요.", ephemeral=True)
        ok, msg = start_crop(self.user_data, self.crop_name, self.worker_index)
        if ok:
            await _save(self.save_func, self.author, self.user_data)
        view = VegetableGardenView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(msg), view=view)


class FishFarmView(_LifeChildView):
    _ACTION_LABELS = {"입식", "먹이", "물갈이", "산소", "청소", "관찰", "방치", "출하"}

    def __init__(self, author, user_data, save_func):
        super().__init__(author, user_data, save_func)
        self._sync_action_buttons()

    def _sync_action_buttons(self):
        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label in self._ACTION_LABELS:
                self.remove_item(item)
        tank = ensure_life_data(self.user_data)["fish_farm"].get("tank")
        if not tank:
            self.add_item(self.start)
        elif tank.get("complete"):
            self.add_item(self.claim)
        else:
            for action_button in (
                self.feed,
                self.water,
                self.oxygen,
                self.clean,
                self.observe,
                self.wait,
            ):
                self.add_item(action_button)

    def get_embed(self, message: str | None = None) -> discord.Embed:
        farm = ensure_life_data(self.user_data)["fish_farm"]
        tank = farm.get("tank")
        embed = discord.Embed(title="🐟 양어장", description=message or "어종별 자체 양식 턴을 관리합니다.", color=discord.Color.blue())
        if tank:
            species = FISH_SPECIES[tank["species"]]
            embed.add_field(name="어종", value=f"{tank['species']} · 담당 {tank['worker_name']}", inline=False)
            embed.add_field(name="진행", value=f"{tank['turn']}/{species['turns']}턴 · 성장 {tank['growth']}%", inline=True)
            embed.add_field(name="환경", value=f"수질 {tank['water_quality']} · 포만 {tank['satiety']}\n스트레스 {tank['stress']} · 질병 {tank['disease']}", inline=True)
            embed.add_field(name="품질", value=f"{tank['quality']} · {'출하 가능' if tank['complete'] else tank['last_log']}", inline=False)
        else:
            embed.add_field(name="양식 상태", value="비어 있음", inline=False)
        return embed

    @discord.ui.button(label="입식", style=discord.ButtonStyle.success)
    async def start(self, interaction, button):
        await _defer(interaction)
        view = FishSetupView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    async def _act(self, interaction, action):
        await _defer(interaction)
        ok, msg = perform_fish_action(self.user_data, action)
        if ok:
            await _save(self.save_func, self.author, self.user_data)
        self._sync_action_buttons()
        await interaction.edit_original_response(embed=self.get_embed(msg), view=self)

    @discord.ui.button(label="먹이", emoji="🍽️", style=discord.ButtonStyle.primary)
    async def feed(self, interaction, button): await self._act(interaction, "feed")

    @discord.ui.button(label="물갈이", emoji="💧", style=discord.ButtonStyle.primary)
    async def water(self, interaction, button): await self._act(interaction, "water")

    @discord.ui.button(label="산소", emoji="🫧", style=discord.ButtonStyle.secondary)
    async def oxygen(self, interaction, button): await self._act(interaction, "oxygen")

    @discord.ui.button(label="청소", emoji="🧹", style=discord.ButtonStyle.secondary)
    async def clean(self, interaction, button): await self._act(interaction, "clean")

    @discord.ui.button(label="관찰", emoji="👀", style=discord.ButtonStyle.secondary)
    async def observe(self, interaction, button): await self._act(interaction, "observe")

    @discord.ui.button(label="방치", emoji="⏳", style=discord.ButtonStyle.secondary)
    async def wait(self, interaction, button): await self._act(interaction, "wait")

    @discord.ui.button(label="출하", emoji="🧺", style=discord.ButtonStyle.success)
    async def claim(self, interaction, button):
        await _defer(interaction)
        ok, msg = claim_fish(self.user_data)
        if ok:
            await _save(self.save_func, self.author, self.user_data)
        self._sync_action_buttons()
        await interaction.edit_original_response(embed=self.get_embed(msg), view=self)

    @discord.ui.button(label="뒤로", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button): await self.go_back(interaction)


class FishSetupView(_PagedButtonMixin, _LifeChildView):
    def __init__(self, author, user_data, save_func):
        super().__init__(author, user_data, save_func)
        self.species = None
        self.worker_index = None
        self.stage = "species"
        self.choice_page = 0
        inventory = _inventory(user_data)
        self.stocked = [
            (
                name,
                data,
                int(inventory.get(FINGERLING_ITEMS[name], 0)),
                int(inventory.get(name, 0)),
            )
            for name, data in FISH_SPECIES.items()
            if int(inventory.get(FINGERLING_ITEMS[name], 0)) > 0 or int(inventory.get(name, 0)) > 0
        ]
        self.characters = list(user_data.get("characters", []))
        self._render_buttons()

    def _render_buttons(self):
        self._clear_paged_buttons()
        if self.confirm in self.children:
            self.remove_item(self.confirm)

        if self.stage == "species":
            self._add_paged_select(
                self.stocked,
                page_attr="choice_page",
                label_func=lambda entry: f"{entry[0]} · 입식 {entry[2] + entry[3]}회",
                description_func=lambda entry: (
                    f"치어 {entry[2]} · 물고기 {entry[3]} · {entry[1]['turns']}턴 · "
                    f"출하 {entry[1]['yield'][0]}~{entry[1]['yield'][1]} · "
                    f"적정 수질 {entry[1]['water'][0]}~{entry[1]['water'][1]}"
                ),
                select_callback=self._select_species,
                namespace="species",
                placeholder="양식할 어종 선택",
            )
        elif self.stage == "worker":
            indexed_characters = list(enumerate(self.characters))
            self._add_paged_buttons(
                indexed_characters,
                page_attr="choice_page",
                label_func=lambda entry: entry[1].get("name", f"캐릭터 {entry[0] + 1}"),
                select_callback=self._select_worker,
                namespace="fish_worker",
            )
            self._add_step_back_button("어종 다시 선택", "species")
        else:
            self._add_step_back_button("담당 다시 선택", "worker")
            if self.species is not None and self.worker_index is not None:
                self.add_item(self.confirm)

    def _add_step_back_button(self, label, target_stage):
        button = discord.ui.Button(
            label=label,
            emoji="↩️",
            style=discord.ButtonStyle.secondary,
            row=2,
            custom_id=f"{self._DYNAMIC_PREFIX}fish:step_back",
        )

        async def callback(interaction):
            await _defer(interaction)
            self.stage = target_stage
            self.choice_page = 0
            self._render_buttons()
            await interaction.edit_original_response(embed=self.get_embed(), view=self)

        button.callback = callback
        self.add_item(button)

    async def _select_species(self, interaction, entry):
        await _defer(interaction)
        self.species = entry[0]
        self.stage = "worker"
        self.choice_page = 0
        self._render_buttons()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def _select_worker(self, interaction, entry):
        await _defer(interaction)
        self.worker_index = int(entry[0])
        self.stage = "confirm"
        self.choice_page = 0
        self._render_buttons()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    def get_embed(self):
        inventory = _inventory(self.user_data)
        stocks = [
            (
                f"• {name}: {FINGERLING_ITEMS[name]} "
                f"{int(inventory.get(FINGERLING_ITEMS[name], 0))} · 물고기 {int(inventory.get(name, 0))}"
            )
            for name in FISH_SPECIES
            if int(inventory.get(FINGERLING_ITEMS[name], 0)) > 0 or int(inventory.get(name, 0)) > 0
        ]
        worker_name = "미선택"
        if self.worker_index is not None:
            characters = self.user_data.get("characters", [])
            if 0 <= self.worker_index < len(characters):
                worker_name = characters[self.worker_index].get("name", f"캐릭터 {self.worker_index + 1}")
        return discord.Embed(
            title="🐟 입식 준비",
            description=(
                f"어종: **{self.species or '미선택'}**\n"
                f"담당: **{worker_name}**\n\n"
                f"현재 단계: **{'어종 선택' if self.stage == 'species' else '담당 선택' if self.stage == 'worker' else '시작 확인'}**\n\n"
                f"**현재 입식 가능 재고**\n"
                f"{chr(10).join(stocks) if stocks else '보유 재고가 없습니다. 생활 상점에서 먼저 구매하세요.'}"
            ),
            color=discord.Color.blue(),
        )

    @discord.ui.button(label="양식 시작", style=discord.ButtonStyle.success, row=2)
    async def confirm(self, interaction, button):
        await _defer(interaction)
        if self.species is None or self.worker_index is None:
            return await interaction.followup.send("어종과 담당 캐릭터를 모두 선택해주세요.", ephemeral=True)
        ok, msg = start_fish_farm(self.user_data, self.species, self.worker_index)
        if ok:
            await _save(self.save_func, self.author, self.user_data)
        view = FishFarmView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(msg), view=view)


class GemCraftingView(_LifeChildView):
    _ACTION_LABELS = {"세공 시작", "달구기", "식히기", "마법부여", "모양 내기", "불순물 제거"}

    def __init__(self, author, user_data, save_func):
        super().__init__(author, user_data, save_func)
        self._sync_action_buttons()

    def _sync_action_buttons(self):
        for item in list(self.children):
            if isinstance(item, discord.ui.Button) and item.label in self._ACTION_LABELS:
                self.remove_item(item)
        craft = ensure_life_data(self.user_data).get("gem_crafting")
        if not craft:
            self.add_item(self.start)
        else:
            for action_button in (
                self.heat,
                self.cool,
                self.enchant,
                self.shape,
                self.purify,
            ):
                self.add_item(action_button)

    def get_embed(self, message: str | None = None) -> discord.Embed:
        life = ensure_life_data(self.user_data)
        craft = life.get("gem_crafting")
        embed = discord.Embed(title="💎 젬 세공", description=message or "총 20턴. 모양 내기 성공 시 성급이 직접 상승합니다.", color=discord.Color.magenta())
        if not craft:
            stones = [f"{k} ×{v}" for k, v in life["stones"].items() if int(v) > 0]
            embed.add_field(name="세공 상태", value="대기 중", inline=False)
            embed.add_field(name="감정된 원석", value="\n".join(stones) or "없음", inline=False)
            embed.add_field(name="완성 젬", value=f"{len(life['gems'])}개", inline=True)
            return embed

        chances = _craft_chances(self.user_data, craft)
        embed.add_field(name="대상", value=f"{craft['gem_def']['name']} · {craft['star']}성", inline=False)
        embed.add_field(name="진행", value=f"{craft['turn']}/{CRAFT_TURNS}턴 · 달굼 {craft['heat']}", inline=True)
        embed.add_field(
            name="현재 수치",
            value=(
                f"고유 효과 **{gem_final_effect_value(craft)}**"
                + (
                    f" (세공값 {craft['effect_value']})"
                    if gem_final_effect_value(craft) != int(craft["effect_value"])
                    else ""
                )
                + "\n"
                f"주 능력 **{gem_main_stat_text(craft)}**\n"
                f"보조 능력 **아티팩트 주 능력치 +{gem_final_aux_value(craft)}**"
            ),
            inline=True,
        )
        embed.add_field(name="담당", value=craft.get("worker_name", "-"), inline=True)
        tools = [f"{name} {level}돌파" for name, level in craft.get("tools", {}).items()]
        embed.add_field(name="도구", value="\n".join(tools) or "미사용", inline=False)
        magnifier_level = _tool_level(craft, "장인의 확대경")
        if magnifier_level is not None:
            worker_bonus = _craft_worker_bonus(self.user_data, craft)
            embed.add_field(
                name="성공률",
                value=(
                    f"마법부여 {chances['enchant']}% · "
                    f"모양 내기 {chances['shape']}% · "
                    f"불순물 제거 {chances['purify']}%"
                    + (f"\n💎 장인의 젬 적용: 성공률 +{worker_bonus}%p" if worker_bonus else "")
                ),
                inline=False,
            )
            if magnifier_level >= 2:
                embed.add_field(
                    name="확대경 예상 성공 효과",
                    value=_craft_gain_preview(craft),
                    inline=False,
                )
        embed.add_field(name="직전 결과", value=craft.get("last_log", "-"), inline=False)
        return embed

    @discord.ui.button(label="세공 시작", style=discord.ButtonStyle.success)
    async def start(self, interaction, button):
        await _defer(interaction)
        life = ensure_life_data(self.user_data)
        if life.get("gem_crafting"):
            return await interaction.followup.send("이미 세공 중입니다.", ephemeral=True)
        stones = [name for name, count in life["stones"].items() if int(count) > 0]
        if not stones:
            return await interaction.followup.send("감정된 원석이 없습니다.", ephemeral=True)
        view = StoneChoiceView(self.author, self.user_data, self.save_func, stones)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    async def _act(self, interaction, action):
        await _defer(interaction)
        ok, msg, result = perform_craft_action(self.user_data, action)
        if ok:
            await _save(self.save_func, self.author, self.user_data)
        if result:
            msg = f"✅ 세공 완료: **{result['star']}성 {result['name']}**"
        self._sync_action_buttons()
        await interaction.edit_original_response(embed=self.get_embed(msg), view=self)

    @discord.ui.button(label="달구기", emoji="🔥", style=discord.ButtonStyle.danger)
    async def heat(self, interaction, button): await self._act(interaction, "heat")

    @discord.ui.button(label="식히기", emoji="❄️", style=discord.ButtonStyle.primary)
    async def cool(self, interaction, button): await self._act(interaction, "cool")

    @discord.ui.button(label="마법부여", emoji="✨", style=discord.ButtonStyle.primary)
    async def enchant(self, interaction, button): await self._act(interaction, "enchant")

    @discord.ui.button(label="모양 내기", emoji="💎", style=discord.ButtonStyle.success)
    async def shape(self, interaction, button): await self._act(interaction, "shape")

    @discord.ui.button(label="불순물 제거", emoji="🔷", style=discord.ButtonStyle.secondary)
    async def purify(self, interaction, button): await self._act(interaction, "purify")

    @discord.ui.button(label="뒤로", style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button): await self.go_back(interaction)


class StoneChoiceView(_PagedButtonMixin, _LifeChildView):
    def __init__(self, author, user_data, save_func, stones):
        super().__init__(author, user_data, save_func)
        self.stones = list(stones)
        self.choice_page = 0
        self._render_buttons()

    def _render_buttons(self):
        stone_stock = ensure_life_data(self.user_data)["stones"]
        self._add_paged_select(
            self.stones,
            page_attr="choice_page",
            label_func=lambda stone: stone,
            description_func=lambda stone: (
                f"현재 {int(stone_stock.get(stone, 0))}개 · 세공 시작 시 1개 소비"
            ),
            select_callback=self._select_stone,
            namespace="stone",
            placeholder="세공할 원석 선택",
        )

    async def _select_stone(self, interaction, stone):
        await _defer(interaction)
        view = GemSetupView(self.author, self.user_data, self.save_func, stone)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    def get_embed(self):
        stocks = [
            f"• {stone}: {int(ensure_life_data(self.user_data)['stones'].get(stone, 0))}개"
            for stone in self.stones
        ]
        return discord.Embed(
            title="💎 원석 선택",
            description=(
                "현재 재고를 확인하고 사용할 원석을 목록에서 선택하세요.\n\n"
                + ("\n".join(stocks) if stocks else "사용 가능한 원석이 없습니다.")
            ),
            color=discord.Color.magenta(),
        )


class GemSetupView(_PagedButtonMixin, _LifeChildView):
    def __init__(self, author, user_data, save_func, stone):
        super().__init__(author, user_data, save_func)
        self.stone = stone
        self.gem_index = None
        self.worker_index = None
        self.tool_names = []
        self.stage = "gem"
        self.choice_page = 0
        self.characters = list(user_data.get("characters", []))
        self.tools = sorted(ensure_life_data(user_data)["tools"].items())
        self._render_buttons()

    def _render_buttons(self):
        self._clear_paged_buttons()
        if self.confirm in self.children:
            self.remove_item(self.confirm)

        if self.stage == "gem":
            gem_entries = list(enumerate(STONE_GEMS[self.stone]))
            self._add_paged_select(
                gem_entries,
                page_attr="choice_page",
                label_func=lambda entry: entry[1]["name"],
                description_func=lambda entry: f"효과: {entry[1]['summary']}",
                select_callback=self._select_gem,
                namespace="gem",
                placeholder="완성할 젬 선택",
            )
        elif self.stage == "worker":
            indexed_characters = list(enumerate(self.characters))
            self._add_paged_buttons(
                indexed_characters,
                page_attr="choice_page",
                label_func=lambda entry: entry[1].get("name", f"캐릭터 {entry[0] + 1}"),
                select_callback=self._select_worker,
                namespace="gem_worker",
            )
            self._add_step_back_button("젬 다시 선택", "gem")
        elif self.stage == "tools":
            self._add_paged_select(
                self.tools,
                page_attr="choice_page",
                label_func=lambda entry: f"{entry[0]} · {entry[1]}돌파",
                description_func=lambda entry: (
                    f"{'선택됨 · ' if entry[0] in self.tool_names else ''}"
                    f"{TOOL_DEFS[entry[0]]['effects'][int(entry[1])]}"
                ),
                select_callback=self._toggle_tool,
                namespace="gem_tools",
                placeholder=f"세공 도구 선택 ({len(self.tool_names)}/{MAX_EQUIPPED_TOOLS})",
                selected_func=lambda entry: entry[0] in self.tool_names,
            )
            self._add_step_back_button("담당 다시 선택", "worker")
            done = discord.ui.Button(
                label="도구 선택 완료",
                emoji="✅",
                style=discord.ButtonStyle.success,
                row=2,
                custom_id=f"{self._DYNAMIC_PREFIX}gem_tools:done",
            )

            async def finish_tools(interaction):
                await _defer(interaction)
                self.stage = "confirm"
                self.choice_page = 0
                self._render_buttons()
                await interaction.edit_original_response(embed=self.get_embed(), view=self)

            done.callback = finish_tools
            self.add_item(done)
        else:
            self._add_step_back_button(
                "도구 다시 선택" if self.tools else "담당 다시 선택",
                "tools" if self.tools else "worker",
            )
            if self.gem_index is not None and self.worker_index is not None:
                self.add_item(self.confirm)

    def _add_step_back_button(self, label, target_stage):
        button = discord.ui.Button(
            label=label,
            emoji="↩️",
            style=discord.ButtonStyle.secondary,
            row=2,
            custom_id=f"{self._DYNAMIC_PREFIX}gem_setup:step_back",
        )

        async def callback(interaction):
            await _defer(interaction)
            self.stage = target_stage
            self.choice_page = 0
            self._render_buttons()
            await interaction.edit_original_response(embed=self.get_embed(), view=self)

        button.callback = callback
        self.add_item(button)

    async def _select_gem(self, interaction, entry):
        await _defer(interaction)
        self.gem_index = int(entry[0])
        self.stage = "worker"
        self.choice_page = 0
        self._render_buttons()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def _select_worker(self, interaction, entry):
        await _defer(interaction)
        self.worker_index = int(entry[0])
        self.stage = "tools" if self.tools else "confirm"
        self.choice_page = 0
        self._render_buttons()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def _toggle_tool(self, interaction, entry):
        await _defer(interaction)
        name = entry[0]
        if name in self.tool_names:
            self.tool_names.remove(name)
        elif len(self.tool_names) >= MAX_EQUIPPED_TOOLS:
            await interaction.followup.send(
                f"세공 도구는 최대 {MAX_EQUIPPED_TOOLS}종까지 선택할 수 있습니다.",
                ephemeral=True,
            )
            return
        else:
            self.tool_names.append(name)
        self._render_buttons()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    def get_embed(self):
        gem_name = "미선택" if self.gem_index is None else STONE_GEMS[self.stone][self.gem_index]["name"]
        worker = "미선택"
        if self.worker_index is not None:
            worker = self.user_data["characters"][self.worker_index].get("name", str(self.worker_index))
        tools = ", ".join(self.tool_names) or "미사용"
        stage_label = {
            "gem": "젬 선택",
            "worker": "담당 캐릭터 선택",
            "tools": f"세공 도구 선택 ({len(self.tool_names)}/{MAX_EQUIPPED_TOOLS})",
            "confirm": "세공 시작 확인",
        }[self.stage]
        gem_summary = ""
        if self.gem_index is not None:
            gem_summary = f"\n효과: {STONE_GEMS[self.stone][self.gem_index]['summary']}"
        return discord.Embed(
            title="💎 세공 준비",
            description=(
                f"현재 단계: **{stage_label}**\n\n"
                f"원석: **{self.stone}**\n"
                f"젬: **{gem_name}**{gem_summary}\n"
                f"담당: **{worker}**\n"
                f"도구: **{tools}**"
            ),
            color=discord.Color.magenta(),
        )

    @discord.ui.button(label="20턴 세공 시작", style=discord.ButtonStyle.success, row=3)
    async def confirm(self, interaction, button):
        await _defer(interaction)
        if self.gem_index is None or self.worker_index is None:
            return await interaction.followup.send("젬과 담당 캐릭터를 모두 선택해주세요.", ephemeral=True)
        ok, msg = start_gem_crafting(
            self.user_data, self.stone, self.gem_index, self.worker_index, self.tool_names
        )
        if ok:
            await _save(self.save_func, self.author, self.user_data)
        view = GemCraftingView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(embed=view.get_embed(msg), view=view)
