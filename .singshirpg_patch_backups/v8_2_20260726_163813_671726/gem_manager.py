# gem-link-v7.3-manager
# rollback-guard-appraisal-gems-v8
# appraisal-gem-affixes-v8.1
from __future__ import annotations

import copy
from typing import Any
import uuid

import discord

from character import (
    GEM_MAIN_STAT_LABELS,
    artifact_effective_stats,
    artifact_primary_stat_key,
    ensure_gem_stat_affixes,
    gem_main_stat_text,
)
from life_system import STONE_GEMS, ensure_life_data
from navigation_v7 import attach_navigation


ITEMS_PER_PAGE = 8

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

GEM_FILTERS = (
    ("all", "전체"),
    ("combat_common", "전투 공용"),
    ("dedicated", "아티팩트 전용"),
    ("life", "생활"),
    ("equipped", "장착 중"),
    ("unequipped", "미장착"),
)

ARTIFACT_FILTERS = (
    ("all", "전체"),
    ("equipped", "장착 중"),
    ("unequipped", "미장착"),
    ("rank_1", "1성"),
    ("rank_2", "2성"),
    ("rank_3", "3성"),
    ("character", "전용·각인"),
)


def gem_definition(gem: dict[str, Any]) -> dict[str, Any] | None:
    for stone_name, definitions in STONE_GEMS.items():
        for definition in definitions:
            if definition.get("name") != gem.get("name"):
                continue
            if gem.get("category") and definition.get("category") != gem.get("category"):
                continue
            if gem.get("target_special") and definition.get("target_special") != gem.get("target_special"):
                continue
            result = dict(definition)
            result.setdefault("stone", stone_name)
            return result
    return None


def gem_summary(gem: dict[str, Any]) -> str:
    definition = gem_definition(gem)
    return str(gem.get("summary") or (definition or {}).get("summary") or "상세 효과가 기록되지 않은 젬입니다.")


def gem_stone_name(gem: dict[str, Any]) -> str:
    definition = gem_definition(gem)
    return str(gem.get("stone") or (definition or {}).get("stone") or "계열 미상")


def gem_star_text(gem: dict[str, Any]) -> str:
    star = max(0, min(5, int(gem.get("star", 0) or 0)))
    return "★" * star + "☆" * (5 - star)


