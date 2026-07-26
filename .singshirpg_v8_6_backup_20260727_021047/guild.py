# rollback-guard-appraisal-gems-v8
# pve-gem-runtime-v8.2
import discord
# cumulative-v2: one shared guild, automatic membership
import random
import json
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from discord.ui import View, Select, Button, Modal, TextInput
from data_manager import (
    get_user_data, get_db_pool, save_user_data, mutate_user_data,
    get_user_guild_info, create_guild, join_guild_by_id,
    deposit_guild_item, deposit_guild_artifact, get_guild_logs, get_guild_list,
    get_guild_items, withdraw_guild_item, craft_guild_item,
    consume_guild_raid_supplies, add_guild_contribution,
    get_or_create_daily_guild_shop, buy_guild_shop_item,
    advance_world_turn
)
from items import ITEM_CATEGORIES
from monsters import RAID_BOSS_DATA, Monster
from character import Character
from cards import get_card
import battle_engine
from gem_effects import (
    battle_end_gem_heal,
    escalation_roll,
    process_gem_turn_start,
    revive_gem_effects,
)

# guild-pvp-stability-v7.2
# raid-private-command-panel-v8.5
# guild-shop-training-v8.6

# --- 설정 데이터 (items.py 기준 통일) ---
ITEM_TOKEN_VALUES = {
    "목재": {"wood": 10}, "철괴": {"iron": 10}, "중급 마력석": {"magic": 10},
    "주술석": {"sorcery": 10}, "구름 블럭": {"wood": 20, "magic": 5},
    "양질 목재": {"wood": 30, "sorcery": 10},
    "강화 철강": {"iron": 20, "magic": 5},
    "상급 마력석": {"magic": 30},
    "고급 주술석": {"sorcery": 30},
    "응결 구름 블럭": {"wood": 40, "magic": 10},
    "낡은 열쇠": {"iron": 5},       
    "낡은 보물상자": {"wood": 15},  
    "평범한 나무판자": {"wood": 5},
    "녹슨 철": {"iron": 5},
}

RANK_NAMES = {1: "브론즈", 2: "실버", 3: "골드", 4: "플래티넘", 5: "다이아몬드"}
RAID_RANK_KEYS = {1: "Bronze", 2: "Silver", 3: "Gold", 4: "Platinum", 5: "Diamond"}

GUILD_CRAFT_RECIPES = {
    "길드 응급상자": {
        "cost": {"wood": 30, "magic": 15},
        "description": "레이드 준비용 공용 회복 물자입니다.",
    },
    "길드 전투도구": {
        "cost": {"iron": 35, "magic": 20},
        "description": "레이드 공격 준비에 쓰는 공용 도구입니다.",
    },
    "길드 보호부적": {
        "cost": {"wood": 15, "iron": 20, "sorcery": 25},
        "description": "레이드 방어 준비에 쓰는 공용 부적입니다.",
    },
}

GUILD_MISSIONS = {
    "donate": ("공용 자재 지원", 50, "길드 환산 자원 50점 납품"),
    "craft": ("길드 상점 이용", 1, "길드 상점에서 상품 1회 구매"),
    "raid": ("길드 토벌 작전", 1, "길드 레이드 1회 시작"),
}

TOKEN_LABELS = {"wood": "목재", "iron": "철괴", "magic": "마력", "sorcery": "주술"}
TOKEN_EMOJIS = {"wood": "🌲", "iron": "⛓️", "magic": "🔮", "sorcery": "🧿"}

GUILD_SHOP_PREMIUM = [
    {
        "item_name": "원석", "category": "material",
        "cost": {"iron": 60, "magic": 60, "sorcery": 40},
        "description": "감정과 젬 세공에 사용하는 미감정 원석입니다.",
    },
    {
        "item_name": "순수한 희망", "category": "consumable",
        "cost": {"wood": 80, "iron": 80, "magic": 100, "sorcery": 100},
        "description": "세공 도구 뽑기 1회에 사용하는 귀한 재화입니다.",
    },
]
GUILD_SHOP_HIGH_TIER = [
    {"item_name": "양질 목재", "category": "material", "cost": {"wood": 25, "sorcery": 8}, "description": "상위 제작용 목재입니다."},
    {"item_name": "강화 철강", "category": "material", "cost": {"iron": 25, "magic": 8}, "description": "상위 제작용 금속입니다."},
    {"item_name": "상급 마력석", "category": "material", "cost": {"magic": 25, "iron": 8}, "description": "응축된 상급 마력 자원입니다."},
    {"item_name": "고급 주술석", "category": "material", "cost": {"sorcery": 25, "wood": 8}, "description": "고급 주술 제작에 쓰는 자원입니다."},
    {"item_name": "응결 구름 블럭", "category": "material", "cost": {"wood": 30, "magic": 15}, "description": "희귀 제작에 쓰는 응결 재료입니다."},
]
GUILD_SHOP_SUPPLIES = [
    {"item_name": name, "category": "consumable", "cost": dict(info["cost"]), "description": info["description"]}
    for name, info in GUILD_CRAFT_RECIPES.items()
]
GUILD_SHOP_SEEDS = [
    {"item_name": name, "category": "seed", "cost": cost, "description": "채소밭 재배를 시작하는 종묘입니다."}
    for name, cost in [
        ("새벽 감자 씨앗", {"wood": 6}), ("별빛 토마토 씨앗", {"wood": 8}),
        ("꿈양배추 씨앗", {"wood": 12, "magic": 3}), ("구름 양파 씨앗", {"wood": 8}),
        ("무지개 당근 씨앗", {"wood": 14, "magic": 4}), ("시간 호박 씨앗", {"wood": 20, "magic": 8}),
        ("달빛 버섯 종균", {"wood": 15, "sorcery": 5}), ("악몽 고추 씨앗", {"wood": 18, "sorcery": 8}),
    ]
]
GUILD_SHOP_FINGERLINGS = [
    {"item_name": name, "category": "fingerling", "cost": cost, "description": "양어장 양식을 시작하는 어린 개체입니다."}
    for name, cost in [
        ("빵잉어 치어", {"iron": 6}), ("버들치 치어", {"iron": 9}),
        ("모래무지 치어", {"iron": 8}), ("등불오징어 유생", {"iron": 15, "magic": 5}),
        ("로운새우 치하", {"iron": 7}), ("어름치 치어", {"iron": 20, "magic": 7}),
        ("별비늘돔 치어", {"iron": 25, "magic": 12}), ("악몽 메기 치어", {"iron": 20, "sorcery": 8}),
    ]
]

TRAINING_REWARD_TIERS = [
    (0, {"money": 5_000}, "참가 보상"),
    (5, {"money": 10_000, "pt": 100}, "유효 주사위 5개"),
    (10, {"money": 20_000, "pt": 250}, "유효 주사위 10개"),
    (15, {"money": 30_000, "pt": 400, "items": {"상급 마력석": 1}, "contribution": 10}, "유효 주사위 15개"),
    (20, {"money": 50_000, "pt": 600, "items": {"순수한 희망": 1}}, "유효 주사위 20개"),
    (25, {"money": 80_000, "pt": 1_000, "items": {"원석": 1}, "contribution": 20}, "유효 주사위 25개"),
]


def _format_token_cost(cost, multiplier=1):
    return " · ".join(
        f"{TOKEN_EMOJIS.get(key, '')}{TOKEN_LABELS.get(key, key)} {int(value) * int(multiplier):,}"
        for key, value in cost.items()
    )


def _build_daily_shop_rotation():
    """Five persisted slots: premium, two materials, seed and fingerling."""
    pools = [
        random.choice(GUILD_SHOP_PREMIUM),
        *random.sample(GUILD_SHOP_HIGH_TIER, 2),
        random.choice(GUILD_SHOP_SEEDS),
        random.choice(GUILD_SHOP_FINGERLINGS),
    ]
    result = []
    for item in pools:
        row = dict(item)
        row["cost"] = dict(item["cost"])
        row["stock"] = random.randint(20, 100)
        result.append(row)
    return result


def _guild_day_key():
    return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


def _guild_activity(user_data):
    life = user_data.setdefault("life_data", {})
    activity = life.setdefault("guild_activity", {})
    if activity.get("date") != _guild_day_key():
        activity.clear()
        activity.update({
            "date": _guild_day_key(),
            "progress": {"donate": 0, "craft": 0, "raid": 0},
            "claimed": [],
            "all_claimed": False,
        })
    activity.setdefault("progress", {"donate": 0, "craft": 0, "raid": 0})
    activity.setdefault("claimed", [])
    activity.setdefault("all_claimed", False)
    return activity


async def advance_guild_mission(user, key, amount=1):
    def merge(data):
        activity = _guild_activity(data)
        activity["progress"][key] = int(activity["progress"].get(key, 0)) + int(amount)

    await mutate_user_data(user.id, merge, user.display_name)


async def advance_guild_world_turn(user, amount=1):
    """Advance shared life jobs from a valid guild combat action."""
    def merge(data):
        advance_world_turn(data, amount)

    return await mutate_user_data(user.id, merge, user.display_name)

# ==================================================================================
# 1. 물자 관리 (입/출고 통합)
# ==================================================================================

