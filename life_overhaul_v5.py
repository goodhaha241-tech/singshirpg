# life-artifact-v5-life-hub
from __future__ import annotations

import discord

from cooking_system_v6 import CookingDeliveryView, CookingView, ensure_cooking_data
from life_system import (
    AppraisalView,
    FishFarmView,
    GemCraftingView,
    LifeSystemView,
    PureHopeShopView,
    ToolGachaView,
    VegetableGardenView,
    CROPS,
    FISH_SPECIES,
    SEED_ITEMS,
    FINGERLING_ITEMS,
    ensure_life_data,
)
from progression_system_v6 import ProgressionView, ensure_progression, sync_life_notifications
from artifact_overhaul_v5 import ArtifactHubView
from gem_manager import GemManagerView


async def _defer(interaction):
    if not interaction.response.is_done():
        await interaction.response.defer()


SUPPLY_PRICES = {
    **{SEED_ITEMS[name]: 3_000 + data["turns"] * 500 for name, data in CROPS.items()},
    **{FINGERLING_ITEMS[name]: 4_000 + data["turns"] * 750 for name, data in FISH_SPECIES.items()},
}


def grant_starter_supplies(user_data):
    life = ensure_life_data(user_data)
    claimed = life["starter_supply_claimed"]
    inv = user_data.setdefault("inventory", {})
    if not claimed["garden"]:
        for item, count in {"새벽 감자 씨앗": 3, "별빛 토마토 씨앗": 2, "구름 양파 씨앗": 2}.items():
            inv[item] = int(inv.get(item, 0)) + count
        claimed["garden"] = True
    if not claimed["fish_farm"]:
        for item, count in {"빵잉어 치어": 3, "버들치 치어": 2, "로운새우 치하": 2}.items():
            inv[item] = int(inv.get(item, 0)) + count
        claimed["fish_farm"] = True


class LifeSupplyShopView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=180)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        select = discord.ui.Select(
            placeholder="구매할 종묘·치어 선택",
            options=[
                discord.SelectOption(label=name, value=name, description=f"{price:,}원")
                for name, price in list(SUPPLY_PRICES.items())[:25]
            ],
        )
        select.callback = self.buy
        self.add_item(select)

    async def buy(self, interaction):
        item = interaction.data["values"][0]
        price = SUPPLY_PRICES[item]
        if int(self.user_data.get("money", 0)) < price:
            return await interaction.response.send_message("머니가 부족합니다.", ephemeral=True)
        self.user_data["money"] -= price
        inv = self.user_data.setdefault("inventory", {})
        inv[item] = int(inv.get(item, 0)) + 1
        try:
            await self.save_func(self.user_data)
        except TypeError:
            await self.save_func(self.author.id, self.user_data)
        await interaction.response.send_message(f"{item} 1개를 구매했습니다.", ephemeral=True)

    def get_embed(self):
        lines = [f"• {name}: {price:,}원" for name, price in SUPPLY_PRICES.items()]
        return discord.Embed(
            title="🌾 생활 상점",
            description="\n".join(lines[:24]),
            color=discord.Color.green(),
        )


class LifeHubView(discord.ui.View):
    """Stable entry point used by both /마이홈 and /생활."""

    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=300)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        ensure_life_data(user_data)
        grant_starter_supplies(user_data)
        ensure_cooking_data(user_data)
        ensure_progression(user_data)
        sync_life_notifications(user_data)

    def get_embed(self):
        life = ensure_life_data(self.user_data)
        cooking = ensure_cooking_data(self.user_data)
        appraisal = life.get("appraisal")
        craft = life.get("gem_crafting")
        plot = life.get("vegetable_garden", {}).get("plot")
        tank = life.get("fish_farm", {}).get("tank")
        e = discord.Embed(
            title="🏡 생활 관리",
            description="생산·감정·세공·요리·수집을 한곳에서 관리합니다.",
            color=discord.Color.green(),
        )
        e.add_field(name="🌱 채소밭", value=(f"{plot.get('crop')} · {plot.get('turn',0)}턴" if plot else "대기 중"), inline=True)
        e.add_field(name="🐟 양어장", value=(f"{tank.get('species')} · {tank.get('turn',0)}턴" if tank else "대기 중"), inline=True)
        e.add_field(name="💎 감정", value=("진행 중" if appraisal else "대기 중"), inline=True)
        e.add_field(name="🔨 세공", value=(f"{craft.get('gem_name','젬')} · {craft.get('turn',0)}/20" if craft else "대기 중"), inline=True)
        e.add_field(name="🍳 완성 요리", value=f"{sum(cooking['foods'].values())}개", inline=True)
        e.add_field(name="🛠️ 세공 도구", value=f"{len(life.get('tools',{}))}종", inline=True)
        return e

    async def _open(self, interaction, view):
        await _defer(interaction)
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    @discord.ui.button(label="채소밭", emoji="🌱", style=discord.ButtonStyle.success)
    async def garden(self, i, b): await self._open(i, VegetableGardenView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="양어장", emoji="🐟", style=discord.ButtonStyle.primary)
    async def fish(self, i, b): await self._open(i, FishFarmView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="원석 감정", emoji="🔍", style=discord.ButtonStyle.secondary)
    async def appraisal(self, i, b): await self._open(i, AppraisalView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="젬 세공", emoji="💎", style=discord.ButtonStyle.danger)
    async def craft(self, i, b): await self._open(i, GemCraftingView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="세공 도구", emoji="🛠️", style=discord.ButtonStyle.secondary, row=1)
    async def tools(self, i, b): await self._open(i, ToolGachaView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="순수한 희망 상점", emoji="🛒", style=discord.ButtonStyle.secondary, row=1)
    async def hope(self, i, b): await self._open(i, PureHopeShopView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="생활 상점", emoji="🌾", style=discord.ButtonStyle.secondary, row=2)
    async def supplies(self, i, b): await self._open(i, LifeSupplyShopView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="요리·완성 요리", emoji="🍳", style=discord.ButtonStyle.success, row=1)
    async def cooking(self, i, b): await self._open(i, CookingView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="납품", emoji="📦", style=discord.ButtonStyle.primary, row=1)
    async def delivery(self, i, b): await self._open(i, CookingDeliveryView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="도감·업적", emoji="📚", style=discord.ButtonStyle.secondary, row=3)
    async def progression(self, i, b): await self._open(i, ProgressionView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="아티팩트 관리", emoji="💍", style=discord.ButtonStyle.secondary, row=3)
    async def artifacts(self, i, b): await self._open(i, ArtifactHubView(self.author, self.user_data, self.save_func))

    @discord.ui.button(label="젬 장착", emoji="🔩", style=discord.ButtonStyle.secondary, row=3)
    async def gems(self, i, b): await self._open(i, GemManagerView(self.author, self.user_data, self.save_func))


# Compatibility name used by early v3 integrations.
LifeSystemViewV5 = LifeHubView
