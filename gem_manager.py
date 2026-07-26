# gem-link-v4-manager
from __future__ import annotations

from typing import Any

import discord

from life_system import STONE_GEMS, ensure_life_data
from navigation_v7 import attach_navigation


CHARACTER_SPECIALS = {
    "youngsan_gold", "luude_imprint", "earthreg_faith",
    "sensho_star", "Sensho_star", "kaian_time", "shayla_light",
}

CATEGORY_LABELS = {
    "combat_common": "전투 공용",
    "dedicated": "아티팩트 전용",
    "life": "생활",
}

TARGET_SPECIAL_LABELS = {
    "reuse_last_dice": "꼼꼼한",
    "fierce_attack": "맹렬한",
    "sturdy_defense": "견고한",
    "reflection": "앙심품은",
    "escalation": "고조된",
    "immortality": "불멸의",
}


def gem_definition(gem: dict[str, Any]) -> dict[str, Any] | None:
    """Find the original definition for old gems that do not store a summary."""
    for definitions in STONE_GEMS.values():
        for definition in definitions:
            if definition.get("name") != gem.get("name"):
                continue
            if gem.get("category") and definition.get("category") != gem.get("category"):
                continue
            if (
                gem.get("target_special")
                and definition.get("target_special") != gem.get("target_special")
            ):
                continue
            return definition
    return None


def gem_summary(gem: dict[str, Any]) -> str:
    definition = gem_definition(gem)
    return str(gem.get("summary") or (definition or {}).get("summary") or "상세 효과가 기록되지 않은 젬입니다.")


def gem_star_text(gem: dict[str, Any]) -> str:
    star = max(0, min(5, int(gem.get("star", 0) or 0)))
    return "★" * star + "☆" * (5 - star)


def gem_detail_text(
    gem: dict[str, Any],
    artifact: dict[str, Any] | None = None,
) -> str:
    category = str(gem.get("category", "unknown"))
    lines = [
        f"**{gem_star_text(gem)} {gem.get('name', '젬')}**",
        f"계열: {CATEGORY_LABELS.get(category, category)}",
        f"고유능력: {gem_summary(gem)}",
        (
            f"현재 수치: 고유 효과 **{int(gem.get('effect_value', 0))}** · "
            f"보조 수치 **{int(gem.get('stat_value', 0))}**"
        ),
    ]
    target = gem.get("target_special")
    if target:
        lines.append(f"전용 대상: {TARGET_SPECIAL_LABELS.get(target, target)} 아티팩트")
    star = max(0, min(5, int(gem.get("star", 0) or 0)))
    if star >= 5:
        lines.append("성급 특수 단계: 3성·5성 강화 활성")
    elif star >= 3:
        lines.append("성급 특수 단계: 3성 강화 활성 · 5성 강화 미해금")
    else:
        lines.append("성급 특수 단계: 기본 능력 · 3성/5성 강화 미해금")
    if artifact is not None:
        lines.append(f"현재 아티팩트: {'장착 가능' if gem_compatible(artifact, gem) else '장착 불가'}")
    if gem.get("crafted_by"):
        lines.append(f"세공 담당: {gem['crafted_by']}")
    return "\n".join(lines)


def artifact_socket_count(artifact: dict[str, Any]) -> int:
    return max(1, min(3, int(artifact.get("rank", artifact.get("rank_level", 1)) or 1)))


def gem_compatible(artifact: dict[str, Any], gem: dict[str, Any]) -> bool:
    category = gem.get("category")
    if category in {"combat_common", "life"}:
        return True
    special = artifact.get("special")
    if special in CHARACTER_SPECIALS:
        return False
    return category == "dedicated" and gem.get("target_special") == special


