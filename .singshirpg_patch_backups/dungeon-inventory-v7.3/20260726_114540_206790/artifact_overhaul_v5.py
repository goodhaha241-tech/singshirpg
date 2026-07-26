# life-artifact-v5-manager
from __future__ import annotations

import random
from typing import Any

import discord

from artifact_events_v5 import CHARACTER_ARTIFACT_EFFECTS, COMMON_ARTIFACT_EFFECTS
from gem_manager import artifact_socket_count


def migrate_artifact(artifact: dict[str, Any]):
    artifact.setdefault("gems", [None] * artifact_socket_count(artifact))
    artifact.setdefault("metadata", {})
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
    art = next((a for a in artifacts if a.get("id") == artifact_id), None)
    if not art:
        return False, "아티팩트를 찾을 수 없습니다."
    migrate_artifact(art)
    if art["metadata"]["locked"]:
        return False, "잠긴 아티팩트는 분해할 수 없습니다."
    if any(g for g in art.get("gems", []) if g):
        return False, "젬을 먼저 해제해주세요."
    if int(art.get("equipped_char_index", -1)) >= 0:
        return False, "장착 중인 아티팩트는 분해할 수 없습니다."
    reward = artifact_dust_value(art)
    artifacts.remove(art)
    inv = user_data.setdefault("inventory", {})
    inv["유물 가루"] = int(inv.get("유물 가루", 0)) + reward
    return True, f"유물 가루 {reward}개를 획득했습니다."


def reroll_artifact(user_data, artifact_id):
    art = next((a for a in user_data.get("artifacts", []) if a.get("id") == artifact_id), None)
    if not art:
        return False, "아티팩트를 찾을 수 없습니다."
    migrate_artifact(art)
    rank = artifact_socket_count(art)
    cost = {1: 20_000, 2: 80_000, 3: 250_000}[rank]
    if int(user_data.get("money", 0)) < cost:
        return False, "머니가 부족합니다."
    user_data["money"] -= cost
    keys = list(art.get("stats", {})) or ["hp", "attack"]
    art["stats"] = {k: random.randint(rank * 2, rank * 8) for k in keys}
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
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=180)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        for art in user_data.get("artifacts", []):
            migrate_artifact(art)
            if art.get("special"):
                try:
                    from progression_system_v6 import add_collection
                    add_collection(user_data, "artifact_effects", art["special"])
                except ImportError:
                    pass
        artifacts = user_data.get("artifacts", [])
        self.selected_artifact_id = artifacts[0].get("id") if artifacts else None
        self.pending_dismantle_id = None
        self._rebuild_components()

    def _selected(self):
        return next(
            (art for art in self.user_data.get("artifacts", [])
             if art.get("id") == self.selected_artifact_id),
            None,
        )

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
        if not self._selected():
            self.selected_artifact_id = artifacts[0].get("id")

        select = discord.ui.Select(
            placeholder="관리할 아티팩트 선택",
            row=0,
            options=[
                discord.SelectOption(
                    label=str(art.get("name", "아티팩트"))[:100],
                    value=str(art.get("id")),
                    default=art.get("id") == self.selected_artifact_id,
                    description=(
                        f"{artifact_socket_count(art)}소켓 · "
                        f"+{art.get('level', 0)} · 분해 {artifact_dust_value(art)}가루"
                    ),
                )
                for art in artifacts[:25]
                if art.get("id") is not None
            ],
        )
        select.callback = self._select
        self.add_item(select)

        artifact = self._selected()
        lock_button = discord.ui.Button(
            label="잠금 해제" if artifact["metadata"]["locked"] else "잠금",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        lock_button.callback = self._toggle_lock
        self.add_item(lock_button)

        reroll_button = discord.ui.Button(
            label="스탯 재조정",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        reroll_button.callback = self._reroll
        self.add_item(reroll_button)

        confirming = self.pending_dismantle_id == self.selected_artifact_id
        dismantle_button = discord.ui.Button(
            label="정말 분해" if confirming else "선택 분해",
            style=discord.ButtonStyle.danger,
            row=1,
        )
        dismantle_button.callback = self._dismantle
        self.add_item(dismantle_button)

    async def _select(self, interaction):
        self.selected_artifact_id = interaction.data["values"][0]
        self.pending_dismantle_id = None
        self._rebuild_components()
        await interaction.response.edit_message(content=None, embed=self.get_embed(), view=self)

    async def _toggle_lock(self, interaction):
        artifact = self._selected()
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
        if self.pending_dismantle_id != self.selected_artifact_id:
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
            remaining = self.user_data.get("artifacts", [])
            self.selected_artifact_id = remaining[0].get("id") if remaining else None
        self._rebuild_components()
        await interaction.response.edit_message(content=message, embed=self.get_embed(), view=self)

    def get_embed(self):
        e = discord.Embed(title="💍 아티팩트 관리", color=discord.Color.gold())
        arts = self.user_data.get("artifacts", [])
        if not arts:
            e.description = "보유 아티팩트가 없습니다."
            return e
        lines = []
        for art in arts[:20]:
            lock = "🔒" if art["metadata"]["locked"] else ""
            selected = "▶ " if art.get("id") == self.selected_artifact_id else ""
            special = COMMON_ARTIFACT_EFFECTS.get(art.get("special"), {}).get("label", art.get("special") or "일반")
            lines.append(
                f"{selected}{lock} **{art.get('name','아티팩트')}** +{art.get('level',0)} · "
                f"{artifact_socket_count(art)}소켓 · {special}"
            )
        e.description = "\n".join(lines)
        e.set_footer(text="잠금·분해·재조정·젬 소켓을 통합 관리합니다.")
        return e