def gem_applied_effect_lines(gem: dict[str, Any]) -> list[str]:
    """Describe the numeric effect that the current runtime actually applies."""
    gem = ensure_gem_stat_affixes(gem)
    name = str(gem.get("name", ""))
    effect = max(0, int(gem.get("effect_value", 0) or 0))
    auxiliary = max(0, int(gem.get("aux_stat_value", 0) or 0))
    star = max(0, min(5, int(gem.get("star", 0) or 0)))

    lines_by_name = {
        "격화의 젬": [f"맹렬한 발동의 추가 주사위 위력 **+{effect}**"],
        "맥박의 젬": [f"견고한 발동의 체력 회복량 **+{effect}**"],
        "가시의 젬": [f"앙심품은 발동의 반사 피해 **+{effect}**"],
        "선봉의 젬": [f"매 턴 첫 유효 주사위 위력 **+{effect}**"],
        "집중의 젬": [f"유효 주사위가 1개인 카드의 주사위 위력 **+{effect}**"],
        "연격의 젬": [
            f"같은 카드의 두 번째 공격 주사위 위력 **+{effect}**",
            f"세 번째 이후 공격 주사위 위력 **+{effect + 2}**",
        ],
        "결의의 젬": [
            (
                f"정신력 **{'50' if star >= 2 else '40'}% 이하**일 때 "
                f"모든 유효 주사위 위력 **+{effect}**"
            )
        ],
        "수호의 젬": [
            f"매 턴 처음 받는 실피해 **{min(40, effect)}% 감소**"
        ],
        "풍요의 젬": [
            f"채소·양식 수확물 1개마다 추가 획득 확률 **{effect}%**",
            *(
                ["최종 품질 85 이상이면 수확량 **+1**"]
                if star >= 5 else []
            ),
        ],
        "경작의 젬": [f"채소 수확의 최종 품질 점수 **+{effect}**"],
        "관개의 젬": [
            f"물주기 수분 회복량 **+{effect}** (기본 25 → **{25 + effect}**)",
            *(
                ["과습 시 건강 감소를 방지"]
                if star >= 3 else []
            ),
        ],
        "청류의 젬": [
            f"물갈이·청소의 수질 회복량 **+{effect}**",
            *(
                ["매 행동의 자연 수질 감소 **-1**"]
                if star >= 2 else []
            ),
            *(
                ["수질 악화 질병을 양식 1회당 **1회 방지**"]
                if star >= 3 else []
            ),
            *(
                ["출하 시 수질 75 이상이면 품질 점수 **+6**"]
                if star >= 5 else []
            ),
        ],
        "양식의 젬": [
            f"적정 수질일 때 행동당 성장도 **+{effect}**",
            *(
                ["먹이 주기의 수질 감소 8 → **6**"]
                if star == 2 else []
            ),
            *(
                ["첫 먹이 주기의 수질 감소 **0**"]
                if star >= 3 else []
            ),
            *(
                ["출하 수량 **+1** 확률 25%"]
                if star >= 5 else []
            ),
        ],
        "장인의 젬": [
            f"마법부여·모양 내기·불순물 제거 성공률 **+{effect + star}%p**"
        ],
        "조리의 젬": [
            (
                f"요리 품질 판정 보너스 **+{effect + star}** "
                "(훌륭함·걸작 가중치 증가)"
            )
        ],
    }
    lines = list(lines_by_name.get(name, []))

    if name == "정화의 젬" and gem.get("category") == "combat_common":
        if star >= 5:
            lines.append("5성 상태이상 전부 제거 효과는 정의되어 있으나 전투 호출 지점은 미연결")
        else:
            lines.append("상태이상 지속시간 감소 효과는 현재 전투 계산에 미연결")
    elif name == "고양의 젬":
        lines.append(f"고조된 보너스 최솟값 +{effect} 수치는 정의되어 있으나 전투 호출 지점은 미연결")
    elif not lines:
        lines.append("현재 수치 보정이 실제 전투·생활 계산에 아직 연결되지 않음")

    lines.append(f"주 능력 보정: **{gem_main_stat_text(gem)}**")
    if auxiliary:
        lines.append(
            f"보조 능력 **+{auxiliary}**: 장착한 아티팩트의 "
            "주 능력치에 상수로 먼저 적용"
        )
    return lines


def gem_applied_effect_summary(gem: dict[str, Any]) -> str:
    line = gem_applied_effect_lines(gem)[0]
    return line.replace("**", "")


def artifact_socket_count(artifact: dict[str, Any]) -> int:
    return max(1, min(3, int(artifact.get("rank", artifact.get("rank_level", 1)) or 1)))


def artifact_entry_key(artifact: dict[str, Any], char_index: int | None = None, slot: str = "") -> str:
    artifact_id = artifact.get("id")
    if artifact_id is not None:
        return f"id:{artifact_id}"
    if char_index is not None:
        return f"char:{char_index}:{slot}"
    return f"object:{id(artifact)}"


