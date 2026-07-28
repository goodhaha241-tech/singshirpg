# economy-exchange-v9.4
# life-artifact-v7.3-manager
# rollback-guard-appraisal-gems-v8
# appraisal-gem-affixes-v8.1
# gem-visibility-tools-v8.3
from __future__ import annotations

import random
from typing import Any

import discord

from artifact_events_v5 import CHARACTER_ARTIFACT_EFFECTS, COMMON_ARTIFACT_EFFECTS
from character import (
    GEM_MAIN_STAT_LABELS,
    artifact_effective_stats,
    artifact_primary_stat_key,
    ensure_gem_stat_affixes,
    gem_main_stat_text,
)
from gem_manager import (
    CHARACTER_SPECIALS,
    GemManagerView,
    artifact_entries,
    artifact_owner,
    artifact_socket_count,
    gem_applied_effect_summary,
    gem_detail_text,
)
from items import ITEM_CATEGORIES, ITEM_PRICES
from navigation_v7 import attach_navigation
from progression_system_v6 import korea_today


ITEMS_PER_PAGE = 8
ARTIFACT_FILTERS = (
    ("all", "전체"),
    ("equipped", "장착 중"),
    ("unequipped", "미장착"),
    ("rank_1", "1성"),
    ("rank_2", "2성"),
    ("rank_3", "3성"),
    ("character", "전용·각인"),
)
ARTIFACT_DUST_ITEM = "유물 가루"
ARTIFACT_TICKET_ITEM = "아티팩트 뽑기권"
PURE_HOPE_ITEM = "순수한 희망"
ARTIFACT_DUST_FIXED_OFFERS = {
    "hope": {
        "label": "순수한 희망 ×1",
        "price": 300,
        "item": PURE_HOPE_ITEM,
        "count": 1,
    },
    "ticket": {
        "label": "아티팩트 뽑기권 ×1",
        "price": 200,
        "item": ARTIFACT_TICKET_ITEM,
        "count": 1,
    },
    "support_fragment": {
        "label": "랜덤 캐릭터 조각 ×1",
        "price": 250,
        "kind": "support_fragment",
        "count": 1,
    },
}


def migrate_artifact(artifact: dict[str, Any]):
    if not isinstance(artifact.get("gems"), list):
        artifact["gems"] = [None] * artifact_socket_count(artifact)
    if not isinstance(artifact.get("metadata"), dict):
        artifact["metadata"] = {}
    artifact["metadata"].setdefault("locked", False)
    artifact["metadata"].setdefault("reroll_count", 0)
    special = artifact.get("special")
    artifact.setdefault("effect_scope", "character" if special in CHARACTER_ARTIFACT_EFFECTS else "common")
    return artifact


def artifact_dust_value(artifact):
    rank = artifact_socket_count(artifact)
    base = {1: 10, 2: 35, 3: 120}[rank]
    return round(base * (1 + 0.05 * int(artifact.get("level", 0) or 0)))


def toggle_lock(artifact):
    migrate_artifact(artifact)
    artifact["metadata"]["locked"] = not artifact["metadata"]["locked"]
    return artifact["metadata"]["locked"]


def dismantle_artifact(user_data, artifact_id):
    ok, message, _, _ = dismantle_artifacts(user_data, [artifact_id])
    return ok, message


def _artifact_dismantle_block_reason(user_data, art):
    migrate_artifact(art)
    if art["metadata"]["locked"]:
        return "잠김"
    if any(g for g in art.get("gems", []) if g):
        return "젬 장착"
    owner = artifact_owner(user_data, art)
    if owner or int(art.get("equipped_char_index", -1)) >= 0:
        return f"장착 중{f'({owner})' if owner else ''}"
    return None


