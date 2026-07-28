# cafe-rewards-v9.3.2
# cafe-tycoon-v9.3
"""Persistent 2-4 player café tycoon run by shared turns."""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any

import aiomysql
import discord

from data_manager import get_db_pool
from items import ITEM_CATEGORIES


MIN_PLAYERS = 2
MAX_PLAYERS = 4
LOBBIES_PER_PAGE = 8
RARE_REWARDS = tuple(
    sorted(
        name for name, info in ITEM_CATEGORIES.items()
        if info.get("type") == "rare_mat"
    )
)
MACHINE_LABELS = {
    "coffee": "커피 머신",
    "oven": "조리 오븐",
    "display": "디저트 쇼케이스",
    "service": "자동 서빙 벨",
    "lounge": "직원 휴게실",
}
MACHINE_MAX = {"coffee": 4, "oven": 4, "display": 4, "service": 3, "lounge": 3}
PRODUCT_LABELS = {"drink": "음료", "food": "음식", "dessert": "디저트"}
RECIPE_PAGE_SIZE = 8
RECIPE_CATALOG = {
    # 처음부터 만들 수 있는 기본 메뉴
    "아메리카노": {
        "kind": "drink", "ingredients": {"원두": 2},
        "price": 8_000, "score": 10, "tier": 0,
    },
    "카페라떼": {
        "kind": "drink", "ingredients": {"원두": 2, "우유": 1},
        "price": 11_000, "score": 13, "tier": 0,
    },
    "감자 수프": {
        "kind": "food", "ingredients": {"감자": 2, "우유": 1},
        "price": 12_000, "score": 15, "tier": 0,
    },
    "샌드위치": {
        "kind": "food", "ingredients": {"밀가루": 2, "채소": 2},
        "price": 14_000, "score": 17, "tier": 0,
    },
    "간단한 다과": {
        "kind": "dessert", "ingredients": {"밀가루": 1, "설탕": 1},
        "price": 10_000, "score": 12, "tier": 0,
    },
    # 연구 1단계
    "바닐라라떼": {
        "kind": "drink", "ingredients": {"원두": 2, "우유": 2, "설탕": 1},
        "price": 18_000, "score": 22, "tier": 1,
    },
    "토마토 샐러드": {
        "kind": "food", "ingredients": {"채소": 3},
        "price": 17_000, "score": 21, "tier": 1,
    },
    "빵잉어 구이": {
        "kind": "food", "ingredients": {"생선": 2, "채소": 1},
        "price": 19_000, "score": 23, "tier": 1,
    },
    "솜사탕": {
        "kind": "dessert", "ingredients": {"설탕": 2},
        "price": 15_000, "score": 18, "tier": 1,
    },
    "구름과자 낱개": {
        "kind": "dessert", "ingredients": {"밀가루": 2, "설탕": 2},
        "price": 19_000, "score": 23, "tier": 1,
    },
    # 연구 2단계
    "카페모카": {
        "kind": "drink", "ingredients": {"원두": 2, "우유": 1, "초콜릿": 1},
        "price": 27_000, "score": 34, "tier": 2,
    },
    "버들치 조림": {
        "kind": "food", "ingredients": {"생선": 2, "채소": 2},
        "price": 28_000, "score": 35, "tier": 2,
    },
    "열매 샐러드": {
        "kind": "food", "ingredients": {"채소": 2, "설탕": 1},
        "price": 25_000, "score": 31, "tier": 2,
    },
    "구름다리 스낵": {
        "kind": "dessert", "ingredients": {"밀가루": 2, "우유": 1, "설탕": 2},
        "price": 31_000, "score": 39, "tier": 2,
    },
    # 연구 3단계
    "악몽 프라페": {
        "kind": "drink",
        "ingredients": {"원두": 2, "우유": 2, "초콜릿": 2},
        "price": 48_000, "score": 62, "tier": 3,
    },
    "바닷물고기 회": {
        "kind": "food", "ingredients": {"생선": 4},
        "price": 46_000, "score": 59, "tier": 3,
    },
    "다과 풀세트": {
        "kind": "dessert",
        "ingredients": {"밀가루": 3, "우유": 2, "설탕": 3, "초콜릿": 1},
        "price": 58_000, "score": 75, "tier": 3,
    },
    "파티 풀세트": {
        "kind": "dessert",
        "ingredients": {"밀가루": 3, "채소": 2, "설탕": 3},
        "price": 62_000, "score": 80, "tier": 3,
    },
}
STARTER_TYCOON_RECIPES = tuple(
    name for name, recipe in RECIPE_CATALOG.items() if int(recipe["tier"]) == 0
)
RESEARCH_COST = {1: 25_000, 2: 60_000, 3: 120_000}
CAFE_STATE_VERSION = 2
DECOR_SLOTS = {
    "sign": "간판",
    "counter": "카운터",
    "seating": "좌석",
    "wall": "벽",
    "lighting": "조명",
    "display_case": "진열장",
}
DECOR_THEMES = {
    "cozy": "포근한 원목",
    "modern": "모던 메탈",
    "garden": "숲속 정원",
    "mystic": "신비한 밤",
}
DECOR_PRICES = {"common": 80, "rare": 180, "epic": 350, "legendary": 650}
DECOR_RARITY_LABELS = {
    "common": "일반", "rare": "희귀", "epic": "영웅", "legendary": "전설",
}
_THEME_ITEMS = {
    "cozy": ("나무 간판", "원목 카운터", "푹신한 소파", "체크 벽지", "전구 조명", "화분 진열장"),
    "modern": ("네온 간판", "스틸 카운터", "바 체어", "타일 벽", "레일 조명", "유리 쇼케이스"),
    "garden": ("잎새 간판", "덩굴 카운터", "라탄 좌석", "이끼 벽", "햇살 조명", "꽃 진열장"),
    "mystic": ("별빛 간판", "달빛 카운터", "벨벳 좌석", "은하 벽", "오로라 조명", "수정 쇼케이스"),
}
_THEME_RARITIES = {
    "cozy": ("common", "common", "rare", "common", "rare", "rare"),
    "modern": ("rare", "common", "rare", "epic", "rare", "epic"),
    "garden": ("rare", "epic", "rare", "epic", "epic", "legendary"),
    "mystic": ("epic", "rare", "epic", "legendary", "legendary", "epic"),
}
DECOR_APPEARANCES = {
    f"{theme}_{slot}": {
        "name": names[index],
        "slot": slot,
        "theme": theme,
        "rarity": _THEME_RARITIES[theme][index],
    }
    for theme, names in _THEME_ITEMS.items()
    for index, slot in enumerate(DECOR_SLOTS)
}
DECOR_EFFECTS = {
    "sign_order_board": {
        "name": "넓은 메뉴 간판", "slot": "sign", "rarity": "rare",
        "description": "대기 주문 +1 · 행동 한도 +1(최대 6)",
    },
    "sign_famous": {
        "name": "명물 간판", "slot": "sign", "rarity": "epic",
        "description": "테마 만족 시 인테리어 코인 +1",
    },
    "counter_stock": {
        "name": "넓은 작업대", "slot": "counter", "rarity": "rare",
        "description": "재료 구매량 +20%",
    },
    "counter_master": {
        "name": "장인의 카운터", "slot": "counter", "rarity": "epic",
        "description": "수동 제작 5회마다 같은 완제품 +1",
    },
    "seating_cash": {
        "name": "회전 좌석", "slot": "seating", "rarity": "rare",
        "description": "납품 수입 +10%",
    },
    "seating_score": {
        "name": "단골석", "slot": "seating", "rarity": "rare",
        "description": "납품 점수 +10%",
    },
    "wall_research_cost": {
        "name": "연구 게시판", "slot": "wall", "rarity": "epic",
        "description": "연구 비용 -15%",
    },
    "wall_research_choice": {
        "name": "레시피 벽", "slot": "wall", "rarity": "legendary",
        "description": "같은 단계 레시피 후보 2개 중 선택",
    },
    "lighting_upgrade": {
        "name": "공방 조명", "slot": "lighting", "rarity": "epic",
        "description": "기계 강화 비용 -10%",
    },
    "lighting_manual_score": {
        "name": "집중 조명", "slot": "lighting", "rarity": "rare",
        "description": "수동 제작 점수 +25%",
    },
    "display_dessert": {
        "name": "추가 쇼케이스", "slot": "display_case", "rarity": "epic",
        "description": "자동 디저트 생산 +1",
    },
    "display_service": {
        "name": "서빙 종", "slot": "display_case", "rarity": "legendary",
        "description": "자동 서빙 횟수 +1",
    },
}
DECOR_MILESTONES = {25: 20, 50: 30, 75: 40, 100: 60}
IDLE_RELEASE_SECONDS = 30 * 60
_schema_lock = asyncio.Lock()
_schema_ready = False


def settlement_reward_candidates(settlement_id: int, user_id: int) -> tuple[str, ...]:
    """Return eight stable rare-material choices for one member's settlement."""
    count = min(8, len(RARE_REWARDS))
    picker = random.Random(f"cafe-settlement:{int(settlement_id)}:{int(user_id)}")
    return tuple(picker.sample(list(RARE_REWARDS), count))


def _loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _default_loadout() -> dict[str, dict[str, str | None]]:
    return {
        slot: {"appearance": None, "effect": None}
        for slot in DECOR_SLOTS
    }


def _season_shop(session_id: int, season_no: int, owned: dict[str, list[str]]) -> list[str]:
    appearances = list(DECOR_APPEARANCES)
    effects = list(DECOR_EFFECTS)
    picker = random.Random(f"cafe-decor-shop:{int(session_id)}:{int(season_no)}")
    unowned_appearances = [
        item for item in appearances if item not in set(owned.get("appearances", []))
    ]
    unowned_effects = [
        item for item in effects if item not in set(owned.get("effects", []))
    ]
    picker.shuffle(unowned_appearances)
    picker.shuffle(unowned_effects)
    picker.shuffle(appearances)
    picker.shuffle(effects)
    selected_appearances = unowned_appearances[:8]
    selected_effects = unowned_effects[:4]
    selected_appearances.extend(
        item for item in appearances
        if item not in selected_appearances
    )
    selected_effects.extend(
        item for item in effects
        if item not in selected_effects
    )
    return selected_appearances[:8] + selected_effects[:4]


def _default_state() -> dict[str, Any]:
    state = {
        "state_version": CAFE_STATE_VERSION,
        "ingredients": {
            "원두": 10, "우유": 8, "밀가루": 8, "채소": 8,
            "감자": 6, "설탕": 6, "생선": 4, "초콜릿": 2,
        },
        "products": {name: 0 for name in STARTER_TYCOON_RECIPES},
        "unlocked_recipes": list(STARTER_TYCOON_RECIPES),
        "machines": {
            "coffee": 1, "oven": 1, "display": 0,
            "service": 0, "lounge": 0,
        },
        "orders": [],
        "next_order_id": 1,
        "served": 0,
        "manual_products": 0,
        "manual_effect_counter": 0,
        "order_reroll_turn": 0,
        "vip_queue": 0,
        "milestones_claimed": [],
        "decor_collection": {"appearances": [], "effects": []},
        "decor_loadout": _default_loadout(),
        "pending_decor_loadout": None,
        "cycle_loadout": None,
        "season_shop": [],
        "log": ["작은 카페의 문을 열 준비를 마쳤습니다."],
    }
    _fill_orders(state, 3)
    return state


def _normalize_state(state: Any) -> dict[str, Any]:
    """Upgrade v9.2 café state in place without discarding an active run."""
    if not isinstance(state, dict):
        return _default_state()
    defaults = {
        "ingredients": {
            "원두": 0, "우유": 0, "밀가루": 0, "채소": 0,
            "감자": 0, "설탕": 0, "생선": 0, "초콜릿": 0,
        },
        "machines": {
            "coffee": 1, "oven": 1, "display": 0,
            "service": 0, "lounge": 0,
        },
    }
    for field, values in defaults.items():
        bucket = state.setdefault(field, {})
        if not isinstance(bucket, dict):
            bucket = {}
            state[field] = bucket
        for key, value in values.items():
            bucket.setdefault(key, value)

    unlocked = state.setdefault("unlocked_recipes", list(STARTER_TYCOON_RECIPES))
    if not isinstance(unlocked, list):
        unlocked = list(STARTER_TYCOON_RECIPES)
        state["unlocked_recipes"] = unlocked
    for name in STARTER_TYCOON_RECIPES:
        if name not in unlocked:
            unlocked.append(name)
    state["unlocked_recipes"] = [
        name for name in dict.fromkeys(unlocked) if name in RECIPE_CATALOG
    ]

    products = state.setdefault("products", {})
    if not isinstance(products, dict):
        products = {}
        state["products"] = products
    legacy_drinks = int(products.pop("drink", 0) or 0)
    legacy_foods = int(products.pop("food", 0) or 0)
    if legacy_drinks:
        products["아메리카노"] = int(products.get("아메리카노", 0)) + legacy_drinks
    if legacy_foods:
        products["샌드위치"] = int(products.get("샌드위치", 0)) + legacy_foods
    for name in state["unlocked_recipes"]:
        products.setdefault(name, 0)

    orders = state.setdefault("orders", [])
    if not isinstance(orders, list):
        orders = []
        state["orders"] = orders
    for order in orders:
        kind = order.get("kind", "drink")
        if kind not in PRODUCT_LABELS:
            kind = "drink"
            order["kind"] = kind
        order["quantity"] = max(1, int(order.get("quantity", 1)))
        order.setdefault(
            "preferred_theme",
            list(DECOR_THEMES)[int(order.get("id", 0)) % len(DECOR_THEMES)],
        )
        order.setdefault("vip", False)
        # v9.3 초기안의 메뉴 지정 주문도 카테고리 주문으로 안전하게 변환한다.
        order.pop("recipe", None)
        order.pop("cash", None)
        order.pop("score", None)
    state.setdefault("next_order_id", 1)
    state.setdefault("served", 0)
    state.setdefault("manual_products", 0)
    state.setdefault("manual_effect_counter", 0)
    state.setdefault("order_reroll_turn", 0)
    state.setdefault("vip_queue", 0)
    state.setdefault("milestones_claimed", [])
    collection = state.setdefault("decor_collection", {"appearances": [], "effects": []})
    if not isinstance(collection, dict):
        collection = {"appearances": [], "effects": []}
        state["decor_collection"] = collection
    collection["appearances"] = [
        item for item in dict.fromkeys(collection.get("appearances", []))
        if item in DECOR_APPEARANCES
    ]
    collection["effects"] = [
        item for item in dict.fromkeys(collection.get("effects", []))
        if item in DECOR_EFFECTS
    ]
    for field in ("decor_loadout",):
        loadout = state.setdefault(field, _default_loadout())
        if not isinstance(loadout, dict):
            loadout = _default_loadout()
            state[field] = loadout
        for slot in DECOR_SLOTS:
            entry = loadout.setdefault(slot, {"appearance": None, "effect": None})
            if not isinstance(entry, dict):
                entry = {"appearance": None, "effect": None}
                loadout[slot] = entry
            appearance = entry.get("appearance")
            effect = entry.get("effect")
            if (
                appearance not in collection["appearances"]
                or DECOR_APPEARANCES.get(appearance, {}).get("slot") != slot
            ):
                entry["appearance"] = None
            if (
                effect not in collection["effects"]
                or DECOR_EFFECTS.get(effect, {}).get("slot") != slot
            ):
                entry["effect"] = None
    pending = state.get("pending_decor_loadout")
    if pending is not None and not isinstance(pending, dict):
        state["pending_decor_loadout"] = None
    cycle = state.get("cycle_loadout")
    if cycle is not None and not isinstance(cycle, dict):
        state["cycle_loadout"] = None
    state.setdefault("season_shop", [])
    state["state_version"] = CAFE_STATE_VERSION
    state.setdefault("log", [])
    return state


def _active_loadout(state: dict[str, Any]) -> dict[str, dict[str, str | None]]:
    return state.get("cycle_loadout") or state.get("decor_loadout") or _default_loadout()


