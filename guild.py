# cafe-guild-market-v9.1
# ripple-artifact-v8.7
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
    deposit_guild_item, store_guild_item, craft_guild_workshop_item,
    deposit_guild_artifact, get_guild_logs, get_guild_list,
    get_guild_items, withdraw_guild_item, craft_guild_item,
    consume_guild_raid_supplies, add_guild_contribution,
    get_or_create_daily_guild_shop, buy_guild_shop_item,
    advance_world_turn, GUILD_RANK_THRESHOLDS, GUILD_DONATION_EFFICIENCY,
    guild_level_for_contribution,
)
from items import ITEM_CATEGORIES
from monsters import RAID_BOSS_DATA, Monster
from character import Character
from cards import get_card
import battle_engine
from gem_effects import (
    apply_escalation_to_dice,
    apply_ripple_to_dice,
    battle_end_gem_heal,
    process_gem_turn_start,
    revive_gem_effects,
)
from guild_dungeon import GuildDungeonLobbyView

# guild-pvp-stability-v7.2
# raid-private-command-panel-v8.5
# comparison-select-ui-v8.6.6
# guild-shop-training-v8.6
# guild-workshop-warehouse-v8.6.1
# guild-rank-training-score-v8.6.2
# guild-inline-navigation-v8.6.3

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

GUILD_WORKSHOP_RECIPES = {
    "목재": {
        "need": {"평범한 나무판자": 3},
        "description": "평범한 판자를 길드 규격의 목재로 가공합니다.",
    },
    "철괴": {
        "need": {"녹슨 철": 3, "반짝가루": 1},
        "description": "녹슨 철을 정련해 쓸 수 있는 철괴로 만듭니다.",
    },
    "중급 마력석": {
        "need": {"하급 마력석": 3, "반짝가루": 1},
        "description": "하급 마력석의 마력을 한 덩어리로 압축합니다.",
    },
    "주술석": {
        "need": {"악몽 파편": 2, "빛구슬": 2},
        "description": "불안정한 파편을 길드용 주술석으로 안정화합니다.",
    },
    "구름 블럭": {
        "need": {"구름 한 줌": 3, "중급 마력석": 1},
        "description": "흩어진 구름을 단단한 제작 블럭으로 굳힙니다.",
    },
    "양질 목재": {
        "need": {"목재": 4, "사랑나무 가지": 1},
        "description": "기본 목재를 상위 제작용 목재로 다듬습니다.",
    },
    "강화 철강": {
        "need": {"철괴": 4, "반짝가루": 2},
        "description": "철괴를 반복 정련해 강화 철강으로 만듭니다.",
    },
    "상급 마력석": {
        "need": {"중급 마력석": 4, "반짝가루": 2},
        "description": "중급 마력석을 한층 더 강하게 응축합니다.",
    },
    "고급 주술석": {
        "need": {"주술석": 4, "상급 마력석": 1},
        "description": "주술석의 불안정성을 상급 마력으로 고정합니다.",
    },
    "응결 구름 블럭": {
        "need": {"구름 블럭": 4, "상급 마력석": 1},
        "description": "구름 블럭을 고밀도로 응결한 희귀 제작 재료입니다.",
    },
}

GUILD_STORABLE_ITEMS = set(GUILD_WORKSHOP_RECIPES)
for _recipe in GUILD_WORKSHOP_RECIPES.values():
    GUILD_STORABLE_ITEMS.update(_recipe["need"])

RANK_NAMES = {level: name for level, name, _ in GUILD_RANK_THRESHOLDS}
RAID_RANK_KEYS = {
    1: "Bronze", 2: "Bronze", 3: "Silver", 4: "Gold", 5: "Platinum",
    6: "Platinum", 7: "Diamond", 8: "Diamond", 9: "Diamond", 10: "Diamond",
}
GUILD_SHOP_SLOT_COUNT = {
    1: 3, 2: 4, 3: 5, 4: 6, 5: 7,
    6: 8, 7: 9, 8: 10, 9: 11, 10: 12,
}

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
        "min_rank": 3,
    },
    {
        "item_name": "순수한 희망", "category": "consumable",
        "cost": {"wood": 80, "iron": 80, "magic": 100, "sorcery": 100},
        "description": "세공 도구 뽑기 1회에 사용하는 귀한 재화입니다.",
        "min_rank": 5,
    },
]
GUILD_SHOP_HIGH_TIER = [
    {"item_name": "양질 목재", "category": "material", "cost": {"wood": 25, "sorcery": 8}, "description": "상위 제작용 목재입니다.", "min_rank": 1},
    {"item_name": "강화 철강", "category": "material", "cost": {"iron": 25, "magic": 8}, "description": "상위 제작용 금속입니다.", "min_rank": 2},
    {"item_name": "상급 마력석", "category": "material", "cost": {"magic": 25, "iron": 8}, "description": "응축된 상급 마력 자원입니다.", "min_rank": 3},
    {"item_name": "고급 주술석", "category": "material", "cost": {"sorcery": 25, "wood": 8}, "description": "고급 주술 제작에 쓰는 자원입니다.", "min_rank": 4},
    {"item_name": "응결 구름 블럭", "category": "material", "cost": {"wood": 30, "magic": 15}, "description": "희귀 제작에 쓰는 응결 재료입니다.", "min_rank": 5},
]
GUILD_SHOP_SUPPLIES = [
    {
        "item_name": name,
        "category": "consumable",
        "cost": dict(info["cost"]),
        "description": info["description"],
        "min_rank": index + 1,
    }
    for index, (name, info) in enumerate(GUILD_CRAFT_RECIPES.items())
]
GUILD_SHOP_SEEDS = [
    {"item_name": name, "category": "seed", "cost": cost, "description": "채소밭 재배를 시작하는 종묘입니다.", "min_rank": min_rank}
    for name, cost, min_rank in [
        ("새벽 감자 씨앗", {"wood": 6}, 1), ("별빛 토마토 씨앗", {"wood": 8}, 1),
        ("꿈양배추 씨앗", {"wood": 12, "magic": 3}, 2), ("구름 양파 씨앗", {"wood": 8}, 2),
        ("무지개 당근 씨앗", {"wood": 14, "magic": 4}, 3), ("시간 호박 씨앗", {"wood": 20, "magic": 8}, 4),
        ("달빛 버섯 종균", {"wood": 15, "sorcery": 5}, 5), ("악몽 고추 씨앗", {"wood": 18, "sorcery": 8}, 6),
    ]
]
GUILD_SHOP_FINGERLINGS = [
    {"item_name": name, "category": "fingerling", "cost": cost, "description": "양어장 양식을 시작하는 어린 개체입니다.", "min_rank": min_rank}
    for name, cost, min_rank in [
        ("빵잉어 치어", {"iron": 6}, 1), ("버들치 치어", {"iron": 9}, 1),
        ("모래무지 치어", {"iron": 8}, 2), ("등불오징어 유생", {"iron": 15, "magic": 5}, 3),
        ("로운새우 치하", {"iron": 7}, 2), ("어름치 치어", {"iron": 20, "magic": 7}, 4),
        ("별비늘돔 치어", {"iron": 25, "magic": 12}, 5), ("악몽 메기 치어", {"iron": 20, "sorcery": 8}, 6),
    ]
]

TRAINING_REWARD_TIERS = [
    (0, {"money": 5_000}, "참가 보상"),
    (100, {"money": 10_000, "pt": 100}, "100점"),
    (250, {"money": 20_000, "pt": 250}, "250점"),
    (500, {"money": 35_000, "pt": 450, "contribution": 10}, "500점"),
    (750, {"money": 50_000, "pt": 700, "items": {"상급 마력석": 1}}, "750점"),
    (1_000, {"money": 70_000, "pt": 1_000, "items": {"순수한 희망": 1}, "contribution": 15}, "1,000점"),
    (1_500, {"money": 100_000, "pt": 1_500, "items": {"응결 구름 블럭": 1}}, "1,500점"),
    (2_000, {"money": 140_000, "pt": 2_000, "items": {"원석": 1}, "contribution": 20}, "2,000점"),
    (3_000, {"money": 200_000, "pt": 3_000, "items": {"원석": 1, "상급 마력석": 2}}, "3,000점"),
    (5_000, {"money": 300_000, "pt": 5_000, "items": {"순수한 희망": 1}, "contribution": 30}, "5,000점"),
    (8_000, {"money": 500_000, "pt": 8_000, "items": {"원석": 2, "순수한 희망": 2}, "contribution": 50}, "8,000점"),
]


