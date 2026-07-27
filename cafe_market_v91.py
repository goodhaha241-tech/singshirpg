# cafe-guild-market-v9.1
"""Inventory-backed café marketplace with sale listings and purchase requests."""

from __future__ import annotations

import json
import uuid
from typing import Any

import aiomysql
import discord

from data_manager import get_db_pool, get_user_data
from items import COMMON_ITEMS, ITEM_CATEGORIES, RARE_ITEMS
from life_system import FINGERLING_ITEMS, SEED_ITEMS, STONE_GEMS, ensure_life_data


PER_PAGE = 8
VALID_CURRENCIES = {"money": "원", "pt": "pt"}


def _loads(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _equipped_gem_ids(user_data: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    artifacts = list(user_data.get("artifacts", []))
    for character in user_data.get("characters", []):
        for key in ("equipped_artifact", "equipped_engraved_artifact"):
            artifact = character.get(key)
            if isinstance(artifact, dict):
                artifacts.append(artifact)
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        for gem in artifact.get("gems", []):
            if isinstance(gem, dict) and gem.get("id") is not None:
                result.add(str(gem["id"]))
    return result


def available_gems(user_data: dict[str, Any], name: str | None = None):
    equipped = _equipped_gem_ids(user_data)
    return [
        gem
        for gem in ensure_life_data(user_data).get("gems", [])
        if isinstance(gem, dict)
        and str(gem.get("id")) not in equipped
        and (name is None or gem.get("name") == name)
    ]


def gem_label(gem: dict[str, Any]) -> str:
    return f"{'★' * int(gem.get('stars', 0) or 0) or '☆'} {gem.get('name', '젬')}"


def request_catalog() -> list[tuple[str, str]]:
    items = {
        *COMMON_ITEMS,
        *RARE_ITEMS,
        *ITEM_CATEGORIES,
        *SEED_ITEMS.values(),
        *FINGERLING_ITEMS.values(),
        "원석",
        "순수한 희망",
    }
    gems = {
        definition["name"]
        for definitions in STONE_GEMS.values()
        for definition in definitions
    }
    return [
        *(("item", name) for name in sorted(items)),
        *(("stone", name) for name in sorted(STONE_GEMS)),
        *(("gem", name) for name in sorted(gems)),
    ]


async def ensure_market_schema() -> None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SHOW COLUMNS FROM global_trades")
            columns = {row["Field"] for row in await cur.fetchall()}
            if "asset_type" not in columns:
                await cur.execute(
                    "ALTER TABLE global_trades ADD COLUMN asset_type VARCHAR(20) NOT NULL DEFAULT 'item'"
                )
            if "asset_data" not in columns:
                await cur.execute("ALTER TABLE global_trades ADD COLUMN asset_data JSON NULL")
            await cur.execute(
                """SELECT 1 FROM information_schema.tables
                   WHERE table_schema=DATABASE()
                     AND table_name='global_purchase_requests' LIMIT 1"""
            )
            if not await cur.fetchone():
                await cur.execute(
                    """CREATE TABLE global_purchase_requests (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    buyer_id BIGINT NOT NULL,
                    buyer_name VARCHAR(100) NOT NULL,
                    asset_type VARCHAR(20) NOT NULL,
                    item_name VARCHAR(100) NOT NULL,
                    quantity INT NOT NULL,
                    price INT NOT NULL,
                    currency VARCHAR(10) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )"""
                )
            await conn.commit()


async def _life_for_update(cur, user_id: int) -> dict[str, Any]:
    await cur.execute(
        "SELECT data FROM user_life_data WHERE user_id=%s FOR UPDATE",
        (str(user_id),),
    )
    row = await cur.fetchone()
    return _loads(row["data"], {}) if row else {}


async def _save_life(cur, user_id: int, life: dict[str, Any]) -> None:
    await cur.execute(
        """INSERT INTO user_life_data (user_id,data)
           VALUES (%s,%s) AS new
           ON DUPLICATE KEY UPDATE data=new.data""",
        (str(user_id), json.dumps(life, ensure_ascii=False)),
    )


async def _db_equipped_gem_ids(cur, user_id: int) -> set[str]:
    result: set[str] = set()
    await cur.execute(
        "SELECT gems FROM artifacts WHERE user_id=%s FOR UPDATE",
        (str(user_id),),
    )
    for row in await cur.fetchall():
        for gem in _loads(row.get("gems"), []):
            if isinstance(gem, dict) and gem.get("id") is not None:
                result.add(str(gem["id"]))
    await cur.execute(
        "SELECT equipped_engraved_artifact FROM characters WHERE user_id=%s FOR UPDATE",
        (str(user_id),),
    )
    for row in await cur.fetchall():
        artifact = _loads(row.get("equipped_engraved_artifact"), {})
        if isinstance(artifact, dict):
            for gem in artifact.get("gems", []):
                if isinstance(gem, dict) and gem.get("id") is not None:
                    result.add(str(gem["id"]))
    return result


async def register_sale(
    user,
    asset_type: str,
    asset_key: str,
    quantity: int,
    price: int,
    currency: str,
):
    if currency not in VALID_CURRENCIES or quantity <= 0 or price <= 0:
        return False, "수량·가격·화폐 설정이 올바르지 않습니다."
    if asset_type == "gem" and quantity != 1:
        return False, "젬은 한 매물에 하나씩 등록할 수 있습니다."

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                payload = None
                if asset_type == "item":
                    await cur.execute(
                        """SELECT quantity FROM inventory
                           WHERE user_id=%s AND item_name=%s FOR UPDATE""",
                        (str(user.id), asset_key),
                    )
                    row = await cur.fetchone()
                    owned = int(row["quantity"]) if row else 0
                    if owned < quantity:
                        await conn.rollback()
                        return False, f"재고가 부족합니다. ({owned}/{quantity})"
                    if owned == quantity:
                        await cur.execute(
                            "DELETE FROM inventory WHERE user_id=%s AND item_name=%s",
                            (str(user.id), asset_key),
                        )
                    else:
                        await cur.execute(
                            """UPDATE inventory SET quantity=quantity-%s
                               WHERE user_id=%s AND item_name=%s""",
                            (quantity, str(user.id), asset_key),
                        )
                    item_name = asset_key
                elif asset_type in {"gem", "stone"}:
                    life = await _life_for_update(cur, user.id)
                    if asset_type == "stone":
                        stones = life.setdefault("stones", {})
                        owned = int(stones.get(asset_key, 0) or 0)
                        if owned < quantity:
                            await conn.rollback()
                            return False, f"감정된 원석이 부족합니다. ({owned}/{quantity})"
                        if owned == quantity:
                            stones.pop(asset_key, None)
                        else:
                            stones[asset_key] = owned - quantity
                        item_name = asset_key
                        await _save_life(cur, user.id, life)
                    else:
                        gems = life.setdefault("gems", [])
                        index = next(
                            (
                                index
                                for index, gem in enumerate(gems)
                                if isinstance(gem, dict) and str(gem.get("id")) == str(asset_key)
                            ),
                            None,
                        )
                        if index is None:
                            await conn.rollback()
                            return False, "판매할 젬을 찾지 못했습니다."
                        if str(asset_key) in await _db_equipped_gem_ids(cur, user.id):
                            await conn.rollback()
                            return False, "아티팩트에 장착된 젬은 판매할 수 없습니다."
                        payload = dict(gems.pop(index))
                        item_name = str(payload.get("name", "젬"))
                        await _save_life(cur, user.id, life)
                else:
                    await conn.rollback()
                    return False, "지원하지 않는 자산 종류입니다."

                await cur.execute(
                    """INSERT INTO global_trades
                       (seller_id,seller_name,item_name,quantity,price,currency,asset_type,asset_data)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        user.id,
                        user.display_name,
                        item_name,
                        quantity,
                        price,
                        currency,
                        asset_type,
                        json.dumps(payload, ensure_ascii=False) if payload else None,
                    ),
                )
                await cur.execute(
                    "UPDATE users SET data_revision=data_revision+1 WHERE user_id=%s",
                    (str(user.id),),
                )
                await conn.commit()
                return True, f"{item_name} ×{quantity} 판매 공고를 등록했습니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"판매 등록 오류: {exc}"


async def register_request(
    user,
    asset_type: str,
    item_name: str,
    quantity: int,
    price: int,
    currency: str,
):
    if currency not in VALID_CURRENCIES or quantity <= 0 or price <= 0:
        return False, "수량·가격·화폐 설정이 올바르지 않습니다."
    if asset_type == "gem" and quantity != 1:
        return False, "젬 구매 의뢰는 한 번에 하나만 등록할 수 있습니다."
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    f"SELECT {currency} AS balance FROM users WHERE user_id=%s FOR UPDATE",
                    (str(user.id),),
                )
                row = await cur.fetchone()
                if not row or int(row["balance"] or 0) < price:
                    await conn.rollback()
                    return False, f"등록 금액이 부족합니다. (필요: {price:,}{VALID_CURRENCIES[currency]})"
                await cur.execute(
                    f"""UPDATE users SET {currency}={currency}-%s,
                           data_revision=data_revision+1 WHERE user_id=%s""",
                    (price, str(user.id)),
                )
                await cur.execute(
                    """INSERT INTO global_purchase_requests
                       (buyer_id,buyer_name,asset_type,item_name,quantity,price,currency)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        user.id,
                        user.display_name,
                        asset_type,
                        item_name,
                        quantity,
                        price,
                        currency,
                    ),
                )
                await conn.commit()
                return True, f"{item_name} ×{quantity} 구매 의뢰를 등록하고 대금을 보관했습니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"구매 의뢰 등록 오류: {exc}"


async def cancel_listing(user, table: str, listing_id: int):
    if table not in {"global_trades", "global_purchase_requests"}:
        return False, "잘못된 게시판입니다."
    owner_column = "seller_id" if table == "global_trades" else "buyer_id"
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    f"SELECT * FROM {table} WHERE id=%s FOR UPDATE",
                    (listing_id,),
                )
                row = await cur.fetchone()
                if not row or str(row[owner_column]) != str(user.id):
                    await conn.rollback()
                    return False, "본인의 공고가 아니거나 이미 처리되었습니다."
                if table == "global_trades":
                    if (row.get("asset_type") or "item") == "gem":
                        life = await _life_for_update(cur, user.id)
                        payload = _loads(row.get("asset_data"), None)
                        if not isinstance(payload, dict):
                            await conn.rollback()
                            return False, "젬 매물 데이터가 손상되어 관리자 확인이 필요합니다."
                        life.setdefault("gems", []).append(payload)
                        await _save_life(cur, user.id, life)
                    elif row.get("asset_type") == "stone":
                        life = await _life_for_update(cur, user.id)
                        stones = life.setdefault("stones", {})
                        stones[row["item_name"]] = (
                            int(stones.get(row["item_name"], 0) or 0)
                            + int(row["quantity"])
                        )
                        await _save_life(cur, user.id, life)
                    else:
                        await cur.execute(
                            """INSERT INTO inventory (user_id,item_name,quantity)
                               VALUES (%s,%s,%s) AS new
                               ON DUPLICATE KEY UPDATE quantity=inventory.quantity+new.quantity""",
                            (str(user.id), row["item_name"], int(row["quantity"])),
                        )
                else:
                    currency = row["currency"]
                    if currency not in VALID_CURRENCIES:
                        await conn.rollback()
                        return False, "의뢰 화폐 정보가 올바르지 않습니다."
                    await cur.execute(
                        f"UPDATE users SET {currency}={currency}+%s WHERE user_id=%s",
                        (int(row["price"]), str(user.id)),
                    )
                await cur.execute(f"DELETE FROM {table} WHERE id=%s", (listing_id,))
                await cur.execute(
                    "UPDATE users SET data_revision=data_revision+1 WHERE user_id=%s",
                    (str(user.id),),
                )
                await conn.commit()
                return True, "공고를 취소하고 보관된 자산을 돌려받았습니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"공고 취소 오류: {exc}"


