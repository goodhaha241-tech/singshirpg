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


MIN_PLAYERS = 2
MAX_PLAYERS = 4
LOBBIES_PER_PAGE = 8
RARE_REWARDS = (
    "형상각인기",
    "생명의 정수",
    "천년얼음",
    "악몽 파편",
    "중급 마력석",
    "상급 마력석",
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
_schema_lock = asyncio.Lock()
_schema_ready = False


def _loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _default_state() -> dict[str, Any]:
    state = {
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
        # v9.3 초기안의 메뉴 지정 주문도 카테고리 주문으로 안전하게 변환한다.
        order.pop("recipe", None)
        order.pop("cash", None)
        order.pop("score", None)
    state.setdefault("next_order_id", 1)
    state.setdefault("served", 0)
    state.setdefault("manual_products", 0)
    state.setdefault("log", [])
    return state


def _action_cap(state: dict[str, Any]) -> int:
    return 2 + max(0, min(3, int(state["machines"].get("lounge", 0))))


def _add_log(state: dict[str, Any], message: str) -> None:
    log = state.setdefault("log", [])
    log.append(message)
    del log[:-8]


def _new_order(state: dict[str, Any]) -> dict[str, Any]:
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
        "quantity": quantity,
    }
    state["next_order_id"] = order["id"] + 1
    return order


def _fill_orders(state: dict[str, Any], target: int = 4) -> None:
    orders = state.setdefault("orders", [])
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
) -> tuple[bool, int, int, str]:
    order = next(
        (item for item in state.get("orders", []) if int(item["id"]) == int(order_id)),
        None,
    )
    if not order:
        return False, 0, 0, "주문을 찾지 못했습니다."
    kind = order["kind"]
    quantity = int(order["quantity"])
    compatible = [
        name for name in state.get("unlocked_recipes", [])
        if RECIPE_CATALOG.get(name, {}).get("kind") == kind
    ]
    if recipe_name is None:
        # 자동 서빙은 조건을 만족하는 메뉴 중 가장 싼 것을 먼저 사용한다.
        recipe_name = next(
            (
                name for name in sorted(
                    compatible, key=lambda item: int(RECIPE_CATALOG[item]["price"])
                )
                if int(state["products"].get(name, 0)) >= quantity
            ),
            None,
        )
    if recipe_name not in compatible:
        return False, 0, 0, f"{PRODUCT_LABELS[kind]} 카테고리의 메뉴를 선택하세요."
    if int(state["products"].get(recipe_name, 0)) < quantity:
        return (
            False,
            0,
            0,
            f"{recipe_name} 재고가 부족합니다. "
            f"({int(state['products'].get(recipe_name, 0))}/{quantity})",
        )
    state["products"][recipe_name] -= quantity
    state["orders"].remove(order)
    state["served"] = int(state.get("served", 0)) + 1
    recipe = RECIPE_CATALOG[recipe_name]
    earned_cash = int(recipe["price"]) * quantity
    earned_score = int(recipe["score"]) * quantity
    return (
        True,
        earned_cash,
        earned_score,
        (
            f"{PRODUCT_LABELS[kind]} 주문에 {recipe_name} {quantity}개를 납품해 "
            f"{earned_cash:,}원과 {earned_score}점을 얻었습니다."
        ),
    )


def _resolve_automatic_turn(state: dict[str, Any]) -> tuple[int, int, list[str]]:
    machines = state["machines"]
    score = 0
    cash = 0
    notes = []
    drinks = _make_product(state, "drink", max(0, int(machines["coffee"]) - 1))
    foods = _make_product(state, "food", max(0, int(machines["oven"]) - 1))
    desserts = _make_product(state, "dessert", max(0, int(machines["display"])))
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
    for _ in range(max(0, int(machines["service"]))):
        order = next(
            (
                item
                for item in state.get("orders", [])
                if any(
                    RECIPE_CATALOG.get(name, {}).get("kind") == item["kind"]
                    and int(state["products"].get(name, 0)) >= int(item["quantity"])
                    for name in state.get("unlocked_recipes", [])
                )
            ),
            None,
        )
        if not order:
            break
        ok, earned_cash, earned_score, _ = _serve_order(state, int(order["id"]))
        if ok:
            served += 1
            cash += earned_cash
            score += earned_score
    if served:
        notes.append(f"자동 서빙 벨이 주문 {served}건 처리")
    _fill_orders(state, 4)
    return cash, score, notes


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
                         AND table_name IN ('cafe_tycoon_sessions','cafe_tycoon_members')"""
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
                cap = _action_cap(state)
                await cur.execute(
                    "UPDATE cafe_tycoon_sessions SET status='running',turn_no=1 WHERE id=%s",
                    (int(session_id),),
                )
                await cur.execute(
                    """UPDATE cafe_tycoon_members
                       SET actions_left=%s,ready=0,end_vote=0
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


