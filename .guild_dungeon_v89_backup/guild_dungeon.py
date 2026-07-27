# guild-dungeon-v8.8
"""Two-to-three player cooperative guild dungeon.

The active run is intentionally kept in memory because Discord views and votes
cannot be reconstructed safely after a process restart.  Currency and loot are
merged into the database immediately after each resolved room, so rewards that
were already shown to players survive a restart.
"""

from __future__ import annotations

import asyncio
import random
from collections import Counter

import discord
from discord.ui import Button, Select

import battle_engine
from cards import get_card
from character import Character
from data_manager import (
    advance_world_turn,
    get_user_data,
    get_user_guild_info,
    mutate_user_data,
)
from gem_effects import (
    apply_escalation_to_dice,
    apply_ripple_to_dice,
    battle_end_gem_heal,
    process_gem_turn_start,
    revive_gem_effects,
)
from items import REGIONS
from monsters import get_dungeon_boss, spawn_monster
from subjugation import generate_dungeon_item


GUILD_DUNGEON_COST = 2_000
GUILD_DUNGEON_MIN_PLAYERS = 2
GUILD_DUNGEON_MAX_PLAYERS = 3
CARD_PAGE_SIZE = 4

_ACTIVE_GUILD_DUNGEON_USERS: set[int] = set()

REGION_MONSTER_POOLS = {
    "기원의 쌍성": ["길 잃은 바람비", "약한 원념", "커다란 별기구"],
    "시간의 신전": ["눈 감은 원념", "약한 원념"],
    "일한산 중턱": ["굴레늑대", "얼어붙은 원념", "경계꽃 골렘"],
    "이루지 못한 꿈들의 별": ["몽상행인", "살아난 발상", "구체화된 악몽"],
    "생명의 숲": ["뒤틀린 식충식물", "굶주린 포식자", "아름다운 나비"],
    "아르카워드 제도": ["아사한 원념", "변질된 바람", "폐허를 지키는 문지기"],
    "공간의 신전": ["취한 파티원", "겁쟁이 원념", "폭주 거대 짤똥이"],
}


def guild_dungeon_hope_reward(depth: int) -> int:
    """Pure Hope granted to every member after a boss kill."""
    return 1 + max(0, int(depth)) // 50


def _bar(current: int, maximum: int, full: str, empty: str, width: int = 10) -> str:
    if maximum <= 0:
        filled = 0
    else:
        filled = max(0, min(width, int(current / maximum * width)))
    return f"{full * filled}{empty * (width - filled)} ({max(0, current)}/{maximum})"


def _artifact_effects(character: Character) -> list[str]:
    result = []
    for artifact in (
        getattr(character, "equipped_artifact", None),
        getattr(character, "equipped_engraved_artifact", None),
    ):
        if isinstance(artifact, dict) and artifact.get("special"):
            result.append(artifact["special"])
    return result


def _available_cards(character: Character) -> list[str]:
    cards = [
        name
        for name in (getattr(character, "equipped_cards", None) or ["기본공격"])
        if get_card(name)
    ]
    return cards or ["기본공격"]


def _normal_room_loot(region_name: str, depth: int) -> dict[str, int]:
    if depth < 30:
        item_name, quantity, rare_quantity = (
            random.choice(["낡은 보물상자", "낡은 열쇠"]),
            10,
            1,
        )
    elif depth < 60:
        item_name, quantity, rare_quantity = (
            random.choice(["섬세한 보물상자", "섬세한 열쇠"]),
            10,
            3,
        )
    else:
        item_name, quantity, rare_quantity = (
            random.choice(["깔끔한 보물상자", "깔끔한 열쇠"]),
            10,
            5,
        )

    rares = REGIONS.get(region_name, {}).get("rare", ["사랑나무 가지"])
    rare_item = random.choice(rares)
    loot = {item_name: quantity, rare_item: rare_quantity}

    bonus = {
        "시간의 신전": ("하급 마력석", 2, 5),
        "일한산 중턱": ("천년얼음", 3, 5),
        "이루지 못한 꿈들의 별": ("별모양 별", 3, 7),
        "생명의 숲": ("뒤틀린 씨앗", 3, 7),
        "아르카워드 제도": ("부유석", 5, 10),
    }.get(region_name)
    if bonus:
        bonus_item, bonus_quantity, base_bonus = bonus
        loot[item_name] += base_bonus
        loot[bonus_item] = loot.get(bonus_item, 0) + bonus_quantity
    return loot


def _monster_rewards(monster) -> tuple[dict[str, int], int, int]:
    money_range = getattr(monster, "money_range", (0, 0))
    pt_range = getattr(monster, "pt_range", (0, 0))
    money = random.randint(int(money_range[0]), int(money_range[1]))
    pt = random.randint(int(pt_range[0]), int(pt_range[1]))
    items: dict[str, int] = {}
    reward = getattr(monster, "reward", None)
    if reward and reward != "보스 전리품":
        items[reward] = max(1, int(getattr(monster, "reward_count", 1)))
    return items, money, pt


def _monster_pool(region_name: str, unlocked_regions: list[str]) -> list[str]:
    pool = list(REGION_MONSTER_POOLS.get(region_name, ["약한 원념"]))
    unlocked = set(unlocked_regions or [])
    if region_name == "기원의 쌍성" and "시간의 신전" in unlocked:
        pool.extend(["주신의 눈물방울", "예민한 집요정"])
    if region_name == "시간의 신전" and "일한산 중턱" in unlocked:
        pool.extend(["시간의 방랑자", "과거의 망집"])
    if region_name == "일한산 중턱" and "이루지 못한 꿈들의 별" in unlocked:
        pool.extend(["굴레늑대 우두머리", "은하새"])
    if region_name == "생명의 숲" and "아르카워드 제도" in unlocked:
        pool.extend(["냉혹한 원념", "사나운 은하새"])
    return pool


async def _advance_participant_turn(participant: dict, amount: int = 1) -> None:
    def merge(latest):
        advance_world_turn(latest, amount)

    participant["data"] = await mutate_user_data(
        participant["user"].id,
        merge,
        participant["user"].display_name,
    )