async def buy_sale(user, listing_id: int):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    "SELECT * FROM global_trades WHERE id=%s FOR UPDATE",
                    (listing_id,),
                )
                row = await cur.fetchone()
                if not row:
                    await conn.rollback()
                    return False, "이미 거래된 매물입니다."
                if str(row["seller_id"]) == str(user.id):
                    await conn.rollback()
                    return False, "본인 매물은 구매 대신 취소할 수 있습니다."
                currency = row["currency"]
                if currency not in VALID_CURRENCIES:
                    await conn.rollback()
                    return False, "지원하지 않는 화폐입니다."
                await cur.execute(
                    f"""SELECT user_id,{currency} AS balance FROM users
                        WHERE user_id IN (%s,%s) ORDER BY user_id FOR UPDATE""",
                    (str(user.id), str(row["seller_id"])),
                )
                accounts = {str(item["user_id"]): item for item in await cur.fetchall()}
                buyer = accounts.get(str(user.id))
                if not buyer or int(buyer["balance"] or 0) < int(row["price"]):
                    await conn.rollback()
                    return False, "구매 금액이 부족합니다."
                await cur.execute(
                    f"""UPDATE users SET {currency}={currency}-%s,
                           data_revision=data_revision+1 WHERE user_id=%s""",
                    (int(row["price"]), str(user.id)),
                )
                await cur.execute(
                    f"""UPDATE users SET {currency}={currency}+%s,
                           data_revision=data_revision+1 WHERE user_id=%s""",
                    (int(row["price"]), str(row["seller_id"])),
                )
                if (row.get("asset_type") or "item") == "gem":
                    life = await _life_for_update(cur, user.id)
                    payload = _loads(row.get("asset_data"), None)
                    if not isinstance(payload, dict):
                        await conn.rollback()
                        return False, "젬 매물 데이터가 손상되었습니다."
                    existing = {str(gem.get("id")) for gem in life.setdefault("gems", []) if isinstance(gem, dict)}
                    if str(payload.get("id")) in existing:
                        payload["id"] = uuid.uuid4().hex
                    life["gems"].append(payload)
                    await _save_life(cur, user.id, life)
                elif row.get("asset_type") == "stone":
                    life = await _life_for_update(cur, user.id)
                    stones = life.setdefault("stones", {})
                    stones[row["item_name"]] = (
                        int(stones.get(row["item_name"], 0) or 0)
                        + int(row["quantity"])
                    )
                    await _save_life(cur, user.id, life)
                else:
                    await cur.execute(
                        """INSERT INTO inventory (user_id,item_name,quantity)
                           VALUES (%s,%s,%s) AS new
                           ON DUPLICATE KEY UPDATE quantity=inventory.quantity+new.quantity""",
                        (str(user.id), row["item_name"], int(row["quantity"])),
                    )
                await cur.execute("DELETE FROM global_trades WHERE id=%s", (listing_id,))
                await conn.commit()
                return True, f"{row['item_name']} ×{row['quantity']} 구매를 완료했습니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"거래 오류: {exc}"


