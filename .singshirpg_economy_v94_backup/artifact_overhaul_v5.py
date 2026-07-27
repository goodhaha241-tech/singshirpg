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
from navigation_v7 import attach_navigation


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
    artifacts = user_data.get("artifacts", [])
    art = next((a for a in artifacts if str(a.get("id")) == str(artifact_id)), None)
    if not art:
        return False, "아티팩트를 찾을 수 없습니다."
    migrate_artifact(art)
    if art["metadata"]["locked"]:
        return False, "잠긴 아티팩트는 분해할 수 없습니다."
    if any(g for g in art.get("gems", []) if g):
        return False, "젬을 먼저 해제해주세요."
    owner = artifact_owner(user_data, art)
    if owner or int(art.get("equipped_char_index", -1)) >= 0:
        return False, f"장착 중인 아티팩트는 분해할 수 없습니다.{f' (장착자: {owner})' if owner else ''}"
    reward = artifact_dust_value(art)
    artifacts.remove(art)
    inv = user_data.setdefault("inventory", {})
    inv["유물 가루"] = int(inv.get("유물 가루", 0)) + reward
    return True, f"유물 가루 {reward}개를 획득했습니다."


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
            confirming = str(self.pending_dismantle_id) == str(self.selected_artifact_id)
            dismantle_button = discord.ui.Button(
                label="정말 분해" if confirming else "선택 분해",
                style=discord.ButtonStyle.danger,
                row=3,
            )
            dismantle_button.callback = self._dismantle
            self.add_item(dismantle_button)
            gem_button = discord.ui.Button(label="젬 관리", emoji="💎", style=discord.ButtonStyle.success, row=3)
            gem_button.callback = self._open_gems
            self.add_item(gem_button)
            equip_button = discord.ui.Button(label="장착·강화", style=discord.ButtonStyle.primary, row=3)
            equip_button.callback = self._open_legacy_equipment
            self.add_item(equip_button)

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