async def _grant_rewards(
    participant: dict,
    *,
    items: dict[str, int] | None = None,
    money: int = 0,
    pt: int = 0,
    hope: int = 0,
) -> None:
    clean_items = {
        str(name): max(0, int(quantity))
        for name, quantity in (items or {}).items()
        if int(quantity) > 0
    }

    def merge(latest):
        latest["money"] = int(latest.get("money", 0) or 0) + max(0, int(money))
        latest["pt"] = int(latest.get("pt", 0) or 0) + max(0, int(pt))
        inventory = latest.setdefault("inventory", {})
        for item_name, quantity in clean_items.items():
            inventory[item_name] = int(inventory.get(item_name, 0) or 0) + quantity
        if hope > 0:
            inventory["순수한 희망"] = (
                int(inventory.get("순수한 희망", 0) or 0) + int(hope)
            )

    participant["data"] = await mutate_user_data(
        participant["user"].id,
        merge,
        participant["user"].display_name,
    )


def _apply_stat_tool(participant: dict, item: dict | None) -> None:
    if not item or item.get("type") != "stat" or participant.get("stat_tool_applied"):
        return
    character = participant["char"]
    stat = item.get("stat")
    value = int(item.get("value", 0) or 0)
    if stat not in {"attack", "defense", "max_hp", "max_mental"} or value <= 0:
        return
    setattr(character, stat, int(getattr(character, stat, 0)) + value)
    if stat == "max_hp":
        character.current_hp += value
    elif stat == "max_mental":
        character.current_mental += value
    participant["stat_tool_applied"] = True


def _remove_stat_tool(participant: dict) -> None:
    item = participant.get("dungeon_item")
    if not item or item.get("type") != "stat" or not participant.get("stat_tool_applied"):
        return
    character = participant["char"]
    stat = item.get("stat")
    value = int(item.get("value", 0) or 0)
    if stat in {"attack", "defense", "max_hp", "max_mental"}:
        setattr(character, stat, max(1, int(getattr(character, stat, 1)) - value))
        if stat == "max_hp":
            character.current_hp = min(character.current_hp, character.max_hp)
        elif stat == "max_mental":
            character.current_mental = min(
                character.current_mental,
                character.max_mental,
            )
    participant["stat_tool_applied"] = False


def _replace_tool(participant: dict, new_item: dict) -> None:
    _remove_stat_tool(participant)
    participant["dungeon_item"] = new_item
    participant["stat_tool_applied"] = False
    _apply_stat_tool(participant, new_item)