async def fulfill_request(user, request_id: int, gem_id: str | None = None):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            try:
                await conn.begin()
                await cur.execute(
                    "SELECT * FROM global_purchase_requests WHERE id=%s FOR UPDATE",
                    (request_id,),
                )
                row = await cur.fetchone()
                if not row:
                    await conn.rollback()
                    return False, "이미 완료되거나 취소된 의뢰입니다."
                if str(row["buyer_id"]) == str(user.id):
                    await conn.rollback()
                    return False, "본인의 구매 의뢰는 납품 대신 취소할 수 있습니다."
                quantity = int(row["quantity"])
                if row["asset_type"] == "gem":
                    life = await _life_for_update(cur, user.id)
                    gems = life.setdefault("gems", [])
                    index = next(
                        (
                            index
                            for index, gem in enumerate(gems)
                            if isinstance(gem, dict)
                            and str(gem.get("id")) == str(gem_id)
                            and gem.get("name") == row["item_name"]
                        ),
                        None,
                    )
                    if index is None:
                        await conn.rollback()
                        return False, "조건에 맞는 젬을 찾지 못했습니다."
                    if str(gem_id) in await _db_equipped_gem_ids(cur, user.id):
                        await conn.rollback()
                        return False, "장착된 젬은 납품할 수 없습니다."
                    payload = dict(gems.pop(index))
                    await _save_life(cur, user.id, life)
                    buyer_life = await _life_for_update(cur, row["buyer_id"])
                    existing = {
                        str(gem.get("id"))
                        for gem in buyer_life.setdefault("gems", [])
                        if isinstance(gem, dict)
                    }
                    if str(payload.get("id")) in existing:
                        payload["id"] = uuid.uuid4().hex
                    buyer_life["gems"].append(payload)
                    await _save_life(cur, row["buyer_id"], buyer_life)
                elif row["asset_type"] == "stone":
                    life = await _life_for_update(cur, user.id)
                    stones = life.setdefault("stones", {})
                    owned = int(stones.get(row["item_name"], 0) or 0)
                    if owned < quantity:
                        await conn.rollback()
                        return False, f"감정된 원석이 부족합니다. ({owned}/{quantity})"
                    if owned == quantity:
                        stones.pop(row["item_name"], None)
                    else:
                        stones[row["item_name"]] = owned - quantity
                    await _save_life(cur, user.id, life)
                    buyer_life = await _life_for_update(cur, row["buyer_id"])
                    buyer_stones = buyer_life.setdefault("stones", {})
                    buyer_stones[row["item_name"]] = (
                        int(buyer_stones.get(row["item_name"], 0) or 0) + quantity
                    )
                    await _save_life(cur, row["buyer_id"], buyer_life)
                else:
                    await cur.execute(
                        """SELECT quantity FROM inventory
                           WHERE user_id=%s AND item_name=%s FOR UPDATE""",
                        (str(user.id), row["item_name"]),
                    )
                    stock = await cur.fetchone()
                    owned = int(stock["quantity"]) if stock else 0
                    if owned < quantity:
                        await conn.rollback()
                        return False, f"재고가 부족합니다. ({owned}/{quantity})"
                    if owned == quantity:
                        await cur.execute(
                            "DELETE FROM inventory WHERE user_id=%s AND item_name=%s",
                            (str(user.id), row["item_name"]),
                        )
                    else:
                        await cur.execute(
                            """UPDATE inventory SET quantity=quantity-%s
                               WHERE user_id=%s AND item_name=%s""",
                            (quantity, str(user.id), row["item_name"]),
                        )
                    await cur.execute(
                        """INSERT INTO inventory (user_id,item_name,quantity)
                           VALUES (%s,%s,%s) AS new
                           ON DUPLICATE KEY UPDATE quantity=inventory.quantity+new.quantity""",
                        (str(row["buyer_id"]), row["item_name"], quantity),
                    )
                currency = row["currency"]
                if currency not in VALID_CURRENCIES:
                    await conn.rollback()
                    return False, "의뢰 화폐 정보가 올바르지 않습니다."
                await cur.execute(
                    f"""UPDATE users SET {currency}={currency}+%s,
                           data_revision=data_revision+1 WHERE user_id=%s""",
                    (int(row["price"]), str(user.id)),
                )
                await cur.execute(
                    "UPDATE users SET data_revision=data_revision+1 WHERE user_id=%s",
                    (str(row["buyer_id"]),),
                )
                await cur.execute(
                    "DELETE FROM global_purchase_requests WHERE id=%s",
                    (request_id,),
                )
                await conn.commit()
                return True, f"{row['item_name']} ×{quantity} 납품 후 대금을 받았습니다."
            except Exception as exc:
                await conn.rollback()
                return False, f"구매 의뢰 납품 오류: {exc}"


