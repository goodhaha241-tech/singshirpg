# cafe-tycoon-v9.2
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
    "service": "자동 서빙 벨",
    "lounge": "직원 휴게실",
}
MACHINE_MAX = {"coffee": 4, "oven": 4, "service": 3, "lounge": 3}
PRODUCT_LABELS = {"drink": "음료", "food": "음식"}
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
        "ingredients": {"원두": 10, "우유": 8, "밀가루": 8, "채소": 8},
        "products": {"drink": 0, "food": 0},
        "machines": {"coffee": 1, "oven": 1, "service": 0, "lounge": 0},
        "orders": [],
        "next_order_id": 1,
        "served": 0,
        "manual_products": 0,
        "log": ["작은 카페의 문을 열 준비를 마쳤습니다."],
    }
    _fill_orders(state, 3)
    return state


def _action_cap(state: dict[str, Any]) -> int:
    return 2 + max(0, min(3, int(state["machines"].get("lounge", 0))))


def _add_log(state: dict[str, Any], message: str) -> None:
    log = state.setdefault("log", [])
    log.append(message)
    del log[:-8]


def _new_order(state: dict[str, Any]) -> dict[str, Any]:
    kind = random.choice(("drink", "food"))
    quantity = random.randint(1, 3)
    unit_cash = 8_000 if kind == "drink" else 12_000
    unit_score = 10 if kind == "drink" else 15
    order = {
        "id": int(state.get("next_order_id", 1)),
        "kind": kind,
        "quantity": quantity,
        "cash": unit_cash * quantity,
        "score": unit_score * quantity,
    }
    state["next_order_id"] = order["id"] + 1
    return order


def _fill_orders(state: dict[str, Any], target: int = 4) -> None:
    orders = state.setdefault("orders", [])
    while len(orders) < target:
        orders.append(_new_order(state))


def _make_product(state: dict[str, Any], kind: str, amount: int = 1) -> int:
    made = 0
    for _ in range(max(0, int(amount))):
        if kind == "drink":
            required = {"원두": 2, "우유": 1}
        else:
            required = {"밀가루": 2, "채소": 2}
        if any(int(state["ingredients"].get(name, 0)) < count for name, count in required.items()):
            break
        for name, count in required.items():
            state["ingredients"][name] -= count
        state["products"][kind] = int(state["products"].get(kind, 0)) + 1
        made += 1
    return made


def _serve_order(state: dict[str, Any], order_id: int) -> tuple[bool, int, int, str]:
    order = next(
        (item for item in state.get("orders", []) if int(item["id"]) == int(order_id)),
        None,
    )
    if not order:
        return False, 0, 0, "주문을 찾지 못했습니다."
    kind = order["kind"]
    quantity = int(order["quantity"])
    if int(state["products"].get(kind, 0)) < quantity:
        return (
            False,
            0,
            0,
            f"{PRODUCT_LABELS[kind]}이 부족합니다. "
            f"({int(state['products'].get(kind, 0))}/{quantity})",
        )
    state["products"][kind] -= quantity
    state["orders"].remove(order)
    state["served"] = int(state.get("served", 0)) + 1
    return (
        True,
        int(order["cash"]),
        int(order["score"]),
        f"{PRODUCT_LABELS[kind]} {quantity}개 주문을 처리했습니다.",
    )