class GuildDungeonLobbyView(discord.ui.View):
    """Public lobby opened from the guild training room."""

    def __init__(self, host, guild_info: dict, parent_view=None):
        super().__init__(timeout=300)
        self.host = host
        self.guild_info = guild_info
        self.parent_view = parent_view
        self.participants: dict[int, dict] = {}
        self.region_name: str | None = None
        self.started = False
        self.lock = asyncio.Lock()
        self.public_message = None

    async def setup(self) -> None:
        await self._add_participant(self.host)
        self._rebuild()

    async def _add_participant(self, user) -> tuple[bool, str]:
        if user.id in self.participants:
            return False, "이미 참가 중입니다."
        if len(self.participants) >= GUILD_DUNGEON_MAX_PLAYERS:
            return False, "파티가 가득 찼습니다."
        if int(user.id) in _ACTIVE_GUILD_DUNGEON_USERS:
            return False, "이미 다른 길드 던전 로비나 탐사에 참가 중입니다."
        guild_info = await get_user_guild_info(user.id)
        if not guild_info or guild_info["guild_id"] != self.guild_info["guild_id"]:
            return False, "같은 길드의 구성원만 참가할 수 있습니다."

        data = await get_user_data(user.id, user.display_name)
        if data.get("current_dungeon"):
            return False, "진행 중인 개인 던전을 먼저 마쳐주세요."
        if int(data.get("pt", 0) or 0) < GUILD_DUNGEON_COST:
            return False, f"참가하려면 {GUILD_DUNGEON_COST:,}pt가 필요합니다."
        characters = data.get("characters", [])
        index = int(data.get("investigator_index", 0) or 0)
        if not 0 <= index < len(characters):
            return False, "현재 조사 캐릭터를 찾지 못했습니다."

        character = Character.from_dict(characters[index])
        character.status_effects = {"bleed": 0, "paralysis": 0, "stun": 0}
        character.runtime_cooldowns = {}
        self.participants[user.id] = {
            "user": user,
            "data": data,
            "char": character,
            "char_idx": index,
            "dungeon_item": None,
            "stat_tool_applied": False,
            "revived": False,
            "loot": {"items": {}, "money": 0, "pt": 0, "hope": 0},
        }
        _ACTIVE_GUILD_DUNGEON_USERS.add(int(user.id))
        return True, f"{character.name}(으)로 참가했습니다."

    def _release_all(self) -> None:
        for user_id in self.participants:
            _ACTIVE_GUILD_DUNGEON_USERS.discard(int(user_id))

    def _rebuild(self) -> None:
        self.clear_items()
        regions = []
        host_data = self.participants.get(self.host.id, {}).get("data", {})
        unlocked = host_data.get("unlocked_regions", ["기원의 쌍성"])
        order = list(REGIONS)
        for name in sorted(
            set(unlocked),
            key=lambda value: order.index(value) if value in order else 999,
        ):
            if name in REGIONS and name != "노드 해역":
                regions.append(
                    discord.SelectOption(
                        label=name,
                        value=name,
                        description=f"파티원마다 {GUILD_DUNGEON_COST:,}pt 소비",
                        default=name == self.region_name,
                    )
                )
        if regions:
            region_select = Select(
                placeholder="호스트가 탐사 지역 선택",
                options=regions[:25],
                row=0,
            )

            async def select_region(interaction):
                if interaction.user.id != self.host.id:
                    return await interaction.response.send_message(
                        "호스트만 지역을 정할 수 있습니다.",
                        ephemeral=True,
                    )
                self.region_name = region_select.values[0]
                self._rebuild()
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            region_select.callback = select_region
            self.add_item(region_select)

        join = Button(label="참가", style=discord.ButtonStyle.success, row=1)
        leave = Button(label="참가 취소", style=discord.ButtonStyle.secondary, row=1)
        start = Button(label="출발", style=discord.ButtonStyle.danger, row=1)
        back = Button(label="수련장으로", style=discord.ButtonStyle.secondary, row=2)

        async def join_callback(interaction):
            await interaction.response.defer()
            async with self.lock:
                if self.started:
                    return await interaction.followup.send(
                        "이미 출발한 파티입니다.",
                        ephemeral=True,
                    )
                ok, message = await self._add_participant(interaction.user)
                self._rebuild()
            if ok:
                self.public_message = await interaction.edit_original_response(
                    embed=self.get_embed(),
                    view=self,
                )
            else:
                await interaction.followup.send(message, ephemeral=True)

        async def leave_callback(interaction):
            async with self.lock:
                if self.started:
                    return await interaction.response.send_message(
                        "탐사 시작 후에는 로비에서 이탈할 수 없습니다.",
                        ephemeral=True,
                    )
                if interaction.user.id == self.host.id:
                    return await interaction.response.send_message(
                        "호스트는 수련장으로 돌아가 로비를 닫아주세요.",
                        ephemeral=True,
                    )
                if interaction.user.id not in self.participants:
                    return await interaction.response.send_message(
                        "참가 중이 아닙니다.",
                        ephemeral=True,
                    )
                self.participants.pop(interaction.user.id, None)
                _ACTIVE_GUILD_DUNGEON_USERS.discard(int(interaction.user.id))
                self._rebuild()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

        async def start_callback(interaction):
            if interaction.user.id != self.host.id:
                return await interaction.response.send_message(
                    "호스트만 출발할 수 있습니다.",
                    ephemeral=True,
                )
            await interaction.response.defer()
            async with self.lock:
                if self.started:
                    return await interaction.followup.send(
                        "이미 출발한 파티입니다.",
                        ephemeral=True,
                    )
                if len(self.participants) < GUILD_DUNGEON_MIN_PLAYERS:
                    return await interaction.followup.send(
                        "길드 던전은 2~3명이 필요합니다.",
                        ephemeral=True,
                    )
                if not self.region_name:
                    return await interaction.followup.send(
                        "탐사 지역을 먼저 선택하세요.",
                        ephemeral=True,
                    )
                charged = []
                try:
                    for participant in self.participants.values():
                        def charge(latest):
                            current = int(latest.get("pt", 0) or 0)
                            if current < GUILD_DUNGEON_COST:
                                raise ValueError(
                                    f"{participant['user'].display_name}님의 포인트가 부족합니다."
                                )
                            latest["pt"] = current - GUILD_DUNGEON_COST

                        participant["data"] = await mutate_user_data(
                            participant["user"].id,
                            charge,
                            participant["user"].display_name,
                        )
                        charged.append(participant)
                except Exception as exc:
                    for participant in charged:
                        def refund(latest):
                            latest["pt"] = (
                                int(latest.get("pt", 0) or 0) + GUILD_DUNGEON_COST
                            )

                        await mutate_user_data(
                            participant["user"].id,
                            refund,
                            participant["user"].display_name,
                        )
                    return await interaction.followup.send(
                        f"출발 비용 결제를 취소했습니다: {exc}",
                        ephemeral=True,
                    )
                self.started = True

            run = GuildDungeonRun(
                self.host,
                self.guild_info,
                self.region_name,
                self.participants,
                interaction.message,
            )
            for participant in run.participants.values():
                character = participant["char"]
                character.current_hp = character.max_hp
                character.current_mental = character.max_mental
                if hasattr(character, "apply_battle_start_buffs"):
                    character.apply_battle_start_buffs()
                character.current_hp = character.max_hp
                character.current_mental = character.max_mental
            await run.show_vote(interaction, "길드 던전 탐사를 시작합니다.")
            self.stop()

        async def back_callback(interaction):
            if interaction.user.id != self.host.id:
                return await interaction.response.send_message(
                    "호스트만 로비를 닫을 수 있습니다.",
                    ephemeral=True,
                )
            if self.started:
                return await interaction.response.send_message(
                    "이미 탐사가 시작되었습니다.",
                    ephemeral=True,
                )
            await interaction.response.defer()
            self._release_all()
            self.stop()
            if self.parent_view is not None:
                await interaction.edit_original_response(
                    embed=await self.parent_view.get_embed(),
                    view=self.parent_view,
                )
            else:
                await interaction.edit_original_response(
                    embed=discord.Embed(
                        title="길드 던전 로비 종료",
                        description="로비를 닫았습니다.",
                    ),
                    view=None,
                )

        join.callback = join_callback
        leave.callback = leave_callback
        start.callback = start_callback
        back.callback = back_callback
        self.add_item(join)
        self.add_item(leave)
        self.add_item(start)
        self.add_item(back)

    def get_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🗺️ 길드 던전 원정대",
            description=(
                "2~3명이 함께 진행하며, 각 방은 생존자의 투표로 결정합니다.\n"
                "동률이면 동률 선택지 중 하나가 무작위로 채택됩니다.\n"
                f"출발 시 각자 **{GUILD_DUNGEON_COST:,}pt**를 사용합니다."
            ),
            color=discord.Color.dark_teal(),
        )
        embed.add_field(
            name="탐사 지역",
            value=self.region_name or "아직 선택하지 않음",
            inline=False,
        )
        lines = []
        for participant in self.participants.values():
            lines.append(
                f"• {participant['user'].display_name} — "
                f"**{participant['char'].name}** "
                f"({int(participant['data'].get('pt', 0)):,}pt)"
            )
        embed.add_field(
            name=f"참가자 {len(self.participants)}/{GUILD_DUNGEON_MAX_PLAYERS}",
            value="\n".join(lines) or "참가자가 없습니다.",
            inline=False,
        )
        embed.set_footer(text="길드 던전 진행 상태는 봇 재시작 후 이어갈 수 없습니다.")
        return embed

    async def on_timeout(self):
        if self.started:
            return
        self._release_all()
        for item in self.children:
            item.disabled = True
        if self.public_message:
            try:
                await self.public_message.edit(
                    content="길드 던전 모집 시간이 끝났습니다.",
                    view=self,
                )
            except (discord.NotFound, discord.HTTPException):
                pass