def _format_token_cost(cost, multiplier=1):
    return " · ".join(
        f"{TOKEN_EMOJIS.get(key, '')}{TOKEN_LABELS.get(key, key)} {int(value) * int(multiplier):,}"
        for key, value in cost.items()
    )


def _message_command_owner_id(interaction):
    """메시지를 처음 연 이용자 ID를 상호작용 메타데이터나 푸터에서 찾는다."""
    message = getattr(interaction, "message", None)
    for attr in ("interaction_metadata", "interaction"):
        metadata = getattr(message, attr, None)
        user = getattr(metadata, "user", None)
        if user is not None and getattr(user, "id", None) is not None:
            return int(user.id)
    embeds = getattr(message, "embeds", None) or []
    if embeds:
        footer_text = str(getattr(getattr(embeds[0], "footer", None), "text", "") or "")
        marker = "owner:"
        if marker in footer_text:
            raw = footer_text.rsplit(marker, 1)[1].split()[0].strip()
            if raw.isdigit():
                return int(raw)
    return None


def _rank_threshold_info(total_contribution):
    total = max(0, int(total_contribution or 0))
    level = guild_level_for_contribution(total)
    current = next(row for row in GUILD_RANK_THRESHOLDS if row[0] == level)
    next_rank = next((row for row in GUILD_RANK_THRESHOLDS if row[0] == level + 1), None)
    return current, next_rank


def _donation_efficiency(level):
    return GUILD_DONATION_EFFICIENCY.get(max(1, min(10, int(level or 1))), 100)


def _scale_donation_rewards(rewards, level):
    efficiency = _donation_efficiency(level)
    return {
        key: (max(0, int(value)) * efficiency + 99) // 100
        for key, value in rewards.items()
        if int(value) > 0
    }


def _build_daily_shop_rotation(level, day_key):
    """Build a deterministic daily roster whose size and pool grow by guild rank."""
    level = max(1, min(10, int(level or 1)))
    rng = random.Random(f"{day_key}:{level}:guild-shop-v2")
    unlocked_high = [item for item in GUILD_SHOP_HIGH_TIER if item["min_rank"] <= level]
    unlocked_seeds = [item for item in GUILD_SHOP_SEEDS if item["min_rank"] <= level]
    unlocked_fish = [item for item in GUILD_SHOP_FINGERLINGS if item["min_rank"] <= level]
    unlocked_all = [
        item
        for item in (
            GUILD_SHOP_PREMIUM
            + GUILD_SHOP_HIGH_TIER
            + GUILD_SHOP_SEEDS
            + GUILD_SHOP_FINGERLINGS
        )
        if item["min_rank"] <= level
    ]

    selected = [
        rng.choice(unlocked_high),
        rng.choice(unlocked_seeds),
        rng.choice(unlocked_fish),
    ]
    selected_names = {item["item_name"] for item in selected}
    extras = [item for item in unlocked_all if item["item_name"] not in selected_names]
    rng.shuffle(extras)
    selected.extend(extras[:max(0, GUILD_SHOP_SLOT_COUNT[level] - len(selected))])

    result = []
    for item in selected[:GUILD_SHOP_SLOT_COUNT[level]]:
        row = dict(item)
        row["cost"] = dict(item["cost"])
        row["stock"] = rng.randint(20, 100)
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