def _resolve_automatic_turn(state: dict[str, Any]) -> tuple[int, int, list[str]]:
    machines = state["machines"]
    score = 0
    cash = 0
    notes = []
    drinks = _make_product(state, "drink", max(0, int(machines["coffee"]) - 1))
    foods = _make_product(state, "food", max(0, int(machines["oven"]) - 1))
    if drinks:
        score += drinks * 3
        notes.append(f"커피 머신이 음료 {drinks}개 자동 제작")
    if foods:
        score += foods * 4
        notes.append(f"오븐이 음식 {foods}개 자동 제작")

    served = 0
    for _ in range(max(0, int(machines["service"]))):
        order = next(
            (
                item
                for item in state.get("orders", [])
                if int(state["products"].get(item["kind"], 0)) >= int(item["quantity"])
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
            session["state"] = _loads(session.pop("state_json"), _default_state())
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
                state = _loads(session["state_json"], _default_state())
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
    return session, member, _loads(session["state_json"], _default_state())


async def perform_action(
    user,
    session_id: int,
    action: str,
    *,
    order_id: int | None = None,
    machine: str | None = None,
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
                    for name, count in {"원두": 6, "우유": 4, "밀가루": 5, "채소": 5}.items():
                        state["ingredients"][name] = int(state["ingredients"].get(name, 0)) + count
                    score_delta = 2
                    message = "재료 묶음을 구매했습니다."
                elif action in {"drink", "food"}:
                    made = _make_product(state, action, 1)
                    if not made:
                        await conn.rollback()
                        needs = "원두 2·우유 1" if action == "drink" else "밀가루 2·채소 2"
                        return False, f"재료가 부족합니다. 필요: {needs}", False
                    score_delta = 6 if action == "drink" else 9
                    state["manual_products"] = int(state.get("manual_products", 0)) + 1
                    message = f"{PRODUCT_LABELS[action]} 1개를 직접 만들었습니다."
                elif action == "serve":
                    if order_id is None:
                        await conn.rollback()
                        return False, "처리할 주문을 선택하세요.", False
                    ok, cash_delta, score_delta, message = _serve_order(state, order_id)
                    if not ok:
                        await conn.rollback()
                        return False, message, False
                    cafe_cash += cash_delta
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
        products = (
            f"음료 {int(state['products'].get('drink', 0))} · "
            f"음식 {int(state['products'].get('food', 0))}"
        )
        machines = " · ".join(
            f"{MACHINE_LABELS[key]} Lv.{int(value)}"
            for key, value in state["machines"].items()
        )
        order_lines = [
            f"#{item['id']} {PRODUCT_LABELS[item['kind']]} ×{item['quantity']} "
            f"→ {int(item['cash']):,}원 / {int(item['score'])}점"
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
        self.selected_order_id = None
        self.selected_machine = "coffee"

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
        orders = self.session["state"].get("orders", []) if self.session else []
        if self.selected_order_id not in {int(row["id"]) for row in orders}:
            self.selected_order_id = int(orders[0]["id"]) if orders else None
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        if not self.session or self.session["status"] != "running" or not self.member:
            close = discord.ui.Button(label="닫기", style=discord.ButtonStyle.secondary)
            close.callback = self.close
            self.add_item(close)
            return
        state = self.session["state"]
        orders = state.get("orders", [])
        if orders:
            order_select = discord.ui.Select(
                placeholder="처리할 주문 선택",
                row=0,
                options=[
                    discord.SelectOption(
                        label=f"#{row['id']} {PRODUCT_LABELS[row['kind']]} ×{row['quantity']}",
                        value=str(row["id"]),
                        description=f"{int(row['cash']):,}원 · {int(row['score'])}점",
                        default=int(row["id"]) == self.selected_order_id,
                    )
                    for row in orders[:25]
                ],
            )
            order_select.callback = self.choose_order
            self.add_item(order_select)
        machine_select = discord.ui.Select(
            placeholder="강화할 보조 기기 선택",
            row=1,
            options=[
                discord.SelectOption(
                    label=f"{label} Lv.{int(state['machines'].get(key, 0))}",
                    value=key,
                    description=(
                        "다음 턴 행동 수 증가"
                        if key == "lounge"
                        else "턴 종료 시 자동 제작·서빙"
                    ),
                    default=key == self.selected_machine,
                )
                for key, label in MACHINE_LABELS.items()
            ],
        )
        machine_select.callback = self.choose_machine
        self.add_item(machine_select)
        disabled = int(self.member["ready"]) or int(self.member["actions_left"]) <= 0
        buttons = (
            ("재료 구매", "stock"),
            ("음료 만들기", "drink"),
            ("음식 만들기", "food"),
            ("주문 처리", "serve"),
        )
        for label, action in buttons:
            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary,
                disabled=disabled or (action == "serve" and self.selected_order_id is None),
                row=2,
            )

            async def callback(interaction, selected_action=action):
                await self.do_action(interaction, selected_action)

            button.callback = callback
            self.add_item(button)
        upgrade = discord.ui.Button(
            label="선택 기기 강화",
            style=discord.ButtonStyle.success,
            disabled=disabled,
            row=3,
        )
        finish = discord.ui.Button(
            label="이번 턴 마치기",
            style=discord.ButtonStyle.danger,
            disabled=int(self.member["ready"]),
            row=3,
        )
        refresh = discord.ui.Button(label="새로고침", style=discord.ButtonStyle.secondary, row=3)
        close = discord.ui.Button(label="닫기", style=discord.ButtonStyle.secondary, row=3)
        upgrade.callback = self.upgrade
        finish.callback = self.finish
        refresh.callback = self.refresh
        close.callback = self.close
        self.add_item(upgrade)
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
            value=(
                f"음료 {int(state['products'].get('drink', 0))} · "
                f"음식 {int(state['products'].get('food', 0))}"
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

    async def choose_order(self, interaction):
        self.selected_order_id = int(interaction.data["values"][0])
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def choose_machine(self, interaction):
        self.selected_machine = interaction.data["values"][0]
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def do_action(self, interaction, action):
        await interaction.response.defer()
        ok, message, _ = await perform_action(
            interaction.user,
            self.session_id,
            action,
            order_id=self.selected_order_id,
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok:
            await self._refresh_public()

    async def upgrade(self, interaction):
        await interaction.response.defer()
        ok, message, _ = await perform_action(
            interaction.user,
            self.session_id,
            "upgrade",
            machine=self.selected_machine,
        )
        await self.load()
        await interaction.edit_original_response(embed=self.get_embed(message), view=self)
        if ok:
            await self._refresh_public()

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