async def perform_action(
    user,
    session_id: int,
    action: str,
    *,
    order_id: int | None = None,
    machine: str | None = None,
    recipe_name: str | None = None,
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
                    return False, "이번 턴의 행동을 이미 마쳤습니다.", False

                cafe_cash = int(session["cafe_cash"])
                score_delta = 0
                cash_delta = 0
                message = ""
                if action == "stock":
                    cost = 5_000
                    if cafe_cash < cost:
                        await conn.rollback()
                        return False, "카페 운영 자금 5,000원이 필요합니다.", False
                    cafe_cash -= cost
                    for name, count in {
                        "원두": 6, "우유": 4, "밀가루": 5, "채소": 5,
                        "감자": 4, "설탕": 4, "생선": 3, "초콜릿": 2,
                    }.items():
                        state["ingredients"][name] = int(state["ingredients"].get(name, 0)) + count
                    score_delta = 2
                    message = "재료 묶음을 구매했습니다."
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
                    score_delta = max(4, int(recipe["score"]) // 2)
                    state["manual_products"] = int(state.get("manual_products", 0)) + 1
                    message = (
                        f"{PRODUCT_LABELS[recipe['kind']]} · {recipe_name} 1개를 "
                        "직접 만들었습니다."
                    )
                elif action == "serve":
                    if order_id is None:
                        await conn.rollback()
                        return False, "처리할 주문을 선택하세요.", False
                    ok, cash_delta, score_delta, message = _serve_order(
                        state, order_id, recipe_name
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
                    cost = RESEARCH_COST[next_tier]
                    if cafe_cash < cost:
                        await conn.rollback()
                        return False, f"연구 자금 {cost:,}원이 필요합니다.", False
                    cafe_cash -= cost
                    recipe_name = random.choice(candidates)
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
                    cost = 20_000 * (current + 1) ** 2
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
                       SET actions_left=%s,ready=%s
                       WHERE session_id=%s AND user_id=%s""",
                    (max(0, actions_left), ready, int(session_id), int(user.id)),
                )
                await cur.execute(
                    """UPDATE cafe_tycoon_sessions
                       SET state_json=%s,cafe_cash=%s,score=score+%s
                       WHERE id=%s""",
                    (
                        json.dumps(state, ensure_ascii=False),
                        cafe_cash,
                        score_delta,
                        int(session_id),
                    ),
                )

                await cur.execute(
                    """SELECT user_id,ready FROM cafe_tycoon_members
                       WHERE session_id=%s ORDER BY user_id FOR UPDATE""",
                    (int(session_id),),
                )
                members = list(await cur.fetchall())
                turn_advanced = bool(members) and all(int(row["ready"]) for row in members)
                if turn_advanced:
                    auto_cash, auto_score, notes = _resolve_automatic_turn(state)
                    for note in notes:
                        _add_log(state, f"⚙️ {note}")
                    next_turn = int(session["turn_no"]) + 1
                    cap = _action_cap(state)
                    await cur.execute(
                        """UPDATE cafe_tycoon_sessions
                           SET turn_no=%s,cafe_cash=%s,score=score+%s,state_json=%s
                           WHERE id=%s""",
                        (
                            next_turn,
                            cafe_cash + auto_cash,
                            auto_score,
                            json.dumps(state, ensure_ascii=False),
                            int(session_id),
                        ),
                    )
                    await cur.execute(
                        """UPDATE cafe_tycoon_members
                           SET actions_left=%s,ready=0
                           WHERE session_id=%s""",
                        (cap, int(session_id)),
                    )
                    for row in members:
                        await cur.execute(
                            """UPDATE users
                               SET total_turns=total_turns+1,
                                   data_revision=data_revision+1
                               WHERE user_id=%s""",
                            (str(row["user_id"]),),
                        )
                    message += (
                        f"\n모두의 행동이 끝나 **{next_turn}턴**으로 넘어갔습니다. "
                        "참가자 전원의 공용 활동 턴이 1 증가했습니다."
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
                    return False, "이미 턴 종료를 선언했습니다.", False
                await cur.execute(
                    """UPDATE cafe_tycoon_members SET actions_left=0,ready=1
                       WHERE session_id=%s AND user_id=%s""",
                    (int(session_id), int(user_id)),
                )
                await cur.execute(
                    """SELECT user_id,ready FROM cafe_tycoon_members
                       WHERE session_id=%s ORDER BY user_id FOR UPDATE""",
                    (int(session_id),),
                )
                members = list(await cur.fetchall())
                advanced = bool(members) and all(int(row["ready"]) for row in members)
                if advanced:
                    auto_cash, auto_score, notes = _resolve_automatic_turn(state)
                    for note in notes:
                        _add_log(state, f"⚙️ {note}")
                    next_turn = int(session["turn_no"]) + 1
                    await cur.execute(
                        """UPDATE cafe_tycoon_sessions
                           SET turn_no=%s,cafe_cash=cafe_cash+%s,score=score+%s,state_json=%s
                           WHERE id=%s""",
                        (
                            next_turn,
                            auto_cash,
                            auto_score,
                            json.dumps(state, ensure_ascii=False),
                            int(session_id),
                        ),
                    )
                    await cur.execute(
                        """UPDATE cafe_tycoon_members SET actions_left=%s,ready=0
                           WHERE session_id=%s""",
                        (_action_cap(state), int(session_id)),
                    )
                    for row in members:
                        await cur.execute(
                            """UPDATE users
                               SET total_turns=total_turns+1,
                                   data_revision=data_revision+1
                               WHERE user_id=%s""",
                            (str(row["user_id"]),),
                        )
                    await conn.commit()
                    return (
                        True,
                        f"턴을 마쳤습니다. 모두 준비되어 **{next_turn}턴**으로 넘어갑니다.",
                        True,
                    )
                await conn.commit()
                return True, "남은 행동을 포기하고 다른 참가자를 기다립니다.", False
            except Exception as exc:
                await conn.rollback()
                return False, f"턴 종료 오류: {exc}", False


async def vote_to_end(user_id: int, session_id: int) -> tuple[bool, str, bool]:
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
                if not session or session["status"] != "running":
                    await conn.rollback()
                    return False, "종료 투표를 할 수 없는 상태입니다.", False
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
                unanimous = total > 0 and votes == total
                if unanimous:
                    await cur.execute(
                        "UPDATE cafe_tycoon_sessions SET status='settling' WHERE id=%s",
                        (int(session_id),),
                    )
                    message = "전원이 동의하여 영업을 종료했습니다. 희귀 재료 2종을 선택해 정산하세요."
                else:
                    message = f"종료에 동의했습니다. ({votes}/{total})"
                await conn.commit()
                return True, message, unanimous
            except Exception as exc:
                await conn.rollback()
                return False, f"종료 투표 오류: {exc}", False


def settlement_amounts(score: int) -> tuple[int, int, int]:
    score = max(0, int(score))
    money = 200_000 + score * 1_500
    points = 8_000 + score * 50
    rare_total = min(60, max(2, 2 + score // 120))
    return money, points, rare_total


async def claim_settlement(
    user_id: int,
    session_id: int,
    choices: list[str],
) -> tuple[bool, str]:
    choices = list(dict.fromkeys(choices))
    if len(choices) != 2 or any(item not in RARE_REWARDS for item in choices):
        return False, "서로 다른 희귀 재료 2종을 선택하세요."
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


def _status_embed(session: dict[str, Any], members: list[dict[str, Any]]) -> discord.Embed:
    state = session["state"]
    status = session["status"]
    title_status = {"lobby": "참가 대기", "running": "영업 중", "settling": "정산 중"}.get(status, status)
    embed = discord.Embed(
        title=f"🏪 카페 타이쿤 #{session['id']} · {title_status}",
        description=(
            f"방장: **{session['host_name']}** · 참가자 {len(members)}/{MAX_PLAYERS}\n"
            f"턴 **{int(session['turn_no'])}** · 점수 **{int(session['score']):,}** · "
            f"운영 자금 **{int(session['cafe_cash']):,}원**"
        ),
        color=discord.Color.orange(),
    )
    if status != "lobby":
        ingredients = " · ".join(
            f"{name} {count}" for name, count in state["ingredients"].items()
        )
        product_totals = {
            kind: sum(
                int(state["products"].get(name, 0))
                for name, recipe in RECIPE_CATALOG.items()
                if recipe["kind"] == kind
            )
            for kind in PRODUCT_LABELS
        }
        products = " · ".join(
            f"{label} {product_totals[kind]}"
            for kind, label in PRODUCT_LABELS.items()
        )
        machines = " · ".join(
            f"{MACHINE_LABELS[key]} Lv.{int(value)}"
            for key, value in state["machines"].items()
        )
        order_lines = [
            f"#{item['id']} {PRODUCT_LABELS[item['kind']]} ×{item['quantity']} "
            "→ 납품 메뉴에 따라 보상 결정"
            for item in state.get("orders", [])
        ]
        embed.add_field(name="공용 재료", value=ingredients, inline=False)
        embed.add_field(name="완제품", value=products, inline=False)
        embed.add_field(name="보조 기기", value=machines, inline=False)
        embed.add_field(
            name="주문",
            value="\n".join(order_lines) or "대기 주문 없음",
            inline=False,
        )
    member_lines = []
    for member in members:
        if status == "lobby":
            flag = " 👑" if int(member["user_id"]) == int(session["host_id"]) else ""
        elif status == "running":
            flag = (
                f" · 행동 {int(member['actions_left'])}"
                + (" · 턴 완료" if int(member["ready"]) else "")
                + (" · 종료 동의" if int(member["end_vote"]) else "")
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
            text="모두 행동을 마치면 카페 턴과 각 참가자의 공용 활동 턴이 1씩 진행됩니다."
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
                "2~4명이 함께 운영하는 무제한 턴제 카페입니다.\n"
                "각자 정해진 행동 수를 사용하고, 모두 마치면 한 턴이 진행됩니다.\n"
                "기기를 강화해 자동 제작·서빙을 구축하고 전원 동의로 정산하세요."
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
            work = discord.ui.Button(label="내 작업창", style=discord.ButtonStyle.success, row=0)
            vote = discord.ui.Button(label="영업 종료 동의", style=discord.ButtonStyle.danger, row=0)
            work.callback = self.work
            vote.callback = self.vote
            self.add_item(work)
            self.add_item(vote)
        elif status == "settling":
            settle = discord.ui.Button(label="내 정산 받기", style=discord.ButtonStyle.success, row=0)
            settle.callback = self.settle
            self.add_item(settle)
        refresh = discord.ui.Button(label="새로고침", style=discord.ButtonStyle.secondary, row=1)
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
            label="이번 턴 마치기",
            style=discord.ButtonStyle.danger,
            disabled=int(self.member["ready"]),
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
            title=f"🏪 내 작업창 · {int(self.session['turn_no'])}턴",
            description=(
                f"남은 행동: **{int(self.member['actions_left'])}/{_action_cap(state)}**\n"
                f"카페 자금: **{int(self.session['cafe_cash']):,}원** · "
                f"점수: **{int(self.session['score']):,}**"
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
                            f"#{order['id']} {PRODUCT_LABELS[order['kind']]} "
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
                        label=f"{name} · 재고 {int(state['products'].get(name, 0))}",
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
        previous = discord.ui.Button(
            label="◀", style=discord.ButtonStyle.secondary,
            disabled=self.page <= 0, row=2,
        )
        following = discord.ui.Button(
            label="▶", style=discord.ButtonStyle.secondary,
            disabled=self.page >= pages - 1, row=2,
        )
        deliver = discord.ui.Button(
            label="선택 주문 납품", style=discord.ButtonStyle.success,
            disabled=(
                self.disabled
                or self.selected_order_id is None
                or self.selected_recipe is None
            ),
            row=2,
        )
        previous.callback = self.previous
        following.callback = self.following
        deliver.callback = self.deliver
        self.add_item(previous)
        self.add_item(following)
        self.add_item(deliver)
        back = discord.ui.Button(label="작업창", style=discord.ButtonStyle.secondary, row=3)
        refresh = discord.ui.Button(label="새로고침", style=discord.ButtonStyle.secondary, row=3)
        back.callback = self.back
        refresh.callback = self.refresh
        self.add_item(back)
        self.add_item(refresh)

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
            ready = "✅" if any(
                int(state["products"].get(name, 0)) >= int(order["quantity"])
                for name in compatible
            ) else "❌"
            marker = "▶ " if int(order["id"]) == self.selected_order_id else ""
            lines.append(
                f"{marker}{ready} **#{order['id']} {PRODUCT_LABELS[order['kind']]} "
                f"×{order['quantity']}** · 같은 카테고리 메뉴 납품"
            )
        embed = discord.Embed(
            title=f"📦 카페 납품 · {self.page + 1}/{pages}",
            description="\n".join(lines) or "대기 중인 주문이 없습니다.",
            color=discord.Color.blurple(),
        )
        order = self._selected_order()
        if order and self.selected_recipe:
            recipe = RECIPE_CATALOG[self.selected_recipe]
            quantity = int(order["quantity"])
            embed.add_field(
                name="선택한 납품",
                value=(
                    f"**{self.selected_recipe} ×{quantity}** · "
                    f"재고 {int(state['products'].get(self.selected_recipe, 0))}/{quantity}\n"
                    f"예상 보상: {int(recipe['price']) * quantity:,}원 · "
                    f"{int(recipe['score']) * quantity}점"
                ),
                inline=False,
            )
        if notice:
            embed.add_field(name="납품 결과", value=notice, inline=False)
        return embed

    async def choose(self, interaction):
        self.selected_order_id = int(interaction.data["values"][0])
        self.selected_recipe = None
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def choose_recipe(self, interaction):
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

    async def deliver(self, interaction):
        await interaction.response.defer()
        ok, message, _ = await perform_action(
            interaction.user, self.session_id, "serve",
            order_id=self.selected_order_id,
            recipe_name=self.selected_recipe,
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
            effect = "턴당 행동 수 증가"
        elif key == "service":
            effect = "턴 종료 시 주문 자동 납품"
        elif key == "display":
            effect = "턴 종료 시 디저트 자동 제조"
        elif key == "coffee":
            effect = "턴 종료 시 음료 자동 제조"
        else:
            effect = "턴 종료 시 음식 자동 제조"
        if level >= MACHINE_MAX[key]:
            return f"{effect} · 최대 강화"
        return f"{effect} · 다음 비용 {20_000 * (level + 1) ** 2:,}원"

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
    def rebuild(self):
        self.clear_items()
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
        back = discord.ui.Button(label="작업창", style=discord.ButtonStyle.secondary, row=1)
        refresh = discord.ui.Button(label="새로고침", style=discord.ButtonStyle.secondary, row=1)
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
                text = (
                    f"다음 단계 {next_tier} · 비용 {RESEARCH_COST[next_tier]:,}원\n"
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


class CafeTycoonSettlementView(discord.ui.View):
    def __init__(self, author, session_id: int, public_message=None):
        super().__init__(timeout=300)
        self.author = author
        self.session_id = int(session_id)
        self.public_message = public_message
        self.choices: list[str] = []
        select = discord.ui.Select(
            placeholder="받을 희귀 재료 2종 선택",
            min_values=2,
            max_values=2,
            options=[discord.SelectOption(label=item, value=item) for item in RARE_REWARDS],
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
                "서로 다른 희귀 재료 2종을 선택한 뒤 정산을 확정하세요."
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