class MarketTermsModal(discord.ui.Modal):
    def __init__(self, parent, asset_type: str, asset_key: str, item_name: str, request=False):
        super().__init__(title="구매 의뢰 조건" if request else "판매 조건")
        self.parent = parent
        self.asset_type = asset_type
        self.asset_key = asset_key
        self.item_name = item_name
        self.request = request
        self.quantity = discord.ui.TextInput(
            label="수량",
            default="1",
            required=True,
            max_length=6,
        )
        self.price = discord.ui.TextInput(
            label="전체 가격",
            placeholder="숫자만 입력",
            required=True,
            max_length=12,
        )
        self.currency = discord.ui.TextInput(
            label="화폐",
            placeholder="돈 또는 pt",
            default="돈",
            required=True,
            max_length=4,
        )
        self.add_item(self.quantity)
        self.add_item(self.price)
        self.add_item(self.currency)

    async def on_submit(self, interaction):
        if not self.quantity.value.isdigit() or not self.price.value.isdigit():
            return await interaction.response.send_message(
                "수량과 가격은 양의 정수로 입력해주세요.",
                ephemeral=True,
            )
        currency_text = self.currency.value.strip().lower()
        currency = "money" if currency_text in {"돈", "원", "money"} else "pt" if currency_text in {"pt", "포인트"} else None
        if currency is None:
            return await interaction.response.send_message(
                "화폐는 `돈` 또는 `pt`로 입력해주세요.",
                ephemeral=True,
            )
        quantity = int(self.quantity.value)
        price = int(self.price.value)
        if self.asset_type == "gem":
            quantity = 1
        if self.request:
            success, message = await register_request(
                interaction.user,
                self.asset_type,
                self.item_name,
                quantity,
                price,
                currency,
            )
        else:
            success, message = await register_sale(
                interaction.user,
                self.asset_type,
                self.asset_key,
                quantity,
                price,
                currency,
            )
        await interaction.response.send_message(
            ("✅ " if success else "❌ ") + message,
            ephemeral=True,
        )
        if success:
            await self.parent.parent.refresh_message(interaction)


