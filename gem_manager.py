# gem-link-v4-manager
from __future__ import annotations

from typing import Any

import discord

from life_system import ensure_life_data


CHARACTER_SPECIALS = {
    "youngsan_gold", "luude_imprint", "earthreg_faith",
    "sensho_star", "Sensho_star", "kaian_time", "shayla_light",
}


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
    def __init__(self, author, user_data, save_func, char_index=0):
        super().__init__(timeout=180)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.char_index = max(0, int(char_index))
        self.selected_artifact_id = None
        self.selected_socket = 0
        self.selected_gem_id = None

        equipped = self._character_artifact()
        artifacts = self.user_data.get("artifacts", [])
        if equipped and equipped.get("id"):
            self.selected_artifact_id = equipped["id"]
        elif artifacts:
            self.selected_artifact_id = artifacts[0].get("id")
        self._rebuild_components()

    def _character_artifact(self):
        chars = self.user_data.get("characters", [])
        if not chars or self.char_index >= len(chars):
            return None
        return chars[self.char_index].get("equipped_artifact") or chars[self.char_index].get("equipped_engraved_artifact")

    def _artifact(self):
        artifacts = self.user_data.get("artifacts", [])
        return next((a for a in artifacts if a.get("id") == self.selected_artifact_id), None)

    async def _save(self):
        try:
            await self.save_func(self.user_data)
        except TypeError:
            await self.save_func(self.author.id, self.user_data)

    def _rebuild_components(self):
        self.clear_items()
        artifacts = self.user_data.get("artifacts", [])
        if not artifacts:
            return

        artifact_select = discord.ui.Select(
            placeholder="아티팩트 선택",
            row=0,
            options=[
                discord.SelectOption(
                    label=str(art.get("name", "아티팩트"))[:100],
                    value=str(art.get("id")),
                    default=art.get("id") == self.selected_artifact_id,
                    description=f"{artifact_socket_count(art)}소켓 · +{art.get('level', 0)}",
                )
                for art in artifacts[:25]
                if art.get("id") is not None
            ],
        )
        artifact_select.callback = self._select_artifact
        self.add_item(artifact_select)

        artifact = self._artifact()
        if not artifact:
            return
        socket_count = artifact_socket_count(artifact)
        self.selected_socket = min(self.selected_socket, socket_count - 1)
        socket_select = discord.ui.Select(
            placeholder="소켓 선택",
            row=1,
            options=[
                discord.SelectOption(
                    label=f"{index + 1}번 소켓",
                    value=str(index),
                    default=index == self.selected_socket,
                )
                for index in range(socket_count)
            ],
        )
        socket_select.callback = self._select_socket
        self.add_item(socket_select)

        life = ensure_life_data(self.user_data)
        compatible = [gem for gem in life.get("gems", []) if gem_compatible(artifact, gem)]
        if compatible:
            valid_ids = {str(gem.get("id")) for gem in compatible}
            if str(self.selected_gem_id) not in valid_ids:
                self.selected_gem_id = compatible[0].get("id")
            gem_select = discord.ui.Select(
                placeholder="장착할 젬 선택",
                row=2,
                options=[
                    discord.SelectOption(
                        label=str(gem.get("name", "젬"))[:100],
                        value=str(gem.get("id")),
                        default=str(gem.get("id")) == str(self.selected_gem_id),
                        description=f"{gem.get('star', 0)}성 · {gem.get('category', '일반')}",
                    )
                    for gem in compatible[:25]
                ],
            )
            gem_select.callback = self._select_gem
            self.add_item(gem_select)

        equip_button = discord.ui.Button(
            label="선택 젬 장착",
            style=discord.ButtonStyle.success,
            row=3,
            disabled=not compatible,
        )
        equip_button.callback = self._equip
        self.add_item(equip_button)

        sockets = artifact.setdefault("gems", [None] * socket_count)
        sockets.extend([None] * (socket_count - len(sockets)))
        unequip_button = discord.ui.Button(
            label="현재 소켓 해제",
            style=discord.ButtonStyle.danger,
            row=3,
            disabled=not bool(sockets[self.selected_socket]),
        )
        unequip_button.callback = self._unequip
        self.add_item(unequip_button)

    async def _select_artifact(self, interaction):
        self.selected_artifact_id = interaction.data["values"][0]
        self.selected_socket = 0
        self.selected_gem_id = None
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

    async def _equip(self, interaction):
        artifact = self._artifact()
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
        ok, message = unequip_gem(self._artifact(), self.selected_socket)
        if ok:
            await self._save()
        self._rebuild_components()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    def get_embed(self):
        art = self._artifact()
        e = discord.Embed(title="💎 젬 소켓", color=discord.Color.purple())
        if not art:
            e.description = "관리할 아티팩트가 없습니다."
            return e
        sockets = art.setdefault("gems", [None] * artifact_socket_count(art))
        sockets.extend([None] * (artifact_socket_count(art) - len(sockets)))
        lines = [
            f"{'▶ ' if i == self.selected_socket else ''}{i+1}. "
            + (f"{g['name']} · {g.get('star', 0)}성" if g else "비어 있음")
            for i, g in enumerate(sockets[:artifact_socket_count(art)])
        ]
        e.description = (
            f"**{art.get('name','아티팩트')}** · {artifact_socket_count(art)}소켓\n"
            + "\n".join(lines)
        )
        e.set_footer(text="아티팩트·소켓·젬을 고른 뒤 장착하거나 해제하세요.")
        return e
