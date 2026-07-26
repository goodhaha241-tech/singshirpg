# life-artifact-v5-life-hub
from __future__ import annotations

import discord

from cooking_system_v6 import CookingDeliveryView, CookingView, ensure_cooking_data
from navigation_v7 import attach_navigation
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
        self.selected_item = None
        self.quantity = 1
        inventory = user_data.setdefault("inventory", {})
        select = discord.ui.Select(
            placeholder="구매할 씨앗·치어 선택",
            options=[
                discord.SelectOption(
                    label=name,
                    value=name,
                    description=f"재고 {int(inventory.get(name, 0))}개 · 개당 {price:,}원",
                )
                for name, price in list(SUPPLY_PRICES.items())[:25]
            ],
        )
        select.callback = self.select_item
        self.add_item(select)

        for label, delta in (("-10", -10), ("-1", -1), ("+1", 1), ("+10", 10)):
            button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=1)
            button.callback = self._quantity_callback(delta)
            self.add_item(button)
        buy_button = discord.ui.Button(label="선택 수량 구매", style=discord.ButtonStyle.success, row=2)
        buy_button.callback = self.buy
        self.add_item(buy_button)

    def _refresh_stock_descriptions(self):
        inventory = self.user_data.setdefault("inventory", {})
        for child in self.children:
            if not isinstance(child, discord.ui.Select):
                continue
            child.options = [
                discord.SelectOption(
                    label=name,
                    value=name,
                    description=f"재고 {int(inventory.get(name, 0))}개 · 개당 {price:,}원",
                    default=name == self.selected_item,
                )
                for name, price in list(SUPPLY_PRICES.items())[:25]
            ]

    async def _save(self):
        try:
            await self.save_func(self.user_data)
        except TypeError:
            await self.save_func(self.author.id, self.user_data)

    async def select_item(self, interaction):
        self.selected_item = interaction.data["values"][0]
        self.quantity = 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    def _quantity_callback(self, delta):
        async def callback(interaction):
            self.quantity = max(1, min(999, self.quantity + delta))
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        return callback

    async def buy(self, interaction):
        if not self.selected_item:
            return await interaction.response.send_message(
                "먼저 구매할 씨앗이나 치어를 선택하세요.",
                ephemeral=True,
            )
        item = self.selected_item
        price = SUPPLY_PRICES[item]
        cost = price * self.quantity
        if int(self.user_data.get("money", 0)) < cost:
            return await interaction.response.send_message(
                f"머니가 부족합니다. 필요: {cost:,}원",
                ephemeral=True,
            )
        self.user_data["money"] -= cost
        inv = self.user_data.setdefault("inventory", {})
        inv[item] = int(inv.get(item, 0)) + self.quantity
        purchased = self.quantity
        self.quantity = 1
        self._refresh_stock_descriptions()
        await self._save()
        await interaction.response.edit_message(
            content=f"{item} {purchased}개를 구매했습니다.",
            embed=self.get_embed(),
            view=self,
        )

    def get_embed(self):
        inventory = self.user_data.setdefault("inventory", {})
        seed_lines = [
            f"• {name}: {int(inventory.get(name, 0))}개"
            for name in SEED_ITEMS.values()
        ]
        fish_lines = [
            f"• {name}: {int(inventory.get(name, 0))}개"
            for name in FINGERLING_ITEMS.values()
        ]
        selected = "미선택"
        if self.selected_item:
            price = SUPPLY_PRICES[self.selected_item]
            selected = (
                f"**{self.selected_item}** ×{self.quantity}\n"
                f"보유 {int(inventory.get(self.selected_item, 0))}개 · "
                f"총 {price * self.quantity:,}원"
            )
        return discord.Embed(
            title="🌾 생활 상점",
            description=(
                f"**선택 상품**\n{selected}\n\n"
                f"**씨앗·종균 재고**\n{chr(10).join(seed_lines)}\n\n"
                f"**치어·유생 재고**\n{chr(10).join(fish_lines)}"
            ),
            color=discord.Color.green(),
        )