def equip_gem(user_data, artifact, gem_id, socket_index):
    life = ensure_life_data(user_data)
    gem = next((g for g in life["gems"] if g.get("id") == gem_id), None)
    if not gem:
        return False, "젬을 찾을 수 없습니다."
    if not gem_compatible(artifact, gem):
        return False, "이 아티팩트에는 해당 젬을 장착할 수 없습니다."
    sockets = artifact.setdefault("gems", [None] * artifact_socket_count(artifact))
    sockets.extend([None] * (artifact_socket_count(artifact) - len(sockets)))
    if not (0 <= int(socket_index) < artifact_socket_count(artifact)):
        return False, "잘못된 소켓입니다."
    if any(s and s.get("name") == gem["name"] for s in sockets):
        return False, "같은 이름의 젬은 하나만 장착할 수 있습니다."
    for art in user_data.get("artifacts", []):
        for i, equipped in enumerate(art.get("gems", [])):
            if equipped and equipped.get("id") == gem_id:
                art["gems"][i] = None
    sockets[int(socket_index)] = dict(gem)
    return True, f"{socket_index + 1}번 소켓에 {gem['name']}을 장착했습니다."


def unequip_gem(artifact, socket_index):
    sockets = artifact.setdefault("gems", [None] * artifact_socket_count(artifact))
    if not (0 <= int(socket_index) < len(sockets)) or not sockets[int(socket_index)]:
        return False, "비어 있는 소켓입니다."
    name = sockets[int(socket_index)]["name"]
    sockets[int(socket_index)] = None
    return True, f"{name}을 해제했습니다."