class InventoryManageView(discord.ui.View):
    """재고를 보면서 수량 버튼으로 납품하거나 공용 창고에 반입한다."""
    PER_PAGE = 8

    def __init__(self, author, guild_info, mode="donate"):
        super().__init__(timeout=180)
        self.author = author
        self.guild_info = guild_info
        self.mode = mode if mode in {"donate", "store"} else "donate"
        self.user_data = {}
        self.guild_stock = {}
        self.items = []
        self.page = 0
        self.selected_item = None
        self.quantity = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인이 연 길드 물자 화면만 조작할 수 있습니다.", ephemeral=True)
        return False

    def _eligible_items(self):
        inventory = self.user_data.get("inventory", {})
        allowed = ITEM_TOKEN_VALUES if self.mode == "donate" else GUILD_STORABLE_ITEMS
        return sorted(
            (name, int(count))
            for name, count in inventory.items()
            if name in allowed and int(count or 0) > 0
        )

    def _item_category(self, item_name):
        return "consumable" if item_name in ITEM_CATEGORIES.get("consumable", []) else "material"

    async def setup_view(self):
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        current_guild = await get_user_guild_info(self.author.id)
        if current_guild:
            self.guild_info = current_guild
        rows = await get_guild_items(self.guild_info["guild_id"])
        self.guild_stock = {
            row["item_name"]: int(row.get("count", 0) or 0)
            for row in rows
        }
        self.items = self._eligible_items()
        total_pages = max(1, (len(self.items) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))

        inventory = self.user_data.get("inventory", {})
        if self.selected_item not in dict(self.items):
            self.selected_item = None
            self.quantity = 0
        elif self.selected_item:
            self.quantity = min(self.quantity, int(inventory.get(self.selected_item, 0)))

        self.clear_items()
        donate = Button(
            label="♻️ 자원 납품",
            style=discord.ButtonStyle.primary if self.mode == "donate" else discord.ButtonStyle.secondary,
            row=0,
        )
        store = Button(
            label="📥 창고 반입",
            style=discord.ButtonStyle.primary if self.mode == "store" else discord.ButtonStyle.secondary,
            row=0,
        )
        donate.callback = self.switch_to_donate
        store.callback = self.switch_to_store
        self.add_item(donate)
        self.add_item(store)

        visible = self.items[self.page * self.PER_PAGE:(self.page + 1) * self.PER_PAGE]
        if visible:
            item_select = Select(
                placeholder=f"처리할 재고 선택 ({self.page + 1}/{total_pages})",
                row=1,
                options=[
                    discord.SelectOption(
                        label=f"{item_name} ×{count}",
                        value=item_name,
                        description=(
                            (
                                f"개인 {count}개 · 1개 납품 시 "
                                f"{_format_token_cost(_scale_donation_rewards(ITEM_TOKEN_VALUES[item_name], self.guild_info.get('level', 1)))}"
                            )
                            if self.mode == "donate"
                            else (
                                f"개인 {count}개 · 공용 {int(self.guild_stock.get(item_name, 0))}개"
                            )
                        )[:100],
                        default=item_name == self.selected_item,
                    )
                    for item_name, count in visible
                ],
            )

            async def select_item(interaction):
                self.selected_item = interaction.data["values"][0]
                self.quantity = min(
                    1,
                    int(self.user_data.get("inventory", {}).get(self.selected_item, 0)),
                )
                await self.setup_view()
                await interaction.response.edit_message(embed=await self.get_embed(), view=self)

            item_select.callback = select_item
            self.add_item(item_select)

        previous = Button(label="이전", disabled=self.page == 0, row=2)
        counter = Button(label=f"{self.page + 1}/{total_pages}", disabled=True, row=2)
        following = Button(label="다음", disabled=self.page >= total_pages - 1, row=2)
        previous.callback = self.prev_page
        following.callback = self.next_page
        self.add_item(previous)
        self.add_item(counter)
        self.add_item(following)

        for label, delta in (("-10", -10), ("-1", -1), ("+1", 1), ("+10", 10)):
            button = Button(label=label, disabled=not self.selected_item, row=3)

            async def adjust(interaction, amount=delta):
                stock = int(self.user_data.get("inventory", {}).get(self.selected_item, 0))
                self.quantity = max(0, min(stock, self.quantity + amount))
                await self.setup_view()
                await interaction.response.edit_message(embed=await self.get_embed(), view=self)

            button.callback = adjust
            self.add_item(button)

        confirm = Button(
            label="납품 확정" if self.mode == "donate" else "반입 확정",
            style=discord.ButtonStyle.success,
            disabled=not self.selected_item or self.quantity <= 0,
            row=4,
        )
        reset = Button(label="수량 초기화", style=discord.ButtonStyle.secondary, disabled=not self.selected_item, row=4)
        back = Button(label="길드로 돌아가기", style=discord.ButtonStyle.secondary, row=4)
        confirm.callback = self.confirm
        reset.callback = self.reset_quantity
        back.callback = self.back_to_guild
        self.add_item(confirm)
        self.add_item(reset)
        self.add_item(back)

    async def get_embed(self):
        if self.mode == "donate":
            title = "♻️ 길드 자원 납품"
            description = (
                "개인 아이템을 길드 공용 자원으로 **환산해 소모**합니다.\n"
                "환산 자원 1점마다 개인 공헌도도 1 올라갑니다.\n"
                f"현재 길드 등급 납품 효율: **{_donation_efficiency(self.guild_info.get('level', 1))}%**"
            )
            color = discord.Color.green()
        else:
            title = "📥 길드 창고 반입"
            description = (
                "개인 아이템을 환산하지 않고 공용 창고로 그대로 옮깁니다.\n"
                "반입한 실물 재료는 길드 제작소의 `공용 재료` 제작에 사용됩니다."
            )
            color = discord.Color.blue()
        embed = discord.Embed(title=title, description=description, color=color)

        visible = self.items[self.page * self.PER_PAGE:(self.page + 1) * self.PER_PAGE]
        lines = []
        for item_name, count in visible:
            suffix = ""
            if self.mode == "donate":
                scaled = _scale_donation_rewards(
                    ITEM_TOKEN_VALUES[item_name],
                    self.guild_info.get("level", 1),
                )
                suffix = " → " + _format_token_cost(scaled)
            else:
                suffix = f" · 공용 {self.guild_stock.get(item_name, 0)}"
            lines.append(f"• **{item_name}**: 개인 {count}{suffix}")
        embed.add_field(
            name="현재 선택 가능한 재고",
            value="\n".join(lines) if lines else "조건에 맞는 개인 재고가 없습니다.",
            inline=False,
        )

        if self.selected_item:
            owned = int(self.user_data.get("inventory", {}).get(self.selected_item, 0))
            detail = [
                f"아이템: **{self.selected_item}**",
                f"선택 수량: **{self.quantity}개**",
                f"처리 후 개인 재고: **{owned - self.quantity}개**",
            ]
            if self.mode == "donate":
                base_rewards = {
                    key: int(value) * self.quantity
                    for key, value in ITEM_TOKEN_VALUES[self.selected_item].items()
                }
                rewards = _scale_donation_rewards(
                    base_rewards,
                    self.guild_info.get("level", 1),
                )
                detail.append(f"획득 공용 자원: {_format_token_cost(rewards) if self.quantity else '없음'}")
                detail.append(f"획득 공헌도: **{sum(rewards.values())}**")
                detail.append(
                    f"현재 등급 효율: **{_donation_efficiency(self.guild_info.get('level', 1))}%**"
                )
            else:
                shared = self.guild_stock.get(self.selected_item, 0)
                detail.append(f"처리 후 공용 재고: **{shared + self.quantity}개**")
            embed.add_field(name="선택 내용", value="\n".join(detail), inline=False)
        return embed

    async def _switch_mode(self, interaction, mode):
        self.mode = mode
        self.page = 0
        self.selected_item = None
        self.quantity = 0
        await self.setup_view()
        await interaction.response.edit_message(content=None, embed=await self.get_embed(), view=self)

    async def switch_to_donate(self, interaction):
        await self._switch_mode(interaction, "donate")

    async def switch_to_store(self, interaction):
        await self._switch_mode(interaction, "store")

    async def prev_page(self, interaction):
        self.page = max(0, self.page - 1)
        await self.setup_view()
        await interaction.response.edit_message(embed=await self.get_embed(), view=self)

    async def next_page(self, interaction):
        self.page += 1
        await self.setup_view()
        await interaction.response.edit_message(embed=await self.get_embed(), view=self)

    async def reset_quantity(self, interaction):
        self.quantity = 0
        await self.setup_view()
        await interaction.response.edit_message(embed=await self.get_embed(), view=self)

    async def confirm(self, interaction):
        item_name = self.selected_item
        quantity = int(self.quantity)
        if not item_name or quantity <= 0:
            return await interaction.response.send_message("아이템과 수량을 먼저 선택해주세요.", ephemeral=True)

        if self.mode == "donate":
            base_rewards = {
                key: int(value) * quantity
                for key, value in ITEM_TOKEN_VALUES[item_name].items()
            }
            scaled_rewards = _scale_donation_rewards(
                base_rewards,
                self.guild_info.get("level", 1),
            )
            success, message = await deposit_guild_item(
                interaction.user.id,
                self.guild_info["guild_id"],
                item_name,
                quantity,
                self._item_category(item_name),
                base_rewards,
                interaction.user.display_name,
            )
            if success:
                await advance_guild_mission(interaction.user, "donate", sum(scaled_rewards.values()))
        else:
            success, message = await store_guild_item(
                interaction.user.id,
                self.guild_info["guild_id"],
                item_name,
                quantity,
                self._item_category(item_name),
                interaction.user.display_name,
            )

        if not success:
            return await interaction.response.send_message(f"❌ {message}", ephemeral=True)
        self.selected_item = None
        self.quantity = 0
        await self.setup_view()
        await interaction.response.edit_message(
            content=f"✅ {message}",
            embed=await self.get_embed(),
            view=self,
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


class GuildWorkshopView(discord.ui.View):
    """길드 제작 재료를 개인 또는 공용 재고 한쪽에서 선택해 사용한다."""
    PER_PAGE = 8

    def __init__(self, author, guild_info):
        super().__init__(timeout=180)
        self.author = author
        self.guild_info = guild_info
        self.source = "personal"
        self.recipe_names = list(GUILD_WORKSHOP_RECIPES)
        self.selected_recipe = self.recipe_names[0] if self.recipe_names else None
        self.page = 0
        self.personal_stock = {}
        self.guild_stock = {}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인이 연 길드 제작소만 조작할 수 있습니다.", ephemeral=True)
        return False

    async def setup_view(self):
        user_data = await get_user_data(self.author.id, self.author.display_name)
        self.personal_stock = {
            name: int(count or 0)
            for name, count in user_data.get("inventory", {}).items()
        }
        rows = await get_guild_items(self.guild_info["guild_id"])
        self.guild_stock = {
            row["item_name"]: int(row.get("count", 0) or 0)
            for row in rows
        }
        total_pages = max(1, (len(self.recipe_names) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))

        self.clear_items()
        personal = Button(
            label="🎒 개인 재료",
            style=discord.ButtonStyle.primary if self.source == "personal" else discord.ButtonStyle.secondary,
            row=0,
        )
        shared = Button(
            label="🏰 공용 재료",
            style=discord.ButtonStyle.primary if self.source == "guild" else discord.ButtonStyle.secondary,
            row=0,
        )
        personal.callback = self.use_personal
        shared.callback = self.use_guild
        self.add_item(personal)
        self.add_item(shared)

        visible = self.recipe_names[self.page * self.PER_PAGE:(self.page + 1) * self.PER_PAGE]
        if visible:
            if self.selected_recipe not in visible:
                self.selected_recipe = visible[0]
            stock = self.personal_stock if self.source == "personal" else self.guild_stock
            recipe_select = Select(
                placeholder=f"제작할 레시피 선택 ({self.page + 1}/{total_pages})",
                row=1,
                options=[
                    discord.SelectOption(
                        label=recipe_name,
                        value=recipe_name,
                        description=(
                            " · ".join(
                                f"{material} {int(stock.get(material, 0))}/{int(need)}"
                                for material, need in GUILD_WORKSHOP_RECIPES[recipe_name]["need"].items()
                            )
                            + f" · {GUILD_WORKSHOP_RECIPES[recipe_name]['description']}"
                        )[:100],
                        default=recipe_name == self.selected_recipe,
                    )
                    for recipe_name in visible
                ],
            )

            async def select_recipe(interaction):
                self.selected_recipe = interaction.data["values"][0]
                await self.setup_view()
                await interaction.response.edit_message(embed=await self.get_embed(), view=self)

            recipe_select.callback = select_recipe
            self.add_item(recipe_select)

        previous = Button(label="이전", disabled=self.page == 0, row=2)
        counter = Button(label=f"{self.page + 1}/{total_pages}", disabled=True, row=2)
        following = Button(label="다음", disabled=self.page >= total_pages - 1, row=2)
        previous.callback = self.prev_page
        following.callback = self.next_page
        self.add_item(previous)
        self.add_item(counter)
        self.add_item(following)

        stock = self.personal_stock if self.source == "personal" else self.guild_stock
        recipe = GUILD_WORKSHOP_RECIPES.get(self.selected_recipe, {})
        for quantity in (1, 5, 10):
            can_make = bool(recipe) and all(
                int(stock.get(name, 0)) >= int(need) * quantity
                for name, need in recipe.get("need", {}).items()
            )
            button = Button(
                label=f"{quantity}개 제작",
                style=discord.ButtonStyle.success if quantity == 1 else discord.ButtonStyle.primary,
                disabled=not can_make,
                row=3,
            )

            async def craft(interaction, amount=quantity):
                await self.craft(interaction, amount)

            button.callback = craft
            self.add_item(button)

        back = Button(label="길드로 돌아가기", style=discord.ButtonStyle.secondary, row=4)
        back.callback = self.back_to_guild
        self.add_item(back)

    async def get_embed(self):
        source_label = "개인 인벤토리" if self.source == "personal" else "길드 공용 창고"
        destination = (
            "개인 인벤토리"
            if self.source == "personal"
            else "길드 공용 자원 자동 납품"
        )
        embed = discord.Embed(
            title="🛠️ 길드 제작소",
            description=(
                "제작 재료의 출처를 고른 뒤 레시피와 수량을 누르세요.\n"
                "개인 재료로 만들면 개인에게 지급됩니다.\n"
                "공용 재료로 만든 결과물은 즉시 길드 자원으로 환산되고 제작자 공헌도가 오릅니다.\n"
                "**두 재고를 한 제작에 섞어 쓰지는 않습니다.**"
            ),
            color=discord.Color.dark_gold(),
        )
        embed.add_field(name="현재 재료 출처 / 결과 위치", value=f"**{source_label}** → **{destination}**", inline=False)

        if not self.selected_recipe:
            embed.add_field(name="레시피", value="등록된 레시피가 없습니다.", inline=False)
            return embed

        recipe = GUILD_WORKSHOP_RECIPES[self.selected_recipe]
        stock = self.personal_stock if self.source == "personal" else self.guild_stock
        requirements = []
        max_craft = None
        for material_name, need in recipe["need"].items():
            have = int(stock.get(material_name, 0))
            need = int(need)
            possible = have // need
            max_craft = possible if max_craft is None else min(max_craft, possible)
            requirements.append(
                f"{'✅' if have >= need else '❌'} **{material_name}** {have}/{need}"
            )
        embed.add_field(
            name=f"선택 레시피: {self.selected_recipe}",
            value=recipe["description"],
            inline=False,
        )
        embed.add_field(name="1개 제작 재료", value="\n".join(requirements), inline=False)
        embed.add_field(name="현재 최대 제작 가능", value=f"**{int(max_craft or 0)}개**", inline=False)
        return embed

    async def _switch_source(self, interaction, source):
        self.source = source
        await self.setup_view()
        await interaction.response.edit_message(content=None, embed=await self.get_embed(), view=self)

    async def use_personal(self, interaction):
        await self._switch_source(interaction, "personal")

    async def use_guild(self, interaction):
        await self._switch_source(interaction, "guild")

    async def prev_page(self, interaction):
        self.page = max(0, self.page - 1)
        await self.setup_view()
        await interaction.response.edit_message(embed=await self.get_embed(), view=self)

    async def next_page(self, interaction):
        self.page += 1
        await self.setup_view()
        await interaction.response.edit_message(embed=await self.get_embed(), view=self)

    async def craft(self, interaction, count):
        if not self.selected_recipe:
            return await interaction.response.send_message("제작할 레시피를 먼저 선택해주세요.", ephemeral=True)
        recipe = GUILD_WORKSHOP_RECIPES[self.selected_recipe]
        success, message = await craft_guild_workshop_item(
            interaction.user.id,
            self.guild_info["guild_id"],
            self.selected_recipe,
            recipe["need"],
            count,
            self.source,
            "material",
            interaction.user.display_name,
            ITEM_TOKEN_VALUES.get(self.selected_recipe) if self.source == "guild" else None,
        )
        if not success:
            return await interaction.response.send_message(f"❌ {message}", ephemeral=True)
        if self.source == "guild" and self.selected_recipe in ITEM_TOKEN_VALUES:
            base_rewards = {
                key: int(value) * int(count)
                for key, value in ITEM_TOKEN_VALUES[self.selected_recipe].items()
            }
            scaled = _scale_donation_rewards(
                base_rewards,
                self.guild_info.get("level", 1),
            )
            await advance_guild_mission(
                interaction.user,
                "donate",
                sum(scaled.values()),
            )
        await self.setup_view()
        await interaction.response.edit_message(
            content=f"✅ {message}",
            embed=await self.get_embed(),
            view=self,
        )

    async def back_to_guild(self, interaction):
        view = GuildMainView()
        await interaction.response.edit_message(
            content=None,
            embed=await view.get_embed(interaction.user.id, interaction.user.display_name),
            view=view,
        )


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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("본인이 연 길드 미션만 조작할 수 있습니다.", ephemeral=True)
        return False

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
    PER_PAGE = 8

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
        current_guild = await get_user_guild_info(self.author.id)
        if current_guild:
            self.guild_info = current_guild
        guild_level = max(1, min(10, int(self.guild_info.get("level", 1) or 1)))
        daily_items = await get_or_create_daily_guild_shop(
            self.guild_info["guild_id"],
            self.day_key,
            _build_daily_shop_rotation(guild_level, self.day_key),
        )
        self.items = [
            row for row in daily_items
            if row.get("item_name") not in GUILD_CRAFT_RECIPES
        ]
        for index, item in enumerate(GUILD_SHOP_SUPPLIES):
            if int(item.get("min_rank", 1)) > guild_level:
                continue
            self.items.append({
                **item,
                "slot_index": 100 + index,
                "persistent": True,
                "stock": -1,
                "initial_stock": -1,
            })
        self.items = [
            item
            for item in self.items
            if item.get("persistent") or int(item.get("stock", 0)) > 0
        ]
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
        visible = self.items[start:start + self.PER_PAGE]
        if visible:
            visible_slots = {int(item["slot_index"]) for item in visible}
            if int(self.selected_slot) not in visible_slots:
                self.selected_slot = int(visible[0]["slot_index"])
            shop_select = Select(
                placeholder=f"길드 상품 선택 ({self.page + 1}/{total_pages})",
                row=0,
                options=[
                    discord.SelectOption(
                        label=item["item_name"],
                        value=str(int(item["slot_index"])),
                        description=(
                            _format_token_cost(item.get("cost", {}))
                            + " · "
                            + (
                                "상시 판매"
                                if item.get("persistent")
                                else f"재고 {int(item.get('stock', 0))}개"
                            )
                            + " · "
                            + (item.get("description") or "길드 상점 상품")
                        )[:100],
                        default=int(item["slot_index"]) == int(self.selected_slot),
                    )
                    for item in visible
                ],
            )

            async def choose(interaction):
                self.selected_slot = int(interaction.data["values"][0])
                self.rebuild()
                await interaction.response.edit_message(content=None, embed=await self.get_embed(), view=self)

            shop_select.callback = choose
            self.add_item(shop_select)

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
                f"현재 길드 등급은 **{RANK_NAMES.get(int(guild.get('level', 1)), '아이언')}**이며 "
                f"오늘의 로테이션은 **{GUILD_SHOP_SLOT_COUNT.get(int(guild.get('level', 1)), 3)}종**입니다.\n"
                "등급이 오르면 로테이션 품목 수와 상시 보급품 종류가 늘어납니다.\n"
                "해금된 보급품은 상시 판매되며 **공용 창고**로 들어갑니다.\n"
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

class GuildWarehouseWithdrawView(discord.ui.View):
    PER_PAGE = 8

    def __init__(self, author, guild_info, category, parent_view):
        super().__init__(timeout=180)
        self.author = author
        self.guild_info = guild_info
        self.category = category
        self.parent_view = parent_view
        self.items = []
        self.page = 0
        self.selected_item = None
        self.quantity = 0

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message(
            "본인이 연 출고 화면만 조작할 수 있습니다.",
            ephemeral=True,
        )
        return False

    async def setup_view(self):
        rows = await get_guild_items(self.guild_info["guild_id"], self.category)
        self.items = [
            (row["item_name"], int(row.get("count", 0) or 0))
            for row in rows
            if int(row.get("count", 0) or 0) > 0
        ]
        total_pages = max(1, (len(self.items) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        visible = self.items[self.page * self.PER_PAGE:(self.page + 1) * self.PER_PAGE]
        if self.selected_item not in {name for name, _ in self.items}:
            self.selected_item = visible[0][0] if visible else None
            self.quantity = 1 if self.selected_item else 0

        self.clear_items()
        if visible:
            select = Select(
                placeholder=f"출고할 공용 재고 선택 ({self.page + 1}/{total_pages})",
                row=0,
                options=[
                    discord.SelectOption(
                        label=f"{name} ×{count}",
                        value=name,
                        default=name == self.selected_item,
                    )
                    for name, count in visible
                ],
            )

            async def choose(interaction):
                self.selected_item = interaction.data["values"][0]
                self.quantity = 1
                await self.setup_view()
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            select.callback = choose
            self.add_item(select)

        previous = Button(label="이전", disabled=self.page == 0, row=1)
        counter = Button(label=f"{self.page + 1}/{total_pages}", disabled=True, row=1)
        following = Button(label="다음", disabled=self.page >= total_pages - 1, row=1)
        previous.callback = self.previous
        following.callback = self.following
        self.add_item(previous)
        self.add_item(counter)
        self.add_item(following)

        stock = dict(self.items).get(self.selected_item, 0)
        for label, amount in (("-10", -10), ("-1", -1), ("+1", 1), ("+10", 10)):
            button = Button(label=label, disabled=not self.selected_item, row=2)

            async def adjust(interaction, delta=amount):
                self.quantity = max(1, min(stock, self.quantity + delta))
                await self.setup_view()
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            button.callback = adjust
            self.add_item(button)

        confirm = Button(
            label="개인 인벤토리로 출고",
            style=discord.ButtonStyle.success,
            disabled=not self.selected_item or self.quantity <= 0,
            row=3,
        )
        close = Button(label="닫기", style=discord.ButtonStyle.secondary, row=3)
        confirm.callback = self.confirm
        close.callback = self.close
        self.add_item(confirm)
        self.add_item(close)

    def get_embed(self):
        stock = dict(self.items).get(self.selected_item, 0)
        embed = discord.Embed(
            title="📤 길드 공용 재고 출고",
            description=(
                "공용 창고의 실물 아이템을 내 인벤토리로 가져옵니다.\n"
                "출고 내역은 길드 활동 로그에 기록됩니다."
            ),
            color=discord.Color.blue(),
        )
        if self.selected_item:
            embed.add_field(
                name=self.selected_item,
                value=(
                    f"공용 재고: **{stock}개**\n"
                    f"출고 수량: **{self.quantity}개**\n"
                    f"출고 후 공용 재고: **{max(0, stock - self.quantity)}개**"
                ),
                inline=False,
            )
        else:
            embed.add_field(name="재고", value="출고할 공용 재고가 없습니다.", inline=False)
        return embed

    async def previous(self, interaction):
        self.page -= 1
        await self.setup_view()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def following(self, interaction):
        self.page += 1
        await self.setup_view()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def confirm(self, interaction):
        success, message = await withdraw_guild_item(
            interaction.user.id,
            self.guild_info["guild_id"],
            self.selected_item,
            self.quantity,
            interaction.user.display_name,
        )
        if not success:
            return await interaction.response.send_message(f"❌ {message}", ephemeral=True)
        self.selected_item = None
        self.quantity = 0
        await self.setup_view()
        await interaction.response.edit_message(
            content=f"✅ {message}",
            embed=self.get_embed(),
            view=self,
        )
        try:
            await self.parent_view.refresh_background()
        except (discord.NotFound, discord.HTTPException):
            pass

    async def close(self, interaction):
        await interaction.response.edit_message(content="출고 화면을 닫았습니다.", embed=None, view=None)


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
        self.add_item(self.btn_withdraw)
        self.add_item(self.btn_deposit_art)
        self.add_item(self.btn_logs)
        self.message = None

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

    async def refresh_background(self):
        if self.message:
            await self.message.edit(embed=await self.get_embed(), view=self)

    @discord.ui.button(label="📤 공용 재고 출고", style=discord.ButtonStyle.primary, row=1)
    async def btn_withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.category == "artifact":
            return await interaction.response.send_message(
                "아티팩트는 별도 보관 규칙을 사용하므로 실물 재고 출고 대상이 아닙니다.",
                ephemeral=True,
            )
        self.message = interaction.message
        view = GuildWarehouseWithdrawView(
            interaction.user,
            self.guild_info,
            self.category,
            self,
        )
        await view.setup_view()
        await interaction.response.send_message(
            embed=view.get_embed(),
            view=view,
            ephemeral=True,
        )

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
                "deposit": "구형 입고",
                "donation": "자원 납품",
                "store_item": "창고 반입",
                "workshop_personal": "개인 제작",
                "workshop_guild": "공용 제작",
                "workshop_auto_donate": "공용 제작·자동 납품",
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


class BossRaidCardSelectView(discord.ui.View):
    """30초 동안 보스 주인에게만 보이는 비공개 커맨드 패널."""

    def __init__(self, author, cards, callback_func, turn):
        super().__init__(timeout=30)
        self.author = author
        self.cards = list(cards)
        self.callback_func = callback_func
        self.turn = int(turn)
        for card in self.cards[:5]:
            button = Button(label=card.name[:80], style=discord.ButtonStyle.danger)

            async def choose(interaction, selected=card):
                await self.callback_func(interaction, selected)

            button.callback = choose
            self.add_item(button)

    def get_embed(self):
        return discord.Embed(
            title=f"👑 보스 커맨드 · {self.turn}턴",
            description="\n\n".join(
                f"**{card.name}**\n{card.description}" for card in self.cards[:5]
            ) or "사용 가능한 기술이 없습니다.",
            color=discord.Color.dark_red(),
        )

    async def interaction_check(self, interaction):
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("보스 조작자만 선택할 수 있습니다.", ephemeral=True)
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
        self.user_boss_record = getattr(lobby_view, "user_boss_record", None)
        self.battle_id = getattr(lobby_view, "battle_id", None)
        self.boss_control_user_id = getattr(lobby_view, "boss_control_user_id", None)
        self.boss_control_user = getattr(lobby_view, "boss_control_user", None)
        self.boss_choice_task = None
        if not self.user_boss_record:
            self.remove_item(self.btn_boss_pick)
        self.decide_boss_action()

    def decide_boss_action(self):
        if self.user_boss_record and self.boss_control_user_id:
            self.boss_intent = None
            if self.boss_choice_task and not self.boss_choice_task.done():
                self.boss_choice_task.cancel()
            self.boss_choice_task = asyncio.create_task(self._boss_choice_timeout(self.turn))
        else:
            self.boss_intent = self.boss.decide_action()

    async def _boss_choice_timeout(self, selected_turn):
        await asyncio.sleep(30)
        async with self.resolve_lock:
            if self.finished or self.turn != selected_turn or self.boss_intent is not None:
                return
            self.boss_intent = self.boss.decide_action()
            self.logs.append(
                f"⏱️ 보스 조작 시간이 지나 AI가 **{self.boss_intent.name}**을 선택했습니다."
            )
        if self.public_message:
            try:
                await self.public_message.edit(embed=self.get_status_embed(), view=self)
            except (discord.NotFound, discord.HTTPException):
                self.public_message = None

    def get_status_embed(self):
        embed = discord.Embed(title=f"⚔️ 길드 레이드: {self.boss.name}", color=discord.Color.dark_red())
        p = self.boss.current_hp / self.boss.max_hp
        boss_hp_bar = "🟥" * int(p * 15) + "⬜" * (15 - int(p * 15))
        embed.add_field(name=f"👹 {self.boss.name}", value=f"❤️ {self.boss.current_hp}/{self.boss.max_hp}\n{boss_hp_bar}", inline=False)
        
        if self.boss_intent is None:
            intent = "🔒 보스 조작자가 비공개로 행동을 선택하는 중입니다. (30초)"
        else:
            intent = f"**{self.boss_intent.name}**" + (
                " (☄️ 광역)" if self.boss_intent.is_aoe else " (🗡️ 단일)"
            )
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
        if self.boss_intent is None:
            return await interaction.response.send_message(
                "보스 행동이 공개된 뒤 공격자 커맨드를 선택할 수 있습니다.",
                ephemeral=True,
            )
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

    @discord.ui.button(label="👑 보스 커맨드", style=discord.ButtonStyle.danger)
    async def btn_boss_pick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.user_boss_record or interaction.user.id != self.boss_control_user_id:
            return await interaction.response.send_message("이번 보스의 조작자가 아닙니다.", ephemeral=True)
        if self.finished:
            return await interaction.response.send_message("이미 종료된 레이드입니다.", ephemeral=True)
        if self.boss_intent is not None:
            return await interaction.response.send_message("이미 이번 턴의 행동을 확정했습니다.", ephemeral=True)
        cards = self.boss.available_cards() if hasattr(self.boss, "available_cards") else []

        async def choose(card_interaction, card):
            async with self.resolve_lock:
                if self.finished or self.boss_intent is not None:
                    return await card_interaction.response.send_message(
                        "이미 행동이 확정되었습니다.", ephemeral=True
                    )
                self.boss_intent = card
                if self.boss_choice_task and not self.boss_choice_task.done():
                    self.boss_choice_task.cancel()
                self.logs.append(f"👑 보스 조작자가 **{card.name}**을 선택했습니다.")
            await card_interaction.response.edit_message(
                embed=discord.Embed(
                    title="✅ 보스 커맨드 확정",
                    description=f"**{card.name}**을 선택했습니다. 공격자들에게 의도가 공개됩니다.",
                    color=discord.Color.dark_red(),
                ),
                view=None,
            )
            if self.public_message:
                try:
                    await self.public_message.edit(embed=self.get_status_embed(), view=self)
                except (discord.NotFound, discord.HTTPException):
                    self.public_message = None

        view = BossRaidCardSelectView(interaction.user, cards, choose, self.turn)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

    async def resolve_turn(self, interaction):
        if self.finished:
            return
        if self.boss_intent is None:
            if interaction.response.is_done():
                return await interaction.followup.send("보스 행동이 아직 확정되지 않았습니다.", ephemeral=True)
            return await interaction.response.send_message("보스 행동이 아직 확정되지 않았습니다.", ephemeral=True)
        self.logs.append(f"--- Turn {self.turn} ---")
        alive = [u for u, p in self.participants.items() if p['char'].current_hp > 0]
        if not alive: return await self.end_raid(interaction, False)
        # A resolved raid round advances one shared activity turn for every participant.
        for participant in self.participants.values():
            participant["data"] = await advance_guild_world_turn(participant["user"], 1)

        boss_card = self.boss_intent
        if hasattr(self.boss, "commit_card"):
            self.boss.commit_card(boss_card)
        if hasattr(self.boss, "on_turn_start"):
            boss_start_log = self.boss.on_turn_start(self.turn, len(alive))
            if boss_start_log:
                self.logs.append(f"👑 {boss_start_log}")
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
            if hasattr(self.boss, "modify_outgoing_dice"):
                self.boss.modify_outgoing_dice(boss_res, self.turn, len(alive))
            user_res = u_card.use_card(char.attack, char.defense, char.current_mental)
            user_res = battle_engine.apply_stat_scaling(user_res, char)
            if hasattr(self.boss, "modify_opponent_dice"):
                boss_special_log = self.boss.modify_opponent_dice(user_res, char)
                if boss_special_log:
                    self.logs.append(f"👑 {boss_special_log}")
            
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

            if "escalation" in u_effs:
                escalation = apply_escalation_to_dice(char, user_res)
                if escalation:
                    summary = ", ".join(
                        f"{entry['index'] + 1}번 {entry['rolled']:+d}"
                        + (f"(연쇄 +{entry['chained']})" if entry["chained"] else "")
                        for entry in escalation
                    )
                    self.logs.append(f"⚡ **{char.name}[고조]** {summary}")
            if "ripple" in u_effs:
                ripple = apply_ripple_to_dice(char, user_res, self.turn)
                if ripple:
                    amounts = " → ".join(
                        f"+{entry['amount']}" for entry in ripple["transfers"]
                    )
                    suffix = ""
                    if ripple["hp_heal"] or ripple["mental_heal"]:
                        suffix = (
                            f" · HP +{ripple['hp_heal']}"
                            f" / 정신 +{ripple['mental_heal']}"
                        )
                    self.logs.append(f"🌊 **{char.name}[파문]** {amounts}{suffix}")

            boss_effects = []
            for artifact in (
                getattr(self.boss, "equipped_artifact", None),
                getattr(self.boss, "equipped_engraved_artifact", None),
            ):
                if isinstance(artifact, dict) and artifact.get("special"):
                    boss_effects.append(artifact.get("special"))

            is_target = (uid in targets)
            if is_target:
                clash_log, dmg_p, dmg_b = battle_engine.process_clash_loop(
                    char, self.boss, user_res, boss_res, u_effs, boss_effects, self.turn
                )
                self.logs.append(f"⚔️ **{char.name}** vs **보스**" + clash_log)
            else:
                for d in boss_res:
                    if d['type'] == 'attack': d['type'] = 'none'; d['value'] = 0
                clash_log, dmg_p, dmg_b = battle_engine.process_clash_loop(
                    char, self.boss, user_res, boss_res, u_effs, boss_effects, self.turn
                )
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
                    if hasattr(self.boss, "on_attacker_defeated"):
                        predator_log = self.boss.on_attacker_defeated()
                        if predator_log:
                            self.logs.append(f"👑 {predator_log}")

        if self.boss.current_hp <= 0: return await self.end_raid(interaction, True)
        if hasattr(self.boss, "on_turn_end"):
            boss_end_log = self.boss.on_turn_end()
            if boss_end_log:
                self.logs.append(f"👑 {boss_end_log}")
        
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
        outcome = {"hope_granted": False}

        def merge(latest):
            characters = latest.setdefault("characters", [])
            if not 0 <= character_index < len(characters):
                raise IndexError(f"레이드 캐릭터 슬롯을 찾지 못했습니다: {character_index}")
            characters[character_index] = character_data
            if win:
                latest["money"] = int(latest.get("money", 0) or 0) + 5000
                latest["pt"] = int(latest.get("pt", 0) or 0) + 1000
                life = latest.setdefault("life_data", {})
                today = _guild_day_key()
                if life.get("guild_raid_hope_date") != today:
                    inventory = latest.setdefault("inventory", {})
                    inventory["순수한 희망"] = (
                        int(inventory.get("순수한 희망", 0) or 0) + 1
                    )
                    life["guild_raid_hope_date"] = today
                    outcome["hope_granted"] = True

        latest = await mutate_user_data(
            uid,
            merge,
            participant["user"].display_name,
        )
        participant["data"] = latest
        return outcome["hope_granted"]

    async def end_raid(self, interaction, win):
        if self.finished:
            return
        self.finished = True
        if self.boss_choice_task and not self.boss_choice_task.done():
            self.boss_choice_task.cancel()
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
            hope_names = []
            for uid, p in self.participants.items():
                if hasattr(p['char'], "remove_battle_buffs"):
                    p['char'].remove_battle_buffs()
                battle_end_gem_heal(p['char'])
                p['char'].current_hp = p['char'].max_hp
                if await self._save_participant_result(uid, p, win=True):
                    hope_names.append(p["user"].display_name)
                await add_guild_contribution(
                    uid, 100, "raid_success", self.boss.name, p["user"].display_name
                )
                log_names.append(p['user'].display_name)
            
            embed = discord.Embed(title="🎉 토벌 성공!", description=f"보스 **{self.boss.name}** 처치!", color=discord.Color.gold())
            embed.add_field(name="영웅들", value=", ".join(log_names))
            if hope_names:
                embed.add_field(
                    name="순수한 희망",
                    value=(
                        "오늘 첫 길드 레이드 승리 보상으로 "
                        f"**순수한 희망 ×1** 지급: {', '.join(hope_names)}"
                    ),
                    inline=False,
                )
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

        if self.user_boss_record and self.battle_id:
            try:
                from boss_training import finish_boss_battle

                challenger_id = next(iter(self.participants), self.lobby.host.id)
                rating = await finish_boss_battle(
                    self.user_boss_record,
                    self.battle_id,
                    challenger_id,
                    attackers_won=bool(win),
                    owner_name=(
                        self.boss_control_user.display_name
                        if self.boss_control_user is not None
                        else None
                    ),
                )
                reward = rating["owner_reward"]
                embed.add_field(
                    name="👑 보스 방어 기록",
                    value=(
                        f"Elo {rating['elo_before']} → **{rating['elo_after']}**\n"
                        f"주인 보상: {reward['money']:,}원 · {reward['pt']:,} PT · "
                        f"공헌도 +{reward['contribution']}"
                    ),
                    inline=False,
                )
            except Exception as exc:
                self.logs.append(f"보스 방어 기록 저장 실패: {exc}")

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
        if self.boss_choice_task and not self.boss_choice_task.done():
            self.boss_choice_task.cancel()
        if self.user_boss_record and self.battle_id:
            try:
                from boss_training import finish_boss_battle

                challenger_id = next(iter(self.participants), self.lobby.host.id)
                await finish_boss_battle(
                    self.user_boss_record,
                    self.battle_id,
                    challenger_id,
                    attackers_won=False,
                    owner_name=(
                        self.boss_control_user.display_name
                        if self.boss_control_user is not None
                        else None
                    ),
                )
            except Exception:
                pass
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
    def __init__(
        self,
        host,
        guild_info,
        boss_data,
        *,
        user_boss_record=None,
        scope="guild",
    ):
        super().__init__(timeout=300)
        self.host = host
        self.guild_info = guild_info
        self.boss_data = boss_data
        self.user_boss_record = user_boss_record
        self.scope = scope
        self.boss_control_user_id = None
        self.boss_control_user = None
        self.battle_id = None
        self.participants = {}
        self.started = False
        self.state_lock = asyncio.Lock()
        self.public_message = None
        if not self.user_boss_record:
            self.remove_item(self.btn_control_boss)

    async def add_participant(self, user):
        async with self.state_lock:
            if self.started or user.id in self.participants or len(self.participants) >= 4:
                return False
            if self.user_boss_record and str(user.id) == str(self.user_boss_record.get("owner_id")):
                return False
            user_data = await get_user_data(user.id)
            idx = user_data.get("investigator_index", 0)
            chars = user_data.get("characters", [])
            char = Character.from_dict(chars[idx]) if chars and idx < len(chars) else Character.from_dict({"name": "모험가", "hp": 100, "attack":10, "defense":5})
            
            char.status_effects = {"bleed": 0, "paralysis": 0, "stun": 0}
            char.runtime_cooldowns = {}
            if hasattr(char, "apply_battle_start_buffs"):
                char.apply_battle_start_buffs()
                char.current_hp = char.max_hp
                char.current_mental = char.max_mental
            self.participants[user.id] = {
                "user": user,
                "char": char,
                "char_idx": idx,
                "data": user_data,
                "revived": False,
            }
            return True

    def get_embed(self):
        if self.user_boss_record:
            title = f"👑 [{self.user_boss_record['grade']}] {self.user_boss_record['boss_name']} 도전"
            description = (
                f"{'월드' if self.scope == 'world' else '길드'} 공개 유저 보스입니다. "
                "최대 4명이 참가하며, 보스 주인이 로비에서 직접 조작에 참여할 수 있습니다."
            )
        else:
            title = f"🛡️ [{self.guild_info['name']}] 레이드 모집"
            description = "혼자 바로 출발하거나, 최대 4명의 길드원과 함께할 수 있습니다."
        embed = discord.Embed(title=title, description=description, color=discord.Color.orange())
        members = [f"{i+1}. {p['user'].display_name} (Lv.{p['char'].attack+p['char'].defense})" for i, p in enumerate(self.participants.values())]
        embed.add_field(name=f"파티원 ({len(self.participants)}/4)", value="\n".join(members), inline=False)
        if self.user_boss_record:
            embed.add_field(
                name="보스 조작",
                value=(
                    f"👑 {self.boss_control_user.display_name} 직접 조작"
                    if self.boss_control_user
                    else "🤖 AI 조작"
                ),
                inline=False,
            )
        return embed

    @discord.ui.button(label="✋ 참가", style=discord.ButtonStyle.success)
    async def btn_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.started:
            return await interaction.response.send_message("이미 출발한 레이드입니다.", ephemeral=True)
        if self.user_boss_record and str(interaction.user.id) == str(self.user_boss_record.get("owner_id")):
            return await interaction.response.send_message("보스 주인은 공격 파티에 참가할 수 없습니다.", ephemeral=True)
        if self.scope != "world":
            u_guild = await get_user_guild_info(interaction.user.id)
            if not u_guild or u_guild['guild_id'] != self.guild_info['guild_id']:
                return await interaction.response.send_message("❌ 같은 길드원이 아닙니다.", ephemeral=True)
        if await self.add_participant(interaction.user): await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else: await interaction.response.send_message("참가 실패 (이미 참가했거나 인원 초과)", ephemeral=True)

    @discord.ui.button(label="👑 보스 직접 조작", style=discord.ButtonStyle.secondary)
    async def btn_control_boss(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.user_boss_record:
            return await interaction.response.send_message("유저 육성 보스 전용 기능입니다.", ephemeral=True)
        if self.started:
            return await interaction.response.send_message("이미 출발한 레이드입니다.", ephemeral=True)
        if str(interaction.user.id) != str(self.user_boss_record.get("owner_id")):
            return await interaction.response.send_message("이 보스를 육성한 주인만 조작할 수 있습니다.", ephemeral=True)
        self.boss_control_user_id = interaction.user.id
        self.boss_control_user = interaction.user
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="🚀 출발", style=discord.ButtonStyle.danger)
    async def btn_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id: return await interaction.response.send_message("호스트만 시작 가능", ephemeral=True)
        async with self.state_lock:
            if self.started:
                return await interaction.response.send_message("이미 출발한 레이드입니다.", ephemeral=True)
            if len(self.participants) < 1:
                return await interaction.response.send_message("참가자가 필요합니다.", ephemeral=True)
            if not self.boss_data and not self.user_boss_record:
                return await interaction.response.send_message("레이드 보스 데이터를 찾지 못했습니다.", ephemeral=True)
            self.started = True

        boss = None
        if self.user_boss_record:
            from boss_training import UserBossMonster, begin_boss_battle

            try:
                self.battle_id = await begin_boss_battle(self.user_boss_record["boss_id"])
                boss = UserBossMonster(self.user_boss_record)
            except Exception as exc:
                self.started = False
                return await interaction.response.send_message(
                    f"유저 보스 레이드를 시작하지 못했습니다: {exc}",
                    ephemeral=True,
                )

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

        if not self.user_boss_record:
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
        if training.get("date") != _guild_day_key() or int(training.get("score_version", 0)) != 2:
            training.clear()
            training.update({
                "date": _guild_day_key(),
                "score_version": 2,
                "best_score": 0,
                "claimed_thresholds": [],
            })
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
        best = (
            int(training.get("best_score", 0))
            if training.get("date") == _guild_day_key()
            and int(training.get("score_version", 0)) == 2
            else 0
        )
        embed = discord.Embed(
            title="🥋 길드 수련장",
            description=(
                "공격하는 무한 체력 샌드백을 상대로 **최대 10턴** 동안 수련합니다.\n"
                "내 캐릭터가 쓰러지면 즉시 종료되며, 실제 체력이나 아이템은 소모되지 않습니다.\n"
                "유효한 수련 행동 1회마다 **공용 활동 턴도 1** 진행됩니다.\n"
                "기존의 주사위 개수 점수제는 폐지되었습니다."
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="🎯 점수 규칙",
            value=(
                "공격·방어·반격·체력 회복·정신 회복 주사위의 **최종 유효값을 전부 합산**합니다.\n"
                "예: 유효 주사위 값이 42, 58이면 해당 턴에 **100점**을 얻습니다."
            ),
            inline=False,
        )
        embed.add_field(
            name="🎁 일일 구간 보상",
            value=(
                "0 / 100 / 250 / 500 / 750 / 1,000 / 1,500 / 2,000 / "
                "3,000 / 5,000 / 8,000점 구간에 보상이 있습니다.\n"
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
        # Guild membership lookup can occasionally approach Discord's
        # three-second acknowledgement deadline.  Acknowledge the component
        # immediately, then replace the same public embed when setup finishes.
        await interaction.response.defer()
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info:
            return await interaction.followup.send(
                "길드 정보를 불러오지 못했습니다.",
                ephemeral=True,
            )
        lobby = GuildDungeonLobbyView(interaction.user, guild_info, self)
        await lobby.setup()
        lobby.public_message = await interaction.edit_original_response(
            content=None,
            embed=lobby.get_embed(),
            view=lobby,
        )

    @discord.ui.button(label="🥊 수련 시작", style=discord.ButtonStyle.success, row=0)
    async def btn_start(self, interaction, button):
        data = await get_user_data(self.author.id, self.author.display_name)
        view = TrainingCharacterSelectView(self.author, self.guild_info, data, self)
        view.rebuild()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="👑 보스 육성", style=discord.ButtonStyle.primary, row=0)
    async def btn_boss_training(self, interaction, button):
        from boss_training import BossTrainingHubView

        view = BossTrainingHubView(self.author, self.guild_info, self)
        await interaction.response.edit_message(embed=await view.get_embed(), view=view)

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
        escalation_summary = ""
        ripple_summary = ""
        if "escalation" in effects:
            escalation = apply_escalation_to_dice(self.character, user_res)
            if escalation:
                escalation_summary = "⚡ 고조: " + ", ".join(
                    f"{entry['index'] + 1}번 {entry['rolled']:+d}"
                    + (f"(연쇄 +{entry['chained']})" if entry["chained"] else "")
                    for entry in escalation
                )
        if "ripple" in effects:
            ripple = apply_ripple_to_dice(
                self.character, user_res, self.turn
            )
            if ripple:
                ripple_summary = "🌊 파문: " + " → ".join(
                    f"+{entry['amount']}" for entry in ripple["transfers"]
                )

        clash_log, _, _ = battle_engine.process_clash_loop(
            self.character,
            self.sandbag,
            user_res,
            bag_res,
            effects,
            [],
            self.turn,
        )
        scored_dice = [
            max(0, int(dice.get("resolved_value", dice.get("value", 0)) or 0))
            for dice in user_res
            if dice.get("resolved_type", dice.get("type")) in self.EFFECTIVE_DICE
            and int(dice.get("resolved_value", dice.get("value", 0)) or 0) > 0
        ]
        turn_score = sum(scored_dice)
        self.score += turn_score
        self.sandbag.current_hp = self.sandbag.max_hp
        self.sandbag.current_mental = self.sandbag.max_mental
        summary = (
            f"**{self.turn}턴** {card_name} vs {bag_card.name} · "
            f"유효 주사위 값 **{'+'.join(map(str, scored_dice)) or '0'} = +{turn_score}점**"
        )
        if gem_log:
            summary += f"\n💎 {gem_log}"
        if art_log:
            summary += f"\n{art_log.strip()}"
        if escalation_summary:
            summary += f"\n{escalation_summary}"
        if ripple_summary:
            summary += f"\n{ripple_summary}"
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
        super().__init__(timeout=None)
        self.page = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        owner_id = _message_command_owner_id(interaction)
        if owner_id is not None and interaction.user.id == owner_id:
            return True
        if owner_id is None:
            message = "소유자를 확인할 수 없는 오래된 길드 메뉴입니다. `/길드`로 새로 열어주세요."
        else:
            message = "다른 이용자가 연 길드 메뉴입니다. `/길드`로 본인 메뉴를 열어주세요."
        await interaction.response.send_message(
            message,
            ephemeral=True,
        )
        return False

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
            self.add_item(self.btn_workshop)
        self._add_navigation()

        g = guild_info
        total_contribution = int(g.get("total_contribution", g.get("exp", 0)) or 0)
        current_rank, next_rank = _rank_threshold_info(total_contribution)
        if next_rank:
            rank_progress = (
                f"{total_contribution:,}/{next_rank[2]:,} "
                f"(다음: {next_rank[1]}, 남은 공헌도 {max(0, next_rank[2] - total_contribution):,})"
            )
        else:
            rank_progress = f"{total_contribution:,} · 최고 등급 달성"
        embed = discord.Embed(
            title=f"🛡️ {g['name']}",
            description=(
                "모든 조사원이 함께 성장시키는 공용 길드입니다.\n"
                f"등급: **{current_rank[1]}**\n"
                f"길드 공헌도: **{rank_progress}**\n"
                f"내 공헌도: **{g.get('contribution', 0):,}**"
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
            name="🏅 현재 등급 혜택",
            value=(
                f"납품 환산 효율 **{_donation_efficiency(current_rank[0])}%** · "
                f"일일 상점 로테이션 **{GUILD_SHOP_SLOT_COUNT[current_rank[0]]}종**\n"
                "공헌도: 납품 환산 1점당 +1 · 미션 +20 · 레이드 성공 +100/실패 +20"
            ),
            inline=False,
        )
        embed.add_field(
            name="📈 길드 등급 공헌도 기준",
            value=(
                "아이언 0 · 브론즈 1,000 · 실버 3,000 · 골드 7,500 · 플래티넘 15,000\n"
                "에메랄드 30,000 · 다이아몬드 60,000 · 마스터 100,000 · "
                "그랜드마스터 175,000 · 챌린저 300,000"
            ),
            inline=False,
        )
        embed.set_footer(
            text=(
                f"메뉴 {self.page + 1}/2 · 생성·검색·탈퇴 없이 모든 이용자가 자동 소속됩니다. "
                f"· owner:{int(user_id)}"
            )
        )
        return embed

    # 공용 길드는 자동 가입이므로 생성·검색·탈퇴 버튼을 노출하지 않는다.
    @discord.ui.button(label="🎯 미션", style=discord.ButtonStyle.success, custom_id="guild_btn_mission")
    async def btn_mission(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        view = GuildMissionView(interaction.user, guild_info)
        await interaction.response.edit_message(content=None, embed=await view.get_embed(), view=view)

    @discord.ui.button(label="🛒 길드 상점", style=discord.ButtonStyle.primary, custom_id="guild_btn_shop")
    async def btn_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info:
            return
        view = GuildShopView(interaction.user, guild_info, None)
        await view.setup()
        await interaction.response.edit_message(content=None, embed=await view.get_embed(), view=view)

    @discord.ui.button(label="📦 창고", style=discord.ButtonStyle.secondary, custom_id="guild_btn_warehouse")
    async def btn_warehouse(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        view = GuildWarehouseView(interaction.user, guild_info)
        await interaction.response.edit_message(content=None, embed=await view.get_embed(), view=view)

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
        await interaction.response.edit_message(content=None, embed=lobby.get_embed(), view=lobby)
        lobby.public_message = interaction.message

    @discord.ui.button(label="🥋 수련장", style=discord.ButtonStyle.success, custom_id="guild_btn_training")
    async def btn_training(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info:
            return
        view = GuildTrainingView(interaction.user, guild_info)
        await interaction.response.edit_message(content=None, embed=await view.get_embed(), view=view)

    @discord.ui.button(label="🛠️ 길드 제작소", style=discord.ButtonStyle.primary, custom_id="guild_btn_workshop")
    async def btn_workshop(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info:
            return
        view = GuildWorkshopView(interaction.user, guild_info)
        await view.setup_view()
        await interaction.response.edit_message(content=None, embed=await view.get_embed(), view=view)
    
    @discord.ui.button(label="⚖️ 물자 관리", style=discord.ButtonStyle.secondary, custom_id="guild_btn_manage")
    async def btn_manage(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_info = await get_user_guild_info(interaction.user.id)
        if not guild_info: return
        view = InventoryManageView(interaction.user, guild_info)
        await view.setup_view()
        await interaction.response.edit_message(content=None, embed=await view.get_embed(), view=view)

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