class MarketAssetSelectView(discord.ui.View):
    def __init__(self, author, parent, *, request=False):
        super().__init__(timeout=180)
        self.author = author
        self.parent = parent
        self.request = request
        self.category = "item"
        self.page = 0
        self.user_data = {}
        self.entries: list[tuple[str, str, str]] = []

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 등록 화면만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def load(self):
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        if self.request:
            self.entries = [
                (asset_type, name, name)
                for asset_type, name in request_catalog()
                if asset_type == self.category
            ]
        elif self.category == "item":
            self.entries = [
                ("item", name, f"{name} · 보유 {int(count)}개")
                for name, count in sorted(self.user_data.get("inventory", {}).items())
                if int(count or 0) > 0
            ]
        elif self.category == "gem":
            self.entries = [
                ("gem", str(gem.get("id")), gem_label(gem))
                for gem in available_gems(self.user_data)
            ]
        else:
            self.entries = [
                ("stone", name, f"{name} · 보유 {int(count)}개")
                for name, count in sorted(
                    ensure_life_data(self.user_data).get("stones", {}).items()
                )
                if int(count or 0) > 0
            ]
        await self.rebuild()

    async def rebuild(self):
        self.clear_items()
        total_pages = max(1, (len(self.entries) + PER_PAGE - 1) // PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        item_button = discord.ui.Button(
            label="일반 아이템",
            style=discord.ButtonStyle.primary if self.category == "item" else discord.ButtonStyle.secondary,
            row=0,
        )
        gem_button = discord.ui.Button(
            label="젬",
            style=discord.ButtonStyle.primary if self.category == "gem" else discord.ButtonStyle.secondary,
            row=0,
        )
        stone_button = discord.ui.Button(
            label="감정된 원석",
            style=discord.ButtonStyle.primary if self.category == "stone" else discord.ButtonStyle.secondary,
            row=0,
        )
        item_button.callback = self.show_items
        gem_button.callback = self.show_gems
        stone_button.callback = self.show_stones
        self.add_item(item_button)
        self.add_item(stone_button)
        self.add_item(gem_button)
        visible = self.entries[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]
        if visible:
            select = discord.ui.Select(
                placeholder="원하는 항목 선택",
                row=1,
                options=[
                    discord.SelectOption(label=label[:100], value=f"{asset_type}|{key}")
                    for asset_type, key, label in visible
                ],
            )
            select.callback = self.select_asset
            self.add_item(select)
        previous = discord.ui.Button(label="이전", disabled=self.page == 0, row=2)
        page = discord.ui.Button(label=f"{self.page + 1}/{total_pages}", disabled=True, row=2)
        following = discord.ui.Button(label="다음", disabled=self.page >= total_pages - 1, row=2)
        back = discord.ui.Button(label="게시판으로", style=discord.ButtonStyle.secondary, row=2)
        previous.callback = self.previous
        following.callback = self.following
        back.callback = self.back
        self.add_item(previous)
        self.add_item(page)
        self.add_item(following)
        self.add_item(back)

    def get_embed(self):
        kind = "구매할 항목" if self.request else "판매할 내 자산"
        description = (
            "원하는 항목을 목록에서 고르세요."
            if self.entries
            else ("등록 가능한 젬이 없습니다. 장착된 젬은 표시되지 않습니다." if self.category == "gem" and not self.request else "표시할 항목이 없습니다.")
        )
        return discord.Embed(title=f"☕ {kind}", description=description, color=discord.Color.gold())

    async def _switch(self, interaction, category):
        self.category = category
        self.page = 0
        await self.load()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def show_items(self, interaction):
        await self._switch(interaction, "item")

    async def show_gems(self, interaction):
        await self._switch(interaction, "gem")

    async def show_stones(self, interaction):
        await self._switch(interaction, "stone")

    async def previous(self, interaction):
        self.page -= 1
        await self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def following(self, interaction):
        self.page += 1
        await self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def back(self, interaction):
        await self.parent.refresh_message(interaction)

    async def select_asset(self, interaction):
        asset_type, asset_key = interaction.data["values"][0].split("|", 1)
        if self.request:
            item_name = asset_key
        elif asset_type == "gem":
            gem = next(
                (
                    gem
                    for gem in available_gems(self.user_data)
                    if str(gem.get("id")) == asset_key
                ),
                None,
            )
            if not gem:
                return await interaction.response.send_message("젬 재고가 바뀌었습니다.", ephemeral=True)
            item_name = str(gem.get("name", "젬"))
        else:
            item_name = asset_key
        await interaction.response.send_modal(
            MarketTermsModal(
                self,
                asset_type,
                asset_key,
                item_name,
                request=self.request,
            )
        )