class GuildDungeonRun:
    def __init__(self, host, guild_info, region_name, participants, public_message):
        self.host = host
        self.guild_info = guild_info
        self.region_name = region_name
        self.participants = participants
        self.public_message = public_message
        self.depth = 0
        self.phase = 0
        self.finished = False
        self.forced_room: str | None = None
        self.lock = asyncio.Lock()

    def living_ids(self) -> list[int]:
        return [
            uid
            for uid, participant in self.participants.items()
            if participant["char"].current_hp > 0
        ]

    def setup_choices(self) -> list[str]:
        if self.forced_room:
            result = [self.forced_room]
            self.forced_room = None
            return result
        next_depth = self.depth + 1
        if next_depth % 30 == 0:
            return ["boss"]
        return random.choices(
            ["monster", "recovery", "item"],
            weights=[40, 35, 25],
            k=3,
        )

    async def edit_public(self, interaction, *, embed, view) -> None:
        if not interaction.response.is_done():
            await interaction.response.edit_message(
                content=None,
                embed=embed,
                view=view,
            )
            try:
                self.public_message = await interaction.original_response()
            except (discord.NotFound, discord.HTTPException):
                pass
            return
        try:
            self.public_message = await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=view,
            )
        except (discord.NotFound, discord.HTTPException):
            self.public_message = await interaction.channel.send(embed=embed, view=view)

    async def show_vote(self, interaction, message: str) -> None:
        if self.finished:
            return
        if not self.living_ids():
            return await self.finish(interaction, "원정대가 전멸했습니다.", defeated=True)
        self.phase += 1
        view = GuildDungeonVoteView(self, self.setup_choices(), self.phase)
        await self.edit_public(
            interaction,
            embed=view.get_embed(message),
            view=view,
        )

    async def advance_shared_turn(self, amount: int = 1) -> None:
        for participant in self.participants.values():
            await _advance_participant_turn(participant, amount)

    def tick_stat_tools(self) -> None:
        for participant in self.participants.values():
            item = participant.get("dungeon_item")
            if not item or item.get("type") != "stat":
                continue
            item["remaining"] = max(0, int(item.get("remaining", 0) or 0) - 1)
            if item["remaining"] <= 0:
                _remove_stat_tool(participant)
                participant["dungeon_item"] = None

    async def resolve_room(self, interaction, room_type: str, vote_summary: str) -> None:
        self.depth += 1
        await self.advance_shared_turn(1)
        self.tick_stat_tools()
        if room_type == "boss":
            await self.start_battle(interaction, is_boss=True, vote_summary=vote_summary)
        elif room_type == "monster":
            await self.start_battle(interaction, is_boss=False, vote_summary=vote_summary)
        elif room_type == "item":
            await self.open_item_room(interaction, vote_summary)
        else:
            await self.open_recovery_room(interaction, vote_summary)

    def _scaled_monster(self, *, is_boss: bool):
        if is_boss:
            monster = get_dungeon_boss(self.region_name, self.depth)
        else:
            host_data = self.participants[self.host.id]["data"]
            pool = _monster_pool(
                self.region_name,
                host_data.get("unlocked_regions", []),
            )
            monster = spawn_monster(random.choice(pool))

        party_size = max(1, len(self.living_ids()))
        hp_factor = 1.0 + 0.55 * (party_size - 1)
        monster.max_hp = max(1, int(monster.max_hp * hp_factor))
        monster.current_hp = monster.max_hp
        buff_sets = self.depth // 10
        if is_boss and self.depth >= 120:
            buff_sets += (self.depth - 90) // 10
        if buff_sets:
            monster.attack += buff_sets
            monster.defense += buff_sets
            monster.max_hp += buff_sets * 10
            monster.current_hp = monster.max_hp
        return monster

    async def start_battle(self, interaction, *, is_boss: bool, vote_summary: str):
        monster = self._scaled_monster(is_boss=is_boss)
        view = GuildDungeonBattleView(self, monster, is_boss)
        await self.edit_public(
            interaction,
            embed=view.get_embed(
                f"{vote_summary}\n\n{'보스' if is_boss else '몬스터'}와 조우했습니다."
            ),
            view=view,
        )
        view.public_message = self.public_message

    async def open_recovery_room(self, interaction, vote_summary: str):
        lines = []
        for participant in self.participants.values():
            character = participant["char"]
            if character.current_hp <= 0:
                continue
            hp = max(1, int(character.max_hp * 0.30))
            mental = max(1, int(character.max_mental * 0.30))
            before_hp = character.current_hp
            before_mental = character.current_mental
            character.current_hp = min(character.max_hp, character.current_hp + hp)
            character.current_mental = min(
                character.max_mental,
                character.current_mental + mental,
            )
            lines.append(
                f"• {participant['user'].display_name}: "
                f"HP +{character.current_hp - before_hp}, "
                f"정신 +{character.current_mental - before_mental}"
            )
        view = GuildDungeonContinueView(self)
        embed = discord.Embed(
            title=f"💚 {self.depth}층 · 회복방",
            description=f"{vote_summary}\n\n" + "\n".join(lines),
            color=discord.Color.green(),
        )
        await self.edit_public(interaction, embed=embed, view=view)

    async def open_item_room(self, interaction, vote_summary: str):
        loot = _normal_room_loot(self.region_name, self.depth)
        for participant in self.participants.values():
            await _grant_rewards(participant, items=loot)
            for name, quantity in loot.items():
                participant["loot"]["items"][name] = (
                    participant["loot"]["items"].get(name, 0) + quantity
                )
            participant["pending_item"] = generate_dungeon_item(self.depth)
            participant["item_decided"] = False
            if participant.get("dungeon_item") is None:
                _replace_tool(participant, participant["pending_item"])
                participant["pending_item"] = None
                participant["item_decided"] = True

        view = GuildDungeonItemRoomView(self)
        loot_text = ", ".join(f"{name} ×{qty}" for name, qty in loot.items())
        embed = discord.Embed(
            title=f"💎 {self.depth}층 · 보물방",
            description=(
                f"{vote_summary}\n\n"
                f"각 참가자가 **{loot_text}**을 즉시 획득했습니다.\n"
                "각자의 던전 도구는 `내 도구 확인`에서 따로 결정합니다."
            ),
            color=discord.Color.gold(),
        )
        await self.edit_public(interaction, embed=embed, view=view)
        view.public_message = self.public_message

    async def after_battle_victory(self, interaction, monster, is_boss: bool):
        items, money, pt = _monster_rewards(monster)
        hope = guild_dungeon_hope_reward(self.depth) if is_boss else 0
        for participant in self.participants.values():
            await _grant_rewards(
                participant,
                items=items,
                money=money,
                pt=pt,
                hope=hope,
            )
            loot = participant["loot"]
            loot["money"] += money
            loot["pt"] += pt
            loot["hope"] += hope
            for name, quantity in items.items():
                loot["items"][name] = loot["items"].get(name, 0) + quantity
            battle_end_gem_heal(participant["char"])

        if is_boss:
            self.forced_room = "item"
        reward_lines = [f"💰 {money:,}원", f"⚡ {pt:,}pt"]
        if items:
            reward_lines.append(
                "📦 " + ", ".join(f"{name} ×{qty}" for name, qty in items.items())
            )
        if hope:
            reward_lines.append(f"🌟 순수한 희망 ×{hope}")
        embed = discord.Embed(
            title=f"🏆 {self.depth}층 전투 승리",
            description=(
                f"**{monster.name}**을 쓰러뜨렸습니다.\n"
                "아래 보상은 각 참가자에게 즉시 지급되었습니다.\n\n"
                + "\n".join(reward_lines)
            ),
            color=discord.Color.gold(),
        )
        await self.edit_public(
            interaction,
            embed=embed,
            view=GuildDungeonContinueView(self),
        )

    async def persist_characters(self, *, defeated: bool) -> None:
        for participant in self.participants.values():
            _remove_stat_tool(participant)
            character = participant["char"]
            if hasattr(character, "remove_battle_buffs"):
                character.remove_battle_buffs()
            if defeated and character.current_hp <= 0:
                character.current_hp = 1
            character_data = character.to_dict()
            index = int(participant["char_idx"])

            def merge(latest):
                characters = latest.setdefault("characters", [])
                if 0 <= index < len(characters):
                    characters[index] = character_data
                myhome = latest.setdefault("myhome", {})
                myhome["total_subjugations"] = (
                    int(myhome.get("total_subjugations", 0) or 0) + self.depth
                )
                if self.depth > int(myhome.get("max_guild_dungeon_depth", 0) or 0):
                    myhome["max_guild_dungeon_depth"] = self.depth
                    myhome["max_guild_dungeon_region"] = self.region_name

            participant["data"] = await mutate_user_data(
                participant["user"].id,
                merge,
                participant["user"].display_name,
            )

    async def finish(self, interaction, reason: str, *, defeated: bool = False):
        async with self.lock:
            if self.finished:
                return
            self.finished = True
        await self.persist_characters(defeated=defeated)
        for user_id in self.participants:
            _ACTIVE_GUILD_DUNGEON_USERS.discard(int(user_id))

        lines = []
        for participant in self.participants.values():
            loot = participant["loot"]
            lines.append(
                f"**{participant['user'].display_name}** — "
                f"{loot['money']:,}원 / {loot['pt']:,}pt / "
                f"순수한 희망 {loot['hope']}개"
            )
        embed = discord.Embed(
            title="🏁 길드 던전 종료",
            description=f"{reason}\n\n최종 깊이: **{self.depth}층**",
            color=discord.Color.red() if defeated else discord.Color.green(),
        )
        embed.add_field(
            name="이번 원정 누적 보상",
            value="\n".join(lines) or "없음",
            inline=False,
        )
        await self.edit_public(interaction, embed=embed, view=None)