def _has_effect(state: dict[str, Any], effect_key: str) -> bool:
    return any(
        entry.get("effect") == effect_key
        for entry in _active_loadout(state).values()
        if isinstance(entry, dict)
    )


def _theme_count(state: dict[str, Any], theme: str) -> int:
    count = 0
    for entry in _active_loadout(state).values():
        appearance = entry.get("appearance") if isinstance(entry, dict) else None
        if DECOR_APPEARANCES.get(appearance, {}).get("theme") == theme:
            count += 1
    return count


def _stock_bundle(state: dict[str, Any]) -> dict[str, int]:
    bundle = {
        "원두": 6, "우유": 4, "밀가루": 5, "채소": 5,
        "감자": 4, "설탕": 4, "생선": 3, "초콜릿": 2,
    }
    if _has_effect(state, "counter_stock"):
        return {name: int(count * 1.20) for name, count in bundle.items()}
    return bundle


def _research_price(state: dict[str, Any], tier: int) -> int:
    cost = int(RESEARCH_COST[int(tier)])
    return int(cost * 0.85) if _has_effect(state, "wall_research_cost") else cost


def _upgrade_price(state: dict[str, Any], current_level: int) -> int:
    cost = 20_000 * (int(current_level) + 1) ** 2
    return int(cost * 0.90) if _has_effect(state, "lighting_upgrade") else cost


def _manual_score(state: dict[str, Any], recipe: dict[str, Any]) -> int:
    score = max(4, int(recipe["score"]) // 2)
    return int(score * 1.25) if _has_effect(state, "lighting_manual_score") else score


def _action_cap(state: dict[str, Any]) -> int:
    base = 2 + max(0, min(3, int(state["machines"].get("lounge", 0))))
    return min(6, base + (1 if _has_effect(state, "sign_order_board") else 0))


def _add_log(state: dict[str, Any], message: str) -> None:
    log = state.setdefault("log", [])
    log.append(message)
    del log[:-8]


def _new_order(state: dict[str, Any], *, vip: bool = False) -> dict[str, Any]:
    _normalize_state(state)
    available_kinds = [
        kind for kind in PRODUCT_LABELS
        if any(
            RECIPE_CATALOG.get(name, {}).get("kind") == kind
            for name in state["unlocked_recipes"]
        )
    ]
    kind = random.choice(available_kinds or list(PRODUCT_LABELS))
    quantity = random.randint(1, 3)
    order = {
        "id": int(state.get("next_order_id", 1)),
        "kind": kind,
        "quantity": 3 if vip else quantity,
        "preferred_theme": random.choice(list(DECOR_THEMES)),
        "vip": bool(vip),
    }
    state["next_order_id"] = order["id"] + 1
    return order


def _fill_orders(state: dict[str, Any], target: int = 4) -> None:
    orders = state.setdefault("orders", [])
    if int(state.get("vip_queue", 0)) > 0 and not any(order.get("vip") for order in orders):
        orders.append(_new_order(state, vip=True))
        state["vip_queue"] = max(0, int(state.get("vip_queue", 0)) - 1)
    while len(orders) < target:
        orders.append(_new_order(state))


def _make_recipe(state: dict[str, Any], recipe_name: str, amount: int = 1) -> int:
    _normalize_state(state)
    recipe = RECIPE_CATALOG.get(recipe_name)
    if not recipe or recipe_name not in state["unlocked_recipes"]:
        return 0
    made = 0
    for _ in range(max(0, int(amount))):
        required = recipe["ingredients"]
        if any(int(state["ingredients"].get(name, 0)) < count for name, count in required.items()):
            break
        for name, count in required.items():
            state["ingredients"][name] -= count
        state["products"][recipe_name] = int(state["products"].get(recipe_name, 0)) + 1
        made += 1
    return made


def _first_recipe(state: dict[str, Any], kind: str) -> str | None:
    return next(
        (
            name for name in state.get("unlocked_recipes", [])
            if RECIPE_CATALOG.get(name, {}).get("kind") == kind
        ),
        None,
    )


def _make_product(state: dict[str, Any], kind: str, amount: int = 1) -> int:
    """Compatibility helper for automatic machines and old callers."""
    recipe_name = _first_recipe(state, kind)
    return _make_recipe(state, recipe_name, amount) if recipe_name else 0


def _serve_order(
    state: dict[str, Any],
    order_id: int,
    recipe_name: str | None = None,
    recipe_allocations: dict[str, int] | None = None,
) -> tuple[bool, int, int, int, int, str]:
    order = next(
        (item for item in state.get("orders", []) if int(item["id"]) == int(order_id)),
        None,
    )
    if not order:
        return False, 0, 0, 0, 0, "주문을 찾지 못했습니다."
    kind = order["kind"]
    quantity = int(order["quantity"])
    compatible = [
        name for name in state.get("unlocked_recipes", [])
        if RECIPE_CATALOG.get(name, {}).get("kind") == kind
    ]
    allocations = {
        name: max(0, int(count))
        for name, count in (recipe_allocations or {}).items()
        if int(count) > 0
    }
    if not allocations and recipe_name:
        allocations = {recipe_name: quantity}
    if not allocations:
        # 자동 서빙은 싼 메뉴부터 조합해 고급 메뉴 재고를 가능한 한 보존한다.
        remaining = quantity
        for name in sorted(
            compatible, key=lambda item: int(RECIPE_CATALOG[item]["price"])
        ):
            used = min(remaining, int(state["products"].get(name, 0)))
            if used > 0:
                allocations[name] = used
                remaining -= used
            if remaining <= 0:
                break
    if not allocations or any(name not in compatible for name in allocations):
        return False, 0, 0, 0, 0, f"{PRODUCT_LABELS[kind]} 카테고리의 메뉴만 납품할 수 있습니다."
    supplied = sum(allocations.values())
    if supplied != quantity:
        return False, 0, 0, 0, 0, f"주문 수량을 정확히 채워주세요. ({supplied}/{quantity})"
    for name, count in allocations.items():
        have = int(state["products"].get(name, 0))
        if have < count:
            return False, 0, 0, 0, 0, f"{name} 재고가 부족합니다. ({have}/{count})"

    earned_cash = 0
    earned_score = 0
    supplied_lines = []
    for name, count in allocations.items():
        state["products"][name] -= count
        recipe = RECIPE_CATALOG[name]
        earned_cash += int(recipe["price"]) * count
        earned_score += int(recipe["score"]) * count
        supplied_lines.append(f"{name} ×{count}")
    average_tier = sum(
        int(RECIPE_CATALOG[name]["tier"]) * count
        for name, count in allocations.items()
    ) // max(1, quantity)
    theme_count = _theme_count(state, str(order.get("preferred_theme", "")))
    theme_bonus = 0.20 if theme_count >= 6 else 0.10 if theme_count >= 3 else 0.0
    if _has_effect(state, "seating_cash"):
        earned_cash = int(earned_cash * 1.10)
    if _has_effect(state, "seating_score"):
        earned_score = int(earned_score * 1.10)
    if theme_bonus:
        earned_cash = int(earned_cash * (1 + theme_bonus))
        earned_score = int(earned_score * (1 + theme_bonus))
    reputation = 1 + (2 if theme_count >= 6 else 1 if theme_count >= 3 else 0)
    decor_tokens = 3 + quantity + average_tier
    if theme_count >= 6:
        decor_tokens += 2
    elif theme_count >= 3:
        decor_tokens += 1
    if theme_count >= 3 and _has_effect(state, "sign_famous"):
        decor_tokens += 1
    if order.get("vip"):
        decor_tokens += 15
    state["orders"].remove(order)
    state["served"] = int(state.get("served", 0)) + 1
    return (
        True,
        earned_cash,
        earned_score,
        reputation,
        decor_tokens,
        (
            f"{PRODUCT_LABELS[kind]} 주문에 {', '.join(supplied_lines)}을(를) 납품해 "
            f"{earned_cash:,}원, {earned_score}점, 명성 {reputation}, "
            f"인테리어 코인 {decor_tokens}개를 얻었습니다."
        ),
    )


def _resolve_automatic_turn(state: dict[str, Any]) -> tuple[int, int, int, int, list[str]]:
    machines = state["machines"]
    score = 0
    cash = 0
    reputation = 0
    decor_tokens = 0
    notes = []
    drinks = _make_product(state, "drink", max(0, int(machines["coffee"]) - 1))
    foods = _make_product(state, "food", max(0, int(machines["oven"]) - 1))
    dessert_amount = max(0, int(machines["display"]))
    if _has_effect(state, "display_dessert"):
        dessert_amount += 1
    desserts = _make_product(state, "dessert", dessert_amount)
    if drinks:
        score += drinks * 3
        notes.append(f"커피 머신이 음료 {drinks}개 자동 제작")
    if foods:
        score += foods * 4
        notes.append(f"오븐이 음식 {foods}개 자동 제작")
    if desserts:
        score += desserts * 4
        notes.append(f"디저트 쇼케이스가 디저트 {desserts}개 자동 제작")

    served = 0
    service_count = max(0, int(machines["service"]))
    if _has_effect(state, "display_service"):
        service_count += 1
    for _ in range(service_count):
        order = next(
            (
                item
                for item in state.get("orders", [])
                if sum(
                    int(state["products"].get(name, 0))
                    for name in state.get("unlocked_recipes", [])
                    if RECIPE_CATALOG.get(name, {}).get("kind") == item["kind"]
                ) >= int(item["quantity"])
            ),
            None,
        )
        if not order:
            break
        ok, earned_cash, earned_score, earned_rep, earned_tokens, _ = _serve_order(
            state, int(order["id"])
        )
        if ok:
            served += 1
            cash += earned_cash
            score += earned_score
            reputation += earned_rep
            decor_tokens += earned_tokens
    if served:
        notes.append(f"자동 서빙 벨이 주문 {served}건 처리")
    order_target = 5 if _has_effect(state, "sign_order_board") else 4
    _fill_orders(state, order_target)
    return cash, score, reputation, decor_tokens, notes


async def ensure_tycoon_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    """SELECT table_name AS name FROM information_schema.tables
                       WHERE table_schema=DATABASE()
                         AND table_name IN (
                           'cafe_tycoon_sessions','cafe_tycoon_members',
                           'cafe_tycoon_seasons','cafe_tycoon_season_rewards'
                         )"""
                )
                existing = {row["name"] for row in await cur.fetchall()}
                if "cafe_tycoon_sessions" not in existing:
                    await cur.execute(
                        """CREATE TABLE cafe_tycoon_sessions (
                            id BIGINT AUTO_INCREMENT PRIMARY KEY,
                            host_id BIGINT NOT NULL,
                            host_name VARCHAR(100) NOT NULL,
                            status VARCHAR(20) NOT NULL DEFAULT 'lobby',
                            turn_no INT NOT NULL DEFAULT 0,
                            score BIGINT NOT NULL DEFAULT 0,
                            cafe_cash BIGINT NOT NULL DEFAULT 30000,
                            season_no INT NOT NULL DEFAULT 1,
                            reputation INT NOT NULL DEFAULT 0,
                            decor_tokens INT NOT NULL DEFAULT 0,
                            state_json JSON NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
                            INDEX idx_tycoon_status (status)
                        )"""
                    )
                if "cafe_tycoon_members" not in existing:
                    await cur.execute(
                        """CREATE TABLE cafe_tycoon_members (
                            session_id BIGINT NOT NULL,
                            user_id BIGINT NOT NULL,
                            user_name VARCHAR(100) NOT NULL,
                            actions_left INT NOT NULL DEFAULT 2,
                            ready TINYINT(1) NOT NULL DEFAULT 0,
                            participating TINYINT(1) NOT NULL DEFAULT 0,
                            last_action_at DATETIME NULL,
                            end_vote TINYINT(1) NOT NULL DEFAULT 0,
                            reward_choices JSON NULL,
                            reward_claimed TINYINT(1) NOT NULL DEFAULT 0,
                            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (session_id,user_id),
                            INDEX idx_tycoon_member_user (user_id),
                            FOREIGN KEY (session_id) REFERENCES cafe_tycoon_sessions(id)
                                ON DELETE CASCADE
                        )"""
                    )
                if "cafe_tycoon_sessions" in existing:
                    await cur.execute(
                        """SELECT column_name AS name FROM information_schema.columns
                           WHERE table_schema=DATABASE()
                             AND table_name='cafe_tycoon_sessions'"""
                    )
                    columns = {row["name"] for row in await cur.fetchall()}
                    for name, definition in (
                        ("season_no", "INT NOT NULL DEFAULT 1"),
                        ("reputation", "INT NOT NULL DEFAULT 0"),
                        ("decor_tokens", "INT NOT NULL DEFAULT 0"),
                    ):
                        if name not in columns:
                            await cur.execute(
                                f"ALTER TABLE cafe_tycoon_sessions ADD COLUMN {name} {definition}"
                            )
                if "cafe_tycoon_members" in existing:
                    await cur.execute(
                        """SELECT column_name AS name FROM information_schema.columns
                           WHERE table_schema=DATABASE()
                             AND table_name='cafe_tycoon_members'"""
                    )
                    columns = {row["name"] for row in await cur.fetchall()}
                    if "participating" not in columns:
                        await cur.execute(
                            """ALTER TABLE cafe_tycoon_members
                               ADD COLUMN participating TINYINT(1) NOT NULL DEFAULT 0"""
                        )
                    if "last_action_at" not in columns:
                        await cur.execute(
                            """ALTER TABLE cafe_tycoon_members
                               ADD COLUMN last_action_at DATETIME NULL"""
                        )
                if "cafe_tycoon_seasons" not in existing:
                    await cur.execute(
                        """CREATE TABLE cafe_tycoon_seasons (
                            id BIGINT AUTO_INCREMENT PRIMARY KEY,
                            session_id BIGINT NOT NULL,
                            season_no INT NOT NULL,
                            score BIGINT NOT NULL,
                            reputation INT NOT NULL,
                            reward_money BIGINT NOT NULL,
                            reward_points BIGINT NOT NULL,
                            reward_rare_total INT NOT NULL,
                            settled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE KEY uq_tycoon_season (session_id,season_no),
                            INDEX idx_tycoon_season_session (session_id,id),
                            FOREIGN KEY (session_id) REFERENCES cafe_tycoon_sessions(id)
                                ON DELETE CASCADE
                        )"""
                    )
                if "cafe_tycoon_season_rewards" not in existing:
                    await cur.execute(
                        """CREATE TABLE cafe_tycoon_season_rewards (
                            season_id BIGINT NOT NULL,
                            user_id BIGINT NOT NULL,
                            reward_choices JSON NULL,
                            claimed TINYINT(1) NOT NULL DEFAULT 0,
                            claimed_at DATETIME NULL,
                            PRIMARY KEY (season_id,user_id),
                            INDEX idx_tycoon_reward_user (user_id,claimed),
                            FOREIGN KEY (season_id) REFERENCES cafe_tycoon_seasons(id)
                                ON DELETE CASCADE
                        )"""
                    )
                await conn.commit()
        _schema_ready = True


async def get_session(session_id: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    await ensure_tycoon_schema()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT * FROM cafe_tycoon_sessions WHERE id=%s",
                (int(session_id),),
            )
            session = await cur.fetchone()
            if not session:
                return None, []
            session["state"] = _normalize_state(
                _loads(session.pop("state_json"), _default_state())
            )
            await cur.execute(
                """SELECT * FROM cafe_tycoon_members
                   WHERE session_id=%s ORDER BY joined_at,user_id""",
                (int(session_id),),
            )
            return session, list(await cur.fetchall())


async def get_user_active_session(user_id: int) -> dict[str, Any] | None:
    await ensure_tycoon_schema()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT s.* FROM cafe_tycoon_sessions s
                   JOIN cafe_tycoon_members m ON m.session_id=s.id
                   WHERE m.user_id=%s AND s.status IN ('lobby','running','settling')
                   ORDER BY s.id DESC LIMIT 1""",
                (int(user_id),),
            )
            return await cur.fetchone()


async def list_lobbies() -> list[dict[str, Any]]:
    await ensure_tycoon_schema()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT s.*,COUNT(m.user_id) AS member_count
                   FROM cafe_tycoon_sessions s
                   LEFT JOIN cafe_tycoon_members m ON m.session_id=s.id
                   WHERE s.status='lobby'
                   GROUP BY s.id ORDER BY s.id DESC"""
            )
            return list(await cur.fetchall())