class QuantityModal(Modal):
    """수량 입력 모달 (입고/출고 공용)"""
    def __init__(self, mode, item_name, guild_id, user_data, parent_view):
        title = "납품 수량 입력" if mode == "deposit" else "수령 수량 입력"
        super().__init__(title=title)
        self.mode = mode
        self.item_name = item_name
        self.guild_id = guild_id
        self.user_data = user_data
        self.parent_view = parent_view
        self.amount = TextInput(label="수량", placeholder="숫자만 입력하세요", min_length=1)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.amount.value)
            if qty <= 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ 올바른 숫자를 입력하세요.", ephemeral=True)

        if self.mode == "deposit":
            # 입고 로직
            inventory = self.user_data.get("inventory", {})
            if inventory.get(self.item_name, 0) < qty:
                return await interaction.response.send_message(f"❌ 보유 수량이 부족합니다. (보유: {inventory.get(self.item_name, 0)}개)", ephemeral=True)

            cat = "material"
            for c_name, items in ITEM_CATEGORIES.items():
                if self.item_name in items:
                    if c_name == "consumable": cat = "consumable"
                    break
            
            tokens_per_unit = ITEM_TOKEN_VALUES.get(self.item_name, {"wood": 1})
            total_tokens = {k: v * qty for k, v in tokens_per_unit.items()}
            
            success, msg = await deposit_guild_item(interaction.user.id, self.guild_id, self.item_name, qty, cat, total_tokens)
        else:
            # 출고 로직
            success, msg = await withdraw_guild_item(interaction.user.id, self.guild_id, self.item_name, qty)

        if success and self.mode == "deposit":
            await advance_guild_mission(interaction.user, "donate", sum(total_tokens.values()))
        await interaction.response.send_message(msg, ephemeral=True)
        if success and hasattr(self.parent_view, 'refresh'):
            await self.parent_view.refresh(interaction)