class GuildDungeonVoteView(discord.ui.View):
    ROOM_TEXT = {
        "monster": "불길한 기운이 느껴진다.",
        "recovery": "고요하고 편안한 기운이 흐른다.",
        "item": "어둠 속에서 무언가 반짝인다.",
        "boss": "압도적인 살기가 길을 가로막는다.",
    }

    def __init__(self, run: GuildDungeonRun, choices: list[str], phase: int):
        super().__init__(timeout=300)
        self.run = run
        self.choices = choices
        self.phase = phase
        self.votes: dict[int, int] = {}
        self.resolving = False
        for index, room_type in enumerate(choices):
            style = (
                discord.ButtonStyle.danger
                if room_type == "boss"
                else discord.ButtonStyle.primary
            )
            button = Button(label=f"선택 {index + 1}", style=style, row=0)

            async def vote(interaction, selected=index):
                await self.cast_vote(interaction, selected)

            button.callback = vote
            self.add_item(button)
        stop = Button(label="원정 종료", style=discord.ButtonStyle.danger, row=1)

        async def stop_callback(interaction):
            if interaction.user.id != self.run.host.id:
                return await interaction.response.send_message(
                    "호스트만 원정을 종료할 수 있습니다.",
                    ephemeral=True,
                )
            await interaction.response.defer()
            await self.run.finish(interaction, "호스트가 원정을 종료했습니다.")

        stop.callback = stop_callback
        self.add_item(stop)

    def get_embed(self, message: str = "") -> discord.Embed:
        embed = discord.Embed(
            title=f"🗺️ {self.run.region_name} 길드 던전 · {self.run.depth}층",
            description=message,
            color=discord.Color.dark_purple(),
        )
        status = []
        for participant in self.run.participants.values():
            character = participant["char"]
            item = participant.get("dungeon_item")
            item_text = item["name"] if item else "없음"
            status.append(
                f"**{participant['user'].display_name} · {character.name}**\n"
                f"❤️ {_bar(character.current_hp, character.max_hp, '🟥', '⬛')}\n"
                f"🎒 {item_text}"
            )
        embed.add_field(name="원정대", value="\n\n".join(status), inline=False)
        choices = [
            f"{index + 1}. {self.ROOM_TEXT[room_type]}"
            for index, room_type in enumerate(self.choices)
        ]
        embed.add_field(name="다음 길", value="\n".join(choices), inline=False)
        if self.votes:
            vote_lines = []
            for user_id, selected in self.votes.items():
                participant = self.run.participants.get(user_id)
                if participant:
                    vote_lines.append(
                        f"{participant['user'].display_name}: 선택 {selected + 1}"
                    )
            embed.add_field(name="현재 투표", value="\n".join(vote_lines), inline=False)
        embed.set_footer(text="생존한 참가자 전원이 투표하면 즉시 결정됩니다.")
        return embed

    async def cast_vote(self, interaction, selected: int):
        should_resolve = False
        async with self.run.lock:
            if self.run.finished:
                return await interaction.response.send_message(
                    "이미 끝난 원정입니다.",
                    ephemeral=True,
                )
            if self.phase != self.run.phase or self.resolving:
                return await interaction.response.send_message(
                    "이전 선택 화면입니다.",
                    ephemeral=True,
                )
            if interaction.user.id not in self.run.living_ids():
                return await interaction.response.send_message(
                    "생존한 원정대원만 투표할 수 있습니다.",
                    ephemeral=True,
                )
            self.votes[interaction.user.id] = selected
            alive = self.run.living_ids()
            should_resolve = all(user_id in self.votes for user_id in alive)
            if should_resolve:
                self.resolving = True
        await interaction.response.defer()
        if not should_resolve:
            await self.run.edit_public(
                interaction,
                embed=self.get_embed("투표가 갱신되었습니다."),
                view=self,
            )
            return

        counts = Counter(self.votes[user_id] for user_id in self.run.living_ids())
        highest = max(counts.values())
        tied = [index for index, count in counts.items() if count == highest]
        selected_index = random.choice(tied)
        room_type = self.choices[selected_index]
        summary = (
            f"투표 결과 **선택 {selected_index + 1}**이 채택되었습니다."
            + (" 동률이어서 무작위로 결정되었습니다." if len(tied) > 1 else "")
        )
        await self.run.resolve_room(interaction, room_type, summary)
        self.stop()


