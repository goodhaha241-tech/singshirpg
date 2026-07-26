from __future__ import annotations

from collections.abc import Callable

import discord


def _embed_for(view):
    if hasattr(view, "get_embed"):
        return view.get_embed()
    if hasattr(view, "create_embed"):
        return view.create_embed()
    return None


def attach_navigation(
    view: discord.ui.View,
    author,
    back_factory: Callable[[], discord.ui.View],
    *,
    back_label: str = "돌아가기",
):
    """Add consistent back/exit controls without changing the child view's logic."""
    for child in list(view.children):
        if isinstance(child, discord.ui.Button) and child.label in {
            "뒤로",
            "상점으로",
            "돌아가기",
            "생활 관리로",
            "마이홈으로",
            "마이홈 나가기",
            back_label,
        }:
            view.remove_item(child)

    back_button = discord.ui.Button(
        label=back_label,
        emoji="↩️",
        style=discord.ButtonStyle.secondary,
        row=4,
    )
    exit_button = discord.ui.Button(
        label="마이홈 나가기",
        emoji="🚪",
        style=discord.ButtonStyle.danger,
        row=4,
    )

    async def back_callback(interaction: discord.Interaction):
        if interaction.user.id != author.id:
            return await interaction.response.send_message(
                "본인의 마이홈만 조작할 수 있습니다.",
                ephemeral=True,
            )
        if not interaction.response.is_done():
            await interaction.response.defer()
        target = back_factory()
        await interaction.edit_original_response(
            content=None,
            embed=_embed_for(target),
            view=target,
        )

    async def exit_callback(interaction: discord.Interaction):
        if interaction.user.id != author.id:
            return await interaction.response.send_message(
                "본인의 마이홈만 조작할 수 있습니다.",
                ephemeral=True,
            )
        await interaction.response.edit_message(
            content="🏠 마이홈을 나왔습니다.",
            embed=None,
            view=None,
        )

    back_button.callback = back_callback
    exit_button.callback = exit_callback
    view.add_item(back_button)
    view.add_item(exit_button)
    return view