class MarketConfirmView(discord.ui.View):
    def __init__(self, author, parent, mode: str, row: dict[str, Any]):
        super().__init__(timeout=120)
        self.author = author
        self.parent = parent
        self.mode = mode
        self.row = row
        self.selected_gem_id = None
        self.gems = []
        self.gem_page = 0

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 확인 화면만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def prepare(self):
        if self.mode == "request_fulfill" and self.row["asset_type"] == "gem":
            data = await get_user_data(self.author.id, self.author.display_name)
            self.gems = available_gems(data, self.row["item_name"])
            self.selected_gem_id = str(self.gems[0].get("id")) if self.gems else None
            self.rebuild_gem_controls()

    def rebuild_gem_controls(self):
        self.clear_items()
        total_pages = max(1, (len(self.gems) + PER_PAGE - 1) // PER_PAGE)
        self.gem_page = max(0, min(self.gem_page, total_pages - 1))
        visible = self.gems[
            self.gem_page * PER_PAGE:(self.gem_page + 1) * PER_PAGE
        ]
        if visible:
            if not any(str(gem.get("id")) == self.selected_gem_id for gem in visible):
                self.selected_gem_id = str(visible[0].get("id"))
            select = discord.ui.Select(
                placeholder=f"납품할 젬 선택 ({self.gem_page + 1}/{total_pages})",
                row=0,
                options=[
                    discord.SelectOption(
                        label=gem_label(gem)[:100],
                        value=str(gem.get("id")),
                        default=str(gem.get("id")) == self.selected_gem_id,
                    )
                    for gem in visible
                ],
            )

            async def choose(interaction):
                self.selected_gem_id = interaction.data["values"][0]
                self.rebuild_gem_controls()
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            select.callback = choose
            self.add_item(select)
        if total_pages > 1:
            previous = discord.ui.Button(
                label="이전",
                disabled=self.gem_page == 0,
                row=1,
            )
            counter = discord.ui.Button(
                label=f"{self.gem_page + 1}/{total_pages}",
                disabled=True,
                row=1,
            )
            following = discord.ui.Button(
                label="다음",
                disabled=self.gem_page >= total_pages - 1,
                row=1,
            )

            async def move(interaction, delta):
                self.gem_page += delta
                self.rebuild_gem_controls()
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            async def prev_page(interaction):
                await move(interaction, -1)

            async def next_page(interaction):
                await move(interaction, 1)

            previous.callback = prev_page
            following.callback = next_page
            self.add_item(previous)
            self.add_item(counter)
            self.add_item(following)
        self.confirm.row = 2
        self.close.row = 2
        self.confirm.disabled = not bool(self.gems)
        self.add_item(self.confirm)
        self.add_item(self.close)

    def get_embed(self):
        action = {
            "sale_buy": "구매",
            "sale_cancel": "판매 취소",
            "request_fulfill": "의뢰 납품",
            "request_cancel": "의뢰 취소",
        }[self.mode]
        unit = VALID_CURRENCIES.get(self.row["currency"], self.row["currency"])
        text = (
            f"항목: **{self.row['item_name']} ×{self.row['quantity']}**\n"
            f"금액: **{int(self.row['price']):,}{unit}**\n"
            f"작업: **{action}**"
        )
        if self.mode == "request_fulfill" and self.row["asset_type"] == "gem":
            text += "\n" + ("납품할 젬을 선택했습니다." if self.selected_gem_id else "조건에 맞는 미장착 젬이 없습니다.")
        return discord.Embed(title="☕ 거래 확인", description=text, color=discord.Color.blurple())

    @discord.ui.button(label="확정", style=discord.ButtonStyle.success, row=1)
    async def confirm(self, interaction, button):
        if self.mode == "sale_buy":
            result = await buy_sale(self.author, int(self.row["id"]))
        elif self.mode == "sale_cancel":
            result = await cancel_listing(self.author, "global_trades", int(self.row["id"]))
        elif self.mode == "request_cancel":
            result = await cancel_listing(self.author, "global_purchase_requests", int(self.row["id"]))
        else:
            result = await fulfill_request(
                self.author,
                int(self.row["id"]),
                self.selected_gem_id,
            )
        success, message = result
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="거래 처리 결과",
                description=("✅ " if success else "❌ ") + message,
                color=discord.Color.green() if success else discord.Color.red(),
            ),
            view=None,
        )
        if success:
            await self.parent.refresh_message(interaction)

    @discord.ui.button(label="닫기", style=discord.ButtonStyle.secondary, row=1)
    async def close(self, interaction, button):
        await interaction.response.edit_message(content="거래 확인을 닫았습니다.", embed=None, view=None)