class GuildDungeonContinueView(discord.ui.View):
    def __init__(self, run: GuildDungeonRun):
        super().__init__(timeout=300)
        self.run = run
        self.used = False

    @discord.ui.button(label="다음 방으로", style=discord.ButtonStyle.success)
    async def continue_button(self, interaction, button):
        if interaction.user.id not in self.run.participants:
            return await interaction.response.send_message(
                "원정 참가자만 진행할 수 있습니다.",
                ephemeral=True,
            )
        async with self.run.lock:
            if self.used or self.run.finished:
                return await interaction.response.send_message(
                    "이미 처리된 화면입니다.",
                    ephemeral=True,
                )
            self.used = True
        await interaction.response.defer()
        await self.run.show_vote(interaction, "원정대가 다음 길을 살핍니다.")
        self.stop()


class GuildDungeonItemDecisionView(discord.ui.View):
    def __init__(self, parent, participant: dict):
        super().__init__(timeout=180)
        self.parent = parent
        self.run = parent.run
        self.participant = participant
        self.user_id = participant["user"].id

    async def interaction_check(self, interaction):
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "본인의 던전 도구만 결정할 수 있습니다.",
            ephemeral=True,
        )
        return False

    def get_embed(self):
        current = self.participant.get("dungeon_item")
        new_item = self.participant.get("pending_item")
        embed = discord.Embed(
            title="🎒 개인 던전 도구 선택",
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="현재 도구",
            value=(
                f"**{current['name']}**\n{current['desc']}"
                if current
                else "없음"
            ),
            inline=False,
        )
        embed.add_field(
            name="발견한 도구",
            value=(
                f"**{new_item['name']}**\n{new_item['desc']}"
                if new_item
                else "이미 자동으로 보관했습니다."
            ),
            inline=False,
        )
        return embed

    async def _finish(self, interaction, *, replace: bool):
        async with self.run.lock:
            if self.participant.get("item_decided"):
                return await interaction.response.send_message(
                    "이미 도구를 결정했습니다.",
                    ephemeral=True,
                )
            new_item = self.participant.get("pending_item")
            if replace and new_item:
                _replace_tool(self.participant, new_item)
            self.participant["pending_item"] = None
            self.participant["item_decided"] = True
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ 도구 결정 완료",
                description=(
                    "새 도구로 교체했습니다."
                    if replace
                    else "현재 도구를 유지했습니다."
                ),
                color=discord.Color.green(),
            ),
            view=None,
        )
        await self.parent.refresh_public()

    @discord.ui.button(label="새 도구로 교체", style=discord.ButtonStyle.success)
    async def replace_button(self, interaction, button):
        await self._finish(interaction, replace=True)

    @discord.ui.button(label="현재 도구 유지", style=discord.ButtonStyle.secondary)
    async def keep_button(self, interaction, button):
        await self._finish(interaction, replace=False)


class GuildDungeonItemRoomView(discord.ui.View):
    def __init__(self, run: GuildDungeonRun):
        super().__init__(timeout=300)
        self.run = run
        self.public_message = None
        self.continuing = False

    def all_decided(self):
        return all(
            participant.get("item_decided")
            for participant in self.run.participants.values()
        )

    async def refresh_public(self):
        if not self.public_message:
            return
        pending = [
            participant["user"].display_name
            for participant in self.run.participants.values()
            if not participant.get("item_decided")
        ]
        try:
            embed = self.public_message.embeds[0].copy()
            embed.set_footer(
                text=(
                    "모든 참가자의 도구 결정 완료"
                    if not pending
                    else "도구 결정 대기: " + ", ".join(pending)
                )
            )
            await self.public_message.edit(embed=embed, view=self)
        except (discord.NotFound, discord.HTTPException, IndexError):
            pass

    @discord.ui.button(label="내 도구 확인", style=discord.ButtonStyle.primary)
    async def inspect_button(self, interaction, button):
        participant = self.run.participants.get(interaction.user.id)
        if not participant:
            return await interaction.response.send_message(
                "원정 참가자만 확인할 수 있습니다.",
                ephemeral=True,
            )
        if participant.get("item_decided"):
            item = participant.get("dungeon_item")
            return await interaction.response.send_message(
                (
                    f"현재 도구: **{item['name']}**\n{item['desc']}"
                    if item
                    else "현재 도구가 없습니다."
                ),
                ephemeral=True,
            )
        view = GuildDungeonItemDecisionView(self, participant)
        await interaction.response.send_message(
            embed=view.get_embed(),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="결정 완료 후 진행", style=discord.ButtonStyle.success)
    async def continue_button(self, interaction, button):
        if interaction.user.id not in self.run.participants:
            return await interaction.response.send_message(
                "원정 참가자만 진행할 수 있습니다.",
                ephemeral=True,
            )
        async with self.run.lock:
            if self.continuing:
                return await interaction.response.send_message(
                    "이미 처리 중입니다.",
                    ephemeral=True,
                )
            if not self.all_decided():
                return await interaction.response.send_message(
                    "아직 도구를 결정하지 않은 참가자가 있습니다.",
                    ephemeral=True,
                )
            self.continuing = True
        await interaction.response.defer()
        await self.run.show_vote(interaction, "보물을 챙기고 다음 길로 향합니다.")
        self.stop()

    @discord.ui.button(label="미응답 자동 유지", style=discord.ButtonStyle.secondary)
    async def force_keep_button(self, interaction, button):
        if interaction.user.id != self.run.host.id:
            return await interaction.response.send_message(
                "호스트만 미응답 결정을 마감할 수 있습니다.",
                ephemeral=True,
            )
        async with self.run.lock:
            for participant in self.run.participants.values():
                if participant.get("item_decided"):
                    continue
                participant["pending_item"] = None
                participant["item_decided"] = True
        await interaction.response.defer()
        await self.refresh_public()