def dismantle_artifacts(user_data, artifact_ids):
    """Safely dismantle multiple artifacts into one consistent dust currency."""
    artifacts = user_data.get("artifacts", [])
    wanted = {str(artifact_id) for artifact_id in artifact_ids}
    selected = [art for art in artifacts if str(art.get("id")) in wanted]
    if not selected:
        return False, "분해할 아티팩트를 찾을 수 없습니다.", 0, 0
    blocked = [
        f"{art.get('name', '아티팩트')}: {_artifact_dismantle_block_reason(user_data, art)}"
        for art in selected
        if _artifact_dismantle_block_reason(user_data, art)
    ]
    if blocked:
        return False, "분해할 수 없는 항목이 포함되어 있습니다: " + ", ".join(blocked[:3]), 0, 0
    reward = sum(artifact_dust_value(art) for art in selected)
    selected_ids = {id(art) for art in selected}
    user_data["artifacts"] = [art for art in artifacts if id(art) not in selected_ids]
    inv = user_data.setdefault("inventory", {})
    inv[ARTIFACT_DUST_ITEM] = int(inv.get(ARTIFACT_DUST_ITEM, 0)) + reward
    return True, f"아티팩트 {len(selected)}개를 분해해 유물 가루 {reward}개를 획득했습니다.", len(selected), reward