class LifeHubView(discord.ui.View):
    """마이홈 안에서 생활 기능을 네 개씩 보여주는 통합 허브."""

    PER_PAGE = 4

    def __init__(self, author, user_data, save_func, page=0):
        super().__init__(timeout=300)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.page = max(0, int(page))
        ensure_life_data(user_data)
        grant_starter_supplies(user_data)
        ensure_cooking_data(user_data)
        ensure_progression(user_data)
        sync_life_notifications(user_data)
        self.update_components()

    def _features(self):
        return [
            ("채소밭", "🌱", discord.ButtonStyle.success, VegetableGardenView),
            ("양어장", "🐟", discord.ButtonStyle.primary, FishFarmView),
            ("생활 상점", "🌾", discord.ButtonStyle.secondary, LifeSupplyShopView),
            ("요리·완성 요리", "🍳", discord.ButtonStyle.success, CookingView),
            ("원석 감정", "🔍", discord.ButtonStyle.secondary, AppraisalView),
            ("젬 세공", "💎", discord.ButtonStyle.danger, GemCraftingView),
            ("세공 도구 관리", "🛠️", discord.ButtonStyle.secondary, ToolGachaView),
            ("순수한 희망 상점", "🛒", discord.ButtonStyle.secondary, PureHopeShopView),
            ("납품", "📦", discord.ButtonStyle.primary, CookingDeliveryView),
            ("도감·업적", "📚", discord.ButtonStyle.secondary, ProgressionView),
            ("아티팩트 관리", "💍", discord.ButtonStyle.secondary, ArtifactHubView),
            ("젬 관리", "💎", discord.ButtonStyle.secondary, GemManagerView),
        ]

    def update_components(self):
        self.clear_items()
        features = self._features()
        total_pages = max(1, (len(features) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page = min(self.page, total_pages - 1)
        start = self.page * self.PER_PAGE

        for label, emoji, style, view_class in features[start:start + self.PER_PAGE]:
            button = discord.ui.Button(label=label, emoji=emoji, style=style, row=0)
            button.callback = self._feature_callback(view_class)
            self.add_item(button)

        previous = discord.ui.Button(
            label="◀️",
            style=discord.ButtonStyle.secondary,
            row=1,
            disabled=self.page == 0,
        )
        previous.callback = self.previous_page
        self.add_item(previous)
        self.add_item(discord.ui.Button(
            label=f"{self.page + 1}/{total_pages}",
            style=discord.ButtonStyle.secondary,
            row=1,
            disabled=True,
        ))
        following = discord.ui.Button(
            label="▶️",
            style=discord.ButtonStyle.secondary,
            row=1,
            disabled=self.page >= total_pages - 1,
        )
        following.callback = self.next_page
        self.add_item(following)

        back = discord.ui.Button(
            label="돌아가기",
            emoji="↩️",
            style=discord.ButtonStyle.secondary,
            row=4,
        )
        back.callback = self.back_to_myhome
        self.add_item(back)
        exit_button = discord.ui.Button(
            label="마이홈 나가기",
            emoji="🚪",
            style=discord.ButtonStyle.danger,
            row=4,
        )
        exit_button.callback = self.exit_myhome
        self.add_item(exit_button)

    def _feature_callback(self, view_class):
        async def callback(interaction):
            view = view_class(self.author, self.user_data, self.save_func)
            await self._open(interaction, view)
        return callback

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "본인의 마이홈만 관리할 수 있습니다.",
                ephemeral=True,
            )
            return False
        return True

    def get_embed(self):
        life = ensure_life_data(self.user_data)
        cooking = ensure_cooking_data(self.user_data)
        appraisal = life.get("appraisal")
        craft = life.get("gem_crafting")
        plot = life.get("vegetable_garden", {}).get("plot")
        tank = life.get("fish_farm", {}).get("tank")
        e = discord.Embed(
            title="🏡 생활 관리",
            description=(
                "생산·감정·세공·요리·수집을 한곳에서 관리합니다.\n"
                f"현재 생활 메뉴 **{self.page + 1}/3페이지**"
            ),
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
        attach_navigation(
            view,
            self.author,
            lambda: LifeHubView(
                self.author,
                self.user_data,
                self.save_func,
                page=self.page,
            ),
            back_label="생활 관리로",
        )
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    async def previous_page(self, interaction):
        self.page = max(0, self.page - 1)
        self.update_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def next_page(self, interaction):
        self.page += 1
        self.update_components()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def back_to_myhome(self, interaction):
        from myhome import MyHomeView
        view = MyHomeView(self.author, self.user_data, self.save_func)
        await interaction.response.edit_message(
            content=None,
            embed=view.get_embed(),
            view=view,
        )

    async def exit_myhome(self, interaction):
        await interaction.response.edit_message(
            content="🏠 마이홈을 나왔습니다.",
            embed=None,
            view=None,
        )


# Compatibility name used by early v3 integrations.
LifeSystemViewV5 = LifeHubView