async def create_session(user) -> tuple[bool, str, int | None]:
    await ensure_tycoon_schema()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    """SELECT s.id FROM cafe_tycoon_sessions s
                       JOIN cafe_tycoon_members m ON m.session_id=s.id
                       WHERE m.user_id=%s AND s.status IN ('lobby','running','settling')
                       FOR UPDATE""",
                    (int(user.id),),
                )
                if await cur.fetchone():
                    await conn.rollback()
                    return False, "이미 참여 중인 카페 타이쿤이 있습니다.", None
                state = _default_state()
                await cur.execute(
                    """INSERT INTO cafe_tycoon_sessions
                       (host_id,host_name,status,turn_no,score,cafe_cash,state_json)
                       VALUES (%s,%s,'lobby',0,0,30000,%s)""",
                    (
                        int(user.id),
                        user.display_name,
                        json.dumps(state, ensure_ascii=False),
                    ),
                )
                session_id = int(cur.lastrowid)
                state["season_shop"] = _season_shop(
                    session_id, 1, state["decor_collection"]
                )
                await cur.execute(
                    "UPDATE cafe_tycoon_sessions SET state_json=%s WHERE id=%s",
                    (json.dumps(state, ensure_ascii=False), session_id),
                )
                await cur.execute(
                    """INSERT INTO cafe_tycoon_members
                       (session_id,user_id,user_name,actions_left)
                       VALUES (%s,%s,%s,2)""",
                    (session_id, int(user.id), user.display_name),
                )
                await conn.commit()
                return True, "카페 타이쿤 대기실을 만들었습니다.", session_id
            except Exception as exc:
                await conn.rollback()
                return False, f"카페 생성 오류: {exc}", None


async def join_session(user, session_id: int) -> tuple[bool, str]:
    await ensure_tycoon_schema()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    "SELECT status FROM cafe_tycoon_sessions WHERE id=%s FOR UPDATE",
                    (int(session_id),),
                )
                session = await cur.fetchone()
                if not session or session["status"] != "lobby":
                    await conn.rollback()
                    return False, "참가할 수 없는 대기실입니다."
                await cur.execute(
                    """SELECT s.id FROM cafe_tycoon_sessions s
                       JOIN cafe_tycoon_members m ON m.session_id=s.id
                       WHERE m.user_id=%s AND s.status IN ('lobby','running','settling')
                       FOR UPDATE""",
                    (int(user.id),),
                )
                active = await cur.fetchone()
                if active:
                    if int(active["id"]) == int(session_id):
                        await conn.rollback()
                        return True, "이미 이 카페에 참가 중입니다."
                    await conn.rollback()
                    return False, "이미 다른 카페 타이쿤에 참가 중입니다."
                await cur.execute(
                    """SELECT user_id FROM cafe_tycoon_members
                       WHERE session_id=%s ORDER BY user_id FOR UPDATE""",
                    (int(session_id),),
                )
                count = len(await cur.fetchall())
                if count >= MAX_PLAYERS:
                    await conn.rollback()
                    return False, "대기실이 가득 찼습니다."
                await cur.execute(
                    """INSERT INTO cafe_tycoon_members
                       (session_id,user_id,user_name,actions_left)
                       VALUES (%s,%s,%s,2)""",
                    (int(session_id), int(user.id), user.display_name),
                )
                await conn.commit()
                return True, "카페 타이쿤에 참가했습니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"참가 오류: {exc}"


async def leave_lobby(user_id: int, session_id: int) -> tuple[bool, str]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    "SELECT * FROM cafe_tycoon_sessions WHERE id=%s FOR UPDATE",
                    (int(session_id),),
                )
                session = await cur.fetchone()
                if not session or session["status"] != "lobby":
                    await conn.rollback()
                    return False, "진행 중인 카페에서는 나갈 수 없습니다."
                await cur.execute(
                    """DELETE FROM cafe_tycoon_members
                       WHERE session_id=%s AND user_id=%s""",
                    (int(session_id), int(user_id)),
                )
                if cur.rowcount <= 0:
                    await conn.rollback()
                    return False, "참가 정보를 찾지 못했습니다."
                await cur.execute(
                    """SELECT user_id,user_name FROM cafe_tycoon_members
                       WHERE session_id=%s ORDER BY joined_at,user_id LIMIT 1""",
                    (int(session_id),),
                )
                next_host = await cur.fetchone()
                if not next_host:
                    await cur.execute(
                        "DELETE FROM cafe_tycoon_sessions WHERE id=%s",
                        (int(session_id),),
                    )
                elif int(session["host_id"]) == int(user_id):
                    await cur.execute(
                        """UPDATE cafe_tycoon_sessions
                           SET host_id=%s,host_name=%s WHERE id=%s""",
                        (next_host["user_id"], next_host["user_name"], int(session_id)),
                    )
                await conn.commit()
                return True, "카페 타이쿤 대기실에서 나왔습니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"나가기 오류: {exc}"


async def start_session(user_id: int, session_id: int) -> tuple[bool, str]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    "SELECT * FROM cafe_tycoon_sessions WHERE id=%s FOR UPDATE",
                    (int(session_id),),
                )
                session = await cur.fetchone()
                if not session or session["status"] != "lobby":
                    await conn.rollback()
                    return False, "시작할 수 없는 상태입니다."
                if int(session["host_id"]) != int(user_id):
                    await conn.rollback()
                    return False, "방장만 영업을 시작할 수 있습니다."
                await cur.execute(
                    """SELECT user_id FROM cafe_tycoon_members
                       WHERE session_id=%s ORDER BY user_id FOR UPDATE""",
                    (int(session_id),),
                )
                count = len(await cur.fetchall())
                if count < MIN_PLAYERS:
                    await conn.rollback()
                    return False, "카페 타이쿤은 최소 2명이 필요합니다."
                state = _normalize_state(_loads(session["state_json"], _default_state()))
                if not state.get("season_shop"):
                    state["season_shop"] = _season_shop(
                        int(session_id), int(session.get("season_no", 1)),
                        state["decor_collection"],
                    )
                cap = _action_cap(state)
                await cur.execute(
                    """UPDATE cafe_tycoon_sessions
                       SET status='running',turn_no=1,state_json=%s WHERE id=%s""",
                    (json.dumps(state, ensure_ascii=False), int(session_id)),
                )
                await cur.execute(
                    """UPDATE cafe_tycoon_members
                       SET actions_left=%s,ready=0,participating=0,
                           last_action_at=NULL,end_vote=0
                       WHERE session_id=%s""",
                    (cap, int(session_id)),
                )
                await conn.commit()
                return True, "카페 영업을 시작했습니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"시작 오류: {exc}"


async def _lock_running(cur, user_id: int, session_id: int):
    await cur.execute(
        "SELECT * FROM cafe_tycoon_sessions WHERE id=%s FOR UPDATE",
        (int(session_id),),
    )
    session = await cur.fetchone()
    if not session or session["status"] != "running":
        return None, None, None
    await cur.execute(
        """SELECT * FROM cafe_tycoon_members
           WHERE session_id=%s AND user_id=%s FOR UPDATE""",
        (int(session_id), int(user_id)),
    )
    member = await cur.fetchone()
    if not member:
        return session, None, None
    return session, member, _normalize_state(
        _loads(session["state_json"], _default_state())
    )


def _apply_reputation_progress(
    state: dict[str, Any], old_reputation: int, new_reputation: int
) -> int:
    """Queue VIPs and return one-time milestone decor-token rewards."""
    old_reputation = max(0, int(old_reputation))
    new_reputation = max(old_reputation, int(new_reputation))
    crossed_vips = new_reputation // 25 - old_reputation // 25
    if crossed_vips > 0:
        state["vip_queue"] = int(state.get("vip_queue", 0)) + crossed_vips
    claimed = {int(value) for value in state.get("milestones_claimed", [])}
    reward = 0
    for threshold, amount in DECOR_MILESTONES.items():
        if old_reputation < threshold <= new_reputation and threshold not in claimed:
            claimed.add(threshold)
            reward += amount
            _add_log(state, f"🌟 명성 {threshold} 달성 · 인테리어 코인 {amount}개")
    state["milestones_claimed"] = sorted(claimed)
    return reward


def _participating_members_ready(members: list[dict[str, Any]]) -> bool:
    participants = [row for row in members if int(row.get("participating", 0))]
    return bool(participants) and all(int(row.get("ready", 0)) for row in participants)


async def _save_or_advance_cycle(
    cur,
    session: dict[str, Any],
    state: dict[str, Any],
    *,
    cafe_cash: int,
    score_delta: int = 0,
    reputation_delta: int = 0,
    decor_tokens_delta: int = 0,
) -> tuple[bool, int]:
    session_id = int(session["id"])
    old_reputation = int(session.get("reputation", 0))
    reputation = old_reputation + int(reputation_delta)
    decor_tokens_delta += _apply_reputation_progress(
        state, old_reputation, reputation
    )
    order_target = 5 if _has_effect(state, "sign_order_board") else 4
    _fill_orders(state, order_target)
    await cur.execute(
        """SELECT user_id,ready,participating FROM cafe_tycoon_members
           WHERE session_id=%s ORDER BY user_id FOR UPDATE""",
        (session_id,),
    )
    members = list(await cur.fetchall())
    advanced = _participating_members_ready(members)
    if not advanced:
        await cur.execute(
            """UPDATE cafe_tycoon_sessions
               SET state_json=%s,cafe_cash=%s,score=score+%s,
                   reputation=reputation+%s,decor_tokens=decor_tokens+%s
               WHERE id=%s""",
            (
                json.dumps(state, ensure_ascii=False),
                int(cafe_cash),
                int(score_delta),
                int(reputation_delta),
                int(decor_tokens_delta),
                session_id,
            ),
        )
        return False, int(session["turn_no"])

    auto_cash, auto_score, auto_rep, auto_tokens, notes = _resolve_automatic_turn(state)
    for note in notes:
        _add_log(state, f"⚙️ {note}")
    auto_tokens += _apply_reputation_progress(
        state, reputation, reputation + auto_rep
    )
    _fill_orders(state, 5 if _has_effect(state, "sign_order_board") else 4)
    pending = state.get("pending_decor_loadout")
    if isinstance(pending, dict):
        state["decor_loadout"] = pending
        state["pending_decor_loadout"] = None
        _add_log(state, "🪑 예약된 인테리어 배치를 적용했습니다.")
    state["cycle_loadout"] = None
    next_turn = int(session["turn_no"]) + 1
    cap = _action_cap(state)
    await cur.execute(
        """UPDATE cafe_tycoon_sessions
           SET turn_no=%s,cafe_cash=%s,score=score+%s,
               reputation=reputation+%s,decor_tokens=decor_tokens+%s,
               state_json=%s
           WHERE id=%s""",
        (
            next_turn,
            int(cafe_cash) + auto_cash,
            int(score_delta) + auto_score,
            int(reputation_delta) + auto_rep,
            int(decor_tokens_delta) + auto_tokens,
            json.dumps(state, ensure_ascii=False),
            session_id,
        ),
    )
    await cur.execute(
        """UPDATE cafe_tycoon_members
           SET actions_left=%s,ready=0,participating=0,last_action_at=NULL
           WHERE session_id=%s""",
        (cap, session_id),
    )
    for row in members:
        await cur.execute(
            """UPDATE users
               SET total_turns=total_turns+1,data_revision=data_revision+1
               WHERE user_id=%s""",
            (str(row["user_id"]),),
        )
    return True, next_turn


async def perform_action(
    user,
    session_id: int,
    action: str,
    *,
    order_id: int | None = None,
    machine: str | None = None,
    recipe_name: str | None = None,
    recipe_allocations: dict[str, int] | None = None,
    category: str | None = None,
) -> tuple[bool, str, bool]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                session, member, state = await _lock_running(cur, user.id, session_id)
                if not session or not member or state is None:
                    await conn.rollback()
                    return False, "진행 중인 카페 참가 정보를 찾지 못했습니다.", False
                if int(member["ready"]) or int(member["actions_left"]) <= 0:
                    await conn.rollback()
                    return False, "이번 사이클의 행동을 이미 마쳤습니다.", False

                if state.get("cycle_loadout") is None:
                    state["cycle_loadout"] = json.loads(
                        json.dumps(state.get("decor_loadout") or _default_loadout())
                    )
                cafe_cash = int(session["cafe_cash"])
                score_delta = 0
                cash_delta = 0
                reputation_delta = 0
                decor_tokens_delta = 0
                message = ""
                if action == "stock":
                    cost = 5_000
                    if cafe_cash < cost:
                        await conn.rollback()
                        return False, "카페 운영 자금 5,000원이 필요합니다.", False
                    cafe_cash -= cost
                    stock_bonus = _has_effect(state, "counter_stock")
                    for name, count in _stock_bundle(state).items():
                        state["ingredients"][name] = int(state["ingredients"].get(name, 0)) + count
                    score_delta = 2
                    message = "재료 묶음을 구매했습니다." + (
                        " (넓은 작업대 +20%)" if stock_bonus else ""
                    )
                elif action == "make":
                    recipe = RECIPE_CATALOG.get(recipe_name or "")
                    if not recipe or recipe_name not in state["unlocked_recipes"]:
                        await conn.rollback()
                        return False, "아직 연구하지 않은 메뉴입니다.", False
                    made = _make_recipe(state, recipe_name, 1)
                    if not made:
                        await conn.rollback()
                        needs = " · ".join(
                            f"{name} {count}" for name, count in recipe["ingredients"].items()
                        )
                        return False, f"재료가 부족합니다. 필요: {needs}", False
                    score_delta = _manual_score(state, recipe)
                    state["manual_products"] = int(state.get("manual_products", 0)) + 1
                    bonus_product = False
                    if _has_effect(state, "counter_master"):
                        counter = int(state.get("manual_effect_counter", 0)) + 1
                        if counter >= 5:
                            counter = 0
                            state["products"][recipe_name] = (
                                int(state["products"].get(recipe_name, 0)) + 1
                            )
                            bonus_product = True
                        state["manual_effect_counter"] = counter
                    message = (
                        f"{PRODUCT_LABELS[recipe['kind']]} · {recipe_name} 1개를 "
                        "직접 만들었습니다."
                        + (" 장인의 카운터로 1개를 더 만들었습니다." if bonus_product else "")
                    )
                elif action == "serve":
                    if order_id is None:
                        await conn.rollback()
                        return False, "처리할 주문을 선택하세요.", False
                    (
                        ok, cash_delta, score_delta, reputation_delta,
                        decor_tokens_delta, message,
                    ) = _serve_order(
                        state, order_id, recipe_name, recipe_allocations
                    )
                    if not ok:
                        await conn.rollback()
                        return False, message, False
                    cafe_cash += cash_delta
                elif action == "research":
                    if category not in PRODUCT_LABELS:
                        await conn.rollback()
                        return False, "연구할 메뉴 분류를 선택하세요.", False
                    locked = [
                        (name, recipe) for name, recipe in RECIPE_CATALOG.items()
                        if recipe["kind"] == category
                        and name not in state["unlocked_recipes"]
                    ]
                    if not locked:
                        await conn.rollback()
                        return False, f"{PRODUCT_LABELS[category]} 레시피를 모두 연구했습니다.", False
                    next_tier = min(int(recipe["tier"]) for _, recipe in locked)
                    candidates = [
                        name for name, recipe in locked if int(recipe["tier"]) == next_tier
                    ]
                    cost = _research_price(state, next_tier)
                    if cafe_cash < cost:
                        await conn.rollback()
                        return False, f"연구 자금 {cost:,}원이 필요합니다.", False
                    cafe_cash -= cost
                    if (
                        recipe_name in candidates
                        and _has_effect(state, "wall_research_choice")
                    ):
                        chosen_recipe = recipe_name
                    else:
                        chosen_recipe = random.choice(candidates)
                    recipe_name = chosen_recipe
                    state["unlocked_recipes"].append(recipe_name)
                    state["products"].setdefault(recipe_name, 0)
                    score_delta = 20 * next_tier
                    message = (
                        f"{PRODUCT_LABELS[category]} 연구에 성공해 "
                        f"**{recipe_name}** 레시피를 발견했습니다."
                    )
                elif action == "upgrade":
                    if machine not in MACHINE_LABELS:
                        await conn.rollback()
                        return False, "강화할 기기를 선택하세요.", False
                    current = int(state["machines"].get(machine, 0))
                    if current >= MACHINE_MAX[machine]:
                        await conn.rollback()
                        return False, "이미 최대 강화입니다.", False
                    cost = _upgrade_price(state, current)
                    if cafe_cash < cost:
                        await conn.rollback()
                        return False, f"카페 운영 자금 {cost:,}원이 필요합니다.", False
                    cafe_cash -= cost
                    state["machines"][machine] = current + 1
                    score_delta = 15 * (current + 1)
                    message = f"{MACHINE_LABELS[machine]}을(를) {current + 1}단계로 강화했습니다."
                else:
                    await conn.rollback()
                    return False, "알 수 없는 행동입니다.", False

                _add_log(state, f"{user.display_name}: {message}")
                actions_left = int(member["actions_left"]) - 1
                ready = 1 if actions_left <= 0 else 0
                await cur.execute(
                    """UPDATE cafe_tycoon_members
                       SET actions_left=%s,ready=%s,participating=1,
                           last_action_at=UTC_TIMESTAMP()
                       WHERE session_id=%s AND user_id=%s""",
                    (max(0, actions_left), ready, int(session_id), int(user.id)),
                )
                turn_advanced, next_turn = await _save_or_advance_cycle(
                    cur,
                    session,
                    state,
                    cafe_cash=cafe_cash,
                    score_delta=score_delta,
                    reputation_delta=reputation_delta,
                    decor_tokens_delta=decor_tokens_delta,
                )
                if turn_advanced:
                    message += (
                        f"\n참여자의 행동이 끝나 **{next_turn}사이클**로 넘어갔습니다. "
                        "카페 멤버 전원의 공용 활동 턴이 1 증가했습니다."
                    )
                await conn.commit()
                return True, message, turn_advanced
            except Exception as exc:
                await conn.rollback()
                return False, f"타이쿤 행동 오류: {exc}", False