def artifact_dust_daily_offers(date_key=None):
    """Return the same two randomized offers for every user on a given Korea date."""
    date_key = str(date_key or korea_today())
    excluded = {
        ARTIFACT_DUST_ITEM,
        ARTIFACT_TICKET_ITEM,
        PURE_HOPE_ITEM,
        "도구 증표",
    }
    candidates = [
        name
        for name, data in ITEM_CATEGORIES.items()
        if name not in excluded
        and data.get("type") in {"material", "rare_mat", "consumable"}
        and int(ITEM_PRICES.get(name, 0) or 0) > 0
    ]
    rng = random.Random(f"singshirpg-artifact-dust-shop:{date_key}")
    if len(candidates) < 2:
        return []
    chosen = rng.sample(sorted(candidates), 2)
    offers = []
    for index, item in enumerate(chosen):
        unit_value = max(1, int(ITEM_PRICES.get(item, 1)))
        base = max(40, min(250, ((unit_value + 4_999) // 5_000) * 10))
        price = max(40, min(250, base + rng.randrange(-2, 3) * 10))
        count = rng.randint(1, 3)
        offers.append({
            "key": f"daily_{index}",
            "label": f"{item} ×{count}",
            "item": item,
            "count": count,
            "price": price,
            "date": date_key,
        })
    return offers


def buy_artifact_dust_offer(user_data, offer_key, date_key=None):
    inventory = user_data.setdefault("inventory", {})
    offers = {
        key: dict(value, key=key)
        for key, value in ARTIFACT_DUST_FIXED_OFFERS.items()
    }
    offers.update({
        offer["key"]: offer
        for offer in artifact_dust_daily_offers(date_key)
    })
    offer = offers.get(offer_key)
    if not offer:
        return False, "오늘의 판매 목록이 변경되었습니다. 상점을 다시 열어주세요."
    dust = int(inventory.get(ARTIFACT_DUST_ITEM, 0))
    price = int(offer["price"])
    if dust < price:
        return False, f"유물 가루가 부족합니다. 필요: {price}개 / 보유: {dust}개"
    inventory[ARTIFACT_DUST_ITEM] = dust - price
    if offer.get("kind") == "support_fragment":
        from boss_training import add_support_fragment

        result = add_support_fragment(user_data)
        return (
            True,
            f"🤝 유물 가루 {price}개로 **{result['name']} 조각 ×1**을 구매했습니다. "
            f"(보유 {result['total']}개 · +{result['upgrade']}강)",
        )
    item, count = offer["item"], int(offer["count"])
    inventory[item] = int(inventory.get(item, 0)) + count
    return True, f"✅ 유물 가루 {price}개로 {item} ×{count}을(를) 구매했습니다."


def reroll_artifact(user_data, artifact_id):
    art = next(
        (a for a in user_data.get("artifacts", []) if str(a.get("id")) == str(artifact_id)),
        None,
    )
    if not art:
        return False, "아티팩트를 찾을 수 없습니다."
    migrate_artifact(art)
    rank = artifact_socket_count(art)
    cost = {1: 20_000, 2: 80_000, 3: 250_000}[rank]
    if int(user_data.get("money", 0)) < cost:
        return False, "머니가 부족합니다."
    user_data["money"] -= cost
    keys = list(art.get("stats", {})) or ["hp", "attack"]
    art["stats"] = {key: random.randint(rank * 2, rank * 8) for key in keys}
    art["metadata"]["reroll_count"] += 1
    try:
        from progression_system_v6 import ensure_progression, weekly_progress
        progression = ensure_progression(user_data)
        if "first_artifact_reroll" not in progression["achievements"]:
            progression["achievements"].append("first_artifact_reroll")
        weekly_progress(user_data, "artifact_maintenance", 1)
    except ImportError:
        pass
    return True, f"스탯을 재조정했습니다. 비용 {cost:,}원"


class ArtifactDismantleView(discord.ui.View):
    """Paged multi-select and safe bulk dismantling."""

    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=300)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.page = 0
        self.selected_ids = set()
        self.pending_action = None
        self.last_message = None
        self._rebuild_components()

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 아티팩트만 분해할 수 있습니다.", ephemeral=True)
        return False

    async def _save(self):
        try:
            await self.save_func(self.author.id, self.user_data)
        except TypeError:
            await self.save_func(self.user_data)

    def _eligible(self):
        return sorted(
            [
                art
                for art in self.user_data.get("artifacts", [])
                if not _artifact_dismantle_block_reason(self.user_data, art)
            ],
            key=lambda art: (
                artifact_socket_count(art),
                str(art.get("name", "")),
                str(art.get("id", "")),
            ),
        )

    def _page_data(self):
        eligible = self._eligible()
        total_pages = max(1, (len(eligible) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        self.page = min(max(0, self.page), total_pages - 1)
        page_arts = eligible[self.page * ITEMS_PER_PAGE:(self.page + 1) * ITEMS_PER_PAGE]
        valid_ids = {str(art.get("id")) for art in eligible}
        self.selected_ids.intersection_update(valid_ids)
        return eligible, page_arts, total_pages

    def _rebuild_components(self):
        self.clear_items()
        eligible, page_arts, total_pages = self._page_data()
        if page_arts:
            select = discord.ui.Select(
                placeholder="분해할 아티팩트 선택 · 페이지당 8개",
                min_values=1,
                max_values=len(page_arts),
                row=0,
                options=[
                    discord.SelectOption(
                        label=f"{art.get('name', '아티팩트')} +{art.get('level', 0)}"[:100],
                        value=str(art.get("id")),
                        description=(
                            f"{artifact_socket_count(art)}성 · "
                            f"유물 가루 {artifact_dust_value(art)}개"
                        )[:100],
                        default=str(art.get("id")) in self.selected_ids,
                    )
                    for art in page_arts
                ],
            )
            select.callback = self._select
            self.add_item(select)

        previous = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=1, disabled=self.page == 0)
        previous.callback = self._previous
        self.add_item(previous)
        self.add_item(discord.ui.Button(
            label=f"{self.page + 1}/{total_pages} · 분해 가능 {len(eligible)}개",
            style=discord.ButtonStyle.secondary,
            row=1,
            disabled=True,
        ))
        following = discord.ui.Button(
            label="▶",
            style=discord.ButtonStyle.secondary,
            row=1,
            disabled=self.page >= total_pages - 1,
        )
        following.callback = self._next
        self.add_item(following)

        selected_label = "정말 선택 분해" if self.pending_action == "selected" else f"선택 분해 ({len(self.selected_ids)})"
        selected = discord.ui.Button(label=selected_label, style=discord.ButtonStyle.danger, row=2)
        selected.callback = lambda interaction: self._confirm_and_dismantle(interaction, "selected")
        self.add_item(selected)
        rank1 = discord.ui.Button(
            label="정말 1성 일괄" if self.pending_action == "rank1" else "1성 일괄 분해",
            style=discord.ButtonStyle.danger,
            row=2,
        )
        rank1.callback = lambda interaction: self._confirm_and_dismantle(interaction, "rank1")
        self.add_item(rank1)
        rank12 = discord.ui.Button(
            label="정말 1~2성 일괄" if self.pending_action == "rank12" else "1~2성 일괄 분해",
            style=discord.ButtonStyle.danger,
            row=2,
        )
        rank12.callback = lambda interaction: self._confirm_and_dismantle(interaction, "rank12")
        self.add_item(rank12)
        back = discord.ui.Button(label="아티팩트 관리로", style=discord.ButtonStyle.secondary, row=3)
        back.callback = self._back
        self.add_item(back)

    async def _select(self, interaction):
        _, page_arts, _ = self._page_data()
        page_ids = {str(art.get("id")) for art in page_arts}
        self.selected_ids.difference_update(page_ids)
        self.selected_ids.update(interaction.data["values"])
        self.pending_action = None
        self.last_message = None
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _previous(self, interaction):
        self.page = max(0, self.page - 1)
        self.pending_action = None
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _next(self, interaction):
        self.page += 1
        self.pending_action = None
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    def _ids_for_action(self, action):
        eligible = self._eligible()
        if action == "selected":
            return list(self.selected_ids)
        max_rank = 1 if action == "rank1" else 2
        return [
            str(art.get("id"))
            for art in eligible
            if artifact_socket_count(art) <= max_rank
        ]

    async def _confirm_and_dismantle(self, interaction, action):
        ids = self._ids_for_action(action)
        if not ids:
            return await interaction.response.send_message("분해할 아티팩트가 없습니다.", ephemeral=True)
        if self.pending_action != action:
            self.pending_action = action
            self.last_message = f"⚠️ {len(ids)}개를 분해합니다. 같은 버튼을 한 번 더 눌러 확정하세요."
            self._rebuild_components()
            return await interaction.response.edit_message(embed=self.get_embed(), view=self)
        ok, message, _, _ = dismantle_artifacts(self.user_data, ids)
        self.pending_action = None
        if ok:
            await self._save()
            self.selected_ids.difference_update({str(value) for value in ids})
        self.last_message = message
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _back(self, interaction):
        view = ArtifactHubView(self.author, self.user_data, self.save_func)
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

    def get_embed(self):
        inventory = self.user_data.setdefault("inventory", {})
        selected_arts = [
            art
            for art in self._eligible()
            if str(art.get("id")) in self.selected_ids
        ]
        selected_dust = sum(artifact_dust_value(art) for art in selected_arts)
        embed = discord.Embed(
            title="🗑️ 아티팩트 분해 관리",
            description=self.last_message or "분해할 항목을 여러 개 선택하거나 성급별로 일괄 분해할 수 있습니다.",
            color=discord.Color.red(),
        )
        embed.add_field(
            name="선택",
            value=f"{len(selected_arts)}개 · 예상 유물 가루 {selected_dust}개",
            inline=True,
        )
        embed.add_field(
            name="보유 유물 가루",
            value=f"{int(inventory.get(ARTIFACT_DUST_ITEM, 0)):,}개",
            inline=True,
        )
        embed.set_footer(text="잠금·장착·젬 장착 아티팩트는 목록에서 자동 제외됩니다.")
        return embed


class ArtifactDustShopView(discord.ui.View):
    """Fixed and daily-rotating artifact dust exchange."""

    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=180)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.date_key = str(korea_today())
        self.selected_offer = "hope"
        self.last_message = None
        self._rebuild_components()

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 유물 가루 상점만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def _save(self):
        try:
            await self.save_func(self.author.id, self.user_data)
        except TypeError:
            await self.save_func(self.user_data)

    def _offers(self):
        fixed = [
            dict(value, key=key)
            for key, value in ARTIFACT_DUST_FIXED_OFFERS.items()
        ]
        return fixed + artifact_dust_daily_offers(self.date_key)

    def _rebuild_components(self):
        self.clear_items()
        offers = self._offers()
        if self.selected_offer not in {offer["key"] for offer in offers}:
            self.selected_offer = offers[0]["key"] if offers else None
        if offers:
            select = discord.ui.Select(
                placeholder="유물 가루 상품",
                row=0,
                options=[
                    discord.SelectOption(
                        label=offer["label"][:100],
                        value=offer["key"],
                        description=f"유물 가루 {offer['price']}개"[:100],
                        default=offer["key"] == self.selected_offer,
                    )
                    for offer in offers
                ],
            )
            select.callback = self._select
            self.add_item(select)
        buy = discord.ui.Button(label="선택 상품 구매", style=discord.ButtonStyle.success, row=1)
        buy.callback = self._buy
        self.add_item(buy)
        back = discord.ui.Button(label="아티팩트 관리로", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)

    async def _select(self, interaction):
        self.selected_offer = interaction.data["values"][0]
        self.last_message = None
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _buy(self, interaction):
        ok, message = buy_artifact_dust_offer(
            self.user_data,
            self.selected_offer,
            self.date_key,
        )
        if ok:
            await self._save()
        self.last_message = message
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _back(self, interaction):
        view = ArtifactHubView(self.author, self.user_data, self.save_func)
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

    def get_embed(self):
        inventory = self.user_data.setdefault("inventory", {})
        offer = next(
            (offer for offer in self._offers() if offer["key"] == self.selected_offer),
            None,
        )
        embed = discord.Embed(
            title="✨ 유물 가루 상점",
            description=self.last_message or "고정 상품과 한국 날짜 기준 일일 로테이션 상품을 판매합니다.",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="보유 유물 가루",
            value=f"{int(inventory.get(ARTIFACT_DUST_ITEM, 0)):,}개",
            inline=True,
        )
        embed.add_field(name="오늘의 로테이션", value=self.date_key, inline=True)
        if offer:
            embed.add_field(
                name=offer["label"],
                value=(
                    f"가격: 유물 가루 {offer['price']:,}개"
                    + (
                        "\n전체 지원 가능 캐릭터 중 하나의 전용 조각을 무작위로 받습니다."
                        if offer.get("kind") == "support_fragment"
                        else ""
                    )
                ),
                inline=False,
            )
        embed.set_footer(text="순수한 희망과 아티팩트 뽑기권은 상시 판매됩니다.")
        return embed


class ArtifactHubView(discord.ui.View):
    """Categorized artifact management with eight items per page."""

    def __init__(self, author, user_data, save_func, selected_artifact_id=None):
        super().__init__(timeout=300)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        for entry in artifact_entries(user_data):
            art = migrate_artifact(entry["artifact"])
            if art.get("special"):
                try:
                    from progression_system_v6 import add_collection
                    add_collection(user_data, "artifact_effects", art["special"])
                except ImportError:
                    pass
        self.category = "all"
        self.page = 0
        artifacts = user_data.get("artifacts", [])
        self.selected_artifact_id = selected_artifact_id or (
            artifacts[0].get("id") if artifacts else None
        )
        self.pending_dismantle_id = None
        self._rebuild_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 아티팩트만 관리할 수 있습니다.", ephemeral=True)
        return False

    def _all_artifacts(self):
        return sorted(
            [entry["artifact"] for entry in artifact_entries(self.user_data)],
            key=lambda art: (
                0 if artifact_owner(self.user_data, art) else 1,
                -artifact_socket_count(art),
                str(art.get("name", "")),
            ),
        )

    def _is_character_artifact(self, art):
        return (
            art.get("effect_scope") == "character"
            or art.get("special") in CHARACTER_SPECIALS
            or art.get("special") in CHARACTER_ARTIFACT_EFFECTS
        )

    def _filtered(self):
        arts = self._all_artifacts()
        if self.category == "equipped":
            return [art for art in arts if artifact_owner(self.user_data, art)]
        if self.category == "unequipped":
            return [art for art in arts if not artifact_owner(self.user_data, art)]
        if self.category.startswith("rank_"):
            rank = int(self.category[-1])
            return [art for art in arts if artifact_socket_count(art) == rank]
        if self.category == "character":
            return [art for art in arts if self._is_character_artifact(art)]
        return arts

    def _selected(self):
        return next(
            (
                art for art in self._all_artifacts()
                if str(art.get("id")) == str(self.selected_artifact_id)
            ),
            None,
        )

    def _sync_selection(self):
        artifacts = self._filtered()
        total_pages = max(1, (len(artifacts) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        self.page = min(max(0, self.page), total_pages - 1)
        page_arts = artifacts[self.page * ITEMS_PER_PAGE:(self.page + 1) * ITEMS_PER_PAGE]
        if not any(str(art.get("id")) == str(self.selected_artifact_id) for art in page_arts):
            self.selected_artifact_id = page_arts[0].get("id") if page_arts else None
        return artifacts, page_arts, total_pages

    async def _save(self):
        try:
            await self.save_func(self.author.id, self.user_data)
        except TypeError:
            await self.save_func(self.user_data)

    def _life_hub_factory(self):
        from life_overhaul_v5 import LifeHubView
        return LifeHubView(self.author, self.user_data, self.save_func)

    def _category_count(self, key):
        old = self.category
        self.category = key
        count = len(self._filtered())
        self.category = old
        return count

    def _rebuild_components(self):
        self.clear_items()
        artifacts, page_arts, total_pages = self._sync_selection()

        category_select = discord.ui.Select(
            placeholder="아티팩트 종류",
            row=0,
            options=[
                discord.SelectOption(
                    label=label,
                    value=key,
                    description=f"{self._category_count(key)}개",
                    default=key == self.category,
                )
                for key, label in ARTIFACT_FILTERS
            ],
        )
        category_select.callback = self._select_category
        self.add_item(category_select)

        if page_arts:
            artifact_select = discord.ui.Select(
                placeholder=f"관리할 아티팩트 · 페이지당 {ITEMS_PER_PAGE}개",
                row=1,
                options=[
                    discord.SelectOption(
                        label=(
                            f"{'🔒 ' if art['metadata']['locked'] else ''}"
                            f"{art.get('name', '아티팩트')} +{art.get('level', 0)}"
                        )[:100],
                        value=str(art.get("id")),
                        description=(
                            f"{artifact_socket_count(art)}성/{artifact_socket_count(art)}소켓 · "
                            f"{'장착자 ' + artifact_owner(self.user_data, art) if artifact_owner(self.user_data, art) else '미장착'}"
                        )[:100],
                        default=str(art.get("id")) == str(self.selected_artifact_id),
                    )
                    for art in page_arts
                    if art.get("id") is not None
                ],
            )
            artifact_select.callback = self._select
            self.add_item(artifact_select)

        previous = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=2, disabled=self.page == 0)
        previous.callback = self._previous_page
        self.add_item(previous)
        self.add_item(discord.ui.Button(
            label=f"{self.page + 1}/{total_pages} · 총 {len(artifacts)}개",
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

        artifact = self._selected()
        if artifact:
            lock_button = discord.ui.Button(
                label="잠금 해제" if artifact["metadata"]["locked"] else "잠금",
                style=discord.ButtonStyle.secondary,
                row=3,
            )
            lock_button.callback = self._toggle_lock
            self.add_item(lock_button)
            reroll_button = discord.ui.Button(label="스탯 재조정", style=discord.ButtonStyle.primary, row=3)
            reroll_button.callback = self._reroll
            self.add_item(reroll_button)
            dismantle_button = discord.ui.Button(
                label="분해 관리",
                style=discord.ButtonStyle.danger,
                row=3,
            )
            dismantle_button.callback = self._open_dismantle
            self.add_item(dismantle_button)
            gem_button = discord.ui.Button(label="젬 관리", emoji="💎", style=discord.ButtonStyle.success, row=3)
            gem_button.callback = self._open_gems
            self.add_item(gem_button)
            equip_button = discord.ui.Button(label="장착·강화", style=discord.ButtonStyle.primary, row=3)
            equip_button.callback = self._open_legacy_equipment
            self.add_item(equip_button)

        dust_shop = discord.ui.Button(
            label="유물 가루 상점",
            emoji="✨",
            style=discord.ButtonStyle.success,
            row=4,
        )
        dust_shop.callback = self._open_dust_shop
        self.add_item(dust_shop)
        attach_navigation(self, self.author, self._life_hub_factory, back_label="생활 관리로")

    async def _select_category(self, interaction):
        self.category = interaction.data["values"][0]
        self.page = 0
        self.selected_artifact_id = None
        self.pending_dismantle_id = None
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _select(self, interaction):
        self.selected_artifact_id = interaction.data["values"][0]
        self.pending_dismantle_id = None
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _previous_page(self, interaction):
        self.page = max(0, self.page - 1)
        self.selected_artifact_id = None
        self.pending_dismantle_id = None
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _next_page(self, interaction):
        self.page += 1
        self.selected_artifact_id = None
        self.pending_dismantle_id = None
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _toggle_lock(self, interaction):
        artifact = self._selected()
        if not artifact:
            return await interaction.response.send_message("아티팩트를 먼저 선택하세요.", ephemeral=True)
        locked = toggle_lock(artifact)
        self.pending_dismantle_id = None
        await self._save()
        self._rebuild_components()
        await interaction.response.edit_message(
            content=f"{artifact.get('name', '아티팩트')} 잠금을 {'설정' if locked else '해제'}했습니다.",
            embed=self.get_embed(),
            view=self,
        )

    async def _reroll(self, interaction):
        ok, message = reroll_artifact(self.user_data, self.selected_artifact_id)
        if ok:
            await self._save()
        self.pending_dismantle_id = None
        self._rebuild_components()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    async def _dismantle(self, interaction):
        if str(self.pending_dismantle_id) != str(self.selected_artifact_id):
            self.pending_dismantle_id = self.selected_artifact_id
            self._rebuild_components()
            return await interaction.response.edit_message(
                content="분해하면 되돌릴 수 없습니다. 같은 버튼을 한 번 더 눌러 확정하세요.",
                embed=self.get_embed(),
                view=self,
            )
        ok, message = dismantle_artifact(self.user_data, self.selected_artifact_id)
        self.pending_dismantle_id = None
        if ok:
            await self._save()
            self.selected_artifact_id = None
        self._rebuild_components()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    async def _open_dismantle(self, interaction):
        view = ArtifactDismantleView(self.author, self.user_data, self.save_func)
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

    async def _open_dust_shop(self, interaction):
        view = ArtifactDustShopView(self.author, self.user_data, self.save_func)
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

    async def _open_gems(self, interaction):
        view = GemManagerView(self.author, self.user_data, self.save_func)
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

    async def _open_legacy_equipment(self, interaction):
        from artifact_manager import ArtifactManageView
        view = ArtifactManageView(self.author, self.user_data, self.save_func)
        embed = view.make_base_embed("💍 아티팩트 장착·강화", "캐릭터 장착, 강화 또는 일괄 분해를 진행합니다.")
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    def get_embed(self):
        artifacts = self._filtered()
        selected = self._selected()
        label = dict(ARTIFACT_FILTERS).get(self.category, self.category)
        embed = discord.Embed(
            title="💍 아티팩트 관리",
            description=f"분류: **{label}** · 페이지당 {ITEMS_PER_PAGE}개",
            color=discord.Color.gold(),
        )
        if not artifacts:
            embed.add_field(name="보유 아티팩트", value="이 분류에 표시할 아티팩트가 없습니다.", inline=False)
            return embed
        if selected:
            owner = artifact_owner(self.user_data, selected) or "미장착"
            special = COMMON_ARTIFACT_EFFECTS.get(
                selected.get("special"), {}
            ).get("label", selected.get("special") or "일반")
            sockets = selected.setdefault("gems", [None] * artifact_socket_count(selected))
            gem_lines = [
                (
                    f"{index + 1}. {gem.get('name', '젬')} — {gem_applied_effect_summary(gem)}"
                    if isinstance(gem, dict)
                    else f"{index + 1}. 비어 있음"
                )
                for index, gem in enumerate(sockets[:artifact_socket_count(selected)])
            ]
            base_stats = selected.get("stats", {})
            effective_stats = artifact_effective_stats(selected)
            primary_stat = artifact_primary_stat_key(selected)
            stat_parts = []
            for key, base_value in base_stats.items():
                if not isinstance(base_value, (int, float)) or base_value <= 0:
                    continue
                actual_value = effective_stats.get(key, base_value)
                unit = "%" if key == "defense_rate" else ""
                label_name = GEM_MAIN_STAT_LABELS.get(key, key)
                primary_marker = " (주)" if key == primary_stat else ""
                stat_parts.append(
                    f"{label_name}{primary_marker} +{base_value}{unit}"
                    + (f" → **+{actual_value}{unit}**" if actual_value != base_value else "")
                )
            stat_text = ", ".join(stat_parts) or "없음"
            main_effects = [
                gem_main_stat_text(ensure_gem_stat_affixes(gem))
                for gem in sockets
                if isinstance(gem, dict)
            ]
            embed.add_field(
                name=f"{'🔒 ' if selected['metadata']['locked'] else ''}{selected.get('name', '아티팩트')} +{selected.get('level', 0)}",
                value=(
                    f"장착자: **{owner}**\n"
                    f"등급/소켓: {artifact_socket_count(selected)}성 · {artifact_socket_count(selected)}소켓\n"
                    f"고유 효과: {special}\n"
                    f"스탯: {stat_text}\n"
                    f"젬 주 능력: {', '.join(main_effects) or '없음'}\n"
                    f"분해 예상: 유물 가루 {artifact_dust_value(selected)}개\n"
                    f"젬: {' / '.join(gem_lines)}"
                ),
                inline=False,
            )
            for index, gem in enumerate(sockets[:artifact_socket_count(selected)]):
                if not isinstance(gem, dict):
                    continue
                detail = gem_detail_text(gem)
                embed.add_field(
                    name=f"💎 {index + 1}번 소켓 · {gem.get('name', '젬')}",
                    value=detail[:1024],
                    inline=False,
                )
        embed.set_footer(text="장착 중인 아티팩트도 숨기지 않으며 장착자를 함께 표시합니다.")
        return embed