class CafeMarketView(discord.ui.View):
    def __init__(self, author, parent_view):
        super().__init__(timeout=180)
        self.author = author
        self.parent_view = parent_view
        self.mode = "sales"
        self.page = 0
        self.rows: list[dict[str, Any]] = []
        self.message = None

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인이 연 카페 게시판만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def load(self):
        await ensure_market_schema()
        table = "global_trades" if self.mode == "sales" else "global_purchase_requests"
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(f"SELECT * FROM {table} ORDER BY id DESC")
                self.rows = list(await cur.fetchall())
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        total_pages = max(1, (len(self.rows) + PER_PAGE - 1) // PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        sales = discord.ui.Button(
            label="판매 공고",
            style=discord.ButtonStyle.primary if self.mode == "sales" else discord.ButtonStyle.secondary,
            row=0,
        )
        requests = discord.ui.Button(
            label="구매 의뢰",
            style=discord.ButtonStyle.primary if self.mode == "requests" else discord.ButtonStyle.secondary,
            row=0,
        )
        add_sale = discord.ui.Button(label="판매 등록", style=discord.ButtonStyle.success, row=0)
        add_request = discord.ui.Button(label="구매 의뢰 등록", style=discord.ButtonStyle.success, row=0)
        sales.callback = self.show_sales
        requests.callback = self.show_requests
        add_sale.callback = self.add_sale
        add_request.callback = self.add_request
        self.add_item(sales)
        self.add_item(requests)
        self.add_item(add_sale)
        self.add_item(add_request)
        visible = self.rows[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]
        if visible:
            options = []
            for row in visible:
                owner_id = row["seller_id"] if self.mode == "sales" else row["buyer_id"]
                owner_name = row["seller_name"] if self.mode == "sales" else row["buyer_name"]
                unit = VALID_CURRENCIES.get(row["currency"], row["currency"])
                options.append(
                    discord.SelectOption(
                        label=f"{row['item_name']} ×{row['quantity']}"[:100],
                        value=str(row["id"]),
                        description=(
                            f"{owner_name} · {int(row['price']):,}{unit}"
                            + (" · 내 공고" if str(owner_id) == str(self.author.id) else "")
                        )[:100],
                    )
                )
            select = discord.ui.Select(placeholder="확인할 공고 선택", options=options, row=1)
            select.callback = self.select_listing
            self.add_item(select)
        previous = discord.ui.Button(label="이전", disabled=self.page == 0, row=2)
        page = discord.ui.Button(label=f"{self.page + 1}/{total_pages}", disabled=True, row=2)
        following = discord.ui.Button(label="다음", disabled=self.page >= total_pages - 1, row=2)
        back = discord.ui.Button(label="카페로", style=discord.ButtonStyle.secondary, row=2)
        previous.callback = self.previous
        following.callback = self.following
        back.callback = self.back
        self.add_item(previous)
        self.add_item(page)
        self.add_item(following)
        self.add_item(back)

    def get_embed(self):
        title = "📜 판매 공고" if self.mode == "sales" else "📥 구매 의뢰"
        description = (
            "인벤토리의 일반 아이템·미감정 원석·감정된 원석·미장착 젬을 골라 판매할 수 있습니다."
            if self.mode == "sales"
            else "원하는 항목의 대금을 먼저 맡기고 구매 공고를 등록합니다."
        )
        embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
        visible = self.rows[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]
        if not visible:
            embed.add_field(name="공고", value="현재 등록된 공고가 없습니다.", inline=False)
        else:
            lines = []
            for row in visible:
                owner = row.get("seller_name") or row.get("buyer_name")
                unit = VALID_CURRENCIES.get(row["currency"], row["currency"])
                kind = {
                    "gem": "젬",
                    "stone": "감정된 원석",
                }.get(row.get("asset_type") or "item", "아이템")
                lines.append(
                    f"• **{row['item_name']} ×{row['quantity']}** · {int(row['price']):,}{unit}\n"
                    f"  {kind} · {owner}"
                )
            embed.add_field(name="현재 페이지", value="\n".join(lines), inline=False)
        return embed

    async def refresh_message(self, interaction):
        fresh = await get_user_data(self.author.id, self.author.display_name)
        if hasattr(self.parent_view, "user_data"):
            self.parent_view.user_data.clear()
            self.parent_view.user_data.update(fresh)
        await self.load()
        same_message = (
            self.message is not None
            and interaction.message is not None
            and getattr(self.message, "id", None) == getattr(interaction.message, "id", None)
        )
        if self.message is not None and not same_message:
            if not interaction.response.is_done():
                await interaction.response.defer()
            try:
                await self.message.edit(embed=self.get_embed(), view=self)
            except (discord.NotFound, discord.HTTPException):
                pass
        elif interaction.response.is_done():
            try:
                self.message = await interaction.edit_original_response(
                    embed=self.get_embed(),
                    view=self,
                )
            except (discord.NotFound, discord.HTTPException):
                pass
        else:
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
            self.message = interaction.message

    async def open(self, interaction):
        self.message = interaction.message
        await self.load()
        if interaction.response.is_done():
            self.message = await interaction.edit_original_response(
                embed=self.get_embed(),
                view=self,
            )
        else:
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
            self.message = interaction.message

    async def _switch(self, interaction, mode):
        self.mode = mode
        self.page = 0
        await self.refresh_message(interaction)

    async def show_sales(self, interaction):
        await self._switch(interaction, "sales")

    async def show_requests(self, interaction):
        await self._switch(interaction, "requests")

    async def add_sale(self, interaction):
        view = MarketAssetSelectView(self.author, self, request=False)
        await view.load()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    async def add_request(self, interaction):
        view = MarketAssetSelectView(self.author, self, request=True)
        await view.load()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    async def previous(self, interaction):
        self.page -= 1
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def following(self, interaction):
        self.page += 1
        self.rebuild()
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

    async def select_listing(self, interaction):
        listing_id = int(interaction.data["values"][0])
        row = next((row for row in self.rows if int(row["id"]) == listing_id), None)
        if not row:
            return await interaction.response.send_message("공고가 이미 변경되었습니다.", ephemeral=True)
        owner_id = row["seller_id"] if self.mode == "sales" else row["buyer_id"]
        if self.mode == "sales":
            mode = "sale_cancel" if str(owner_id) == str(self.author.id) else "sale_buy"
        else:
            mode = "request_cancel" if str(owner_id) == str(self.author.id) else "request_fulfill"
        view = MarketConfirmView(self.author, self, mode, row)
        await view.prepare()
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)