async def finish_turn_early(user_id: int, session_id: int) -> tuple[bool, str, bool]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                session, member, state = await _lock_running(cur, user_id, session_id)
                if not session or not member or state is None:
                    await conn.rollback()
                    return False, "진행 중인 카페 참가 정보를 찾지 못했습니다.", False
                if int(member["ready"]):
                    await conn.rollback()
                    return False, "이미 영업 완료를 선언했습니다.", False
                if not int(member.get("participating", 0)):
                    await conn.rollback()
                    return False, "이번 사이클에 한 번 이상 행동한 뒤 마칠 수 있습니다.", False
                await cur.execute(
                    """UPDATE cafe_tycoon_members SET actions_left=0,ready=1,
                           last_action_at=UTC_TIMESTAMP()
                       WHERE session_id=%s AND user_id=%s""",
                    (int(session_id), int(user_id)),
                )
                advanced, next_turn = await _save_or_advance_cycle(
                    cur, session, state, cafe_cash=int(session["cafe_cash"])
                )
                if advanced:
                    await conn.commit()
                    return (
                        True,
                        f"영업을 마쳤습니다. 참여자가 모두 준비되어 **{next_turn}사이클**로 넘어갑니다.",
                        True,
                    )
                await conn.commit()
                return True, "남은 행동을 포기하고 다른 참여자를 기다립니다.", False
            except Exception as exc:
                await conn.rollback()
                return False, f"영업 완료 오류: {exc}", False


async def release_idle_member(
    requester_id: int, session_id: int, target_user_id: int
) -> tuple[bool, str, bool]:
    if int(requester_id) == int(target_user_id):
        return False, "본인은 작업창의 영업 마치기를 사용하세요.", False
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                session, requester, state = await _lock_running(
                    cur, requester_id, session_id
                )
                if not session or not requester or state is None:
                    await conn.rollback()
                    return False, "진행 중인 카페 참가 정보가 없습니다.", False
                await cur.execute(
                    """UPDATE cafe_tycoon_members
                       SET actions_left=0,ready=1
                       WHERE session_id=%s AND user_id=%s
                         AND participating=1 AND ready=0
                         AND last_action_at IS NOT NULL
                         AND last_action_at <= UTC_TIMESTAMP() - INTERVAL 30 MINUTE""",
                    (int(session_id), int(target_user_id)),
                )
                if cur.rowcount <= 0:
                    await conn.rollback()
                    return False, "30분 이상 자리를 비운 미완료 참여자가 아닙니다.", False
                advanced, next_turn = await _save_or_advance_cycle(
                    cur, session, state, cafe_cash=int(session["cafe_cash"])
                )
                await conn.commit()
                message = "자리 비움 처리로 남은 행동을 정리했습니다."
                if advanced:
                    message += f" **{next_turn}사이클**로 넘어갑니다."
                return True, message, advanced
            except Exception as exc:
                await conn.rollback()
                return False, f"자리 비움 처리 오류: {exc}", False


async def reroll_order(
    user_id: int, session_id: int, order_id: int
) -> tuple[bool, str]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                session, member, state = await _lock_running(cur, user_id, session_id)
                if not session or not member or state is None:
                    await conn.rollback()
                    return False, "진행 중인 카페 참가 정보가 없습니다."
                if int(state.get("order_reroll_turn", 0)) == int(session["turn_no"]):
                    await conn.rollback()
                    return False, "이번 사이클의 무료 주문 교체를 이미 사용했습니다."
                order = next(
                    (
                        item for item in state.get("orders", [])
                        if int(item["id"]) == int(order_id)
                    ),
                    None,
                )
                if not order:
                    await conn.rollback()
                    return False, "교체할 주문을 찾지 못했습니다."
                if order.get("vip"):
                    await conn.rollback()
                    return False, "VIP 주문은 교체할 수 없습니다."
                state["orders"].remove(order)
                state["orders"].append(_new_order(state))
                state["order_reroll_turn"] = int(session["turn_no"])
                _add_log(state, f"🔄 주문 #{order_id}을 무료로 교체했습니다.")
                await cur.execute(
                    "UPDATE cafe_tycoon_sessions SET state_json=%s WHERE id=%s",
                    (json.dumps(state, ensure_ascii=False), int(session_id)),
                )
                await conn.commit()
                return True, "일반 주문을 새 주문으로 교체했습니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"주문 교체 오류: {exc}"


def _decor_item(item_key: str) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    if item_key in DECOR_APPEARANCES:
        return "appearances", DECOR_APPEARANCES[item_key]
    if item_key in DECOR_EFFECTS:
        return "effects", DECOR_EFFECTS[item_key]
    return None, None


def _next_season_state(
    old_state: dict[str, Any], session_id: int, next_season: int
) -> dict[str, Any]:
    old_state = _normalize_state(old_state)
    next_state = _default_state()
    next_state["unlocked_recipes"] = list(old_state["unlocked_recipes"])
    next_state["products"] = {
        name: 0 for name in next_state["unlocked_recipes"]
    }
    next_state["decor_collection"] = json.loads(
        json.dumps(old_state["decor_collection"])
    )
    next_state["decor_loadout"] = json.loads(json.dumps(
        old_state.get("pending_decor_loadout")
        or old_state["decor_loadout"]
    ))
    next_state["season_shop"] = _season_shop(
        int(session_id), int(next_season), next_state["decor_collection"]
    )
    _add_log(next_state, f"🎉 시즌 {int(next_season)} 영업을 시작했습니다.")
    return next_state


async def purchase_decor(
    user_name: str, user_id: int, session_id: int, item_key: str
) -> tuple[bool, str]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    "SELECT * FROM cafe_tycoon_sessions WHERE id=%s FOR UPDATE",
                    (int(session_id),),
                )
                session = await cur.fetchone()
                if not session or session["status"] not in ("lobby", "running"):
                    await conn.rollback()
                    return False, "구매할 수 없는 카페 상태입니다."
                await cur.execute(
                    """SELECT 1 FROM cafe_tycoon_members
                       WHERE session_id=%s AND user_id=%s FOR UPDATE""",
                    (int(session_id), int(user_id)),
                )
                if not await cur.fetchone():
                    await conn.rollback()
                    return False, "카페 멤버만 구매할 수 있습니다."
                state = _normalize_state(_loads(session["state_json"], _default_state()))
                if not state.get("season_shop"):
                    state["season_shop"] = _season_shop(
                        int(session_id), int(session.get("season_no", 1)),
                        state["decor_collection"],
                    )
                bucket, item = _decor_item(item_key)
                if not item or item_key not in state["season_shop"]:
                    await conn.rollback()
                    return False, "이번 시즌 상점의 상품이 아닙니다."
                if item_key in state["decor_collection"][bucket]:
                    await conn.rollback()
                    return False, "이미 보유한 인테리어입니다."
                price = DECOR_PRICES[item["rarity"]]
                if int(session.get("decor_tokens", 0)) < price:
                    await conn.rollback()
                    return False, f"인테리어 코인 {price}개가 필요합니다."
                state["decor_collection"][bucket].append(item_key)
                _add_log(state, f"🛍️ {user_name}: {item['name']} 구매")
                await cur.execute(
                    """UPDATE cafe_tycoon_sessions
                       SET decor_tokens=decor_tokens-%s,state_json=%s WHERE id=%s""",
                    (price, json.dumps(state, ensure_ascii=False), int(session_id)),
                )
                await conn.commit()
                return True, f"{item['name']}을(를) {price}코인에 구매했습니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"인테리어 구매 오류: {exc}"


async def equip_decor(
    user_name: str,
    user_id: int,
    session_id: int,
    slot: str,
    item_type: str,
    item_key: str | None,
) -> tuple[bool, str]:
    if slot not in DECOR_SLOTS or item_type not in ("appearance", "effect"):
        return False, "잘못된 인테리어 위치입니다."
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    "SELECT * FROM cafe_tycoon_sessions WHERE id=%s FOR UPDATE",
                    (int(session_id),),
                )
                session = await cur.fetchone()
                if not session or session["status"] not in ("lobby", "running"):
                    await conn.rollback()
                    return False, "배치할 수 없는 카페 상태입니다."
                await cur.execute(
                    """SELECT 1 FROM cafe_tycoon_members
                       WHERE session_id=%s AND user_id=%s FOR UPDATE""",
                    (int(session_id), int(user_id)),
                )
                if not await cur.fetchone():
                    await conn.rollback()
                    return False, "카페 멤버만 배치할 수 있습니다."
                state = _normalize_state(_loads(session["state_json"], _default_state()))
                bucket = "appearances" if item_type == "appearance" else "effects"
                catalog = DECOR_APPEARANCES if item_type == "appearance" else DECOR_EFFECTS
                if item_key is not None:
                    item = catalog.get(item_key)
                    if (
                        not item
                        or item_key not in state["decor_collection"][bucket]
                        or item["slot"] != slot
                    ):
                        await conn.rollback()
                        return False, "해당 공간에 배치할 수 없는 미보유 항목입니다."
                await cur.execute(
                    """SELECT COUNT(*) AS count FROM cafe_tycoon_members
                       WHERE session_id=%s AND participating=1""",
                    (int(session_id),),
                )
                active = int((await cur.fetchone())["count"]) > 0
                if active:
                    loadout = state.get("pending_decor_loadout")
                    if not isinstance(loadout, dict):
                        loadout = json.loads(json.dumps(state["decor_loadout"]))
                    state["pending_decor_loadout"] = loadout
                    timing = "다음 사이클부터"
                else:
                    loadout = state["decor_loadout"]
                    timing = "즉시"
                loadout[slot][item_type] = item_key
                if not active and session["status"] == "running":
                    await cur.execute(
                        """UPDATE cafe_tycoon_members
                           SET actions_left=%s,ready=0
                           WHERE session_id=%s AND participating=0""",
                        (_action_cap(state), int(session_id)),
                    )
                label = "해제" if item_key is None else catalog[item_key]["name"]
                _add_log(
                    state,
                    f"🪑 {user_name}: {DECOR_SLOTS[slot]} {item_type} → {label} ({timing})",
                )
                await cur.execute(
                    "UPDATE cafe_tycoon_sessions SET state_json=%s WHERE id=%s",
                    (json.dumps(state, ensure_ascii=False), int(session_id)),
                )
                await conn.commit()
                return True, f"{DECOR_SLOTS[slot]} 구성을 {label}(으)로 변경했습니다. {timing} 적용됩니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"인테리어 배치 오류: {exc}"