class GuildDungeonCardView(discord.ui.View):
    def __init__(self, battle, user_id: int, turn: int):
        super().__init__(timeout=120)
        self.battle = battle
        self.user_id = user_id
        self.turn = turn
        self.page = 0
        self.cards = _available_cards(battle.run.participants[user_id]["char"])
        self.rebuild()

    async def interaction_check(self, interaction):
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "본인의 커맨드만 선택할 수 있습니다.",
            ephemeral=True,
        )
        return False

    def rebuild(self):
        self.clear_items()
        total_pages = max(1, (len(self.cards) + CARD_PAGE_SIZE - 1) // CARD_PAGE_SIZE)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * CARD_PAGE_SIZE
        for card_name in self.cards[start:start + CARD_PAGE_SIZE]:
            button = Button(label=card_name[:80], style=discord.ButtonStyle.primary, row=0)

            async def choose(interaction, selected=card_name):
                await self.battle.choose_card(
                    interaction,
                    self.user_id,
                    self.turn,
                    selected,
                )

            button.callback = choose
            self.add_item(button)
        if total_pages > 1:
            previous = Button(label="이전", disabled=self.page == 0, row=1)
            counter = Button(label=f"{self.page + 1}/{total_pages}", disabled=True, row=1)
            following = Button(
                label="다음",
                disabled=self.page >= total_pages - 1,
                row=1,
            )

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

    def get_embed(self):
        start = self.page * CARD_PAGE_SIZE
        lines = []
        for card_name in self.cards[start:start + CARD_PAGE_SIZE]:
            card = get_card(card_name)
            lines.append(
                f"**{card_name}**\n{card.description if card else '효과 정보 없음'}"
            )
        return discord.Embed(
            title=f"🎴 길드 던전 커맨드 · {self.turn}턴",
            description="\n\n".join(lines),
            color=discord.Color.blurple(),
        )


class GuildDungeonBattleView(discord.ui.View):
    def __init__(self, run: GuildDungeonRun, monster, is_boss: bool):
        super().__init__(timeout=600)
        self.run = run
        self.monster = monster
        self.is_boss = is_boss
        self.turn = 1
        self.selected_cards: dict[int, str] = {}
        self.command_messages = {}
        self.logs: list[str] = []
        self.resolve_lock = asyncio.Lock()
        self.finished = False
        self.public_message = None
        self.shayla_triggers = {
            uid: False for uid in self.run.participants
        }

    def get_embed(self, message: str = ""):
        embed = discord.Embed(
            title=(
                f"👑 길드 던전 보스 · {self.run.depth}층"
                if self.is_boss
                else f"⚔️ 길드 던전 전투 · {self.run.depth}층"
            ),
            description=message,
            color=discord.Color.dark_red(),
        )
        embed.add_field(
            name=self.monster.name,
            value=f"❤️ {_bar(self.monster.current_hp, self.monster.max_hp, '🟥', '⬛', 15)}",
            inline=False,
        )
        for user_id, participant in self.run.participants.items():
            character = participant["char"]
            state = "💀 전투 불능"
            if character.current_hp > 0:
                state = "✅ 선택 완료" if user_id in self.selected_cards else "💭 선택 대기"
            embed.add_field(
                name=f"{participant['user'].display_name} · {character.name}",
                value=(
                    f"❤️ {max(0, character.current_hp)}/{character.max_hp}\n"
                    f"{state}"
                ),
                inline=True,
            )
        if self.logs:
            text = "\n".join(self.logs[-5:])
            embed.add_field(name="최근 전투 기록", value=text[-1000:], inline=False)
        embed.set_footer(text="각 참가자는 `내 커맨드 열기`에서 카드를 선택합니다.")
        return embed

    @discord.ui.button(label="내 커맨드 열기", style=discord.ButtonStyle.primary)
    async def open_command(self, interaction, button):
        participant = self.run.participants.get(interaction.user.id)
        if not participant:
            return await interaction.response.send_message(
                "전투 참가자가 아닙니다.",
                ephemeral=True,
            )
        if self.finished:
            return await interaction.response.send_message(
                "이미 끝난 전투입니다.",
                ephemeral=True,
            )
        if participant["char"].current_hp <= 0:
            return await interaction.response.send_message(
                "전투 불능 상태입니다.",
                ephemeral=True,
            )
        if interaction.user.id in self.selected_cards:
            return await interaction.response.send_message(
                "이번 턴의 카드를 이미 선택했습니다.",
                ephemeral=True,
            )
        view = GuildDungeonCardView(self, interaction.user.id, self.turn)
        await interaction.response.send_message(
            embed=view.get_embed(),
            view=view,
            ephemeral=True,
        )
        try:
            self.command_messages[interaction.user.id] = (
                await interaction.original_response()
            )
        except (discord.NotFound, discord.HTTPException):
            pass

    @discord.ui.button(label="원정 종료", style=discord.ButtonStyle.danger)
    async def stop_run(self, interaction, button):
        if interaction.user.id != self.run.host.id:
            return await interaction.response.send_message(
                "호스트만 원정을 종료할 수 있습니다.",
                ephemeral=True,
            )
        await interaction.response.defer()
        self.finished = True
        await self.run.finish(interaction, "호스트가 전투 중 원정을 종료했습니다.")
        await self.refresh_command_panels()

    async def choose_card(self, interaction, user_id: int, turn: int, card_name: str):
        should_resolve = False
        async with self.resolve_lock:
            if self.finished or self.run.finished:
                return await interaction.response.send_message(
                    "이미 끝난 전투입니다.",
                    ephemeral=True,
                )
            if turn != self.turn:
                return await interaction.response.send_message(
                    "이전 턴의 커맨드 창입니다.",
                    ephemeral=True,
                )
            if user_id in self.selected_cards:
                return await interaction.response.send_message(
                    "이번 턴의 카드를 이미 선택했습니다.",
                    ephemeral=True,
                )
            self.selected_cards[user_id] = card_name
            alive = self.run.living_ids()
            should_resolve = all(uid in self.selected_cards for uid in alive)
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"✅ {self.turn}턴 선택 완료",
                description=f"**{card_name}**을 선택했습니다.",
                color=discord.Color.green(),
            ),
            view=None,
        )
        if should_resolve:
            await self.resolve_turn(interaction)
        elif self.public_message:
            try:
                await self.public_message.edit(embed=self.get_embed(), view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    async def refresh_command_panels(self):
        for user_id, message in list(self.command_messages.items()):
            participant = self.run.participants.get(user_id)
            try:
                if self.finished or self.run.finished:
                    await message.edit(
                        embed=discord.Embed(
                            title="길드 던전 전투 종료",
                            description="커맨드 입력이 끝났습니다.",
                        ),
                        view=None,
                    )
                elif not participant or participant["char"].current_hp <= 0:
                    await message.edit(
                        embed=discord.Embed(
                            title="전투 불능",
                            description="이번 턴에는 행동할 수 없습니다.",
                        ),
                        view=None,
                    )
                else:
                    view = GuildDungeonCardView(self, user_id, self.turn)
                    await message.edit(embed=view.get_embed(), view=view)
            except (discord.NotFound, discord.HTTPException):
                self.command_messages.pop(user_id, None)

    def _tool_after_clash(self, participant, before_hp, before_enemy_hp, damage_enemy):
        character = participant["char"]
        item = participant.get("dungeon_item")
        notes = []
        if not item:
            return notes
        if (
            item.get("type") == "consumable"
            and item.get("effect") == "ignore_dmg"
            and character.current_hp < before_hp
            and int(item.get("remaining", 0) or 0) > 0
        ):
            prevented = before_hp - character.current_hp
            character.current_hp = before_hp
            item["remaining"] -= 1
            notes.append(f"{item['name']} 피해 {prevented} 무효")
        if item.get("type") == "passive" and item.get("effect") == "fixed_dmg":
            value = max(0, int(item.get("value", 0) or 0))
            self.monster.current_hp -= value
            notes.append(f"{item['name']} 추가 피해 {value}")
        if (
            item.get("type") == "passive"
            and item.get("effect") == "lifesteal"
            and damage_enemy > 0
        ):
            value = max(
                0,
                int(damage_enemy * int(item.get("value", 0) or 0) / 100),
            )
            before = character.current_hp
            character.current_hp = min(character.max_hp, character.current_hp + value)
            if character.current_hp > before:
                notes.append(f"{item['name']} HP +{character.current_hp - before}")
        if item.get("type") == "passive" and item.get("effect") == "hp_regen":
            value = max(0, int(item.get("value", 0) or 0))
            before = character.current_hp
            character.current_hp = min(character.max_hp, character.current_hp + value)
            if character.current_hp > before:
                notes.append(f"{item['name']} HP +{character.current_hp - before}")
        return notes

    def _try_revive(self, participant, effects):
        character = participant["char"]
        if character.current_hp > 0:
            return None
        if "immortality" in effects and not participant.get("revived"):
            participant["revived"] = True
            character.current_hp = character.max_hp
            gem_log = revive_gem_effects(character)
            return "불멸의 아티팩트로 부활" + (
                f" · {gem_log}" if gem_log else ""
            )
        item = participant.get("dungeon_item")
        if (
            item
            and item.get("type") == "consumable"
            and item.get("effect") == "revive"
            and int(item.get("remaining", 0) or 0) > 0
        ):
            item["remaining"] -= 1
            character.current_hp = character.max_hp
            return f"{item['name']}으로 부활"
        character.current_hp = 0
        return None

    async def resolve_turn(self, interaction):
        async with self.resolve_lock:
            if self.finished:
                return
            alive = self.run.living_ids()
            if not alive:
                self.finished = True
                await self.run.finish(
                    interaction,
                    "원정대가 전투에서 전멸했습니다.",
                    defeated=True,
                )
                return
            await self.run.advance_shared_turn(1)
            turn_logs = [f"--- {self.turn}턴 ---"]
            for user_id in alive:
                if self.monster.current_hp <= 0:
                    break
                participant = self.run.participants[user_id]
                character = participant["char"]
                card_name = self.selected_cards[user_id]
                user_card = get_card(card_name)
                monster_card = self.monster.decide_action() or get_card("기본공격")
                if not user_card or not monster_card:
                    continue

                gem_log = process_gem_turn_start(
                    character,
                    self.monster,
                    self.turn,
                    card_name,
                )
                user_result = user_card.use_card(
                    character.attack,
                    character.defense,
                    character.current_mental,
                )
                monster_result = monster_card.use_card(
                    self.monster.attack,
                    self.monster.defense,
                    self.monster.current_mental,
                )
                user_result = battle_engine.apply_stat_scaling(user_result, character)
                monster_result = battle_engine.apply_stat_scaling(
                    monster_result,
                    self.monster,
                )
                effects = _artifact_effects(character)
                artifact_log, trigger = battle_engine.process_turn_start_artifacts(
                    character,
                    self.monster,
                    user_result,
                    monster_result,
                    self.turn,
                    self.shayla_triggers.get(user_id, False),
                    card_name,
                )
                self.shayla_triggers[user_id] = trigger
                if "escalation" in effects:
                    apply_escalation_to_dice(character, user_result)
                if "ripple" in effects:
                    apply_ripple_to_dice(character, user_result, self.turn)

                before_hp = character.current_hp
                before_enemy_hp = self.monster.current_hp
                clash_log, _, damage_enemy = battle_engine.process_clash_loop(
                    character,
                    self.monster,
                    user_result,
                    monster_result,
                    effects,
                    [],
                    self.turn,
                )
                notes = self._tool_after_clash(
                    participant,
                    before_hp,
                    before_enemy_hp,
                    max(0, int(damage_enemy or before_enemy_hp - self.monster.current_hp)),
                )
                revive = self._try_revive(participant, effects)
                summary = f"**{participant['user'].display_name}** {card_name}{clash_log}"
                extras = [text for text in (gem_log, artifact_log, *notes, revive) if text]
                if extras:
                    summary += "\n" + " · ".join(extras)
                turn_logs.append(summary[-700:])

            self.logs.extend(turn_logs)
            if self.monster.current_hp <= 0:
                self.finished = True
                await self.run.after_battle_victory(
                    interaction,
                    self.monster,
                    self.is_boss,
                )
                await self.refresh_command_panels()
                self.stop()
                return
            if not self.run.living_ids():
                self.finished = True
                await self.run.finish(
                    interaction,
                    "원정대가 전투에서 전멸했습니다.",
                    defeated=True,
                )
                await self.refresh_command_panels()
                self.stop()
                return
            self.turn += 1
            self.selected_cards = {}

        if self.public_message:
            try:
                await self.public_message.edit(
                    embed=self.get_embed("다음 커맨드를 선택하세요."),
                    view=self,
                )
            except (discord.NotFound, discord.HTTPException):
                self.public_message = await interaction.channel.send(
                    embed=self.get_embed("다음 커맨드를 선택하세요."),
                    view=self,
                )
        await self.refresh_command_panels()

    async def on_timeout(self):
        if self.finished or self.run.finished:
            return
        self.finished = True
        if self.public_message:
            try:
                await self.public_message.edit(
                    content="입력이 없어 길드 던전 전투가 종료되었습니다.",
                    view=None,
                )
            except (discord.NotFound, discord.HTTPException):
                pass
        for user_id in self.run.participants:
            _ACTIVE_GUILD_DUNGEON_USERS.discard(int(user_id))
        await self.refresh_command_panels()