class InventoryManageView(discord.ui.View):
    """길드 물자 관리 뷰 (입고/출고 탭)"""
    def __init__(self, author, guild_info, mode="deposit"):
        super().__init__(timeout=60)
        self.author = author
        self.guild_info = guild_info
        self.mode = mode # 'deposit' or 'withdraw'
        self.user_data = None
        self.page = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 길드 납품 화면만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def setup_view(self):
        self.clear_items()
        self.user_data = await get_user_data(self.author.id)
        
        # 상단 탭 버튼
        btn_dep = Button(label="📥 입고(납품)", style=discord.ButtonStyle.primary if self.mode=="deposit" else discord.ButtonStyle.secondary)
        btn_dep.callback = self.switch_to_deposit
        self.add_item(btn_dep)
        
        # 공용 길드의 자원은 개인 인벤토리로 출고하지 않는다.

        # 아이템 선택 메뉴
        if self.mode == "deposit":
            inventory = self.user_data.get("inventory", {})
            items = [(name, count) for name, count in inventory.items() if name in ITEM_TOKEN_VALUES and count > 0]
            placeholder = "납품할 자재 선택"
        else:
            # 출고: 길드 인벤토리 조회
            g_items = await get_guild_items(self.guild_info['guild_id'])
            items = [(i['item_name'], i['count']) for i in g_items]
            placeholder = "꺼낼 자재 선택"

        if not items:
            self.add_item(Button(label="가능한 아이템이 없습니다", disabled=True, row=1))
        else:
            options = []
            visible = items[self.page * 8:self.page * 8 + 8]
            for name, count in visible:
                options.append(discord.SelectOption(label=f"{name} (x{count})", value=name))
            
            select = Select(placeholder=placeholder, options=options, row=1)
            select.callback = self.on_select
            self.add_item(select)
            if len(items) > 8:
                prev = Button(label="이전", disabled=self.page == 0, row=2)
                nxt = Button(label="다음", disabled=(self.page + 1) * 8 >= len(items), row=2)
                prev.callback = self.prev_page
                nxt.callback = self.next_page
                self.add_item(prev); self.add_item(nxt)
        back = Button(label="길드로 돌아가기", style=discord.ButtonStyle.secondary, row=3)
        back.callback = self.back_to_guild
        self.add_item(back)

    async def get_embed(self):
        lines = []
        for item_name, rewards in ITEM_TOKEN_VALUES.items():
            conversion = ", ".join(
                f"{TOKEN_EMOJIS.get(key, '')}{TOKEN_LABELS.get(key, key)} +{int(value)}"
                for key, value in rewards.items()
            )
            lines.append(f"**{item_name} ×1** → {conversion}")
        embed = discord.Embed(
            title="📥 길드 자재 납품",
            description=(
                "아래 목록에서 보유 자재를 선택해 납품합니다.\n"
                "환산된 **공용 자원 1점마다 개인 공헌도도 1** 올라갑니다."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(name="📊 재료별 환산표", value="\n".join(lines), inline=False)
        embed.add_field(
            name="🏅 공헌도 획득 안내",
            value=(
                "• 자재 납품: 환산 자원 합계만큼\n"
                "• 일일 길드 미션 보상 수령: 미션당 +20\n"
                "• 레이드 성공: +100 / 실패: +20\n"
                "• 수련 점수 15·25 도달: 각각 +10·+20 (일일 최초)\n"
                "• 상시 보급품 구매: 제작 수량 1개당 +10\n"
                "• 로테이션 상품 구매 자체는 공헌도를 주지 않습니다."
            ),
            inline=False,
        )
        return embed

    async def prev_page(self, interaction):
        self.page = max(0, self.page - 1)
        await self.setup_view()
        await interaction.response.edit_message(embed=await self.get_embed(), view=self)

    async def next_page(self, interaction):
        self.page += 1
        await self.setup_view()
        await interaction.response.edit_message(embed=await self.get_embed(), view=self)

    async def switch_to_deposit(self, interaction):
        self.mode = "deposit"
        await self.setup_view()
        await interaction.response.edit_message(content=None, embed=await self.get_embed(), view=self)

    async def switch_to_withdraw(self, interaction):
        await interaction.response.send_message(
            "📦 공용 자원은 개인 인벤토리로 출고할 수 없습니다.",
            ephemeral=True,
        )

    async def on_select(self, interaction):
        if interaction.user.id != self.author.id: return
        item_name = interaction.data["values"][0]
        await interaction.response.send_modal(
            QuantityModal(self.mode, item_name, self.guild_info['guild_id'], self.user_data, self)
        )

    async def back_to_guild(self, interaction):
        view = GuildMainView()
        await interaction.response.edit_message(
            content=None,
            embed=await view.get_embed(interaction.user.id, interaction.user.display_name),
            view=view,
        )
    
    async def refresh(self, interaction):
        await self.setup_view()
        # 메시지 갱신이 필요하면 여기서 처리 (보통 모달 후 메시지는 유지됨)

# ==================================================================================
# 2. 길드 미션 시스템
# ==================================================================================

class GuildMissionView(discord.ui.View):
    def __init__(self, author, guild_info):
        super().__init__(timeout=60)
        self.author = author
        self.guild_info = guild_info
        self.selected_mission = "donate"
        self.add_item(self._mission_select())

    def _mission_select(self):
        select = Select(
            placeholder="보상을 확인할 미션",
            options=[
                discord.SelectOption(label=title, description=desc, value=key)
                for key, (title, _, desc) in GUILD_MISSIONS.items()
            ],
            row=0,
        )
        select.callback = self.on_select_mission
        return select
        
    async def get_embed(self):
        user_data = await get_user_data(self.author.id, self.author.display_name)
        activity = _guild_activity(user_data)
        embed = discord.Embed(title=f"📜 {self.guild_info['name']} 길드 미션", color=discord.Color.green())
        for key, (title, target, desc) in GUILD_MISSIONS.items():
            progress = min(target, int(activity["progress"].get(key, 0)))
            claimed = key in activity["claimed"]
            mark = "✅" if claimed else "🎁" if progress >= target else "▫️"
            embed.add_field(
                name=f"{mark} {title}",
                value=f"{desc}\n진행: **{progress}/{target}** · 개별 보상: 30,000원",
                inline=False,
            )
        embed.add_field(
            name="🌟 오늘의 전체 보상",
            value="세 미션 보상 수령 완료 시 **순수한 희망 ×1**",
            inline=False,
        )
        embed.set_footer(text="한국 시간 자정에 개인 진행도가 갱신됩니다.")
        return embed

    async def on_select_mission(self, interaction):
        self.selected_mission = interaction.data["values"][0]
        await interaction.response.defer()

    @discord.ui.button(label="선택 미션 보상", style=discord.ButtonStyle.success, row=1)
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        key = self.selected_mission
        title, target, _ = GUILD_MISSIONS[key]
        outcome = {"error": None, "all_bonus": False}

        def claim(latest):
            activity = _guild_activity(latest)
            if key in activity["claimed"]:
                outcome["error"] = "이미 받은 미션 보상입니다."
                return
            if int(activity["progress"].get(key, 0)) < target:
                outcome["error"] = "아직 미션 조건을 달성하지 못했습니다."
                return
            activity["claimed"].append(key)
            latest["money"] = int(latest.get("money", 0)) + 30_000
            if len(activity["claimed"]) == len(GUILD_MISSIONS) and not activity["all_claimed"]:
                activity["all_claimed"] = True
                inv = latest.setdefault("inventory", {})
                inv["순수한 희망"] = int(inv.get("순수한 희망", 0)) + 1
                outcome["all_bonus"] = True

        await mutate_user_data(self.author.id, claim, self.author.display_name)
        if outcome["error"]:
            return await interaction.response.send_message(outcome["error"], ephemeral=True)
        await add_guild_contribution(
            self.author.id,
            20,
            "mission",
            title,
            self.author.display_name,
        )
        extra = (
            " 모든 미션을 완료해 **순수한 희망 ×1**도 받았습니다."
            if outcome["all_bonus"] else ""
        )
        await interaction.response.edit_message(
            content=f"✅ {title} 보상 30,000원과 공헌도 20을 받았습니다.{extra}",
            embed=await self.get_embed(),
            view=self,
        )

    @discord.ui.button(label="길드 상점", style=discord.ButtonStyle.primary, row=1)
    async def btn_craft(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = GuildShopView(self.author, self.guild_info, self)
        await view.setup()
        await interaction.response.edit_message(embed=await view.get_embed(), view=view)

    @discord.ui.button(label="길드로 돌아가기", style=discord.ButtonStyle.secondary, row=1)
    async def btn_back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = GuildMainView()
        await interaction.response.edit_message(
            content=None,
            embed=await view.get_embed(interaction.user.id, interaction.user.display_name),
            view=view,
        )


class GuildShopView(discord.ui.View):
    PER_PAGE = 4

    def __init__(self, author, guild_info, parent_view):
        super().__init__(timeout=120)
        self.author = author
        self.guild_info = guild_info
        self.parent_view = parent_view
        self.day_key = _guild_day_key()
        self.items = []
        self.selected_slot = 0
        self.page = 0

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 길드 상점 화면만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def setup(self):
        self.day_key = _guild_day_key()
        daily_items = await get_or_create_daily_guild_shop(
            self.guild_info["guild_id"],
            self.day_key,
            _build_daily_shop_rotation(),
        )
        # Early v8.6 test data may still contain one rotating raid supply.
        # Hide it because the three original workshop products are now permanent.
        self.items = [
            row for row in daily_items
            if row.get("item_name") not in GUILD_CRAFT_RECIPES
        ]
        for index, item in enumerate(GUILD_SHOP_SUPPLIES):
            self.items.append({
                **item,
                "slot_index": 100 + index,
                "persistent": True,
                "stock": -1,
                "initial_stock": -1,
            })
        valid_slots = {int(item["slot_index"]) for item in self.items}
        if self.selected_slot not in valid_slots and self.items:
            self.selected_slot = int(self.items[0]["slot_index"])
        self.rebuild()

    def selected_item(self):
        for item in self.items:
            if int(item["slot_index"]) == int(self.selected_slot):
                return item
        return self.items[0] if self.items else None

    def rebuild(self):
        self.clear_items()
        total_pages = max(1, (len(self.items) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * self.PER_PAGE
        for item in self.items[start:start + self.PER_PAGE]:
            slot = int(item["slot_index"])
            selected = slot == int(self.selected_slot)
            button = Button(
                label=f"{'✓ ' if selected else ''}{item['item_name']}"[:80],
                style=discord.ButtonStyle.primary if selected else discord.ButtonStyle.secondary,
                disabled=(
                    not item.get("persistent")
                    and int(item.get("stock", 0)) <= 0
                ),
                row=0,
            )

            async def choose(interaction, selected_slot=slot):
                self.selected_slot = selected_slot
                self.rebuild()
                await interaction.response.edit_message(content=None, embed=await self.get_embed(), view=self)

            button.callback = choose
            self.add_item(button)

        if total_pages > 1:
            previous = Button(label="이전", disabled=self.page == 0, row=1)
            counter = Button(label=f"{self.page + 1}/{total_pages}", disabled=True, row=1)
            following = Button(label="다음", disabled=self.page >= total_pages - 1, row=1)

            async def move(interaction, delta):
                self.page = max(0, min(self.page + delta, total_pages - 1))
                self.rebuild()
                await interaction.response.edit_message(content=None, embed=await self.get_embed(), view=self)

            async def previous_page(interaction):
                await move(interaction, -1)

            async def next_page(interaction):
                await move(interaction, 1)

            previous.callback = previous_page
            following.callback = next_page
            self.add_item(previous)
            self.add_item(counter)
            self.add_item(following)

        for quantity, label in ((1, "1개 구매"), (5, "5개 구매"), (10, "10개 구매")):
            buy = Button(label=label, style=discord.ButtonStyle.success, row=2)

            async def purchase(interaction, amount=quantity):
                await self.purchase(interaction, amount)

            buy.callback = purchase
            self.add_item(buy)

        back = Button(label="돌아가기", style=discord.ButtonStyle.secondary, row=3)
        back.callback = self.go_back
        self.add_item(back)

    async def get_embed(self):
        guild = await get_user_guild_info(self.author.id)
        item = self.selected_item()
        page_items = self.items[self.page * self.PER_PAGE:(self.page + 1) * self.PER_PAGE]
        lines = [
            f"{'▶' if int(row['slot_index']) == int(self.selected_slot) else '•'} "
            f"**{row['item_name']}** · "
            + (
                "상시 판매 · 공용 창고 지급"
                if row.get("persistent")
                else f"공용 재고 {int(row['stock'])}/{int(row['initial_stock'])}"
            )
            for row in page_items
        ]
        embed = discord.Embed(
            title="🛒 길드 상점",
            description=(
                "원래 제작소의 보급품 3종은 상시 판매되며 **공용 창고**로 들어갑니다.\n"
                "나머지는 한국 시간 자정마다 상품과 **길드원 전체가 공유하는 재고**가 교체됩니다.\n\n"
                + ("\n".join(lines) if lines else "오늘의 상품을 불러오지 못했습니다.")
            ),
            color=discord.Color.blurple(),
        )
        if item:
            destination = (
                "길드 공용 창고"
                if item.get("persistent")
                else "구매자 개인 인벤토리"
            )
            stock_text = (
                "상시 판매"
                if item.get("persistent")
                else f"{int(item.get('stock', 0))}개"
            )
            embed.add_field(
                name=f"선택: {item['item_name']}",
                value=(
                    f"{item.get('description') or '길드 상점 상품입니다.'}\n"
                    f"가격: **{_format_token_cost(item.get('cost', {}))}**\n"
                    f"재고: **{stock_text}**\n"
                    f"지급 위치: **{destination}**"
                ),
                inline=False,
            )
        embed.add_field(
            name="🏗️ 현재 공용 자원",
            value=(
                f"🌲 목재 {int(guild.get('token_wood', 0)):,} · "
                f"⛓️ 철괴 {int(guild.get('token_iron', 0)):,}\n"
                f"🔮 마력 {int(guild.get('token_magic', 0)):,} · "
                f"🧿 주술 {int(guild.get('token_sorcery', 0)):,}"
            ),
            inline=False,
        )
        embed.set_footer(
            text=(
                f"오늘의 로테이션: {self.day_key} · "
                "상시 보급품은 공용 창고, 로테이션 상품은 개인 인벤토리로 지급"
            )
        )
        return embed

    async def purchase(self, interaction, count):
        item = self.selected_item()
        if not item:
            return await interaction.response.send_message("구매할 상품이 없습니다.", ephemeral=True)
        if item.get("persistent"):
            success, message = await craft_guild_item(
                interaction.user.id,
                self.guild_info["guild_id"],
                item["item_name"],
                item.get("category", "consumable"),
                item.get("cost", {}),
                count,
            )
        else:
            success, message = await buy_guild_shop_item(
                interaction.user.id,
                self.guild_info["guild_id"],
                self.day_key,
                int(item["slot_index"]),
                count,
                interaction.user.display_name,
            )
        if success:
            await advance_guild_mission(interaction.user, "craft")
        await self.setup()
        await interaction.response.edit_message(
            content=("✅ " if success else "❌ ") + message,
            embed=await self.get_embed(),
            view=self,
        )

    async def go_back(self, interaction):
        if isinstance(self.parent_view, GuildMissionView):
            return await interaction.response.edit_message(
                content=None,
                embed=await self.parent_view.get_embed(),
                view=self.parent_view,
            )
        view = GuildMainView()
        await interaction.response.edit_message(
            content=None,
            embed=await view.get_embed(interaction.user.id, interaction.user.display_name),
            view=view,
        )

# ==================================================================================
# 3. 길드 창고 및 아티팩트
# ==================================================================================

class ArtifactDepositSelectView(discord.ui.View):
    def __init__(self, author, user_data, guild_id, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.guild_id = guild_id
        self.parent_view = parent_view
        self.artifacts = self.user_data.get("artifacts", [])
        self.page = 0
        self.add_select()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 아티팩트만 보관할 수 있습니다.", ephemeral=True)
        return False

    def add_select(self):
        if not self.artifacts:
            self.add_item(Button(label="❌ 보관할 아티팩트가 없습니다.", disabled=True))
            return

        options = []
        start = self.page * 8
        for i, art in enumerate(self.artifacts[start:start + 8], start=start):
            label = f"{art['name']} (+{art.get('level', 0)})"
            desc = f"{art.get('rank', art.get('rank_level', 1))}성 | {art.get('prefix', '')}"
            options.append(discord.SelectOption(label=label, description=desc, value=str(i)))

        select = discord.ui.Select(placeholder="길드 창고에 넣을 아티팩트 선택", options=options)
        select.callback = self.callback
        self.add_item(select)
        if len(self.artifacts) > 8:
            prev = Button(label="이전", disabled=self.page == 0, row=1)
            nxt = Button(label="다음", disabled=(self.page + 1) * 8 >= len(self.artifacts), row=1)
            async def move(interaction, delta):
                self.page += delta; self.clear_items(); self.add_select()
                await interaction.response.edit_message(view=self)
            prev.callback = lambda i: move(i, -1)
            nxt.callback = lambda i: move(i, 1)
            self.add_item(prev); self.add_item(nxt)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return
        idx = int(interaction.data["values"][0])
        if idx >= len(self.artifacts): return
            
        artifact = self.artifacts.pop(idx)
        success, msg = await deposit_guild_artifact(self.author.id, self.guild_id, artifact)
        
        if success:
            # The DB helper moves the artifact atomically and increments the
            # snapshot revision. Reload instead of writing the old full snapshot.
            self.user_data = await get_user_data(self.author.id, self.author.display_name)
            self.artifacts = self.user_data.get("artifacts", [])
            await interaction.response.send_message(f"✅ **{artifact['name']}**을(를) 보관했습니다!", ephemeral=True)
        else:
            self.artifacts.insert(idx, artifact)
            await interaction.response.send_message(f"❌ 보관 실패: {msg}", ephemeral=True)

class GuildWarehouseView(discord.ui.View):
    def __init__(self, author, guild_info):
        super().__init__(timeout=120)
        self.author = author
        self.guild_info = guild_info
        self.category = "consumable"
        self.clear_items()
        category = Select(
            placeholder="창고 분류 선택",
            options=[
                discord.SelectOption(label="소모품", value="consumable"),
                discord.SelectOption(label="재료·제작품", value="material"),
                discord.SelectOption(label="아티팩트", value="artifact"),
            ],
        )
        category.callback = self.select_category
        self.add_item(category)
        self.add_item(self.btn_deposit_art)
        self.add_item(self.btn_logs)

    async def select_category(self, interaction):
        self.category = interaction.data["values"][0]
        await self.refresh(interaction)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인이 연 길드 창고 화면만 조작할 수 있습니다.", ephemeral=True)
        return False
        
    async def get_embed(self):
        new_info = await get_user_guild_info(self.author.id)
        if new_info: self.guild_info = new_info
        g = self.guild_info
        
        embed = discord.Embed(title=f"🏰 {g['name']} 길드 창고", color=discord.Color.blue())
        tokens = (
            f"🌲 목재: {g['token_wood']:,} | ⛓️ 철괴: {g['token_iron']:,}\n"
            f"🔮 마력: {g['token_magic']:,} | 🧿 주술: {g['token_sorcery']:,}"
        )
        embed.add_field(name="💰 길드 자금", value=tokens, inline=False)
        
        items = await get_guild_items(g['guild_id'], self.category)
        titles = {"consumable": "🍎 소모품", "material": "🪵 재료/제작품", "artifact": "💍 아티팩트"}
        content = ""
        
        if not items:
            content = "*(비어있음)*"
        else:
            if self.category == "artifact":
                lines = []
                for item in items[:15]:
                    data = item.get('data', {})
                    if isinstance(data, str):
                        try: data = json.loads(data)
                        except: data = {}
                    prefix = data.get('prefix', '')
                    lines.append(f"• **{item['name']}** (+{item.get('level', 0)}) [{prefix}]")
                content = "\n".join(lines)
                if len(items) > 15: content += f"\n...외 {len(items)-15}개"
            else:
                lines = [f"• **{i['item_name']}**: {i['count']}개" for i in items]
                content = "\n".join(lines)

        embed.add_field(name=f"📂 {titles[self.category]} 보관함", value=content, inline=False)
        return embed

    async def refresh(self, interaction):
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=await self.get_embed(), view=self)
        else:
            await interaction.response.edit_message(embed=await self.get_embed(), view=self)

    @discord.ui.button(label="🍎 소모품", style=discord.ButtonStyle.secondary)
    async def btn_consumable(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category = "consumable"; await self.refresh(interaction)

    @discord.ui.button(label="🪵 재료", style=discord.ButtonStyle.secondary)
    async def btn_material(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category = "material"; await self.refresh(interaction)

    @discord.ui.button(label="💍 아티팩트", style=discord.ButtonStyle.secondary)
    async def btn_artifact(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category = "artifact"; await self.refresh(interaction)
    
    @discord.ui.button(label="📥 아티팩트 보관", style=discord.ButtonStyle.success, row=1)
    async def btn_deposit_art(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_data = await get_user_data(interaction.user.id)
        view = ArtifactDepositSelectView(interaction.user, user_data, self.guild_info['guild_id'], self)
        await interaction.response.send_message("보관할 아티팩트를 선택하세요.", view=view, ephemeral=True)

    @discord.ui.button(label="📜 로그", style=discord.ButtonStyle.primary, row=1)
    async def btn_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        logs = await get_guild_logs(self.guild_info['guild_id'])
        if not logs: return await interaction.response.send_message("기록이 없습니다.", ephemeral=True)
        text = ""
        for l in logs:
            action = {
                "deposit": "입고",
                "withdraw": "출고",
                "deposit_artifact": "보관",
                "craft": "제작",
                "shop_purchase": "상점 구매",
                "mission": "미션 공헌",
                "training": "수련 공헌",
                "raid_success": "레이드 성공",
                "raid_failure": "레이드 참가",
            }.get(l["action_type"], "활동")
            text += f"• [{action}] **{l['item_name']}** x{l['count']} ({l.get('user_name', '알수없음')})\n"
        await interaction.response.send_message(embed=discord.Embed(title="📋 최근 활동", description=text), ephemeral=True)

# ==================================================================================
# 4. 레이드 (기존 유지)
# ==================================================================================
class RaidCardSelectView(discord.ui.View):
    PER_PAGE = 4

    def __init__(self, author, cards, callback_func, turn):
        super().__init__(timeout=60)
        self.author = author
        self.callback_func = callback_func
        self.cards = list(cards)
        self.turn = int(turn)
        self.page = 0
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        total_pages = max(1, (len(self.cards) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * self.PER_PAGE
        for card_name in self.cards[start:start + self.PER_PAGE]:
            button = Button(label=card_name[:80], style=discord.ButtonStyle.primary, row=0)

            async def choose(interaction, selected=card_name):
                await self.callback_func(interaction, selected)

            button.callback = choose
            self.add_item(button)

        if total_pages > 1:
            prev = Button(label="이전", disabled=self.page == 0, row=1)
            page = Button(label=f"{self.page + 1}/{total_pages}", disabled=True, row=1)
            nxt = Button(label="다음", disabled=self.page >= total_pages - 1, row=1)

            async def move(interaction, delta):
                self.page = max(0, min(self.page + delta, total_pages - 1))
                self.rebuild()
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            async def previous(interaction):
                await move(interaction, -1)

            async def following(interaction):
                await move(interaction, 1)

            prev.callback = previous
            nxt.callback = following
            self.add_item(prev)
            self.add_item(page)
            self.add_item(nxt)

    def get_embed(self):
        start = self.page * self.PER_PAGE
        lines = []
        for card_name in self.cards[start:start + self.PER_PAGE]:
            card_obj = get_card(card_name)
            description = card_obj.description if card_obj else "효과 정보 없음"
            lines.append(f"**{card_name}**\n{description}")
        return discord.Embed(
            title=f"🎴 레이드 커맨드 · {self.turn}턴",
            description="\n\n".join(lines) or "사용 가능한 기술이 없습니다.",
            color=discord.Color.blurple(),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 카드만 선택할 수 있습니다.", ephemeral=True)
        return False

class RaidBattleView(discord.ui.View):
    def __init__(self, lobby_view, boss: Monster, message=None):
        super().__init__(timeout=600)
        self.lobby = lobby_view
        self.boss = boss
        self.participants = lobby_view.participants
        self.turn = 1
        self.logs = []
        self.selected_cards = {}
        self.shayla_triggers = {uid: False for uid in self.participants}
        self.boss_intent = None
        self.public_message = message
        self.command_messages = {}
        self.resolve_lock = asyncio.Lock()
        self.finished = False
        self.decide_boss_action()

    def decide_boss_action(self):
        self.boss_intent = self.boss.decide_action()

    def get_status_embed(self):
        embed = discord.Embed(title=f"⚔️ 길드 레이드: {self.boss.name}", color=discord.Color.dark_red())
        p = self.boss.current_hp / self.boss.max_hp
        boss_hp_bar = "🟥" * int(p * 15) + "⬜" * (15 - int(p * 15))
        embed.add_field(name=f"👹 {self.boss.name}", value=f"❤️ {self.boss.current_hp}/{self.boss.max_hp}\n{boss_hp_bar}", inline=False)
        
        intent = f"**{self.boss_intent.name}**" + (" (☄️ 광역)" if self.boss_intent.is_aoe else " (🗡️ 단일)")
        embed.add_field(name="⚠️ 보스 의도", value=intent, inline=False)

        for uid, p in self.participants.items():
            char = p['char']
            st = "✅ 준비완료" if uid in self.selected_cards else "💭 고민중..."
            if char.current_hp <= 0: st = "💀 행동불가"
            embed.add_field(name=f"👤 {p['user'].display_name}", value=f"❤️ {char.current_hp} | {st}", inline=True)
        
        if self.logs:
            log_text = "\n".join(self.logs[-4:])
            if len(log_text) > 1000:
                log_text = "…(앞부분 생략)\n" + log_text[-980:]
            embed.add_field(name="📜 전투 로그", value=log_text, inline=False)
        return embed

    def _make_raid_card_callback(self, uid, selected_turn):
        async def callback(interaction, card_name):
            should_resolve = False
            async with self.resolve_lock:
                if self.finished:
                    return await interaction.response.send_message("이미 종료된 레이드입니다.", ephemeral=True)
                if selected_turn != self.turn:
                    return await interaction.response.send_message(
                        "이 커맨드 창은 이전 턴의 것입니다. 현재 창을 다시 열어주세요.",
                        ephemeral=True,
                    )
                if uid in self.selected_cards:
                    return await interaction.response.send_message(
                        "이미 이번 턴의 카드를 선택했습니다.",
                        ephemeral=True,
                    )
                self.selected_cards[uid] = card_name
                alive = [user_id for user_id, data in self.participants.items() if data["char"].current_hp > 0]
                should_resolve = all(user_id in self.selected_cards for user_id in alive)

            await interaction.response.edit_message(
                embed=discord.Embed(
                    title=f"✅ {self.turn}턴 커맨드 확정",
                    description=f"**{card_name}**을 선택했습니다.\n다른 참가자의 선택을 기다립니다.",
                    color=discord.Color.green(),
                ),
                view=None,
            )
            if self.public_message and not should_resolve:
                try:
                    await self.public_message.edit(embed=self.get_status_embed(), view=self)
                except (discord.NotFound, discord.HTTPException):
                    self.public_message = None
            if should_resolve:
                await self.resolve_turn(interaction)

        return callback

    def _new_command_view(self, uid):
        participant = self.participants[uid]
        cards = list(getattr(participant["char"], "equipped_cards", []) or [])
        return RaidCardSelectView(
            participant["user"],
            cards,
            self._make_raid_card_callback(uid, self.turn),
            self.turn,
        )

    async def _refresh_command_panels(self):
        for uid, message in list(self.command_messages.items()):
            participant = self.participants.get(uid)
            if not participant:
                continue
            try:
                if self.finished:
                    await message.edit(
                        embed=discord.Embed(
                            title="⚔️ 레이드 종료",
                            description="레이드가 종료되어 커맨드 입력을 마쳤습니다.",
                            color=discord.Color.dark_grey(),
                        ),
                        view=None,
                    )
                elif participant["char"].current_hp <= 0:
                    await message.edit(
                        embed=discord.Embed(
                            title=f"💀 {self.turn}턴 행동 불가",
                            description="전투 불능 상태라 커맨드를 선택할 수 없습니다.",
                            color=discord.Color.dark_grey(),
                        ),
                        view=None,
                    )
                else:
                    view = self._new_command_view(uid)
                    await message.edit(embed=view.get_embed(), view=view)
            except (discord.NotFound, discord.HTTPException):
                self.command_messages.pop(uid, None)

    @discord.ui.button(label="🎴 내 커맨드 열기", style=discord.ButtonStyle.primary)
    async def btn_pick(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        if uid not in self.participants: return await interaction.response.send_message("참여자가 아닙니다.", ephemeral=True)
        if self.finished: return await interaction.response.send_message("이미 종료된 레이드입니다.", ephemeral=True)
        if self.public_message is None:
            self.public_message = interaction.message
        
        char_info = self.participants[uid]
        if char_info['char'].current_hp <= 0: return await interaction.response.send_message("행동 불가 상태입니다.", ephemeral=True)
        if uid in self.selected_cards: return await interaction.response.send_message("이미 선택했습니다.", ephemeral=True)

        cards = list(getattr(char_info['char'], "equipped_cards", []) or [])
        if not cards:
            return await interaction.response.send_message("선택 가능한 카드가 없습니다.", ephemeral=True)
        view = self._new_command_view(uid)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)
        try:
            self.command_messages[uid] = await interaction.original_response()
        except (discord.NotFound, discord.HTTPException):
            pass

    async def resolve_turn(self, interaction):
        if self.finished:
            return
        self.logs.append(f"--- Turn {self.turn} ---")
        alive = [u for u, p in self.participants.items() if p['char'].current_hp > 0]
        if not alive: return await self.end_raid(interaction, False)
        # A resolved raid round advances one shared activity turn for every participant.
        for participant in self.participants.values():
            participant["data"] = await advance_guild_world_turn(participant["user"], 1)

        boss_card = self.boss_intent
        targets = alive if boss_card.is_aoe else [random.choice(alive)]
        
        for uid in alive:
            char = self.participants[uid]['char']
            u_card_name = self.selected_cards[uid]
            u_card = get_card(u_card_name)

            gem_log = process_gem_turn_start(
                char, self.boss, self.turn, u_card_name
            )
            if gem_log:
                self.logs.append(f"💎 **{char.name}** {gem_log}")
            if self.boss.current_hp <= 0:
                break
            
            boss_res = boss_card.use_card(self.boss.attack, self.boss.defense)
            boss_res = battle_engine.apply_stat_scaling(boss_res, self.boss)
            user_res = u_card.use_card(char.attack, char.defense, char.current_mental)
            user_res = battle_engine.apply_stat_scaling(user_res, char)
            
            u_effs = []
            art = getattr(char, "equipped_artifact", None)
            if art: u_effs.append(art.get("special"))
            engraved = getattr(char, "equipped_engraved_artifact", None)
            if engraved:
                u_effs.append(engraved.get("special"))
            
            art_log, next_trig = battle_engine.process_turn_start_artifacts(
                char, self.boss, user_res, boss_res, self.turn, self.shayla_triggers.get(uid, False), u_card_name
            )
            self.shayla_triggers[uid] = next_trig
            if art_log: self.logs.append(art_log)

            if "escalation" in u_effs and user_res:
                last = char.runtime_cooldowns.get("escalation", -10)
                if self.turn - last >= 2:
                    bonus = escalation_roll(char)
                    user_res[-1]["value"] += bonus
                    char.runtime_cooldowns["escalation"] = self.turn
                    self.logs.append(f"🔥 **{char.name}[고조된]** +{bonus}")

            is_target = (uid in targets)
            if is_target:
                clash_log, dmg_p, dmg_b = battle_engine.process_clash_loop(char, self.boss, user_res, boss_res, u_effs, [], self.turn)
                self.logs.append(f"⚔️ **{char.name}** vs **보스**" + clash_log)
            else:
                for d in boss_res:
                    if d['type'] == 'attack': d['type'] = 'none'; d['value'] = 0
                clash_log, dmg_p, dmg_b = battle_engine.process_clash_loop(char, self.boss, user_res, boss_res, u_effs, [], self.turn)
                self.logs.append(f"🗡️ **{char.name}** 일방 공격!" + clash_log)

            if char.current_hp <= 0:
                if "immortality" in u_effs and not self.participants[uid].get("revived"):
                    self.participants[uid]["revived"] = True
                    char.current_hp = char.max_hp
                    revive_log = revive_gem_effects(char)
                    self.logs.append(
                        f"👼 **{char.name}** 부활!"
                        + (f" ({revive_log})" if revive_log else "")
                    )
                else:
                    char.current_hp = 0
                    self.logs.append(f"💀 **{char.name}** 쓰러짐!")

        if self.boss.current_hp <= 0: return await self.end_raid(interaction, True)
        
        self.turn += 1
        self.selected_cards = {}
        self.decide_boss_action()
        
        if self.public_message:
            try:
                await self.public_message.edit(embed=self.get_status_embed(), view=self)
            except (discord.NotFound, discord.HTTPException):
                self.public_message = None
        if self.public_message is None:
            self.public_message = await interaction.channel.send(embed=self.get_status_embed(), view=self)
        await self._refresh_command_panels()

    async def _save_participant_result(self, uid, participant, *, win):
        """Merge only the raid result into the latest protected user snapshot."""
        character_index = int(participant["char_idx"])
        character_data = participant["char"].to_dict()

        def merge(latest):
            characters = latest.setdefault("characters", [])
            if not 0 <= character_index < len(characters):
                raise IndexError(f"레이드 캐릭터 슬롯을 찾지 못했습니다: {character_index}")
            characters[character_index] = character_data
            if win:
                latest["money"] = int(latest.get("money", 0) or 0) + 5000
                latest["pt"] = int(latest.get("pt", 0) or 0) + 1000

        latest = await mutate_user_data(
            uid,
            merge,
            participant["user"].display_name,
        )
        participant["data"] = latest

    async def end_raid(self, interaction, win):
        if self.finished:
            return
        self.finished = True
        self.clear_items()
        embed = None
        if win:
            rewards = self.boss.reward_tokens if hasattr(self.boss, 'reward_tokens') else {}
            guild_id = self.lobby.guild_info['guild_id']
            
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    set_c = [f"token_{k} = token_{k} + {v}" for k, v in rewards.items()]
                    if set_c:
                        await cur.execute(f"UPDATE guilds SET {', '.join(set_c)} WHERE guild_id=%s", (guild_id,))
                        await conn.commit()
            
            log_names = []
            for uid, p in self.participants.items():
                if hasattr(p['char'], "remove_battle_buffs"):
                    p['char'].remove_battle_buffs()
                battle_end_gem_heal(p['char'])
                p['char'].current_hp = p['char'].max_hp
                await self._save_participant_result(uid, p, win=True)
                await add_guild_contribution(
                    uid, 100, "raid_success", self.boss.name, p["user"].display_name
                )
                log_names.append(p['user'].display_name)
            
            embed = discord.Embed(title="🎉 토벌 성공!", description=f"보스 **{self.boss.name}** 처치!", color=discord.Color.gold())
            embed.add_field(name="영웅들", value=", ".join(log_names))
        else:
            embed = discord.Embed(title="☠️ 토벌 실패", description="파티가 전멸했습니다...", color=discord.Color.dark_grey())
            for uid, p in self.participants.items():
                if hasattr(p['char'], "remove_battle_buffs"):
                    p['char'].remove_battle_buffs()
                p['char'].current_hp = 1 
                await self._save_participant_result(uid, p, win=False)
                await add_guild_contribution(
                    uid, 20, "raid_failure", self.boss.name, p["user"].display_name
                )

        if self.public_message:
            try:
                await self.public_message.edit(embed=embed, view=None)
            except (discord.NotFound, discord.HTTPException):
                await interaction.channel.send(embed=embed)
        else:
            await interaction.channel.send(embed=embed)
        await self._refresh_command_panels()
        self.stop()

    async def on_timeout(self):
        if self.finished:
            return
        self.finished = True
        for p in self.participants.values():
            if hasattr(p['char'], "remove_battle_buffs"):
                p['char'].remove_battle_buffs()
        for child in self.children:
            child.disabled = True
        if self.public_message:
            try:
                await self.public_message.edit(content="⏱️ 레이드가 장시간 입력 없이 종료되었습니다.", view=self)
            except (discord.NotFound, discord.HTTPException):
                pass
        await self._refresh_command_panels()

class RaidLobbyView(discord.ui.View):
    def __init__(self, host, guild_info, boss_data):
        super().__init__(timeout=300)
        self.host = host
        self.guild_info = guild_info
        self.boss_data = boss_data
        self.participants = {}
        self.started = False
        self.state_lock = asyncio.Lock()
        self.public_message = None

    async def add_participant(self, user):
        async with self.state_lock:
            if self.started or user.id in self.participants or len(self.participants) >= 4:
                return False
            user_data = await get_user_data(user.id)
            idx = user_data.get("investigator_index", 0)
            chars = user_data.get("characters", [])
            char = Character.from_dict(chars[idx]) if chars and idx < len(chars) else Character.from_dict({"name": "모험가", "hp": 100, "attack":10, "defense":5})
            
            char.status_effects = {"bleed": 0, "paralysis": 0, "stun": 0}
            char.runtime_cooldowns = {}
            if hasattr(char, "apply_battle_start_buffs"):
                char.apply_battle_start_buffs()
            self.participants[user.id] = {
                "user": user,
                "char": char,
                "char_idx": idx,
                "data": user_data,
                "revived": False,
            }
            return True

    def get_embed(self):
        embed = discord.Embed(title=f"🛡️ [{self.guild_info['name']}] 레이드 모집", description="혼자 바로 출발하거나, 최대 4명의 길드원과 함께할 수 있습니다.", color=discord.Color.orange())
        members = [f"{i+1}. {p['user'].display_name} (Lv.{p['char'].attack+p['char'].defense})" for i, p in enumerate(self.participants.values())]
        embed.add_field(name=f"파티원 ({len(self.participants)}/4)", value="\n".join(members), inline=False)
        return embed

    @discord.ui.button(label="✋ 참가", style=discord.ButtonStyle.success)
    async def btn_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.started:
            return await interaction.response.send_message("이미 출발한 레이드입니다.", ephemeral=True)
        u_guild = await get_user_guild_info(interaction.user.id)
        if not u_guild or u_guild['guild_id'] != self.guild_info['guild_id']:
            return await interaction.response.send_message("❌ 같은 길드원이 아닙니다.", ephemeral=True)
        if await self.add_participant(interaction.user): await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else: await interaction.response.send_message("참가 실패 (이미 참가했거나 인원 초과)", ephemeral=True)

    @discord.ui.button(label="🚀 출발", style=discord.ButtonStyle.danger)
    async def btn_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id: return await interaction.response.send_message("호스트만 시작 가능", ephemeral=True)
        async with self.state_lock:
            if self.started:
                return await interaction.response.send_message("이미 출발한 레이드입니다.", ephemeral=True)
            if len(self.participants) < 1:
                return await interaction.response.send_message("참가자가 필요합니다.", ephemeral=True)
            if not self.boss_data:
                return await interaction.response.send_message("레이드 보스 데이터를 찾지 못했습니다.", ephemeral=True)
            self.started = True

        for participant in self.participants.values():
            await advance_guild_mission(participant["user"], "raid")

        supplies = await consume_guild_raid_supplies(self.guild_info["guild_id"])
        for participant in self.participants.values():
            char = participant["char"]
            if "길드 응급상자" in supplies:
                char.current_hp = min(char.max_hp, char.current_hp + 20)
            if "길드 전투도구" in supplies:
                char.runtime_cooldowns["guild_attack_bonus"] = 3
            if "길드 보호부적" in supplies:
                char.runtime_cooldowns["guild_defense_bonus"] = 3

        boss = Monster(self.boss_data['name'], self.boss_data['hp'], self.boss_data['atk'], self.boss_data['def'], card_deck=self.boss_data['deck'])
        boss.reward_tokens = self.boss_data.get('reward_tokens', {})
        boss.status_effects = {"bleed": 0, "paralysis": 0, "stun": 0}
        
        view = RaidBattleView(self, boss, interaction.message)
        supply_text = ", ".join(supplies) if supplies else "사용한 보급품 없음"
        await interaction.response.edit_message(
            content=f"⚔️ **전투 시작!**\n📦 {supply_text}",
            embed=view.get_status_embed(),
            view=view,
        )

    async def on_timeout(self):
        if self.started:
            return
        for child in self.children:
            child.disabled = True
        if self.public_message:
            try:
                await self.public_message.edit(content="⏱️ 레이드 모집이 종료되었습니다.", view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

# ==================================================================================
# 5. 메인 뷰 (동적 버튼 처리)
# ==================================================================================

class GuildJoinListView(discord.ui.View):
    def __init__(self, author, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.parent_view = parent_view
        self.page = 0
        self.guilds_per_page = 5

    async def load_and_update(self, interaction):
        guilds = await get_guild_list(self.guilds_per_page, self.page * self.guilds_per_page)
        self.clear_items()
        
        if guilds:
            opts = [discord.SelectOption(label=g['name'], description=f"Lv.{g['level']} | 멤버 {g['member_count']}명", value=str(g['guild_id'])) for g in guilds]
            sel = discord.ui.Select(placeholder="가입할 길드 선택", options=opts)
            sel.callback = self.on_select
            self.add_item(sel)

        self.add_item(Button(label="이전", disabled=(self.page==0), custom_id="prev"))
        self.add_item(Button(label="다음", disabled=(len(guilds)<self.guilds_per_page), custom_id="next"))
        
        desc = "\n".join([f"**{g['name']}** (ID: {g['guild_id']}) - Lv.{g['level']}" for g in guilds]) if guilds else "생성된 길드가 없습니다."
        embed = discord.Embed(title="📜 길드 목록", description=desc, color=discord.Color.blue())
        
        if interaction.response.is_done(): await interaction.edit_original_response(embed=embed, view=self)
        else: await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def on_select(self, interaction):
        try: gid = int(interaction.data["values"][0])
        except: return
        suc, msg = await join_guild_by_id(self.author.id, gid)
        if suc: 
            await interaction.response.send_message(f"✅ {msg}", ephemeral=True)
            await self.parent_view.refresh_ui(interaction)
        else: await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

async def _grant_training_rewards(user, score):
    """Grant only newly crossed daily thresholds so repeated attempts remain safe."""
    outcome = {"lines": [], "contribution": 0}

    def grant(latest):
        life = latest.setdefault("life_data", {})
        training = life.setdefault("guild_training", {})
        if training.get("date") != _guild_day_key():
            training.clear()
            training.update({"date": _guild_day_key(), "best_score": 0, "claimed_thresholds": []})
        claimed = {int(value) for value in training.setdefault("claimed_thresholds", [])}
        training["best_score"] = max(int(training.get("best_score", 0)), int(score))
        inventory = latest.setdefault("inventory", {})
        for threshold, reward, label in TRAINING_REWARD_TIERS:
            if int(score) < threshold or threshold in claimed:
                continue
            claimed.add(threshold)
            money = int(reward.get("money", 0))
            pt = int(reward.get("pt", 0))
            if money:
                latest["money"] = int(latest.get("money", 0)) + money
            if pt:
                latest["pt"] = int(latest.get("pt", 0)) + pt
            item_text = []
            for item_name, count in reward.get("items", {}).items():
                inventory[item_name] = int(inventory.get(item_name, 0)) + int(count)
                item_text.append(f"{item_name} ×{int(count)}")
            contribution = int(reward.get("contribution", 0))
            outcome["contribution"] += contribution
            parts = [f"{money:,}원" if money else "", f"{pt:,} PT" if pt else "", *item_text]
            if contribution:
                parts.append(f"공헌도 +{contribution}")
            outcome["lines"].append(f"• {label}: " + ", ".join(part for part in parts if part))
        training["claimed_thresholds"] = sorted(claimed)

    await mutate_user_data(user.id, grant, user.display_name)
    if outcome["contribution"]:
        await add_guild_contribution(
            user.id,
            outcome["contribution"],
            "training",
            f"수련 점수 {int(score)}",
            user.display_name,
        )
    return outcome["lines"]


class GuildTrainingView(discord.ui.View):
    def __init__(self, author, guild_info):
        super().__init__(timeout=180)
        self.author = author
        self.guild_info = guild_info

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 길드 수련장만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def get_embed(self):
        data = await get_user_data(self.author.id, self.author.display_name)
        training = data.get("life_data", {}).get("guild_training", {})
        best = int(training.get("best_score", 0)) if training.get("date") == _guild_day_key() else 0
        embed = discord.Embed(
            title="🥋 길드 수련장",
            description=(
                "공격하는 무한 체력 샌드백을 상대로 **최대 10턴** 동안 수련합니다.\n"
                "내 캐릭터가 쓰러지면 즉시 종료되며, 실제 체력이나 아이템은 소모되지 않습니다.\n"
                "유효한 수련 행동 1회마다 **공용 활동 턴도 1** 진행됩니다."
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="🎯 점수 규칙",
            value=(
                "전투 처리 후 남은 유효한 공격·방어·반격·체력 회복·정신 회복 "
                "주사위 하나당 1점입니다."
            ),
            inline=False,
        )
        embed.add_field(
            name="🎁 일일 구간 보상",
            value=(
                "0 / 5 / 10 / 15 / 20 / 25점 구간을 처음 넘을 때마다 보상이 열립니다.\n"
                "같은 날 재도전해 더 높은 구간을 넘으면 새 구간 보상만 추가 지급됩니다."
            ),
            inline=False,
        )
        embed.add_field(name="오늘의 최고 점수", value=f"**{best}점**", inline=False)
        return embed

    @discord.ui.button(label="🌳 길드 나무", style=discord.ButtonStyle.secondary, row=0)
    async def btn_tree(self, interaction, button):
        embed = discord.Embed(
            title="🌳 길드 나무",
            description="동료 개발자가 준비할 공간입니다. 현재는 입구만 마련되어 있습니다.",
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🗺️ 길드 던전", style=discord.ButtonStyle.secondary, row=0)
    async def btn_dungeon(self, interaction, button):
        embed = discord.Embed(
            title="🗺️ 길드 던전 — 계획 중",
            description=(
                "일반 던전 규칙을 바탕으로 한 **2~3인 협동 콘텐츠**입니다.\n"
                "로비·턴 동기화·중도 이탈 복구·공동 보상 설계를 마친 뒤 별도 패치로 구현합니다."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🥊 수련 시작", style=discord.ButtonStyle.success, row=0)
    async def btn_start(self, interaction, button):
        data = await get_user_data(self.author.id, self.author.display_name)
        view = TrainingCharacterSelectView(self.author, self.guild_info, data, self)
        view.rebuild()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="길드로 돌아가기", style=discord.ButtonStyle.secondary, row=1)
    async def btn_back(self, interaction, button):
        view = GuildMainView()
        await interaction.response.edit_message(
            content=None,
            embed=await view.get_embed(interaction.user.id, interaction.user.display_name),
            view=view,
        )


class TrainingCharacterSelectView(discord.ui.View):
    PER_PAGE = 4

    def __init__(self, author, guild_info, user_data, parent_view):
        super().__init__(timeout=120)
        self.author = author
        self.guild_info = guild_info
        self.user_data = user_data
        self.parent_view = parent_view
        self.page = 0
        self.characters = list(enumerate(user_data.get("characters", [])))

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 캐릭터만 선택할 수 있습니다.", ephemeral=True)
        return False

    def get_embed(self):
        start = self.page * self.PER_PAGE
        lines = []
        for _, data in self.characters[start:start + self.PER_PAGE]:
            lines.append(
                f"**{data.get('name', '이름 없음')}** · "
                f"체력 {int(data.get('hp', 0))} · 공격 {int(data.get('attack', 0))} · "
                f"방어 {int(data.get('defense', 0))}"
            )
        return discord.Embed(
            title="🥊 수련 캐릭터 선택",
            description="\n".join(lines) or "수련할 수 있는 캐릭터가 없습니다.",
            color=discord.Color.orange(),
        )

    def rebuild(self):
        self.clear_items()
        total_pages = max(1, (len(self.characters) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * self.PER_PAGE
        for index, data in self.characters[start:start + self.PER_PAGE]:
            button = Button(label=data.get("name", "이름 없음")[:80], style=discord.ButtonStyle.primary, row=0)

            async def choose(interaction, character_index=index):
                latest = await get_user_data(self.author.id, self.author.display_name)
                characters = latest.get("characters", [])
                if not 0 <= character_index < len(characters):
                    return await interaction.response.send_message(
                        "캐릭터 정보가 바뀌었습니다. 수련장을 다시 열어주세요.",
                        ephemeral=True,
                    )
                character = Character.from_dict(characters[character_index])
                character.current_hp = character.max_hp
                character.current_mental = character.max_mental
                character.apply_battle_start_buffs()
                character.current_hp = character.max_hp
                character.current_mental = character.max_mental
                battle = TrainingBattleView(self.author, self.guild_info, character, self.parent_view)
                battle.rebuild()
                await interaction.response.edit_message(embed=battle.get_embed(), view=battle)

            button.callback = choose
            self.add_item(button)

        if total_pages > 1:
            previous = Button(label="이전", disabled=self.page == 0, row=1)
            counter = Button(label=f"{self.page + 1}/{total_pages}", disabled=True, row=1)
            following = Button(label="다음", disabled=self.page >= total_pages - 1, row=1)

            async def move(interaction, delta):
                self.page = max(0, min(self.page + delta, total_pages - 1))
                self.rebuild()
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            async def previous_page(interaction):
                await move(interaction, -1)

            async def next_page(interaction):
                await move(interaction, 1)

            previous.callback = previous_page
            following.callback = next_page
            self.add_item(previous)
            self.add_item(counter)
            self.add_item(following)

        back = Button(label="수련장으로", style=discord.ButtonStyle.secondary, row=2)

        async def go_back(interaction):
            await interaction.response.edit_message(
                embed=await self.parent_view.get_embed(),
                view=self.parent_view,
            )

        back.callback = go_back
        self.add_item(back)


class TrainingBattleView(discord.ui.View):
    PER_PAGE = 4
    EFFECTIVE_DICE = {"attack", "defense", "counter", "heal", "heal_hp", "mental_heal"}

    def __init__(self, author, guild_info, character, parent_view):
        super().__init__(timeout=300)
        self.author = author
        self.guild_info = guild_info
        self.character = character
        self.parent_view = parent_view
        self.sandbag = Monster(
            "공격하는 무한 샌드백",
            hp=1_000_000_000,
            attack=max(1, int(character.attack * 0.55)),
            defense=max(1, int(character.defense * 0.45)),
            description="맞기만 하지는 않는 길드 수련용 샌드백입니다.",
            pattern_type="aggressive",
            card_deck=["기본공격", "기본공격", "기본방어", "기본반격"],
        )
        self.turn = 1
        self.score = 0
        self.page = 0
        self.finished = False
        self.logs = []
        self.shayla_trigger = False

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인의 수련 커맨드만 조작할 수 있습니다.", ephemeral=True)
        return False

    def available_cards(self):
        return [
            card_name
            for card_name in (getattr(self.character, "equipped_cards", None) or ["기본공격"])
            if get_card(card_name)
        ]

    def rebuild(self):
        self.clear_items()
        if self.finished:
            back = Button(label="수련장으로", style=discord.ButtonStyle.secondary)

            async def go_back(interaction):
                view = GuildTrainingView(self.author, self.guild_info)
                await interaction.response.edit_message(embed=await view.get_embed(), view=view)

            back.callback = go_back
            self.add_item(back)
            return

        cards = self.available_cards()
        total_pages = max(1, (len(cards) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * self.PER_PAGE
        for card_name in cards[start:start + self.PER_PAGE]:
            button = Button(label=card_name[:80], style=discord.ButtonStyle.primary, row=0)

            async def choose(interaction, selected=card_name):
                await self.run_turn(interaction, selected)

            button.callback = choose
            self.add_item(button)

        if total_pages > 1:
            previous = Button(label="이전", disabled=self.page == 0, row=1)
            counter = Button(label=f"{self.page + 1}/{total_pages}", disabled=True, row=1)
            following = Button(label="다음", disabled=self.page >= total_pages - 1, row=1)

            async def move(interaction, delta):
                self.page = max(0, min(self.page + delta, total_pages - 1))
                self.rebuild()
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            async def previous_page(interaction):
                await move(interaction, -1)

            async def next_page(interaction):
                await move(interaction, 1)

            previous.callback = previous_page
            following.callback = next_page
            self.add_item(previous)
            self.add_item(counter)
            self.add_item(following)

        stop = Button(label="수련 중단", style=discord.ButtonStyle.danger, row=2)

        async def stop_training(interaction):
            await self.finish(interaction, "수련을 중단했습니다.")

        stop.callback = stop_training
        self.add_item(stop)

    def get_embed(self):
        embed = discord.Embed(
            title=f"🥊 길드 수련 · {min(self.turn, 10)}/10턴",
            description=(
                f"**{self.character.name}** ❤️ {max(0, self.character.current_hp)}/{self.character.max_hp}\n"
                f"**공격하는 무한 샌드백** ❤️ ∞\n"
                f"현재 점수: **{self.score}점**"
            ),
            color=discord.Color.orange(),
        )
        cards = self.available_cards()
        start = self.page * self.PER_PAGE
        if not self.finished:
            details = []
            for card_name in cards[start:start + self.PER_PAGE]:
                card = get_card(card_name)
                details.append(f"**{card_name}**\n{card.description if card else '효과 정보 없음'}")
            embed.add_field(name="🎴 이번 턴 커맨드", value="\n\n".join(details) or "사용 가능한 카드가 없습니다.", inline=False)
        if self.logs:
            text = "\n".join(self.logs[-3:])
            embed.add_field(name="최근 결과", value=text[-1000:], inline=False)
        return embed

    async def run_turn(self, interaction, card_name):
        if self.finished:
            return await interaction.response.send_message("이미 끝난 수련입니다.", ephemeral=True)
        user_card = get_card(card_name)
        if not user_card:
            return await interaction.response.send_message("카드 정보를 찾지 못했습니다.", ephemeral=True)
        # Every valid sandbag command is one shared activity turn.
        await advance_guild_world_turn(self.author, 1)

        bag_card = self.sandbag.decide_action() or get_card("기본공격")
        gem_log = process_gem_turn_start(self.character, self.sandbag, self.turn, card_name)
        user_res = user_card.use_card(
            self.character.attack,
            self.character.defense,
            self.character.current_mental,
        )
        bag_res = bag_card.use_card(
            self.sandbag.attack,
            self.sandbag.defense,
            self.sandbag.current_mental,
        )
        user_res = battle_engine.apply_stat_scaling(user_res, self.character)
        bag_res = battle_engine.apply_stat_scaling(bag_res, self.sandbag)
        effects = []
        for artifact in (
            getattr(self.character, "equipped_artifact", None),
            getattr(self.character, "equipped_engraved_artifact", None),
        ):
            if isinstance(artifact, dict) and artifact.get("special"):
                effects.append(artifact.get("special"))
        art_log, self.shayla_trigger = battle_engine.process_turn_start_artifacts(
            self.character,
            self.sandbag,
            user_res,
            bag_res,
            self.turn,
            self.shayla_trigger,
            card_name,
        )
        if "escalation" in effects and user_res:
            last = self.character.runtime_cooldowns.get("escalation", -10)
            if self.turn - last >= 2:
                bonus = escalation_roll(self.character)
                user_res[-1]["value"] += bonus
                self.character.runtime_cooldowns["escalation"] = self.turn

        clash_log, _, _ = battle_engine.process_clash_loop(
            self.character,
            self.sandbag,
            user_res,
            bag_res,
            effects,
            [],
            self.turn,
        )
        effective = sum(
            1
            for dice in user_res
            if dice.get("type") in self.EFFECTIVE_DICE and int(dice.get("value", 0)) > 0
        )
        self.score += effective
        self.sandbag.current_hp = self.sandbag.max_hp
        self.sandbag.current_mental = self.sandbag.max_mental
        summary = (
            f"**{self.turn}턴** {card_name} vs {bag_card.name} · "
            f"유효 주사위 **+{effective}**"
        )
        if gem_log:
            summary += f"\n💎 {gem_log}"
        if art_log:
            summary += f"\n{art_log.strip()}"
        if clash_log:
            compact = " ".join(clash_log.replace("\n", " ").split())
            summary += f"\n{compact[:400]}"
        self.logs.append(summary)

        if self.character.current_hp <= 0:
            self.character.current_hp = 0
            return await self.finish(interaction, "캐릭터가 쓰러져 수련을 마쳤습니다.")
        if self.turn >= 10:
            return await self.finish(interaction, "10턴 수련을 모두 마쳤습니다.")
        self.turn += 1
        self.page = 0
        self.rebuild()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def finish(self, interaction, reason):
        if self.finished:
            return
        self.finished = True
        rewards = await _grant_training_rewards(self.author, self.score)
        self.rebuild()
        embed = self.get_embed()
        embed.title = "🏁 길드 수련 결과"
        embed.description = (
            f"{reason}\n\n최종 점수: **{self.score}점**\n"
            + ("\n".join(rewards) if rewards else "오늘 이미 획득한 점수 구간의 보상입니다.")
        )
        await interaction.response.edit_message(embed=embed, view=self)


class GuildMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.page = 0

    def _add_navigation(self):
        previous = Button(label="이전", disabled=self.page == 0, row=1)
        counter = Button(label=f"{self.page + 1}/2", disabled=True, row=1)
        following = Button(label="다음", disabled=self.page == 1, row=1)

        async def move(interaction, page):
            self.page = page
            await interaction.response.edit_message(
                embed=await self.get_embed(interaction.user.id, interaction.user.display_name),
                view=self,
            )

        async def previous_page(interaction):
            await move(interaction, 0)

        async def next_page(interaction):
            await move(interaction, 1)

        previous.callback = previous_page
        following.callback = next_page
        self.add_item(previous)
        self.add_item(counter)
        self.add_item(following)

    async def get_embed(self, user_id, user_name):
        guild_info = await get_user_guild_info(user_id)
        self.clear_items()
        if not guild_info:
            return discord.Embed(
                title="🛡️ 공용 길드",
                description="길드 정보를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.",
                color=discord.Color.red(),
            )
        if self.page == 0:
            self.add_item(self.btn_mission)
            self.add_item(self.btn_shop)
            self.add_item(self.btn_manage)
            self.add_item(self.btn_warehouse)
        else:
            self.add_item(self.btn_training)
            self.add_item(self.btn_raid)
        self._add_navigation()

        g = guild_info
        embed = discord.Embed(
            title=f"🛡️ {g['name']}",
            description=(
                "모든 조사원이 함께 성장시키는 공용 길드입니다.\n"
                f"등급: {RANK_NAMES.get(g['level'], '브론즈')}\n"
                f"개인 공헌도: {g.get('contribution', 0):,}"
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="🏗️ 공용 자원",
            value=(
                f"🌲 {g['token_wood']:,} | ⛓️ {g['token_iron']:,} | "
                f"🔮 {g['token_magic']:,} | 🧿 {g['token_sorcery']:,}"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏅 공헌도 핵심",
            value="납품 환산 1점당 +1 · 미션 보상 +20 · 레이드 성공 +100/실패 +20",
            inline=False,
        )
        embed.set_footer(
            text=f"메뉴 {self.page + 1}/2 · 생성·검색·탈퇴 없이 모든 이용자가 자동 소속됩니다."
        )
        return embed

    # 공용 길드는 자동 가입이므로 생성·검색·탈퇴 버튼을 노출하지 않는다.
    @discord.ui.button(label="🎯 미션", style=discord.ButtonStyle.success, custom_id="guild_btn_mission")
    async def btn_mission(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        view = GuildMissionView(interaction.user, guild_info)
        await interaction.response.send_message(embed=await view.get_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="🛒 길드 상점", style=discord.ButtonStyle.primary, custom_id="guild_btn_shop")
    async def btn_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info:
            return
        view = GuildShopView(interaction.user, guild_info, None)
        await view.setup()
        await interaction.response.send_message(embed=await view.get_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="📦 창고", style=discord.ButtonStyle.secondary, custom_id="guild_btn_warehouse")
    async def btn_warehouse(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        view = GuildWarehouseView(interaction.user, guild_info)
        await interaction.response.send_message(embed=await view.get_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="⚔️ 레이드", style=discord.ButtonStyle.danger, custom_id="guild_btn_raid")
    async def btn_raid(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        boss_rank = RAID_RANK_KEYS.get(guild_info['level'], "Bronze")
        boss_data = RAID_BOSS_DATA.get(boss_rank) or RAID_BOSS_DATA.get("Gold")
        if not boss_data:
            return await interaction.response.send_message("레이드 보스 데이터를 찾지 못했습니다.", ephemeral=True)
        lobby = RaidLobbyView(interaction.user, guild_info, boss_data)
        await lobby.add_participant(interaction.user)
        await interaction.response.send_message(embed=lobby.get_embed(), view=lobby)
        try:
            lobby.public_message = await interaction.original_response()
        except (discord.NotFound, discord.HTTPException):
            pass

    @discord.ui.button(label="🥋 수련장", style=discord.ButtonStyle.success, custom_id="guild_btn_training")
    async def btn_training(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info:
            return
        view = GuildTrainingView(interaction.user, guild_info)
        await interaction.response.send_message(embed=await view.get_embed(), view=view, ephemeral=True)
    
    @discord.ui.button(label="⚖️ 물자 관리", style=discord.ButtonStyle.secondary, custom_id="guild_btn_manage")
    async def btn_manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        view = InventoryManageView(interaction.user, guild_info)
        await view.setup_view()
        await interaction.response.send_message(embed=await view.get_embed(), view=view, ephemeral=True)

    async def refresh_ui(self, interaction):
        embed = await self.get_embed(interaction.user.id, interaction.user.display_name)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

class GuildCreateModal(Modal, title="길드 생성"):
    name = TextInput(label="이름", min_length=2)
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
    async def on_submit(self, interaction: discord.Interaction):
        suc, msg = await create_guild(interaction.user.id, self.name.value)
        if suc: 
            await interaction.response.send_message(msg, ephemeral=True)
            await self.parent_view.refresh_ui(interaction)
        else: await interaction.response.send_message(msg, ephemeral=True)