async def vote_to_end(user_id: int, session_id: int) -> tuple[bool, str, bool]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    "SELECT * FROM cafe_tycoon_sessions WHERE id=%s FOR UPDATE",
                    (int(session_id),),
                )
                session = await cur.fetchone()
                if not session or session["status"] != "running":
                    await conn.rollback()
                    return False, "종료 투표를 할 수 없는 상태입니다.", False
                if int(session.get("reputation", 0)) < 100:
                    await conn.rollback()
                    return False, "시즌 결산에는 명성 100 이상이 필요합니다.", False
                await cur.execute(
                    """UPDATE cafe_tycoon_members SET end_vote=1
                       WHERE session_id=%s AND user_id=%s""",
                    (int(session_id), int(user_id)),
                )
                if cur.rowcount <= 0:
                    await conn.rollback()
                    return False, "참가자만 종료 투표를 할 수 있습니다.", False
                await cur.execute(
                    """SELECT end_vote FROM cafe_tycoon_members
                       WHERE session_id=%s ORDER BY user_id FOR UPDATE""",
                    (int(session_id),),
                )
                member_votes = list(await cur.fetchall())
                total = len(member_votes)
                votes = sum(int(row["end_vote"]) for row in member_votes)
                needed = _season_vote_needed(total)
                settled = total > 0 and votes >= needed
                if settled:
                    score = int(session["score"])
                    money, points, rare_total = settlement_amounts(score)
                    await cur.execute(
                        """INSERT INTO cafe_tycoon_seasons
                           (session_id,season_no,score,reputation,reward_money,
                            reward_points,reward_rare_total)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            int(session_id), int(session.get("season_no", 1)), score,
                            int(session["reputation"]), money, points, rare_total,
                        ),
                    )
                    season_id = int(cur.lastrowid)
                    await cur.execute(
                        """SELECT user_id FROM cafe_tycoon_members
                           WHERE session_id=%s ORDER BY user_id FOR UPDATE""",
                        (int(session_id),),
                    )
                    members = list(await cur.fetchall())
                    for row in members:
                        await cur.execute(
                            """INSERT INTO cafe_tycoon_season_rewards
                               (season_id,user_id) VALUES (%s,%s)""",
                            (season_id, int(row["user_id"])),
                        )
                    next_season = int(session.get("season_no", 1)) + 1
                    next_state = _next_season_state(
                        _loads(session["state_json"], _default_state()),
                        int(session_id),
                        next_season,
                    )
                    await cur.execute(
                        """UPDATE cafe_tycoon_sessions
                           SET season_no=%s,turn_no=1,score=0,cafe_cash=30000,
                               reputation=0,state_json=%s
                           WHERE id=%s""",
                        (
                            next_season,
                            json.dumps(next_state, ensure_ascii=False),
                            int(session_id),
                        ),
                    )
                    await cur.execute(
                        """UPDATE cafe_tycoon_members
                           SET actions_left=%s,ready=0,participating=0,
                               last_action_at=NULL,end_vote=0
                           WHERE session_id=%s""",
                        (_action_cap(next_state), int(session_id)),
                    )
                    message = (
                        f"과반수 동의로 시즌 {next_season - 1}을 결산했습니다. "
                        f"시즌 {next_season}이 즉시 시작되었으며 지난 보상은 시즌 기록에서 받을 수 있습니다."
                    )
                else:
                    message = f"시즌 결산에 동의했습니다. ({votes}/{needed} 필요)"
                await conn.commit()
                return True, message, settled
            except Exception as exc:
                await conn.rollback()
                return False, f"종료 투표 오류: {exc}", False


def settlement_amounts(score: int) -> tuple[int, int, int]:
    score = max(0, int(score))
    money = 200_000 + score * 1_500
    points = 8_000 + score * 50
    rare_total = min(60, max(2, 2 + score // 120))
    return money, points, rare_total


def _season_vote_needed(member_count: int) -> int:
    return max(1, int(member_count) // 2 + 1)


async def claim_settlement(
    user_id: int,
    session_id: int,
    choices: list[str],
) -> tuple[bool, str]:
    choices = list(dict.fromkeys(choices))
    candidates = settlement_reward_candidates(session_id, user_id)
    if len(choices) != 2 or any(item not in candidates for item in choices):
        return False, "이번 정산 후보 8종 중 서로 다른 희귀 재료 2종을 선택하세요."
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    "SELECT status,score FROM cafe_tycoon_sessions WHERE id=%s FOR UPDATE",
                    (int(session_id),),
                )
                session = await cur.fetchone()
                if not session or session["status"] != "settling":
                    await conn.rollback()
                    return False, "정산 가능한 카페가 아닙니다."
                await cur.execute(
                    """SELECT reward_claimed FROM cafe_tycoon_members
                       WHERE session_id=%s AND user_id=%s FOR UPDATE""",
                    (int(session_id), int(user_id)),
                )
                member = await cur.fetchone()
                if not member:
                    await conn.rollback()
                    return False, "참가 기록을 찾지 못했습니다."
                if int(member["reward_claimed"]):
                    await conn.rollback()
                    return False, "이미 정산을 받았습니다."
                money, points, total = settlement_amounts(int(session["score"]))
                first = (total + 1) // 2
                second = total // 2
                await cur.execute(
                    """UPDATE users
                       SET money=money+%s,pt=pt+%s,data_revision=data_revision+1
                       WHERE user_id=%s""",
                    (money, points, str(user_id)),
                )
                for item, count in zip(choices, (first, second)):
                    await cur.execute(
                        """INSERT INTO inventory (user_id,item_name,quantity)
                           VALUES (%s,%s,%s) AS new
                           ON DUPLICATE KEY UPDATE
                             quantity=inventory.quantity+new.quantity""",
                        (str(user_id), item, count),
                    )
                await cur.execute(
                    """UPDATE cafe_tycoon_members
                       SET reward_choices=%s,reward_claimed=1
                       WHERE session_id=%s AND user_id=%s""",
                    (
                        json.dumps(choices, ensure_ascii=False),
                        int(session_id),
                        int(user_id),
                    ),
                )
                await cur.execute(
                    """SELECT reward_claimed FROM cafe_tycoon_members
                       WHERE session_id=%s ORDER BY user_id FOR UPDATE""",
                    (int(session_id),),
                )
                claims = list(await cur.fetchall())
                if claims and all(int(row["reward_claimed"]) for row in claims):
                    await cur.execute(
                        "UPDATE cafe_tycoon_sessions SET status='closed' WHERE id=%s",
                        (int(session_id),),
                    )
                await conn.commit()
                return True, (
                    f"{money:,}원, {points:,}pt, "
                    f"{choices[0]} ×{first}, {choices[1]} ×{second}을(를) 받았습니다."
                )
            except Exception as exc:
                await conn.rollback()
                return False, f"정산 오류: {exc}"


async def list_season_rewards(
    session_id: int, user_id: int
) -> list[dict[str, Any]]:
    await ensure_tycoon_schema()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                """SELECT s.*,r.claimed,r.reward_choices
                   FROM cafe_tycoon_seasons s
                   JOIN cafe_tycoon_season_rewards r ON r.season_id=s.id
                   WHERE s.session_id=%s AND r.user_id=%s
                   ORDER BY s.season_no DESC LIMIT 25""",
                (int(session_id), int(user_id)),
            )
            return list(await cur.fetchall())


async def claim_season_reward(
    user_id: int, season_id: int, choices: list[str]
) -> tuple[bool, str]:
    choices = list(dict.fromkeys(choices))
    candidates = settlement_reward_candidates(season_id, user_id)
    if len(choices) != 2 or any(item not in candidates for item in choices):
        return False, "이번 시즌 후보 중 서로 다른 희귀 재료 2종을 선택하세요."
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    """SELECT s.reward_money,s.reward_points,s.reward_rare_total,
                              s.season_no,r.claimed
                       FROM cafe_tycoon_seasons s
                       JOIN cafe_tycoon_season_rewards r ON r.season_id=s.id
                       WHERE s.id=%s AND r.user_id=%s FOR UPDATE""",
                    (int(season_id), int(user_id)),
                )
                reward = await cur.fetchone()
                if not reward:
                    await conn.rollback()
                    return False, "받을 수 있는 시즌 정산을 찾지 못했습니다."
                if int(reward["claimed"]):
                    await conn.rollback()
                    return False, "이미 받은 시즌 정산입니다."
                total = int(reward["reward_rare_total"])
                first, second = (total + 1) // 2, total // 2
                await cur.execute(
                    """UPDATE users
                       SET money=money+%s,pt=pt+%s,data_revision=data_revision+1
                       WHERE user_id=%s""",
                    (
                        int(reward["reward_money"]),
                        int(reward["reward_points"]),
                        str(user_id),
                    ),
                )
                for item, count in zip(choices, (first, second)):
                    await cur.execute(
                        """INSERT INTO inventory (user_id,item_name,quantity)
                           VALUES (%s,%s,%s) AS new
                           ON DUPLICATE KEY UPDATE
                             quantity=inventory.quantity+new.quantity""",
                        (str(user_id), item, count),
                    )
                await cur.execute(
                    """UPDATE cafe_tycoon_season_rewards
                       SET claimed=1,reward_choices=%s,claimed_at=UTC_TIMESTAMP()
                       WHERE season_id=%s AND user_id=%s AND claimed=0""",
                    (
                        json.dumps(choices, ensure_ascii=False),
                        int(season_id),
                        int(user_id),
                    ),
                )
                if cur.rowcount != 1:
                    await conn.rollback()
                    return False, "정산이 이미 처리되었습니다."
                await conn.commit()
                return True, (
                    f"시즌 {int(reward['season_no'])} 정산: "
                    f"{int(reward['reward_money']):,}원, "
                    f"{int(reward['reward_points']):,}pt, "
                    f"{choices[0]} ×{first}, {choices[1]} ×{second}"
                )
            except Exception as exc:
                await conn.rollback()
                return False, f"시즌 정산 오류: {exc}"


def _status_embed(session: dict[str, Any], members: list[dict[str, Any]]) -> discord.Embed:
    state = session["state"]
    status = session["status"]
    title_status = {"lobby": "참가 대기", "running": "영업 중", "settling": "정산 중"}.get(status, status)
    embed = discord.Embed(
        title=f"🏪 카페 타이쿤 #{session['id']} · {title_status}",
        description=(
            f"방장: **{session['host_name']}** · 참가자 {len(members)}/{MAX_PLAYERS}\n"
            f"시즌 **{int(session.get('season_no', 1))}** · "
            f"사이클 **{int(session['turn_no'])}** · 점수 **{int(session['score']):,}**\n"
            f"명성 **{int(session.get('reputation', 0))}** · "
            f"운영 자금 **{int(session['cafe_cash']):,}원** · "
            f"인테리어 코인 **{int(session.get('decor_tokens', 0))}**"
        ),
        color=discord.Color.orange(),
    )
    member_lines = []
    for member in members:
        if status == "lobby":
            flag = " 👑" if int(member["user_id"]) == int(session["host_id"]) else ""
        elif status == "running":
            flag = (
                (
                    f" · 참여 · 행동 {int(member['actions_left'])}"
                    if int(member.get("participating", 0))
                    else " · 휴식 중"
                )
                + (" · 완료" if int(member["ready"]) else "")
                + (" · 결산 동의" if int(member["end_vote"]) else "")
            )
        else:
            flag = " · 정산 완료" if int(member["reward_claimed"]) else " · 정산 대기"
        member_lines.append(f"• {member['user_name']}{flag}")
    embed.add_field(name="참가자", value="\n".join(member_lines), inline=False)
    if status != "lobby":
        embed.add_field(
            name="최근 기록",
            value="\n".join(f"• {line}" for line in state.get("log", [])[-5:]) or "기록 없음",
            inline=False,
        )
    if status == "lobby":
        embed.set_footer(text="2~4명이 참가한 뒤 방장이 영업을 시작합니다.")
    elif status == "running":
        embed.set_footer(
            text="이번 사이클에 행동한 참여자들만 모두 마치면 다음 사이클로 진행됩니다."
        )
    else:
        embed.set_footer(text="점수에 비례한 정산과 희귀 재료 2종을 선택할 수 있습니다.")
    return embed


class CafeTycoonEntryView(discord.ui.View):
    def __init__(self, author, parent_view):
        super().__init__(timeout=300)
        self.author = author
        self.parent_view = parent_view
        self.lobbies: list[dict[str, Any]] = []
        self.selected_session_id: int | None = None
        self.page = 0

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 카페 메뉴만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def open(self, interaction):
        await ensure_tycoon_schema()
        active = await get_user_active_session(self.author.id)
        if active:
            view = CafeTycoonSessionView(int(active["id"]), self.parent_view)
            await view.refresh(interaction)
            return
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def load(self):
        self.lobbies = await list_lobbies()
        pages = max(1, (len(self.lobbies) + LOBBIES_PER_PAGE - 1) // LOBBIES_PER_PAGE)
        self.page = max(0, min(self.page, pages - 1))
        visible = self.lobbies[
            self.page * LOBBIES_PER_PAGE:(self.page + 1) * LOBBIES_PER_PAGE
        ]
        if self.selected_session_id not in {int(row["id"]) for row in visible}:
            self.selected_session_id = int(visible[0]["id"]) if visible else None
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        pages = max(1, (len(self.lobbies) + LOBBIES_PER_PAGE - 1) // LOBBIES_PER_PAGE)
        visible = self.lobbies[
            self.page * LOBBIES_PER_PAGE:(self.page + 1) * LOBBIES_PER_PAGE
        ]
        if visible:
            select = discord.ui.Select(
                placeholder=f"참가할 카페 선택 ({self.page + 1}/{pages})",
                row=0,
                options=[
                    discord.SelectOption(
                        label=f"#{row['id']} {row['host_name']}의 카페",
                        value=str(row["id"]),
                        description=f"참가자 {int(row['member_count'])}/{MAX_PLAYERS}",
                        default=int(row["id"]) == self.selected_session_id,
                    )
                    for row in visible
                ],
            )
            select.callback = self.select_lobby
            self.add_item(select)
        create = discord.ui.Button(label="새 카페 만들기", style=discord.ButtonStyle.success, row=1)
        join = discord.ui.Button(
            label="선택 카페 참가",
            style=discord.ButtonStyle.primary,
            disabled=self.selected_session_id is None,
            row=1,
        )
        refresh = discord.ui.Button(label="새로고침", style=discord.ButtonStyle.secondary, row=1)
        create.callback = self.create
        join.callback = self.join
        refresh.callback = self.refresh
        self.add_item(create)
        self.add_item(join)
        self.add_item(refresh)
        if pages > 1:
            previous = discord.ui.Button(label="이전", disabled=self.page == 0, row=2)
            counter = discord.ui.Button(label=f"{self.page + 1}/{pages}", disabled=True, row=2)
            following = discord.ui.Button(label="다음", disabled=self.page >= pages - 1, row=2)
            previous.callback = self.previous
            following.callback = self.following
            self.add_item(previous)
            self.add_item(counter)
            self.add_item(following)
        back = discord.ui.Button(label="카페로", style=discord.ButtonStyle.secondary, row=3)
        back.callback = self.back
        self.add_item(back)

    def get_embed(self):
        return discord.Embed(
            title="🏪 카페 타이쿤",
            description=(
                "2~4명이 함께 꾸미고 운영하는 영구 카페입니다.\n"
                "그 사이클에 실제로 행동한 멤버들만 영업을 마치면 진행됩니다.\n"
                "명성 100부터 과반수 동의로 시즌을 결산하고 장식·레시피를 이어가세요."
            ),
            color=discord.Color.orange(),
        )

    async def select_lobby(self, interaction):
        self.selected_session_id = int(interaction.data["values"][0])
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def create(self, interaction):
        await interaction.response.defer()
        ok, message, session_id = await create_session(interaction.user)
        if not ok:
            return await interaction.followup.send(message, ephemeral=True)
        view = CafeTycoonSessionView(int(session_id), self.parent_view)
        await view.refresh(interaction, notice=message)

    async def join(self, interaction):
        await interaction.response.defer()
        ok, message = await join_session(interaction.user, int(self.selected_session_id))
        if not ok:
            return await interaction.followup.send(message, ephemeral=True)
        view = CafeTycoonSessionView(int(self.selected_session_id), self.parent_view)
        await view.refresh(interaction, notice=message)

    async def refresh(self, interaction):
        await interaction.response.defer()
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def previous(self, interaction):
        self.page -= 1
        await self.load()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def following(self, interaction):
        self.page += 1
        await self.load()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def back(self, interaction):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="☕ 카페",
                description="카페에 오신 것을 환영합니다.",
                color=discord.Color.gold(),
            ),
            view=self.parent_view,
        )


class CafeTycoonSessionView(discord.ui.View):
    def __init__(self, session_id: int, parent_view=None):
        super().__init__(timeout=900)
        self.session_id = int(session_id)
        self.parent_view = parent_view

    async def refresh(self, interaction, notice: str | None = None):
        session, members = await get_session(self.session_id)
        if not session:
            embed = discord.Embed(title="카페 타이쿤", description="세션을 찾지 못했습니다.")
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=None)
            else:
                await interaction.response.edit_message(embed=embed, view=None)
            return
        self.rebuild(session, members)
        embed = _status_embed(session, members)
        if notice:
            embed.add_field(name="처리 결과", value=notice, inline=False)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    def rebuild(self, session, members):
        self.clear_items()
        status = session["status"]
        if status == "lobby":
            join = discord.ui.Button(
                label="참가",
                style=discord.ButtonStyle.success,
                disabled=len(members) >= MAX_PLAYERS,
                row=0,
            )
            start = discord.ui.Button(label="영업 시작", style=discord.ButtonStyle.primary, row=0)
            leave = discord.ui.Button(label="대기실 나가기", style=discord.ButtonStyle.danger, row=0)
            join.callback = self.join
            start.callback = self.start
            leave.callback = self.leave
            self.add_item(join)
            self.add_item(start)
            self.add_item(leave)
        elif status == "running":
            work = discord.ui.Button(label="영업", style=discord.ButtonStyle.success, row=0)
            interior = discord.ui.Button(label="인테리어", style=discord.ButtonStyle.primary, row=0)
            shop = discord.ui.Button(label="도감·시즌 상점", style=discord.ButtonStyle.primary, row=0)
            vote = discord.ui.Button(label="시즌 결산 동의", style=discord.ButtonStyle.danger, row=1)
            history = discord.ui.Button(label="시즌 기록", style=discord.ButtonStyle.secondary, row=1)
            idle = discord.ui.Button(label="자리 비움 처리", style=discord.ButtonStyle.secondary, row=1)
            work.callback = self.work
            interior.callback = self.interior
            shop.callback = self.shop
            vote.callback = self.vote
            history.callback = self.history
            idle.callback = self.idle
            self.add_item(work)
            self.add_item(interior)
            self.add_item(shop)
            self.add_item(vote)
            self.add_item(history)
            self.add_item(idle)
        elif status == "settling":
            settle = discord.ui.Button(label="내 정산 받기", style=discord.ButtonStyle.success, row=0)
            settle.callback = self.settle
            self.add_item(settle)
        refresh = discord.ui.Button(label="새로고침", style=discord.ButtonStyle.secondary, row=2)
        refresh.callback = self.refresh_button
        self.add_item(refresh)

    async def join(self, interaction):
        await interaction.response.defer()
        ok, message = await join_session(interaction.user, self.session_id)
        if not ok:
            return await interaction.followup.send(message, ephemeral=True)
        await self.refresh(interaction, notice=message)

    async def start(self, interaction):
        await interaction.response.defer()
        ok, message = await start_session(interaction.user.id, self.session_id)
        if not ok:
            return await interaction.followup.send(message, ephemeral=True)
        await self.refresh(interaction, notice=message)

    async def leave(self, interaction):
        await interaction.response.defer()
        ok, message = await leave_lobby(interaction.user.id, self.session_id)
        if not ok:
            return await interaction.followup.send(message, ephemeral=True)
        entry = CafeTycoonEntryView(interaction.user, self.parent_view)
        await entry.load()
        await interaction.edit_original_response(embed=entry.get_embed(), view=entry)

    async def work(self, interaction):
        session, members = await get_session(self.session_id)
        if interaction.user.id not in {int(row["user_id"]) for row in members}:
            return await interaction.response.send_message("참가자만 작업할 수 있습니다.", ephemeral=True)
        view = CafeTycoonActionView(interaction.user, self.session_id, interaction.message)
        await view.load()
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

    async def vote(self, interaction):
        await interaction.response.defer()
        ok, message, _ = await vote_to_end(interaction.user.id, self.session_id)
        if not ok:
            return await interaction.followup.send(message, ephemeral=True)
        await self.refresh(interaction, notice=message)

    async def interior(self, interaction):
        view = CafeTycoonInteriorView(interaction.user, self.session_id)
        await view.load()
        await interaction.response.send_message(
            embed=view.get_embed(), view=view, ephemeral=True
        )

    async def shop(self, interaction):
        view = CafeTycoonDecorShopView(interaction.user, self.session_id)
        await view.load()
        await interaction.response.send_message(
            embed=view.get_embed(), view=view, ephemeral=True
        )

    async def history(self, interaction):
        view = CafeTycoonSeasonHistoryView(interaction.user, self.session_id)
        await view.load()
        await interaction.response.send_message(
            embed=view.get_embed(), view=view, ephemeral=True
        )

    async def idle(self, interaction):
        view = CafeTycoonIdleView(interaction.user, self.session_id, interaction.message)
        await view.load()
        await interaction.response.send_message(
            embed=view.get_embed(), view=view, ephemeral=True
        )

    async def settle(self, interaction):
        session, members = await get_session(self.session_id)
        member = next(
            (row for row in members if int(row["user_id"]) == int(interaction.user.id)),
            None,
        )
        if not member:
            return await interaction.response.send_message("참가자만 정산할 수 있습니다.", ephemeral=True)
        if int(member["reward_claimed"]):
            return await interaction.response.send_message("이미 정산을 받았습니다.", ephemeral=True)
        view = CafeTycoonSettlementView(interaction.user, self.session_id, interaction.message)
        await interaction.response.send_message(embed=view.get_embed(int(session["score"])), view=view, ephemeral=True)

    async def refresh_button(self, interaction):
        await interaction.response.defer()
        await self.refresh(interaction)


class CafeTycoonActionView(discord.ui.View):
    def __init__(self, author, session_id: int, public_message=None):
        super().__init__(timeout=300)
        self.author = author
        self.session_id = int(session_id)
        self.public_message = public_message
        self.session = None
        self.members = []
        self.member = None

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 작업창만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def load(self):
        self.session, self.members = await get_session(self.session_id)
        self.member = next(
            (row for row in self.members if int(row["user_id"]) == int(self.author.id)),
            None,
        )
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        if not self.session or self.session["status"] != "running" or not self.member:
            close = discord.ui.Button(label="닫기", style=discord.ButtonStyle.secondary)
            close.callback = self.close
            self.add_item(close)
            return
        disabled = int(self.member["ready"]) or int(self.member["actions_left"]) <= 0
        buttons = (
            ("📦 납품", self.open_delivery, discord.ButtonStyle.primary),
            ("🍳 제조", self.open_manufacturing, discord.ButtonStyle.success),
            ("🔧 강화", self.open_upgrade, discord.ButtonStyle.primary),
            ("📚 연구", self.open_research, discord.ButtonStyle.primary),
        )
        for label, callback, style in buttons:
            button = discord.ui.Button(
                label=label,
                style=style,
                disabled=disabled,
                row=0,
            )
            button.callback = callback
            self.add_item(button)
        stock = discord.ui.Button(
            label="🧺 재료 구매",
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
            row=1,
        )
        finish = discord.ui.Button(
            label="내 영업 마치기",
            style=discord.ButtonStyle.danger,
            disabled=(
                int(self.member["ready"])
                or not int(self.member.get("participating", 0))
            ),
            row=1,
        )
        refresh = discord.ui.Button(label="새로고침", style=discord.ButtonStyle.secondary, row=1)
        close = discord.ui.Button(label="닫기", style=discord.ButtonStyle.secondary, row=1)
        stock.callback = self.buy_stock
        finish.callback = self.finish
        refresh.callback = self.refresh
        close.callback = self.close
        self.add_item(stock)
        self.add_item(finish)
        self.add_item(refresh)
        self.add_item(close)

    def get_embed(self, notice: str | None = None):
        if not self.session or not self.member:
            return discord.Embed(title="🏪 내 작업창", description="참가 정보를 찾지 못했습니다.")
        state = self.session["state"]
        embed = discord.Embed(
            title=f"🏪 내 작업창 · {int(self.session['turn_no'])}사이클",
            description=(
                f"남은 행동: **{int(self.member['actions_left'])}/{_action_cap(state)}**\n"
                f"카페 자금: **{int(self.session['cafe_cash']):,}원** · "
                f"점수: **{int(self.session['score']):,}** · "
                f"명성: **{int(self.session.get('reputation', 0))}**\n"
                + (
                    "현재 사이클 참여 중"
                    if int(self.member.get("participating", 0))
                    else "첫 성공 행동부터 현재 사이클 참여자로 등록됩니다."
                )
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="재료",
            value=" · ".join(f"{key} {value}" for key, value in state["ingredients"].items()),
            inline=False,
        )
        embed.add_field(
            name="완제품",
            value=" · ".join(
                f"{label} "
                + str(
                    sum(
                        int(state["products"].get(name, 0))
                        for name, recipe in RECIPE_CATALOG.items()
                        if recipe["kind"] == kind
                    )
                )
                for kind, label in PRODUCT_LABELS.items()
            ),
            inline=False,
        )
        embed.add_field(
            name="메뉴",
            value=(
                f"연구 완료 **{len(state['unlocked_recipes'])}/{len(RECIPE_CATALOG)}종** · "
                f"대기 주문 **{len(state.get('orders', []))}건**\n"
                "납품·제조·강화·연구는 각각의 버튼에서 관리합니다."
            ),
            inline=False,
        )
        if notice:
            embed.add_field(name="행동 결과", value=notice, inline=False)
        return embed

    async def _refresh_public(self):
        if not self.public_message:
            return
        try:
            session, members = await get_session(self.session_id)
            if session:
                view = CafeTycoonSessionView(self.session_id)
                view.rebuild(session, members)
                await self.public_message.edit(embed=_status_embed(session, members), view=view)
        except (discord.NotFound, discord.HTTPException):
            pass

    async def buy_stock(self, interaction):
        await interaction.response.defer()
        ok, message, _ = await perform_action(
            interaction.user,
            self.session_id,
            "stock",
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok:
            await self._refresh_public()

    async def _open_subview(self, interaction, view):
        await view.load()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    async def open_delivery(self, interaction):
        await self._open_subview(
            interaction,
            CafeTycoonDeliveryView(
                self.author, self.session_id, self, self.public_message
            ),
        )

    async def open_manufacturing(self, interaction):
        await self._open_subview(
            interaction,
            CafeTycoonManufacturingView(
                self.author, self.session_id, self, self.public_message
            ),
        )

    async def open_upgrade(self, interaction):
        await self._open_subview(
            interaction,
            CafeTycoonUpgradeView(
                self.author, self.session_id, self, self.public_message
            ),
        )

    async def open_research(self, interaction):
        await self._open_subview(
            interaction,
            CafeTycoonResearchView(
                self.author, self.session_id, self, self.public_message
            ),
        )

    async def finish(self, interaction):
        await interaction.response.defer()
        ok, message, _ = await finish_turn_early(interaction.user.id, self.session_id)
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok:
            await self._refresh_public()

    async def refresh(self, interaction):
        await interaction.response.defer()
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def close(self, interaction):
        await interaction.response.edit_message(content="작업창을 닫았습니다.", embed=None, view=None)


class _CafeTycoonSubView(discord.ui.View):
    def __init__(self, author, session_id: int, parent, public_message=None):
        super().__init__(timeout=300)
        self.author = author
        self.session_id = int(session_id)
        self.parent = parent
        self.public_message = public_message
        self.session = None
        self.members = []
        self.member = None

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 작업창만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def load(self):
        self.session, self.members = await get_session(self.session_id)
        self.member = next(
            (row for row in self.members if int(row["user_id"]) == int(self.author.id)),
            None,
        )
        self.rebuild()

    @property
    def disabled(self):
        return (
            not self.member
            or int(self.member["ready"])
            or int(self.member["actions_left"]) <= 0
        )

    async def _refresh_public(self):
        if not self.public_message:
            return
        try:
            session, members = await get_session(self.session_id)
            if session:
                view = CafeTycoonSessionView(self.session_id)
                view.rebuild(session, members)
                await self.public_message.edit(embed=_status_embed(session, members), view=view)
        except (discord.NotFound, discord.HTTPException):
            pass

    async def back(self, interaction):
        await self.parent.load()
        await interaction.response.edit_message(embed=self.parent.get_embed(), view=self.parent)

    async def refresh(self, interaction):
        await interaction.response.defer()
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)


class CafeTycoonManufacturingView(_CafeTycoonSubView):
    def __init__(self, author, session_id: int, parent, public_message=None):
        super().__init__(author, session_id, parent, public_message)
        self.page = 0
        self.selected_recipe = None

    def _recipes(self):
        if not self.session:
            return []
        return [
            name for name in self.session["state"]["unlocked_recipes"]
            if name in RECIPE_CATALOG
        ]

    def rebuild(self):
        self.clear_items()
        recipes = self._recipes()
        pages = max(1, (len(recipes) + RECIPE_PAGE_SIZE - 1) // RECIPE_PAGE_SIZE)
        self.page = max(0, min(self.page, pages - 1))
        visible = recipes[
            self.page * RECIPE_PAGE_SIZE:(self.page + 1) * RECIPE_PAGE_SIZE
        ]
        if self.selected_recipe not in recipes:
            self.selected_recipe = visible[0] if visible else None
        if visible:
            select = discord.ui.Select(
                placeholder="만들 메뉴 선택 · 한 페이지에 8개",
                row=0,
                options=[
                    discord.SelectOption(
                        label=f"{PRODUCT_LABELS[RECIPE_CATALOG[name]['kind']]} · {name}",
                        value=name,
                        description=self._option_description(name),
                        default=name == self.selected_recipe,
                    )
                    for name in visible
                ],
            )
            select.callback = self.choose
            self.add_item(select)
        previous = discord.ui.Button(
            label="◀", style=discord.ButtonStyle.secondary,
            disabled=self.page <= 0, row=1,
        )
        following = discord.ui.Button(
            label="▶", style=discord.ButtonStyle.secondary,
            disabled=self.page >= pages - 1, row=1,
        )
        make = discord.ui.Button(
            label="선택 메뉴 1개 제조", style=discord.ButtonStyle.success,
            disabled=self.disabled or self.selected_recipe is None, row=1,
        )
        previous.callback = self.previous
        following.callback = self.following
        make.callback = self.make
        self.add_item(previous)
        self.add_item(following)
        self.add_item(make)
        back = discord.ui.Button(label="작업창", style=discord.ButtonStyle.secondary, row=2)
        refresh = discord.ui.Button(label="새로고침", style=discord.ButtonStyle.secondary, row=2)
        back.callback = self.back
        refresh.callback = self.refresh
        self.add_item(back)
        self.add_item(refresh)

    def _option_description(self, name):
        recipe = RECIPE_CATALOG[name]
        state = self.session["state"]
        materials = " · ".join(
            f"{item} {int(state['ingredients'].get(item, 0))}/{need}"
            for item, need in recipe["ingredients"].items()
        )
        return f"{materials} · 재고 {int(state['products'].get(name, 0))}"[:100]

    def get_embed(self, notice=None):
        state = self.session["state"]
        recipes = self._recipes()
        pages = max(1, (len(recipes) + RECIPE_PAGE_SIZE - 1) // RECIPE_PAGE_SIZE)
        visible = recipes[
            self.page * RECIPE_PAGE_SIZE:(self.page + 1) * RECIPE_PAGE_SIZE
        ]
        lines = []
        for name in visible:
            recipe = RECIPE_CATALOG[name]
            materials = " · ".join(
                f"{item} {int(state['ingredients'].get(item, 0))}/{need}"
                for item, need in recipe["ingredients"].items()
            )
            marker = "▶ " if name == self.selected_recipe else ""
            lines.append(
                f"{marker}**{name}** [{PRODUCT_LABELS[recipe['kind']]}] · {materials} "
                f"· 완성품 {int(state['products'].get(name, 0))}"
            )
        embed = discord.Embed(
            title=f"🍳 카페 제조 · {self.page + 1}/{pages}",
            description="\n".join(lines) or "제조할 수 있는 메뉴가 없습니다.",
            color=discord.Color.orange(),
        )
        if notice:
            embed.add_field(name="제조 결과", value=notice, inline=False)
        return embed

    async def choose(self, interaction):
        self.selected_recipe = interaction.data["values"][0]
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def previous(self, interaction):
        self.page -= 1
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def following(self, interaction):
        self.page += 1
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def make(self, interaction):
        await interaction.response.defer()
        ok, message, _ = await perform_action(
            interaction.user, self.session_id, "make",
            recipe_name=self.selected_recipe,
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok:
            await self._refresh_public()


class CafeTycoonDeliveryView(_CafeTycoonSubView):
    def __init__(self, author, session_id: int, parent, public_message=None):
        super().__init__(author, session_id, parent, public_message)
        self.page = 0
        self.selected_order_id = None
        self.selected_recipe = None
        self.allocation_order_id = None
        self.allocations: dict[str, int] = {}

    def _orders(self):
        return self.session["state"].get("orders", []) if self.session else []

    def _selected_order(self):
        return next(
            (
                order for order in self._orders()
                if int(order["id"]) == int(self.selected_order_id or -1)
            ),
            None,
        )

    def _compatible_recipes(self):
        order = self._selected_order()
        if not order or not self.session:
            return []
        state = self.session["state"]
        return [
            name for name in state["unlocked_recipes"]
            if RECIPE_CATALOG.get(name, {}).get("kind") == order["kind"]
        ]

    def rebuild(self):
        self.clear_items()
        orders = self._orders()
        pages = max(1, (len(orders) + RECIPE_PAGE_SIZE - 1) // RECIPE_PAGE_SIZE)
        self.page = max(0, min(self.page, pages - 1))
        visible = orders[
            self.page * RECIPE_PAGE_SIZE:(self.page + 1) * RECIPE_PAGE_SIZE
        ]
        valid_ids = {int(order["id"]) for order in orders}
        if self.selected_order_id not in valid_ids:
            self.selected_order_id = int(visible[0]["id"]) if visible else None
        if self.allocation_order_id != self.selected_order_id:
            self.allocation_order_id = self.selected_order_id
            self.allocations.clear()
        compatible = self._compatible_recipes()
        if self.selected_recipe not in compatible:
            self.selected_recipe = compatible[0] if compatible else None
        if visible:
            select = discord.ui.Select(
                placeholder="납품할 주문 선택 · 한 페이지에 8개",
                row=0,
                options=[
                    discord.SelectOption(
                        label=(
                            f"{'VIP · ' if order.get('vip') else ''}#{order['id']} "
                            f"{PRODUCT_LABELS[order['kind']]} "
                            f"×{order['quantity']}"
                        ),
                        value=str(order["id"]),
                        description="같은 카테고리 메뉴 중 원하는 것을 골라 납품",
                        default=int(order["id"]) == self.selected_order_id,
                    )
                    for order in visible
                ],
            )
            select.callback = self.choose
            self.add_item(select)
        if compatible:
            state = self.session["state"]
            menu_select = discord.ui.Select(
                placeholder="이 주문에 납품할 메뉴 선택",
                row=1,
                options=[
                    discord.SelectOption(
                        label=(
                            f"{name} · 재고 {int(state['products'].get(name, 0))} "
                            f"· 담기 {int(self.allocations.get(name, 0))}"
                        ),
                        value=name,
                        description=(
                            f"개당 {int(RECIPE_CATALOG[name]['price']):,}원 · "
                            f"{int(RECIPE_CATALOG[name]['score'])}점"
                        ),
                        default=name == self.selected_recipe,
                    )
                    for name in compatible[:RECIPE_PAGE_SIZE]
                ],
            )
            menu_select.callback = self.choose_recipe
            self.add_item(menu_select)
        order = self._selected_order()
        required = int(order["quantity"]) if order else 0
        allocated = sum(int(count) for count in self.allocations.values())
        selected_count = int(self.allocations.get(self.selected_recipe or "", 0))
        selected_stock = int(
            self.session["state"]["products"].get(self.selected_recipe or "", 0)
        )
        add = discord.ui.Button(
            label="선택 메뉴 +1",
            style=discord.ButtonStyle.primary,
            disabled=(
                self.disabled
                or self.selected_recipe is None
                or allocated >= required
                or selected_count >= selected_stock
            ),
            row=2,
        )
        remove = discord.ui.Button(
            label="선택 메뉴 -1",
            style=discord.ButtonStyle.secondary,
            disabled=self.disabled or self.selected_recipe is None or selected_count <= 0,
            row=2,
        )
        clear = discord.ui.Button(
            label="구성 초기화",
            style=discord.ButtonStyle.secondary,
            disabled=self.disabled or allocated <= 0,
            row=2,
        )
        deliver = discord.ui.Button(
            label="선택 주문 납품", style=discord.ButtonStyle.success,
            disabled=(
                self.disabled
                or self.selected_order_id is None
                or allocated != required
            ),
            row=2,
        )
        add.callback = self.add_recipe
        remove.callback = self.remove_recipe
        clear.callback = self.clear_recipes
        deliver.callback = self.deliver
        self.add_item(add)
        self.add_item(remove)
        self.add_item(clear)
        self.add_item(deliver)
        back = discord.ui.Button(label="작업창", style=discord.ButtonStyle.secondary, row=3)
        refresh = discord.ui.Button(label="새로고침", style=discord.ButtonStyle.secondary, row=3)
        reroll = discord.ui.Button(
            label="일반 주문 무료 교체",
            style=discord.ButtonStyle.secondary,
            disabled=(
                order is None
                or bool(order.get("vip"))
                or int(self.session["state"].get("order_reroll_turn", 0))
                == int(self.session["turn_no"])
            ),
            row=3,
        )
        back.callback = self.back
        refresh.callback = self.refresh
        reroll.callback = self.reroll
        self.add_item(back)
        self.add_item(refresh)
        self.add_item(reroll)

    def get_embed(self, notice=None):
        state = self.session["state"]
        orders = self._orders()
        pages = max(1, (len(orders) + RECIPE_PAGE_SIZE - 1) // RECIPE_PAGE_SIZE)
        visible = orders[
            self.page * RECIPE_PAGE_SIZE:(self.page + 1) * RECIPE_PAGE_SIZE
        ]
        lines = []
        for order in visible:
            compatible = [
                name for name in state["unlocked_recipes"]
                if RECIPE_CATALOG.get(name, {}).get("kind") == order["kind"]
            ]
            ready = "✅" if sum(
                int(state["products"].get(name, 0)) for name in compatible
            ) >= int(order["quantity"]) else "❌"
            marker = "▶ " if int(order["id"]) == self.selected_order_id else ""
            lines.append(
                f"{marker}{ready} **{'👑 VIP · ' if order.get('vip') else ''}"
                f"#{order['id']} {PRODUCT_LABELS[order['kind']]} ×{order['quantity']}** · "
                f"선호 {DECOR_THEMES.get(order.get('preferred_theme'), '없음')}"
            )
        embed = discord.Embed(
            title=f"📦 카페 납품 · {self.page + 1}/{pages}",
            description="\n".join(lines) or "대기 중인 주문이 없습니다.",
            color=discord.Color.blurple(),
        )
        order = self._selected_order()
        if order:
            quantity = int(order["quantity"])
            allocation_lines = [
                f"{name} ×{count}"
                for name, count in self.allocations.items()
                if int(count) > 0
            ]
            earned_cash = sum(
                int(RECIPE_CATALOG[name]["price"]) * int(count)
                for name, count in self.allocations.items()
            )
            earned_score = sum(
                int(RECIPE_CATALOG[name]["score"]) * int(count)
                for name, count in self.allocations.items()
            )
            allocated = sum(int(count) for count in self.allocations.values())
            embed.add_field(
                name=f"납품 구성 · {allocated}/{quantity}",
                value=(
                    ("\n".join(allocation_lines) or "아직 담은 메뉴가 없습니다.")
                    + f"\n예상 보상: {earned_cash:,}원 · {earned_score}점"
                ),
                inline=False,
            )
        if notice:
            embed.add_field(name="납품 결과", value=notice, inline=False)
        return embed

    async def choose(self, interaction):
        self.selected_order_id = int(interaction.data["values"][0])
        self.selected_recipe = None
        self.allocation_order_id = self.selected_order_id
        self.allocations.clear()
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def choose_recipe(self, interaction):
        self.selected_recipe = interaction.data["values"][0]
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def add_recipe(self, interaction):
        if self.selected_recipe:
            self.allocations[self.selected_recipe] = (
                int(self.allocations.get(self.selected_recipe, 0)) + 1
            )
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def remove_recipe(self, interaction):
        if self.selected_recipe:
            current = int(self.allocations.get(self.selected_recipe, 0))
            if current <= 1:
                self.allocations.pop(self.selected_recipe, None)
            else:
                self.allocations[self.selected_recipe] = current - 1
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def clear_recipes(self, interaction):
        self.allocations.clear()
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def deliver(self, interaction):
        await interaction.response.defer()
        ok, message, _ = await perform_action(
            interaction.user, self.session_id, "serve",
            order_id=self.selected_order_id,
            recipe_allocations=dict(self.allocations),
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok:
            await self._refresh_public()

    async def reroll(self, interaction):
        await interaction.response.defer()
        ok, message = await reroll_order(
            interaction.user.id, self.session_id, int(self.selected_order_id or 0)
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok:
            await self._refresh_public()


class CafeTycoonUpgradeView(_CafeTycoonSubView):
    def __init__(self, author, session_id: int, parent, public_message=None):
        super().__init__(author, session_id, parent, public_message)
        self.selected_machine = "coffee"

    def rebuild(self):
        self.clear_items()
        state = self.session["state"] if self.session else _default_state()
        select = discord.ui.Select(
            placeholder="강화할 보조 기기 선택",
            row=0,
            options=[
                discord.SelectOption(
                    label=f"{label} Lv.{int(state['machines'].get(key, 0))}",
                    value=key,
                    description=self._machine_description(key, state)[:100],
                    default=key == self.selected_machine,
                )
                for key, label in MACHINE_LABELS.items()
            ],
        )
        select.callback = self.choose
        self.add_item(select)
        upgrade = discord.ui.Button(
            label="선택 기기 강화", style=discord.ButtonStyle.success,
            disabled=self.disabled, row=1,
        )
        back = discord.ui.Button(label="작업창", style=discord.ButtonStyle.secondary, row=1)
        upgrade.callback = self.upgrade
        back.callback = self.back
        self.add_item(upgrade)
        self.add_item(back)

    @staticmethod
    def _machine_description(key, state):
        level = int(state["machines"].get(key, 0))
        if key == "lounge":
            effect = "사이클당 행동 수 증가"
        elif key == "service":
            effect = "사이클 종료 시 주문 자동 납품"
        elif key == "display":
            effect = "사이클 종료 시 디저트 자동 제조"
        elif key == "coffee":
            effect = "사이클 종료 시 음료 자동 제조"
        else:
            effect = "사이클 종료 시 음식 자동 제조"
        if level >= MACHINE_MAX[key]:
            return f"{effect} · 최대 강화"
        cost = _upgrade_price(state, level)
        return f"{effect} · 다음 비용 {cost:,}원"

    def get_embed(self, notice=None):
        state = self.session["state"]
        lines = [
            f"**{label} Lv.{int(state['machines'].get(key, 0))}** · "
            f"{self._machine_description(key, state)}"
            for key, label in MACHINE_LABELS.items()
        ]
        embed = discord.Embed(
            title="🔧 카페 보조 기기 강화",
            description="\n".join(lines),
            color=discord.Color.dark_gold(),
        )
        if notice:
            embed.add_field(name="강화 결과", value=notice, inline=False)
        return embed

    async def choose(self, interaction):
        self.selected_machine = interaction.data["values"][0]
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def upgrade(self, interaction):
        await interaction.response.defer()
        ok, message, _ = await perform_action(
            interaction.user, self.session_id, "upgrade",
            machine=self.selected_machine,
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok:
            await self._refresh_public()


class CafeTycoonResearchView(_CafeTycoonSubView):
    def __init__(self, author, session_id: int, parent, public_message=None):
        super().__init__(author, session_id, parent, public_message)
        self.selected_recipe: str | None = None

    def rebuild(self):
        self.clear_items()
        choice_enabled = bool(
            self.session and _has_effect(
                self.session["state"], "wall_research_choice"
            )
        )
        for index, (kind, label) in enumerate(PRODUCT_LABELS.items()):
            locked = self._locked(kind)
            button = discord.ui.Button(
                label=f"{label} 연구",
                style=discord.ButtonStyle.primary,
                disabled=self.disabled or not locked,
                row=0,
            )

            async def callback(interaction, selected_kind=kind):
                await self.research(interaction, selected_kind)

            button.callback = callback
            self.add_item(button)
        if choice_enabled:
            candidates = []
            for kind in PRODUCT_LABELS:
                locked = self._locked(kind)
                if locked:
                    tier = min(int(recipe["tier"]) for _, recipe in locked)
                    candidates.extend(
                        (name, kind) for name, recipe in locked
                        if int(recipe["tier"]) == tier
                    )
            valid = {name for name, _ in candidates}
            if self.selected_recipe not in valid:
                self.selected_recipe = candidates[0][0] if candidates else None
            if candidates:
                select = discord.ui.Select(
                    placeholder="레시피 벽 · 직접 연구할 후보 선택",
                    row=1,
                    options=[
                        discord.SelectOption(
                            label=name,
                            value=name,
                            description=f"{PRODUCT_LABELS[kind]} · 직접 선택 연구",
                            default=name == self.selected_recipe,
                        )
                        for name, kind in candidates[:25]
                    ],
                )
                select.callback = self.choose_recipe
                self.add_item(select)
                choose_button = discord.ui.Button(
                    label="선택 레시피 연구",
                    style=discord.ButtonStyle.success,
                    disabled=self.disabled or self.selected_recipe is None,
                    row=2,
                )
                choose_button.callback = self.research_selected
                self.add_item(choose_button)
        back = discord.ui.Button(label="작업창", style=discord.ButtonStyle.secondary, row=3)
        refresh = discord.ui.Button(label="새로고침", style=discord.ButtonStyle.secondary, row=3)
        back.callback = self.back
        refresh.callback = self.refresh
        self.add_item(back)
        self.add_item(refresh)

    def _locked(self, kind):
        unlocked = set(self.session["state"]["unlocked_recipes"]) if self.session else set()
        return [
            (name, recipe) for name, recipe in RECIPE_CATALOG.items()
            if recipe["kind"] == kind and name not in unlocked
        ]

    def get_embed(self, notice=None):
        fields = []
        for kind, label in PRODUCT_LABELS.items():
            locked = self._locked(kind)
            if not locked:
                text = "모든 레시피 연구 완료"
            else:
                next_tier = min(int(recipe["tier"]) for _, recipe in locked)
                names = [
                    name for name, recipe in locked if int(recipe["tier"]) == next_tier
                ]
                cost = _research_price(self.session["state"], next_tier)
                text = (
                    f"다음 단계 {next_tier} · 비용 {cost:,}원\n"
                    f"발견 후보: {', '.join(names)}"
                )
            fields.append((label, text))
        embed = discord.Embed(
            title="📚 카페 레시피 연구",
            description=(
                "분류를 골라 현재 단계의 미발견 레시피 하나를 연구합니다.\n"
                "높은 단계일수록 납품가와 점수가 높은 메뉴가 열립니다."
            ),
            color=discord.Color.purple(),
        )
        for label, text in fields:
            embed.add_field(name=label, value=text, inline=False)
        if notice:
            embed.add_field(name="연구 결과", value=notice, inline=False)
        return embed

    async def research(self, interaction, kind):
        await interaction.response.defer()
        ok, message, _ = await perform_action(
            interaction.user, self.session_id, "research", category=kind,
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok:
            await self._refresh_public()

    async def choose_recipe(self, interaction):
        self.selected_recipe = interaction.data["values"][0]
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def research_selected(self, interaction):
        recipe = RECIPE_CATALOG.get(self.selected_recipe or "")
        if not recipe:
            return await interaction.response.send_message(
                "연구 후보를 선택하세요.", ephemeral=True
            )
        await interaction.response.defer()
        ok, message, _ = await perform_action(
            interaction.user,
            self.session_id,
            "research",
            category=recipe["kind"],
            recipe_name=self.selected_recipe,
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok:
            await self._refresh_public()


class _CafeTycoonFreeView(discord.ui.View):
    def __init__(self, author, session_id: int, *, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.author = author
        self.session_id = int(session_id)
        self.session = None
        self.members = []

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message(
            "본인의 카페 보조 창만 조작할 수 있습니다.", ephemeral=True
        )
        return False

    async def load(self):
        self.session, self.members = await get_session(self.session_id)
        self.rebuild()


class CafeTycoonInteriorView(_CafeTycoonFreeView):
    def __init__(self, author, session_id: int):
        super().__init__(author, session_id)
        self.selected_slot = "sign"

    def rebuild(self):
        self.clear_items()
        if not self.session:
            return
        state = self.session["state"]
        slot_select = discord.ui.Select(
            placeholder="꾸밀 공간 선택",
            row=0,
            options=[
                discord.SelectOption(
                    label=label, value=slot, default=slot == self.selected_slot
                )
                for slot, label in DECOR_SLOTS.items()
            ],
        )
        slot_select.callback = self.choose_slot
        self.add_item(slot_select)
        collection = state["decor_collection"]
        appearance_options = [
            discord.SelectOption(label="외형 해제", value="__none__")
        ]
        for key in collection["appearances"]:
            item = DECOR_APPEARANCES[key]
            if item["slot"] == self.selected_slot:
                appearance_options.append(
                    discord.SelectOption(
                        label=item["name"],
                        value=key,
                        description=DECOR_THEMES[item["theme"]],
                    )
                )
        appearance_select = discord.ui.Select(
            placeholder="보이는 외형 선택",
            row=1,
            options=appearance_options,
        )
        appearance_select.callback = self.choose_appearance
        self.add_item(appearance_select)
        effect_options = [
            discord.SelectOption(label="경영 효과 해제", value="__none__")
        ]
        for key in collection["effects"]:
            item = DECOR_EFFECTS[key]
            if item["slot"] == self.selected_slot:
                effect_options.append(
                    discord.SelectOption(
                        label=item["name"],
                        value=key,
                        description=item["description"][:100],
                    )
                )
        effect_select = discord.ui.Select(
            placeholder="경영 효과 선택",
            row=2,
            options=effect_options,
        )
        effect_select.callback = self.choose_effect
        self.add_item(effect_select)
        refresh = discord.ui.Button(label="새로고침", row=3)
        close = discord.ui.Button(label="닫기", row=3)
        refresh.callback = self.refresh
        close.callback = self.close
        self.add_item(refresh)
        self.add_item(close)

    def get_embed(self, notice: str | None = None):
        if not self.session:
            return discord.Embed(title="🪑 인테리어", description="카페를 찾지 못했습니다.")
        state = self.session["state"]
        loadout = state["decor_loadout"]
        lines = []
        for slot, label in DECOR_SLOTS.items():
            appearance_key = loadout[slot].get("appearance")
            effect_key = loadout[slot].get("effect")
            appearance = DECOR_APPEARANCES.get(appearance_key, {}).get("name", "기본 외형")
            effect = DECOR_EFFECTS.get(effect_key, {}).get("name", "효과 없음")
            lines.append(f"**{label}** · {appearance} / {effect}")
        description = "\n".join(lines)
        if state.get("pending_decor_loadout"):
            description += "\n\n⏳ 참여 중인 사이클이 끝나면 예약 배치를 적용합니다."
        embed = discord.Embed(
            title="🪑 카페 공동 인테리어",
            description=description,
            color=discord.Color.teal(),
        )
        embed.add_field(
            name="보유 도감",
            value=(
                f"외형 {len(state['decor_collection']['appearances'])}/{len(DECOR_APPEARANCES)} · "
                f"효과 {len(state['decor_collection']['effects'])}/{len(DECOR_EFFECTS)}"
            ),
            inline=False,
        )
        if notice:
            embed.add_field(name="배치 결과", value=notice, inline=False)
        return embed

    async def choose_slot(self, interaction):
        self.selected_slot = interaction.data["values"][0]
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _equip(self, interaction, item_type: str):
        value = interaction.data["values"][0]
        item_key = None if value == "__none__" else value
        await interaction.response.defer()
        ok, message = await equip_decor(
            interaction.user.display_name,
            interaction.user.id,
            self.session_id,
            self.selected_slot,
            item_type,
            item_key,
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)

    async def choose_appearance(self, interaction):
        await self._equip(interaction, "appearance")

    async def choose_effect(self, interaction):
        await self._equip(interaction, "effect")

    async def refresh(self, interaction):
        await interaction.response.defer()
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def close(self, interaction):
        await interaction.response.edit_message(content="인테리어 창을 닫았습니다.", embed=None, view=None)


class CafeTycoonDecorShopView(_CafeTycoonFreeView):
    def __init__(self, author, session_id: int):
        super().__init__(author, session_id)
        self.selected_item: str | None = None

    def _items(self):
        if not self.session:
            return []
        state = self.session["state"]
        items = state.get("season_shop") or _season_shop(
            self.session_id,
            int(self.session.get("season_no", 1)),
            state["decor_collection"],
        )
        return [item for item in items if _decor_item(item)[1]]

    def rebuild(self):
        self.clear_items()
        items = self._items()
        if self.selected_item not in items:
            self.selected_item = items[0] if items else None
        if items:
            select = discord.ui.Select(
                placeholder="이번 시즌 상품 선택",
                row=0,
                options=[
                    discord.SelectOption(
                        label=_decor_item(key)[1]["name"],
                        value=key,
                        description=(
                            f"{DECOR_RARITY_LABELS[_decor_item(key)[1]['rarity']]} · "
                            f"{DECOR_PRICES[_decor_item(key)[1]['rarity']]}코인"
                        ),
                        default=key == self.selected_item,
                    )
                    for key in items[:25]
                ],
            )
            select.callback = self.choose
            self.add_item(select)
        owned = False
        if self.session and self.selected_item:
            bucket, _ = _decor_item(self.selected_item)
            owned = self.selected_item in self.session["state"]["decor_collection"][bucket]
        buy = discord.ui.Button(
            label="공동 코인으로 구매",
            style=discord.ButtonStyle.success,
            disabled=self.selected_item is None or owned,
            row=1,
        )
        refresh = discord.ui.Button(label="새로고침", row=1)
        close = discord.ui.Button(label="닫기", row=1)
        buy.callback = self.buy
        refresh.callback = self.refresh
        close.callback = self.close
        self.add_item(buy)
        self.add_item(refresh)
        self.add_item(close)

    def get_embed(self, notice: str | None = None):
        if not self.session:
            return discord.Embed(title="🛍️ 시즌 상점", description="카페를 찾지 못했습니다.")
        state = self.session["state"]
        lines = []
        for key in self._items():
            bucket, item = _decor_item(key)
            owned = "✅" if key in state["decor_collection"][bucket] else "▫️"
            extra = item.get("description") or (
                f"{DECOR_THEMES[item['theme']]} · {DECOR_SLOTS[item['slot']]}"
            )
            lines.append(
                f"{owned} **{item['name']}** · {DECOR_RARITY_LABELS[item['rarity']]} "
                f"{DECOR_PRICES[item['rarity']]}코인\n{extra}"
            )
        embed = discord.Embed(
            title=f"🛍️ 시즌 {int(self.session.get('season_no', 1))} 인테리어 상점",
            description="\n".join(lines) or "판매 중인 상품이 없습니다.",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="공동 인테리어 코인",
            value=f"**{int(self.session.get('decor_tokens', 0))}개** · 다음 결산 전까지 목록 고정",
            inline=False,
        )
        if notice:
            embed.add_field(name="구매 결과", value=notice, inline=False)
        return embed

    async def choose(self, interaction):
        self.selected_item = interaction.data["values"][0]
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def buy(self, interaction):
        await interaction.response.defer()
        ok, message = await purchase_decor(
            interaction.user.display_name,
            interaction.user.id,
            self.session_id,
            str(self.selected_item),
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)

    async def refresh(self, interaction):
        await interaction.response.defer()
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def close(self, interaction):
        await interaction.response.edit_message(content="시즌 상점 창을 닫았습니다.", embed=None, view=None)


class CafeTycoonIdleView(_CafeTycoonFreeView):
    def __init__(self, author, session_id: int, public_message=None):
        super().__init__(author, session_id)
        self.public_message = public_message
        self.target_user_id: int | None = None

    def _targets(self):
        return [
            row for row in self.members
            if int(row["user_id"]) != int(self.author.id)
            and int(row.get("participating", 0))
            and not int(row["ready"])
        ]

    def rebuild(self):
        self.clear_items()
        targets = self._targets()
        ids = {int(row["user_id"]) for row in targets}
        if self.target_user_id not in ids:
            self.target_user_id = int(targets[0]["user_id"]) if targets else None
        if targets:
            select = discord.ui.Select(
                placeholder="자리 비움 확인 대상",
                row=0,
                options=[
                    discord.SelectOption(
                        label=row["user_name"],
                        value=str(row["user_id"]),
                        description="30분 이상 미행동일 때만 처리 가능",
                        default=int(row["user_id"]) == self.target_user_id,
                    )
                    for row in targets
                ],
            )
            select.callback = self.choose
            self.add_item(select)
        release = discord.ui.Button(
            label="자리 비움 처리",
            style=discord.ButtonStyle.danger,
            disabled=self.target_user_id is None,
            row=1,
        )
        close = discord.ui.Button(label="닫기", row=1)
        release.callback = self.release
        close.callback = self.close
        self.add_item(release)
        self.add_item(close)

    def get_embed(self, notice: str | None = None):
        lines = [
            f"• {row['user_name']} · 남은 행동 {int(row['actions_left'])}"
            for row in self._targets()
        ]
        embed = discord.Embed(
            title="🕒 자리 비움 처리",
            description=(
                "\n".join(lines)
                or "현재 사이클을 막고 있는 미완료 참여자가 없습니다."
            ),
            color=discord.Color.orange(),
        )
        embed.set_footer(text="마지막 행동 후 30분이 지난 참여자만 남은 행동을 정리할 수 있습니다.")
        if notice:
            embed.add_field(name="처리 결과", value=notice, inline=False)
        return embed

    async def choose(self, interaction):
        self.target_user_id = int(interaction.data["values"][0])
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def release(self, interaction):
        await interaction.response.defer()
        ok, message, _ = await release_idle_member(
            interaction.user.id, self.session_id, int(self.target_user_id or 0)
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok and self.public_message:
            try:
                session, members = await get_session(self.session_id)
                view = CafeTycoonSessionView(self.session_id)
                view.rebuild(session, members)
                await self.public_message.edit(embed=_status_embed(session, members), view=view)
            except (discord.NotFound, discord.HTTPException):
                pass

    async def close(self, interaction):
        await interaction.response.edit_message(content="자리 비움 창을 닫았습니다.", embed=None, view=None)


class CafeTycoonSeasonHistoryView(_CafeTycoonFreeView):
    def __init__(self, author, session_id: int):
        super().__init__(author, session_id)
        self.rewards: list[dict[str, Any]] = []
        self.selected_season_id: int | None = None

    async def load(self):
        self.session, self.members = await get_session(self.session_id)
        self.rewards = await list_season_rewards(self.session_id, self.author.id)
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        ids = {int(row["id"]) for row in self.rewards}
        if self.selected_season_id not in ids:
            pending = next((row for row in self.rewards if not int(row["claimed"])), None)
            row = pending or (self.rewards[0] if self.rewards else None)
            self.selected_season_id = int(row["id"]) if row else None
        if self.rewards:
            select = discord.ui.Select(
                placeholder="시즌 기록 선택",
                row=0,
                options=[
                    discord.SelectOption(
                        label=f"시즌 {int(row['season_no'])} · {int(row['score']):,}점",
                        value=str(row["id"]),
                        description=(
                            "수령 완료" if int(row["claimed"]) else "정산 보상 미수령"
                        ),
                        default=int(row["id"]) == self.selected_season_id,
                    )
                    for row in self.rewards[:25]
                ],
            )
            select.callback = self.choose
            self.add_item(select)
        selected = next(
            (row for row in self.rewards if int(row["id"]) == self.selected_season_id),
            None,
        )
        claim = discord.ui.Button(
            label="선택 시즌 정산 받기",
            style=discord.ButtonStyle.success,
            disabled=selected is None or bool(int(selected["claimed"])),
            row=1,
        )
        close = discord.ui.Button(label="닫기", row=1)
        claim.callback = self.claim
        close.callback = self.close
        self.add_item(claim)
        self.add_item(close)

    def get_embed(self):
        lines = [
            (
                f"{'✅' if int(row['claimed']) else '🎁'} **시즌 {int(row['season_no'])}** · "
                f"점수 {int(row['score']):,} · 명성 {int(row['reputation'])}"
            )
            for row in self.rewards
        ]
        return discord.Embed(
            title="📜 카페 시즌 기록",
            description="\n".join(lines) or "아직 완료한 시즌이 없습니다.",
            color=discord.Color.blurple(),
        )

    async def choose(self, interaction):
        self.selected_season_id = int(interaction.data["values"][0])
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def claim(self, interaction):
        reward = next(
            (row for row in self.rewards if int(row["id"]) == self.selected_season_id),
            None,
        )
        if not reward:
            return await interaction.response.send_message("시즌 기록을 선택하세요.", ephemeral=True)
        view = CafeTycoonSeasonSettlementView(
            self.author, self.session_id, reward
        )
        await interaction.response.edit_message(
            embed=view.get_embed(), view=view
        )

    async def close(self, interaction):
        await interaction.response.edit_message(content="시즌 기록 창을 닫았습니다.", embed=None, view=None)


class CafeTycoonSeasonSettlementView(discord.ui.View):
    def __init__(self, author, session_id: int, reward: dict[str, Any]):
        super().__init__(timeout=300)
        self.author = author
        self.session_id = int(session_id)
        self.reward = reward
        self.season_id = int(reward["id"])
        self.choices: list[str] = []
        self.candidates = settlement_reward_candidates(self.season_id, author.id)
        select = discord.ui.Select(
            placeholder="받을 희귀 재료 2종 선택",
            min_values=2,
            max_values=2,
            options=[
                discord.SelectOption(label=item, value=item)
                for item in self.candidates
            ],
            row=0,
        )
        select.callback = self.choose
        self.add_item(select)
        claim = discord.ui.Button(
            label="정산 확정", style=discord.ButtonStyle.success, row=1
        )
        claim.callback = self.claim
        self.add_item(claim)

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 정산만 받을 수 있습니다.", ephemeral=True)
        return False

    def get_embed(self):
        return discord.Embed(
            title=f"🏪 시즌 {int(self.reward['season_no'])} 정산",
            description=(
                f"점수 **{int(self.reward['score']):,}** · 명성 **{int(self.reward['reputation'])}**\n"
                f"**{int(self.reward['reward_money']):,}원 · "
                f"{int(self.reward['reward_points']):,}pt · "
                f"희귀 재료 {int(self.reward['reward_rare_total'])}개**\n\n"
                "고정 후보 중 서로 다른 재료 2종을 선택하세요."
            ),
            color=discord.Color.gold(),
        )

    async def choose(self, interaction):
        self.choices = list(interaction.data["values"])
        await interaction.response.edit_message(
            content="선택: " + ", ".join(self.choices), embed=self.get_embed(), view=self
        )

    async def claim(self, interaction):
        await interaction.response.defer()
        ok, message = await claim_season_reward(
            interaction.user.id, self.season_id, self.choices
        )
        if ok:
            await interaction.edit_original_response(
                content="✅ " + message, embed=None, view=None
            )
        else:
            await interaction.edit_original_response(
                content="❌ " + message, embed=self.get_embed(), view=self
            )


class CafeTycoonSettlementView(discord.ui.View):
    def __init__(self, author, session_id: int, public_message=None):
        super().__init__(timeout=300)
        self.author = author
        self.session_id = int(session_id)
        self.public_message = public_message
        self.choices: list[str] = []
        self.candidates = settlement_reward_candidates(session_id, author.id)
        select = discord.ui.Select(
            placeholder="받을 희귀 재료 2종 선택",
            min_values=2,
            max_values=2,
            options=[
                discord.SelectOption(
                    label=item,
                    value=item,
                    description=(
                        f"희귀 재료 · 기준가 "
                        f"{int(ITEM_CATEGORIES.get(item, {}).get('price', 0)):,}원"
                    ),
                )
                for item in self.candidates
            ],
        )
        select.callback = self.choose
        self.add_item(select)

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 정산만 받을 수 있습니다.", ephemeral=True)
        return False

    def get_embed(self, score: int):
        money, points, total = settlement_amounts(score)
        return discord.Embed(
            title="🏪 카페 타이쿤 정산",
            description=(
                f"최종 점수: **{score:,}점**\n"
                f"예상 보상: **{money:,}원 · {points:,}pt · 희귀 재료 총 {total}개**\n\n"
                "무작위로 제시된 희귀 재료 8종 중 서로 다른 2종을 선택하세요.\n"
                "후보는 화면을 다시 열어도 바뀌지 않습니다."
            ),
            color=discord.Color.gold(),
        )

    async def choose(self, interaction):
        self.choices = list(interaction.data["values"])
        await interaction.response.edit_message(
            content="선택: " + ", ".join(self.choices),
            view=self,
        )

    @discord.ui.button(label="정산 확정", style=discord.ButtonStyle.success, row=1)
    async def claim(self, interaction, button):
        await interaction.response.defer()
        ok, message = await claim_settlement(
            interaction.user.id,
            self.session_id,
            self.choices,
        )
        if ok:
            await interaction.edit_original_response(
                content="✅ " + message,
                embed=None,
                view=None,
            )
            if self.public_message:
                try:
                    session, members = await get_session(self.session_id)
                    if session:
                        view = CafeTycoonSessionView(self.session_id)
                        view.rebuild(session, members)
                        await self.public_message.edit(
                            embed=_status_embed(session, members),
                            view=view,
                        )
                except (discord.NotFound, discord.HTTPException):
                    pass
        else:
            await interaction.edit_original_response(content="❌ " + message, view=self)