def artifact_entries(user_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return inventory and engraved artifacts once, with their current wearer."""
    owner_by_id: dict[str, str] = {}
    owner_by_object: dict[int, str] = {}
    source_by_object: dict[int, tuple[int, str]] = {}
    characters = user_data.get("characters", [])

    for char_index, character in enumerate(characters):
        char_name = str(character.get("name", f"캐릭터 {char_index + 1}"))
        for slot in ("equipped_artifact", "equipped_engraved_artifact"):
            artifact = character.get(slot)
            if not isinstance(artifact, dict):
                continue
            if artifact.get("id") is None:
                artifact["id"] = f"legacy-artifact-{uuid.uuid4().hex}"
            if not isinstance(artifact.get("gems"), list):
                artifact["gems"] = []
            if artifact.get("id") is not None:
                owner_by_id[str(artifact["id"])] = char_name
            owner_by_object[id(artifact)] = char_name
            source_by_object[id(artifact)] = (char_index, slot)

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact in user_data.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        if artifact.get("id") is None:
            artifact["id"] = f"legacy-artifact-{uuid.uuid4().hex}"
        if not isinstance(artifact.get("gems"), list):
            artifact["gems"] = []
        key = artifact_entry_key(artifact)
        if key in seen:
            continue
        seen.add(key)
        owner = owner_by_id.get(str(artifact.get("id"))) or owner_by_object.get(id(artifact))
        result.append({"key": key, "artifact": artifact, "owner": owner, "slot": "inventory"})

    for char_index, character in enumerate(characters):
        for slot in ("equipped_artifact", "equipped_engraved_artifact"):
            artifact = character.get(slot)
            if not isinstance(artifact, dict):
                continue
            key = artifact_entry_key(artifact, char_index, slot)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "key": key,
                "artifact": artifact,
                "owner": owner_by_object.get(id(artifact)),
                "slot": slot,
            })
    return result


def artifact_owner(user_data: dict[str, Any], artifact: dict[str, Any]) -> str | None:
    target_id = artifact.get("id")
    for entry in artifact_entries(user_data):
        candidate = entry["artifact"]
        if candidate is artifact or (
            target_id is not None and str(candidate.get("id")) == str(target_id)
        ):
            return entry.get("owner")
    return None


def gem_compatible(artifact: dict[str, Any], gem: dict[str, Any]) -> bool:
    category = gem.get("category")
    if category in {"combat_common", "life"}:
        return True
    special = artifact.get("special")
    if special in CHARACTER_SPECIALS:
        return False
    return category == "dedicated" and gem.get("target_special") == special


def gem_locations(user_data: dict[str, Any], gem_id: Any) -> list[tuple[dict[str, Any], int, str | None]]:
    result = []
    for entry in artifact_entries(user_data):
        artifact = entry["artifact"]
        for index, equipped in enumerate(artifact.get("gems", [])):
            if isinstance(equipped, dict) and str(equipped.get("id")) == str(gem_id):
                result.append((artifact, index, entry.get("owner")))
    return result


def equip_gem(user_data, artifact, gem_id, socket_index):
    life = ensure_life_data(user_data)
    gem = next((g for g in life["gems"] if str(g.get("id")) == str(gem_id)), None)
    if not gem:
        return False, "젬을 찾을 수 없습니다."
    if not gem_compatible(artifact, gem):
        return False, "이 아티팩트에는 해당 젬을 장착할 수 없습니다."

    socket_count = artifact_socket_count(artifact)
    if not (0 <= int(socket_index) < socket_count):
        return False, "잘못된 소켓입니다."
    sockets = artifact.setdefault("gems", [None] * socket_count)
    sockets.extend([None] * (socket_count - len(sockets)))
    if any(
        equipped
        and equipped.get("name") == gem.get("name")
        and str(equipped.get("id")) != str(gem_id)
        for equipped in sockets
    ):
        return False, "같은 이름의 젬은 하나만 장착할 수 있습니다."

    for entry in artifact_entries(user_data):
        other = entry["artifact"]
        for index, equipped in enumerate(other.get("gems", [])):
            if isinstance(equipped, dict) and str(equipped.get("id")) == str(gem_id):
                other["gems"][index] = None
    sockets[int(socket_index)] = dict(gem)
    return True, f"{socket_index + 1}번 소켓에 {gem['name']}을 장착했습니다."


def unequip_gem(artifact, socket_index):
    sockets = artifact.setdefault("gems", [None] * artifact_socket_count(artifact))
    if not (0 <= int(socket_index) < len(sockets)) or not sockets[int(socket_index)]:
        return False, "비어 있는 소켓입니다."
    name = sockets[int(socket_index)]["name"]
    sockets[int(socket_index)] = None
    return True, f"{name}을 해제했습니다."


def gem_detail_text(gem: dict[str, Any], user_data: dict[str, Any] | None = None) -> str:
    category = str(gem.get("category", "unknown"))
    lines = [
        f"**{gem_star_text(gem)} {gem.get('name', '젬')}**",
        f"원석 계열: {gem_stone_name(gem)}",
        f"분류: {CATEGORY_LABELS.get(category, category)}",
        f"고유능력: {gem_summary(gem)}",
        "",
        "**현재 실제 적용 효과**",
        *(f"• {line}" for line in gem_applied_effect_lines(gem)),
    ]
    target = gem.get("target_special")
    if target:
        lines.append(f"전용 대상: {TARGET_SPECIAL_LABELS.get(target, target)} 아티팩트")
    star = max(0, min(5, int(gem.get("star", 0) or 0)))
    if star >= 5:
        lines.append("성급 강화: 3성·5성 특수능력 활성")
    elif star >= 3:
        lines.append("성급 강화: 3성 특수능력 활성 · 5성 미해금")
    else:
        lines.append("성급 강화: 기본 능력 · 3성/5성 미해금")
    if user_data is not None:
        locations = gem_locations(user_data, gem.get("id"))
        if locations:
            artifact, socket, owner = locations[0]
            wearer = f" · 장착자 {owner}" if owner else ""
            lines.append(f"장착 위치: {artifact.get('name', '아티팩트')} {socket + 1}번 소켓{wearer}")
        else:
            lines.append("장착 위치: 미장착")
    if gem.get("crafted_by"):
        lines.append(f"세공 담당: {gem['crafted_by']}")
    return "\n".join(lines)


class _OwnedView(discord.ui.View):
    def __init__(self, author, user_data, save_func, timeout=300):
        super().__init__(timeout=timeout)
        self.author, self.user_data, self.save_func = author, user_data, save_func

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 장비만 관리할 수 있습니다.", ephemeral=True)
        return False

    async def _save(self):
        try:
            await self.save_func(self.author.id, self.user_data)
        except TypeError:
            await self.save_func(self.user_data)

    def _life_hub_factory(self):
        from life_overhaul_v5 import LifeHubView
        return LifeHubView(self.author, self.user_data, self.save_func)


class GemManagerView(_OwnedView):
    """Gem collection view. Artifact/socket selection is handled on a second screen."""

    def __init__(self, author, user_data, save_func, selected_gem_id=None):
        super().__init__(author, user_data, save_func)
        self.category = "all"
        self.page = 0
        gems = ensure_life_data(user_data).get("gems", [])
        self.selected_gem_id = selected_gem_id or (gems[0].get("id") if gems else None)
        self._rebuild_components()

    def _all_gems(self):
        return sorted(
            ensure_life_data(self.user_data).get("gems", []),
            key=lambda gem: (
                str(gem.get("category", "")),
                str(gem.get("name", "")),
                -int(gem.get("star", 0) or 0),
            ),
        )

    def _filtered_gems(self):
        gems = self._all_gems()
        if self.category in {"combat_common", "dedicated", "life"}:
            return [gem for gem in gems if gem.get("category") == self.category]
        if self.category == "equipped":
            return [gem for gem in gems if gem_locations(self.user_data, gem.get("id"))]
        if self.category == "unequipped":
            return [gem for gem in gems if not gem_locations(self.user_data, gem.get("id"))]
        return gems

    def _selected(self):
        return next(
            (gem for gem in self._all_gems() if str(gem.get("id")) == str(self.selected_gem_id)),
            None,
        )

    def _sync_selection(self):
        gems = self._filtered_gems()
        total_pages = max(1, (len(gems) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        self.page = min(max(0, self.page), total_pages - 1)
        page_gems = gems[self.page * ITEMS_PER_PAGE:(self.page + 1) * ITEMS_PER_PAGE]
        if not any(str(g.get("id")) == str(self.selected_gem_id) for g in page_gems):
            self.selected_gem_id = page_gems[0].get("id") if page_gems else None
        return gems, page_gems, total_pages

    def _rebuild_components(self):
        self.clear_items()
        gems, page_gems, total_pages = self._sync_selection()

        category_options = []
        all_gems = self._all_gems()
        for key, label in GEM_FILTERS:
            if key == "all":
                count = len(all_gems)
            elif key in {"combat_common", "dedicated", "life"}:
                count = sum(g.get("category") == key for g in all_gems)
            elif key == "equipped":
                count = sum(bool(gem_locations(self.user_data, g.get("id"))) for g in all_gems)
            else:
                count = sum(not gem_locations(self.user_data, g.get("id")) for g in all_gems)
            category_options.append(discord.SelectOption(
                label=label,
                value=key,
                description=f"{count}개",
                default=key == self.category,
            ))
        category_select = discord.ui.Select(placeholder="젬 종류", options=category_options, row=0)
        category_select.callback = self._select_category
        self.add_item(category_select)

        if page_gems:
            gem_select = discord.ui.Select(
                placeholder=f"젬 선택 · 페이지당 {ITEMS_PER_PAGE}개",
                row=1,
                options=[
                    discord.SelectOption(
                        label=f"{gem_star_text(gem)} {gem.get('name', '젬')}"[:100],
                        value=str(gem.get("id")),
                        description=(
                            f"{gem_stone_name(gem)} · "
                            f"{'장착 중' if gem_locations(self.user_data, gem.get('id')) else '미장착'} · "
                            f"{gem_applied_effect_summary(gem)}"
                        )[:100],
                        default=str(gem.get("id")) == str(self.selected_gem_id),
                    )
                    for gem in page_gems
                ],
            )
            gem_select.callback = self._select_gem
            self.add_item(gem_select)

        self._add_page_buttons(total_pages)
        selected = self._selected()
        attach_button = discord.ui.Button(
            label="아티팩트에 장착",
            emoji="🔩",
            style=discord.ButtonStyle.success,
            row=3,
            disabled=selected is None,
        )
        attach_button.callback = self._open_equip
        self.add_item(attach_button)
        detach_button = discord.ui.Button(
            label="현재 위치에서 해제",
            style=discord.ButtonStyle.danger,
            row=3,
            disabled=not bool(selected and gem_locations(self.user_data, selected.get("id"))),
        )
        detach_button.callback = self._detach_selected
        self.add_item(detach_button)

        attach_navigation(self, self.author, self._life_hub_factory, back_label="생활 관리로")

    def _add_page_buttons(self, total_pages):
        previous = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=2, disabled=self.page == 0)
        previous.callback = self._previous_page
        self.add_item(previous)
        self.add_item(discord.ui.Button(
            label=f"{self.page + 1}/{total_pages} · 총 {len(self._filtered_gems())}개",
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

    async def _select_category(self, interaction):
        self.category = interaction.data["values"][0]
        self.page = 0
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _select_gem(self, interaction):
        self.selected_gem_id = interaction.data["values"][0]
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _previous_page(self, interaction):
        self.page = max(0, self.page - 1)
        self.selected_gem_id = None
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _next_page(self, interaction):
        self.page += 1
        self.selected_gem_id = None
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _open_equip(self, interaction):
        gem = self._selected()
        if not gem:
            return await interaction.response.send_message("젬을 먼저 선택하세요.", ephemeral=True)
        view = GemEquipArtifactView(
            self.author, self.user_data, self.save_func, gem.get("id")
        )
        await interaction.response.edit_message(content=None, embed=view.get_embed(), view=view)

    async def _detach_selected(self, interaction):
        gem = self._selected()
        locations = gem_locations(self.user_data, gem.get("id")) if gem else []
        if not locations:
            return await interaction.response.send_message("이 젬은 장착되어 있지 않습니다.", ephemeral=True)
        artifact, socket, _ = locations[0]
        ok, message = unequip_gem(artifact, socket)
        if ok:
            await self._save()
        self._rebuild_components()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    def get_embed(self):
        gems = self._filtered_gems()
        selected = self._selected()
        label = dict(GEM_FILTERS).get(self.category, self.category)
        embed = discord.Embed(
            title="💎 젬 관리",
            description=f"분류: **{label}** · 페이지당 {ITEMS_PER_PAGE}개",
            color=discord.Color.purple(),
        )
        if selected:
            embed.add_field(name="선택 젬", value=gem_detail_text(selected, self.user_data), inline=False)
        elif not gems:
            embed.add_field(name="보유 젬", value="이 분류에 표시할 젬이 없습니다.", inline=False)
        embed.set_footer(text="젬 상세 확인과 장착·해제를 한곳에서 관리합니다.")
        return embed


class GemEquipArtifactView(_OwnedView):
    """Choose an artifact in an 8-item categorized list, then choose its socket."""

    def __init__(self, author, user_data, save_func, gem_id):
        super().__init__(author, user_data, save_func)
        self.gem_id = gem_id
        self.category = "all"
        self.page = 0
        self.selected_artifact_key = None
        self.selected_socket = 0
        self._rebuild_components()

    def _gem(self):
        return next(
            (
                gem for gem in ensure_life_data(self.user_data).get("gems", [])
                if str(gem.get("id")) == str(self.gem_id)
            ),
            None,
        )

    def _all_entries(self):
        return sorted(
            artifact_entries(self.user_data),
            key=lambda entry: (
                0 if entry.get("owner") else 1,
                -artifact_socket_count(entry["artifact"]),
                str(entry["artifact"].get("name", "")),
            ),
        )

    def _filtered_entries(self):
        entries = self._all_entries()
        if self.category == "equipped":
            return [entry for entry in entries if entry.get("owner")]
        if self.category == "unequipped":
            return [entry for entry in entries if not entry.get("owner")]
        if self.category.startswith("rank_"):
            rank = int(self.category[-1])
            return [entry for entry in entries if artifact_socket_count(entry["artifact"]) == rank]
        if self.category == "character":
            return [
                entry for entry in entries
                if entry["artifact"].get("special") in CHARACTER_SPECIALS
                or entry["artifact"].get("effect_scope") == "character"
                or entry.get("slot") == "equipped_engraved_artifact"
            ]
        return entries

    def _entry(self):
        return next(
            (entry for entry in self._all_entries() if entry["key"] == self.selected_artifact_key),
            None,
        )

    def _sync_selection(self):
        entries = self._filtered_entries()
        total_pages = max(1, (len(entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        self.page = min(max(0, self.page), total_pages - 1)
        page_entries = entries[self.page * ITEMS_PER_PAGE:(self.page + 1) * ITEMS_PER_PAGE]
        if not any(entry["key"] == self.selected_artifact_key for entry in page_entries):
            self.selected_artifact_key = page_entries[0]["key"] if page_entries else None
            self.selected_socket = 0
        return entries, page_entries, total_pages

    def _rebuild_components(self):
        self.clear_items()
        entries, page_entries, total_pages = self._sync_selection()

        options = []
        all_entries = self._all_entries()
        for key, label in ARTIFACT_FILTERS:
            old_category = self.category
            self.category = key
            count = len(self._filtered_entries())
            self.category = old_category
            options.append(discord.SelectOption(
                label=label,
                value=key,
                description=f"{count}개",
                default=key == self.category,
            ))
        category_select = discord.ui.Select(placeholder="아티팩트 종류", options=options, row=0)
        category_select.callback = self._select_category
        self.add_item(category_select)

        if page_entries:
            artifact_select = discord.ui.Select(
                placeholder=f"장착 대상 선택 · 페이지당 {ITEMS_PER_PAGE}개",
                row=1,
                options=[
                    discord.SelectOption(
                        label=str(entry["artifact"].get("name", "아티팩트"))[:100],
                        value=entry["key"],
                        description=(
                            f"{artifact_socket_count(entry['artifact'])}소켓 · "
                            f"{'장착자 ' + entry['owner'] if entry.get('owner') else '미장착'} · "
                            f"{'호환' if self._gem() and gem_compatible(entry['artifact'], self._gem()) else '장착 불가'}"
                        )[:100],
                        default=entry["key"] == self.selected_artifact_key,
                    )
                    for entry in page_entries
                ],
            )
            artifact_select.callback = self._select_artifact
            self.add_item(artifact_select)

        previous = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, row=2, disabled=self.page == 0)
        previous.callback = self._previous_page
        self.add_item(previous)
        self.add_item(discord.ui.Button(
            label=f"{self.page + 1}/{total_pages} · 총 {len(entries)}개",
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

        entry = self._entry()
        artifact = entry["artifact"] if entry else None
        if artifact:
            socket_count = artifact_socket_count(artifact)
            self.selected_socket = min(self.selected_socket, socket_count - 1)
            sockets = artifact.setdefault("gems", [None] * socket_count)
            sockets.extend([None] * (socket_count - len(sockets)))
            socket_select = discord.ui.Select(
                placeholder="장착할 소켓",
                row=3,
                options=[
                    discord.SelectOption(
                        label=(
                            f"{index + 1}번 · {sockets[index].get('name', '젬')}"
                            if sockets[index] else f"{index + 1}번 · 비어 있음"
                        )[:100],
                        value=str(index),
                        default=index == self.selected_socket,
                    )
                    for index in range(socket_count)
                ],
            )
            socket_select.callback = self._select_socket
            self.add_item(socket_select)

        gem = self._gem()
        equip_button = discord.ui.Button(
            label="선택 소켓에 장착",
            style=discord.ButtonStyle.success,
            row=4,
            disabled=not bool(artifact and gem and gem_compatible(artifact, gem)),
        )
        equip_button.callback = self._equip
        self.add_item(equip_button)
        sockets = artifact.get("gems", []) if artifact else []
        unequip_button = discord.ui.Button(
            label="소켓 해제",
            style=discord.ButtonStyle.danger,
            row=4,
            disabled=not bool(
                artifact
                and self.selected_socket < len(sockets)
                and sockets[self.selected_socket]
            ),
        )
        unequip_button.callback = self._unequip
        self.add_item(unequip_button)
        attach_navigation(
            self,
            self.author,
            lambda: GemManagerView(
                self.author, self.user_data, self.save_func, self.gem_id
            ),
            back_label="젬 목록으로",
        )

    async def _select_category(self, interaction):
        self.category = interaction.data["values"][0]
        self.page = 0
        self.selected_artifact_key = None
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _select_artifact(self, interaction):
        self.selected_artifact_key = interaction.data["values"][0]
        self.selected_socket = 0
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _select_socket(self, interaction):
        self.selected_socket = int(interaction.data["values"][0])
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _previous_page(self, interaction):
        self.page = max(0, self.page - 1)
        self.selected_artifact_key = None
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _next_page(self, interaction):
        self.page += 1
        self.selected_artifact_key = None
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _equip(self, interaction):
        entry = self._entry()
        gem = self._gem()
        if not entry or not gem:
            return await interaction.response.send_message("젬과 아티팩트를 다시 선택하세요.", ephemeral=True)
        ok, message = equip_gem(
            self.user_data, entry["artifact"], self.gem_id, self.selected_socket
        )
        if ok:
            await self._save()
        self._rebuild_components()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    async def _unequip(self, interaction):
        entry = self._entry()
        if not entry:
            return await interaction.response.send_message("아티팩트를 먼저 선택하세요.", ephemeral=True)
        ok, message = unequip_gem(entry["artifact"], self.selected_socket)
        if ok:
            await self._save()
        self._rebuild_components()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    def get_embed(self):
        gem = self._gem()
        entry = self._entry()
        label = dict(ARTIFACT_FILTERS).get(self.category, self.category)
        embed = discord.Embed(
            title="🔩 젬 장착 대상 선택",
            description=(
                f"젬: **{gem_star_text(gem)} {gem.get('name', '젬')}**\n"
                f"아티팩트 분류: **{label}** · 페이지당 {ITEMS_PER_PAGE}개"
                if gem else "선택한 젬을 찾을 수 없습니다."
            ),
            color=discord.Color.blurple(),
        )
        if gem:
            embed.add_field(
                name="현재 실제 적용 효과",
                value="\n".join(f"• {line}" for line in gem_applied_effect_lines(gem)),
                inline=False,
            )
        if entry:
            artifact = entry["artifact"]
            owner = entry.get("owner") or "미장착"
            sockets = artifact.setdefault("gems", [None] * artifact_socket_count(artifact))
            socket_lines = [
                f"{'▶ ' if index == self.selected_socket else ''}{index + 1}. "
                f"{slot.get('name', '젬') if isinstance(slot, dict) else '비어 있음'}"
                for index, slot in enumerate(sockets[:artifact_socket_count(artifact)])
            ]
            embed.add_field(
                name=artifact.get("name", "아티팩트"),
                value=(
                    f"장착자: **{owner}**\n"
                    f"등급/소켓: {artifact_socket_count(artifact)}성 · {artifact_socket_count(artifact)}소켓\n"
                    + "\n".join(socket_lines)
                ),
                inline=False,
            )
            preview_artifact = copy.deepcopy(artifact)
            preview_sockets = preview_artifact.setdefault(
                "gems", [None] * artifact_socket_count(preview_artifact)
            )
            preview_sockets.extend(
                [None] * (artifact_socket_count(preview_artifact) - len(preview_sockets))
            )
            if gem and gem_compatible(preview_artifact, gem):
                preview_sockets[self.selected_socket] = gem
            base_stats = artifact.get("stats", {})
            preview_stats = artifact_effective_stats(preview_artifact)
            primary = artifact_primary_stat_key(preview_artifact)
            stat_lines = []
            for key, base in base_stats.items():
                if not isinstance(base, (int, float)) or base <= 0:
                    continue
                label_name = GEM_MAIN_STAT_LABELS.get(key, key)
                value = preview_stats.get(key, base)
                unit = "%" if key == "defense_rate" else ""
                marker = " (주 능력)" if key == primary else ""
                stat_lines.append(
                    f"{label_name}{marker}: {base}{unit}"
                    + (f" → **{value}{unit}**" if value != base else "")
                )
            embed.add_field(
                name="장착 후 아티팩트 예상 수치",
                value="\n".join(stat_lines) or "표시할 기본 스탯이 없습니다.",
                inline=False,
            )
            if gem:
                embed.add_field(
                    name="호환 여부",
                    value="✅ 장착 가능" if gem_compatible(artifact, gem) else "❌ 이 젬과 호환되지 않음",
                    inline=False,
                )
        return embed