class GemManagerView(discord.ui.View):
    GEMS_PER_PAGE = 25

    def __init__(self, author, user_data, save_func, char_index=0):
        super().__init__(timeout=180)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.char_index = max(0, int(char_index))
        self.selected_artifact_id = None
        self.selected_socket = 0
        self.selected_gem_id = None
        self.gem_page = 0

        equipped = self._character_artifact()
        artifacts = self.user_data.get("artifacts", [])
        if equipped and equipped.get("id"):
            self.selected_artifact_id = equipped["id"]
        elif artifacts:
            self.selected_artifact_id = artifacts[0].get("id")
        gems = ensure_life_data(self.user_data).get("gems", [])
        if gems:
            self.selected_gem_id = gems[0].get("id")
        self._rebuild_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "본인의 젬만 관리할 수 있습니다.",
                ephemeral=True,
            )
            return False
        return True

    def _character_artifact(self):
        chars = self.user_data.get("characters", [])
        if not chars or self.char_index >= len(chars):
            return None
        return chars[self.char_index].get("equipped_artifact") or chars[self.char_index].get("equipped_engraved_artifact")

    def _artifact(self):
        artifacts = self.user_data.get("artifacts", [])
        return next(
            (artifact for artifact in artifacts
             if str(artifact.get("id")) == str(self.selected_artifact_id)),
            None,
        )

    def _selected_gem(self):
        gems = ensure_life_data(self.user_data).get("gems", [])
        return next(
            (gem for gem in gems if str(gem.get("id")) == str(self.selected_gem_id)),
            None,
        )

    def _life_hub_factory(self):
        from life_overhaul_v5 import LifeHubView
        return LifeHubView(self.author, self.user_data, self.save_func)

    async def _save(self):
        try:
            await self.save_func(self.user_data)
        except TypeError:
            await self.save_func(self.author.id, self.user_data)

    def _rebuild_components(self):
        self.clear_items()
        artifacts = self.user_data.get("artifacts", [])
        if artifacts:
            if not self._artifact():
                self.selected_artifact_id = artifacts[0].get("id")
            artifact_select = discord.ui.Select(
                placeholder="아티팩트 선택",
                row=0,
                options=[
                    discord.SelectOption(
                        label=str(art.get("name", "아티팩트"))[:100],
                        value=str(art.get("id")),
                        default=str(art.get("id")) == str(self.selected_artifact_id),
                        description=f"{artifact_socket_count(art)}소켓 · +{art.get('level', 0)}",
                    )
                    for art in artifacts[:25]
                    if art.get("id") is not None
                ],
            )
            artifact_select.callback = self._select_artifact
            self.add_item(artifact_select)

        artifact = self._artifact()
        life = ensure_life_data(self.user_data)
        gems = list(life.get("gems", []))

        if artifact:
            socket_count = artifact_socket_count(artifact)
            self.selected_socket = min(self.selected_socket, socket_count - 1)
            sockets = artifact.setdefault("gems", [None] * socket_count)
            sockets.extend([None] * (socket_count - len(sockets)))
            socket_select = discord.ui.Select(
                placeholder="소켓 선택",
                row=1,
                options=[
                    discord.SelectOption(
                        label=(
                            f"{index + 1}번 · {sockets[index].get('name', '젬')}"
                            if sockets[index] else f"{index + 1}번 소켓 · 비어 있음"
                        )[:100],
                        value=str(index),
                        default=index == self.selected_socket,
                    )
                    for index in range(socket_count)
                ],
            )
            socket_select.callback = self._select_socket
            self.add_item(socket_select)

        if gems:
            valid_ids = {str(gem.get("id")) for gem in gems}
            if str(self.selected_gem_id) not in valid_ids:
                self.selected_gem_id = gems[0].get("id")
                self.gem_page = 0

            total_pages = max(1, (len(gems) + self.GEMS_PER_PAGE - 1) // self.GEMS_PER_PAGE)
            self.gem_page = min(max(0, self.gem_page), total_pages - 1)
            start = self.gem_page * self.GEMS_PER_PAGE
            page_gems = gems[start:start + self.GEMS_PER_PAGE]
            gem_select = discord.ui.Select(
                placeholder="상세히 볼 젬 선택",
                row=2 if artifact else 0,
                options=[
                    discord.SelectOption(
                        label=(
                            f"{gem_star_text(gem)} {gem.get('name', '젬')} "
                            f"· 효과 {int(gem.get('effect_value', 0))}"
                        )[:100],
                        value=str(gem.get("id")),
                        default=str(gem.get("id")) == str(self.selected_gem_id),
                        description=(
                            f"{'장착 가능' if artifact and gem_compatible(artifact, gem) else '상세 보기'}"
                            f" · {gem_summary(gem)}"
                        )[:100],
                    )
                    for gem in page_gems
                ],
            )
            gem_select.callback = self._select_gem
            self.add_item(gem_select)

        selected_gem = self._selected_gem()
        equip_button = discord.ui.Button(
            label="선택 젬 장착",
            style=discord.ButtonStyle.success,
            row=3,
            disabled=not bool(
                artifact and selected_gem and gem_compatible(artifact, selected_gem)
            ),
        )
        equip_button.callback = self._equip
        self.add_item(equip_button)

        sockets = artifact.get("gems", []) if artifact else []
        unequip_button = discord.ui.Button(
            label="현재 소켓 해제",
            style=discord.ButtonStyle.danger,
            row=3,
            disabled=not bool(
                artifact
                and 0 <= self.selected_socket < len(sockets)
                and sockets[self.selected_socket]
            ),
        )
        unequip_button.callback = self._unequip
        self.add_item(unequip_button)

        if gems:
            total_pages = max(1, (len(gems) + self.GEMS_PER_PAGE - 1) // self.GEMS_PER_PAGE)
            previous = discord.ui.Button(
                label="◀",
                style=discord.ButtonStyle.secondary,
                row=3,
                disabled=self.gem_page == 0,
            )
            previous.callback = self._previous_gem_page
            self.add_item(previous)
            page_indicator = discord.ui.Button(
                label=f"{self.gem_page + 1}/{total_pages}",
                style=discord.ButtonStyle.secondary,
                row=3,
                disabled=True,
            )
            self.add_item(page_indicator)
            following = discord.ui.Button(
                label="▶",
                style=discord.ButtonStyle.secondary,
                row=3,
                disabled=self.gem_page >= total_pages - 1,
            )
            following.callback = self._next_gem_page
            self.add_item(following)

        attach_navigation(
            self,
            self.author,
            self._life_hub_factory,
            back_label="생활 관리로",
        )

    async def _select_artifact(self, interaction):
        self.selected_artifact_id = interaction.data["values"][0]
        self.selected_socket = 0
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _select_socket(self, interaction):
        self.selected_socket = int(interaction.data["values"][0])
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _select_gem(self, interaction):
        self.selected_gem_id = interaction.data["values"][0]
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _previous_gem_page(self, interaction):
        self.gem_page = max(0, self.gem_page - 1)
        gems = ensure_life_data(self.user_data).get("gems", [])
        if gems:
            self.selected_gem_id = gems[self.gem_page * self.GEMS_PER_PAGE].get("id")
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _next_gem_page(self, interaction):
        gems = ensure_life_data(self.user_data).get("gems", [])
        total_pages = max(1, (len(gems) + self.GEMS_PER_PAGE - 1) // self.GEMS_PER_PAGE)
        self.gem_page = min(total_pages - 1, self.gem_page + 1)
        if gems:
            self.selected_gem_id = gems[self.gem_page * self.GEMS_PER_PAGE].get("id")
        self._rebuild_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def _equip(self, interaction):
        artifact = self._artifact()
        if not artifact or not self._selected_gem():
            return await interaction.response.send_message(
                "아티팩트와 젬을 먼저 선택하세요.",
                ephemeral=True,
            )
        ok, message = equip_gem(
            self.user_data,
            artifact,
            self.selected_gem_id,
            self.selected_socket,
        )
        if ok:
            await self._save()
        self._rebuild_components()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    async def _unequip(self, interaction):
        artifact = self._artifact()
        if not artifact:
            return await interaction.response.send_message(
                "아티팩트를 먼저 선택하세요.",
                ephemeral=True,
            )
        ok, message = unequip_gem(artifact, self.selected_socket)
        if ok:
            await self._save()
        self._rebuild_components()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    def get_embed(self):
        art = self._artifact()
        gems = ensure_life_data(self.user_data).get("gems", [])
        e = discord.Embed(title="💎 젬 상세·장착", color=discord.Color.purple())

        if art:
            sockets = art.setdefault("gems", [None] * artifact_socket_count(art))
            sockets.extend([None] * (artifact_socket_count(art) - len(sockets)))
            lines = [
                f"{'▶ ' if i == self.selected_socket else ''}{i + 1}. "
                + (
                    f"{gem_star_text(gem)} {gem.get('name', '젬')}"
                    if gem else "비어 있음"
                )
                for i, gem in enumerate(sockets[:artifact_socket_count(art)])
            ]
            e.description = (
                f"**{art.get('name', '아티팩트')}** · {artifact_socket_count(art)}소켓\n"
                + "\n".join(lines)
            )
            equipped = (
                sockets[self.selected_socket]
                if 0 <= self.selected_socket < len(sockets) else None
            )
            if equipped:
                e.add_field(
                    name=f"현재 {self.selected_socket + 1}번 소켓",
                    value=gem_detail_text(equipped, art)[:1024],
                    inline=False,
                )
        else:
            e.description = (
                "장착할 아티팩트가 없습니다. 보유 젬의 고유능력은 아래에서 확인할 수 있습니다."
            )

        selected_gem = self._selected_gem()
        if selected_gem:
            e.add_field(
                name="선택한 보유 젬",
                value=gem_detail_text(selected_gem, art)[:1024],
                inline=False,
            )
        elif not gems:
            e.add_field(
                name="보유 젬",
                value="완성한 젬이 없습니다.",
                inline=False,
            )

        total_pages = max(1, (len(gems) + self.GEMS_PER_PAGE - 1) // self.GEMS_PER_PAGE)
        e.set_footer(
            text=(
                f"보유 젬 {len(gems)}개 · 젬 목록 {self.gem_page + 1}/{total_pages}페이지 · "
                "젬을 선택하면 고유능력과 현재 수치를 바로 확인합니다."
            )
        )
        return e
