# subjugation.py
import discord
import random
import asyncio
import uuid
from items import REGIONS, RARE_ITEMS, STAT_UP_ITEMS, ITEM_CATEGORIES
from monsters import spawn_monster, get_dungeon_boss
from battle import BattleView
from character import Character
from data_manager import get_user_data, get_subjugation_ranking, advance_world_turn
from trade import update_cafe_quest_progress
from decorators import auto_defer

SUBJUGATION_COST = 2000
_DUNGEON_LOCKS = {}
# guild-shared-turns-v8.6


def _dungeon_lock(user_id):
    lock = _DUNGEON_LOCKS.get(int(user_id))
    if lock is None:
        lock = asyncio.Lock()
        _DUNGEON_LOCKS[int(user_id)] = lock
    return lock

# ==================================================================================
# 4. Dungeon Item Logic (New)
# ==================================================================================
def generate_dungeon_item(depth):
    """던전 전용 아이템 생성 로직"""
    # 깊이에 따른 가중치 (후반부일수록 강력)
    tier = 1 + (depth // 30)
    multiplier = 1.0 + (depth * 0.05) 

    item_type = random.choice(["passive", "consumable", "stat"])
    
    item = {
        "name": "",
        "category": "dungeon",
        "type": item_type,
        "effect": "",
        "value": 0,
        "desc": "",
        "remaining": 0 # 소모성 횟수 or 지속 턴
    }

    if item_type == "passive":
        nouns = ["인형", "카드", "조각상", "조각", "종이학"]
        prefixes = [
            ("축복받은", "hp_regen", 5 * tier),   # 턴당 HP 회복
            ("공격적인", "fixed_dmg", 3 * tier),  # 턴당 고정 피해
            ("끈질긴", "lifesteal", 5 + (tier * 2)) # 흡혈 (%)
        ]
        prefix, effect, base_val = random.choice(prefixes)
        item["name"] = f"{prefix} {random.choice(nouns)}"
        item["effect"] = effect
        item["value"] = int(base_val * multiplier)
        
        if effect == "hp_regen": item["desc"] = f"턴 종료 시 HP {item['value']} 회복"
        elif effect == "fixed_dmg": item["desc"] = f"공격 시 고정 피해 {item['value']} 추가"
        elif effect == "lifesteal": item["desc"] = f"가한 피해의 {item['value']}% 흡혈"

    elif item_type == "consumable":
        nouns = ["토템", "완드", "검", "고서", "수정구"]
        prefixes = [
            ("부활의", "revive", 1), # 부활 횟수 (기본 1회 + 티어 보정 확률)
            ("회피의", "ignore_dmg", 1 + tier) # 피해 무시 횟수
        ]
        prefix, effect, base_count = random.choice(prefixes)
        
        # 부활은 너무 많이 나오면 안되므로 티어에 따라 확률적으로 횟수 증가
        if effect == "revive" and tier >= 3 and random.random() < 0.3:
            base_count += 1
            
        item["name"] = f"{prefix} {random.choice(nouns)}"
        item["effect"] = effect
        item["remaining"] = base_count
        item["value"] = base_count # 초기값 저장
        
        if effect == "revive": item["desc"] = f"사망 시 HP 100%로 부활 ({item['remaining']}회)"
        elif effect == "ignore_dmg": item["desc"] = f"받는 피해 0으로 무효화 ({item['remaining']}회)"

    elif item_type == "stat":
        stat_types = ["attack", "defense", "max_hp", "max_mental"]
        stat_map = {"attack": "공격력", "defense": "방어력", "max_hp": "체력", "max_mental": "정신력"}
        selected_stat = random.choice(stat_types)
        
        val = int(5 * tier * multiplier)
        if selected_stat in ["max_hp", "max_mental"]: val *= 5
        
        item["name"] = f"무적의 {stat_map[selected_stat]} 증강제"
        item["effect"] = "stat_up"
        item["stat"] = selected_stat
        item["value"] = val
        item["remaining"] = 30 # 30번 선택 동안 지속
        item["desc"] = f"{stat_map[selected_stat]} +{val} (30턴간 지속)"

    return item

class DungeonItemSwapView(discord.ui.View):
    """던전 아이템 교체 선택 뷰"""
    def __init__(self, author, dungeon_view, new_item):
        super().__init__(timeout=600)
        self.author = author
        self.dungeon_view = dungeon_view
        self.new_item = new_item
        self.current_item = dungeon_view.dungeon_item
        self.message = None

    @discord.ui.button(label="기존 아이템 유지", style=discord.ButtonStyle.secondary)
    async def keep_current(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer()
        await self.dungeon_view.show_main_screen(interaction, "기존 아이템을 유지하고 이동합니다.")

    @discord.ui.button(label="새 아이템으로 교체", style=discord.ButtonStyle.primary)
    async def swap_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer()
        
        # 스탯 아이템이었다면 기존 효과 제거
        if self.current_item and self.current_item["type"] == "stat":
            self.dungeon_view.remove_stat_item_effect()
            
        self.dungeon_view.dungeon_item = self.new_item
        
        # 새 아이템이 스탯 아이템이면 효과 즉시 적용
        if self.new_item["type"] == "stat":
            self.dungeon_view.apply_stat_item_effect()
            
        await self.dungeon_view.show_main_screen(interaction, f"[{self.new_item['name']}]을(를) 장착했습니다!")

    async def on_timeout(self):
        if self.dungeon_view:
            await self.dungeon_view.save_dungeon_state()
        if self.message:
            try: await self.message.edit(content="⌛ 시간 초과 (자동 저장됨)", view=None)
            except: pass

# ==================================================================================
# 3. Dungeon Item Use View (Existing)
# ==================================================================================
class DungeonItemUseView(discord.ui.View):
    """던전 내에서 아이템을 사용하기 위한 전용 뷰"""
    def __init__(self, author, user_data, save_func, char_index, dungeon_view, recovery_view):
        super().__init__(timeout=600)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.char_index = char_index
        self.dungeon_view = dungeon_view
        self.recovery_view = recovery_view
        
                
        self.item_page = 0
        self.PER_PAGE = 7
        self.message = None
        self.update_components()


    def update_components(self):
        self.clear_items()
        inv = self.user_data.get("inventory", {})
        valid_items = []
        
        for item_name, count in inv.items():
            if count <= 0: continue
            
            desc = ""
            is_usable = False
            
            stat_map = {"hp": "최대 체력", "max_hp": "최대 체력", "max_mental": "최대 정신력", "attack": "공격력", "defense": "방어력", "defense_rate": "방어율", "success_rate": "조사 성공률"}

            if item_name in STAT_UP_ITEMS:
                info = STAT_UP_ITEMS[item_name]
                if "duration" in info:
                    is_usable = True
                    s_name = stat_map.get(info.get("stat"), "능력치")
                    desc = f"{s_name} +{info.get('value', 0)} ({info.get('duration', 0)}회 지속)"
            elif item_name in ITEM_CATEGORIES:
                info = ITEM_CATEGORIES[item_name]
                if info.get("type") == "consumable" and info.get("effect") in ["hp", "mental"]:
                    is_usable = True
                    desc = f"{info.get('effect').upper()} {info.get('value')} 회복"
            
            if is_usable:
                valid_items.append((item_name, count, desc))

        total_pages = (len(valid_items) - 1) // self.PER_PAGE + 1 if valid_items else 1
        self.item_page = max(0, min(self.item_page, total_pages - 1))

        if not valid_items:
            self.add_item(discord.ui.Select(placeholder="사용 가능한 아이템 없음", disabled=True))
        else:
            start = self.item_page * self.PER_PAGE
            end = start + self.PER_PAGE
            current_items = valid_items[start:end]

            options = [discord.SelectOption(label=f"{name} ({count}개)", description=desc, value=name) for name, count, desc in current_items]
            select = discord.ui.Select(placeholder=f"아이템 선택 ({self.item_page+1}/{total_pages})", options=options)
            select.callback = self.on_item_select
            self.add_item(select)

        if total_pages > 1:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=3, disabled=(self.item_page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=3, disabled=(self.item_page == total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

        back_btn = discord.ui.Button(label="⬅️ 쉼터로 돌아가기", style=discord.ButtonStyle.gray, row=4)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

    async def on_item_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return
        item_name = interaction.data['values'][0]
        await interaction.response.defer()
        
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        char_data = self.user_data["characters"][self.char_index]
        inv = self.user_data["inventory"]
        
        if inv.get(item_name, 0) <= 0:
            return await interaction.followup.send("❌ 아이템이 부족합니다.", ephemeral=True)

        used = False
        
        if item_name in STAT_UP_ITEMS:
            info = STAT_UP_ITEMS[item_name]
            if "duration" in info:
                buffs = self.user_data.setdefault("buffs", {})
                buffs[item_name] = {"stat": info["stat"], "value": info["value"], "duration": info["duration"], "target": char_data["name"]}
                while len(buffs) > 2:
                    oldest_key = next(iter(buffs))
                    del buffs[oldest_key]
                used = True
        elif item_name in ITEM_CATEGORIES and ITEM_CATEGORIES[item_name].get("type") == "consumable":
            info = ITEM_CATEGORIES[item_name]
            eff, val = info.get("effect"), info.get("value", 0)
            # 던전 내에서는 던전 전용 스탯(증강제 등)이 포함된 max_hp를 기준으로 회복 제한
            if eff == "hp":
                char_data["current_hp"] = min(self.dungeon_view.player.max_hp, char_data["current_hp"] + val)
                used = True
            elif eff == "mental":
                char_data["current_mental"] = min(self.dungeon_view.player.max_mental, char_data["current_mental"] + val)
                used = True

        if used:
            inv[item_name] -= 1
            if inv[item_name] <= 0: del inv[item_name]
            await self.save_func(self.author.id, self.user_data)
            self.update_components()
            
            # 던전 뷰의 플레이어 객체 상태 동기화
            self.dungeon_view.player.current_hp = char_data["current_hp"]
            self.dungeon_view.player.current_mental = char_data["current_mental"]
            
            embed = discord.Embed(title=f"✅ {item_name} 사용 완료", color=discord.Color.green())
            embed.add_field(name="현재 상태", value=f"❤️ HP: {char_data['current_hp']}/{char_data['hp']}\n🧠 멘탈: {char_data['current_mental']}/{char_data['max_mental']}")
            
            await interaction.edit_original_response(content=None, embed=embed, view=self)
        else:
            await interaction.followup.send("❌ 던전에서 사용할 수 없는 아이템입니다.", ephemeral=True)

    async def prev_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer()
        self.item_page -= 1
        self.update_components()
        await interaction.edit_original_response(view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer()
        self.item_page += 1
        self.update_components()
        await interaction.edit_original_response(view=self)

    async def go_back(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer()
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        self.dungeon_view.user_data = self.user_data
        self.recovery_view.user_data = self.user_data
        
        new_char_data = self.user_data["characters"][self.dungeon_view.char_index]
        self.dungeon_view.player = Character.from_dict(new_char_data)
        self.dungeon_view.apply_stat_item_effect() # 던전 전용 스탯 아이템 효과 재적용

        await interaction.edit_original_response(embed=self.recovery_view.get_embed(), view=self.recovery_view)

    async def on_timeout(self):
        if self.dungeon_view:
            await self.dungeon_view.save_dungeon_state()
        if self.message:
            try: await self.message.edit(content="⌛ 시간 초과 (자동 저장됨)", view=None)
            except: pass

# ==================================================================================
# 2. Dungeon Core Views
# ==================================================================================
class DungeonRecoveryView(discord.ui.View):
    """던전 내 회복방 뷰"""
    def __init__(self, author, user_data, save_func, dungeon_view):
        super().__init__(timeout=600)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.dungeon_view = dungeon_view
        self.message = None

    def get_embed(self):
        return discord.Embed(title="쉼터", description="안전한 공간을 발견했습니다. 잠시 정비할 수 있습니다.", color=discord.Color.green())

    @discord.ui.button(label="🔧 정비 (아이템 사용)", style=discord.ButtonStyle.primary)
    async def use_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer()
        char_data = self.user_data["characters"][self.dungeon_view.char_index]
        char_data["current_hp"] = self.dungeon_view.player.current_hp
        char_data["current_mental"] = self.dungeon_view.player.current_mental
        await self.save_func(self.author.id, self.user_data)
        
        view = DungeonItemUseView(self.author, self.user_data, self.save_func, self.dungeon_view.char_index, self.dungeon_view, self)
        msg = await interaction.edit_original_response(content="사용할 아이템을 선택하세요.", embed=None, view=view)
        view.message = msg


    @discord.ui.button(label="▶️ 탐사 계속하기", style=discord.ButtonStyle.success)
    async def continue_dungeon(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer()
        await self.dungeon_view.show_main_screen(interaction, "회복을 마치고 다시 탐사를 시작합니다.")

    @discord.ui.button(label="🚪 던전 나가기", style=discord.ButtonStyle.danger)
    async def exit_dungeon(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer()
        await self.dungeon_view.end_dungeon(interaction, "탐사를 중단하고 던전에서 나왔습니다.")

    async def on_timeout(self):
        if self.dungeon_view:
            await self.dungeon_view.save_dungeon_state()
        if self.message:
            try: await self.message.edit(content="⌛ 시간 초과 (자동 저장됨)", view=None)
            except: pass

class BossEncounterView(discord.ui.View):
    """보스 조우 시 정보를 보여주는 뷰"""
    def __init__(self, author, dungeon_view, boss, extra_msg=""):
        super().__init__(timeout=600)
        self.author = author
        self.dungeon_view = dungeon_view
        self.boss = boss
        self.extra_msg = extra_msg
        self.message = None

    def get_embed(self):
        embed = discord.Embed(title=f"☠️ 보스 출현: {self.boss.name}", description=self.boss.description, color=discord.Color.dark_red())
        embed.add_field(name="정보", value=f"❤️ HP: {self.boss.max_hp}\n⚔️ 공격력: {self.boss.attack}\n🛡️ 방어력: {self.boss.defense}", inline=False)
        if self.extra_msg:
            embed.add_field(name="⚠️ 알림", value=self.extra_msg, inline=False)
        embed.set_footer(text="준비가 되었다면 전투를 시작하세요.")
        return embed

    @discord.ui.button(label="⚔️ 전투 시작", style=discord.ButtonStyle.danger)
    async def start_battle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer()
        await self.dungeon_view.start_boss_battle(interaction, self.boss)

    async def on_timeout(self):
        if self.dungeon_view:
            await self.dungeon_view.save_dungeon_state()
        if self.message:
            try: await self.message.edit(content="⌛ 시간 초과 (자동 저장됨)", view=None)
            except: pass

class DungeonMainView(discord.ui.View):
    """던전 탐사 메인 뷰"""
    def __init__(self, author=None, user_data=None, save_func=None, char_index=0, region_name="", timeout=None):
        super().__init__(timeout=timeout)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.char_index = char_index
        self.region_name = region_name
        
        self.choices = []
        self.dungeon_item = None # 현재 소지한 던전 전용 아이템
        self.forced_next_room = None # 보스 클리어 후 아이템 방 확정용
        self.pending_room = None
        self.choice_token = uuid.uuid4().hex
        self.stat_item_applied = False
        self._ending = False
        self.message = None

        if user_data:
            # 기존 진행 데이터가 있다면 로드, 없으면 초기화
            state = user_data.get("current_dungeon", {})
            self.depth = state.get("depth", 0)
            self.world_turns_counted = int(state.get("world_turns_counted", 0) or 0)
            self.accumulated_loot = state.get("loot", {"items": {}, "money": 0, "pt": 0})
            self.choices = state.get("choices", [])
            self.dungeon_item = state.get("dungeon_item")
            self.forced_next_room = state.get("forced_next_room")
            self.pending_room = state.get("pending_room")
            self.choice_token = state.get("choice_token") or uuid.uuid4().hex
            self.region_name = state.get("region", region_name)
            self.char_index = state.get("char_index", char_index)

            if not (0 <= self.char_index < len(user_data.get("characters", []))):
                self.char_index = 0
            player_data = state.get("player_state") or user_data["characters"][self.char_index]
            self.player = Character.from_dict(player_data)
            if "equipped_engraved_artifact" in user_data["characters"][self.char_index]:
                self.player.equipped_engraved_artifact = user_data["characters"][self.char_index]["equipped_engraved_artifact"]
            self.stat_item_applied = bool(state.get("stat_item_applied", False))
            if self.dungeon_item and self.dungeon_item.get("type") == "stat" and not self.stat_item_applied:
                self.apply_stat_item_effect()
        else:
            self.depth = 0
            self.world_turns_counted = 0
            self.accumulated_loot = {"items": {}, "money": 0, "pt": 0}
            self.player = None
            
            # [신규] 지속성 뷰 등록을 위한 더미 버튼 추가 (선택지 1~3)
            for i in range(3):
                btn = discord.ui.Button(label=f"선택 {i+1}", custom_id=f"dungeon:choice:{i}")
                btn.callback = self.make_choice_callback(i)
                self.add_item(btn)

    async def save_dungeon_state(self):
        """현재 던전 진행 상태를 DB에 동기화"""
        if not self.user_data: return
        player_state = self.player.to_dict() if self.player else None
        if (
            player_state
            and self.stat_item_applied
            and self.dungeon_item
            and self.dungeon_item.get("type") == "stat"
        ):
            stat = self.dungeon_item.get("stat")
            value = int(self.dungeon_item.get("value", 0))
            if stat in {"attack", "defense"}:
                player_state[stat] = max(1, int(player_state.get(stat, 1)) - value)
            elif stat == "max_hp":
                player_state["current_hp"] = max(1, int(player_state.get("current_hp", 1)) - value)
            elif stat == "max_mental":
                player_state["current_mental"] = max(0, int(player_state.get("current_mental", 0)) - value)
        self.user_data["current_dungeon"] = {
            "depth": self.depth, "loot": self.accumulated_loot,
            "world_turns_counted": self.world_turns_counted,
            "choices": self.choices, "dungeon_item": self.dungeon_item,
            "region": self.region_name, "char_index": self.char_index,
            "forced_next_room": self.forced_next_room,
            "pending_room": self.pending_room,
            "choice_token": self.choice_token,
            # player_state is stored without the temporary stat item, then reapplied once on load.
            "stat_item_applied": False,
            "player_state": player_state,
        }
        await self.save_func(self.author.id, self.user_data)

    def apply_stat_item_effect(self):
        """스탯 아이템 효과 적용"""
        if self.dungeon_item and self.dungeon_item["type"] == "stat" and not self.stat_item_applied:
            stat = self.dungeon_item["stat"]
            val = self.dungeon_item["value"]
            curr_val = getattr(self.player, stat)
            setattr(self.player, stat, curr_val + val)
            if stat in ["max_hp", "max_mental"]:
                curr_curr = getattr(self.player, "current_" + stat.split("_")[1])
                setattr(self.player, "current_" + stat.split("_")[1], curr_curr + val)
            self.stat_item_applied = True

    def remove_stat_item_effect(self):
        """스탯 아이템 효과 제거"""
        if self.dungeon_item and self.dungeon_item["type"] == "stat" and self.stat_item_applied:
            stat = self.dungeon_item["stat"]
            val = self.dungeon_item["value"]
            curr_val = getattr(self.player, stat)
            setattr(self.player, stat, max(1, curr_val - val)) # 0 이하 방지
            if stat in ["max_hp", "max_mental"]:
                current_name = "current_" + stat.split("_")[1]
                setattr(self.player, current_name, min(getattr(self.player, current_name), getattr(self.player, stat)))
            self.stat_item_applied = False

    async def show_main_screen(self, interaction: discord.Interaction, message: str, refresh_choices=True):
        if refresh_choices or not self.choices:
            self.setup_choices()
        else:
            self.render_choice_buttons()
        
        # [중요] 선택지가 생성된 시점에 즉시 DB 저장 (재시작 대비)
        if self.user_data:
            await self.save_dungeon_state()

        embed = self.create_embed(message)
        
        if interaction.response.is_done():
            self.message = await interaction.edit_original_response(content=None, embed=embed, view=self)
        else:
            await interaction.response.edit_message(content=None, embed=embed, view=self)
            self.message = await interaction.original_response()

    def create_embed(self, description: str):
        embed = discord.Embed(title=f"⛓️ {self.region_name} 던전", description=description, color=discord.Color.dark_purple())
        embed.add_field(name="탐사 정보", value=f"현재 깊이: {self.depth}층", inline=True)
        embed.add_field(name="캐릭터", value=f"{self.player.name}", inline=True)
        
        hp_bar = "🟩" * int(self.player.current_hp / self.player.max_hp * 10) + "⬛" * (10 - int(self.player.current_hp / self.player.max_hp * 10))
        mental_bar = "🟦" * int(self.player.current_mental / self.player.max_mental * 10) + "⬛" * (10 - int(self.player.current_mental / self.player.max_mental * 10))
        embed.add_field(name="상태", value=f"❤️ HP: {hp_bar} ({self.player.current_hp}/{self.player.max_hp})\n🧠 멘탈: {mental_bar} ({self.player.current_mental}/{self.player.max_mental})", inline=False)
        
        # 던전 아이템 정보 표시
        if self.dungeon_item:
            d_item = self.dungeon_item
            info_str = f"**{d_item['name']}**\n{d_item['desc']}"
            if d_item['type'] == 'consumable': info_str += f"\n(남은 횟수: {d_item['remaining']}회)"
            elif d_item['type'] == 'stat': info_str += f"\n(남은 턴: {d_item['remaining']}회)"
            embed.add_field(name="🎒 던전 전용 아이템", value=info_str, inline=False)

        choice_texts = {"monster": "불길한 기운이 느껴진다.", "item": "반짝거림이 보인다.", "recovery": "고요하다.", "boss": "압도적인 살기가 느껴진다!!"}
        choices_str = [f"{i+1}. {choice_texts[c]}" for i, c in enumerate(self.choices)]
        embed.add_field(name="선택지", value="\n".join(choices_str), inline=False)
        return embed

    @discord.ui.button(label="🚪 잠시 나가기", style=discord.ButtonStyle.gray, row=2, custom_id="dungeon:temp_exit")
    @auto_defer(reload_data=True)
    async def temp_exit(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 데이터 재로드 및 객체 복구 (지속성 뷰 대응)
        state = self.user_data.get("current_dungeon", {})
        if not state:
            return await interaction.edit_original_response(content="❌ 저장할 던전 정보가 없습니다.", embed=None, view=None)

        active_view = DungeonMainView(self.author, self.user_data, self.save_func)
        await active_view.save_dungeon_state()
        await interaction.edit_original_response(content="💾 던전 진행 상황이 저장되었습니다. 나중에 '이어하기'를 통해 계속할 수 있습니다.", embed=None, view=None)

    def setup_choices(self):
        # 보스 확정 로직 (29, 59, 89...)
        next_step = self.depth 
        
        # 확정된 다음 방 (보스 클리어 후 아이템방)
        if self.forced_next_room:
            self.choices = [self.forced_next_room]
            self.forced_next_room = None
        # 보스방 체크 (29, 59, 89, 119...)
        elif next_step == 29 or next_step == 59 or next_step >= 89 and (next_step + 1) % 30 == 0:
            self.choices = ["boss"]
        else:
            self.choices = random.choices(["monster", "recovery", "item"], weights=[40, 35, 25], k=3)
        self.choice_token = uuid.uuid4().hex
        self.render_choice_buttons()

    def render_choice_buttons(self):
        self.clear_items()
        for i, choice_type in enumerate(self.choices):
            style = discord.ButtonStyle.secondary
            if choice_type == "boss": style = discord.ButtonStyle.danger
            elif choice_type == "item" and len(self.choices) == 1: style = discord.ButtonStyle.success # 보스 클리어 보상
            
            # 지속성 뷰를 위해 custom_id 부여
            btn = discord.ui.Button(label=f"선택 {i+1}", style=style, custom_id=f"dungeon:choice:{i}")
            btn.callback = self.make_choice_callback(i)
            self.add_item(btn)
            
        # 잠시 나가기 버튼 유지
        self.add_item(self.temp_exit)

    def make_choice_callback(self, choice_idx):
        async def callback(interaction: discord.Interaction):
            if self.author and interaction.user.id != self.author.id:
                return await interaction.response.send_message("❌ 본인의 던전만 조작할 수 있습니다.", ephemeral=True)
            lock = _dungeon_lock(interaction.user.id)
            if lock.locked():
                return await interaction.response.send_message("⏳ 이전 던전 행동을 처리 중입니다.", ephemeral=True)
            await interaction.response.defer()
            async with lock:
                user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
                state = user_data.get("current_dungeon") or {}
                if not state:
                    return await interaction.followup.send("❌ 진행 중인 던전 정보가 없습니다.", ephemeral=True)
                expected_token = self.choice_token if self.player is not None else state.get("choice_token")
                if expected_token and state.get("choice_token") != expected_token:
                    return await interaction.followup.send("♻️ 이미 처리된 선택지입니다. 최신 던전 화면에서 계속해주세요.", ephemeral=True)
                active_view = DungeonMainView(interaction.user, user_data, self.save_func)
                await active_view.process_choice(interaction, choice_idx)
                # The action has now been handed to a freshly loaded view. Stop
                # the previous in-memory view after the handoff succeeds.
                self.stop()
        return callback

    async def process_choice(self, interaction, choice_idx):
        if not interaction.response.is_done():
            await interaction.response.defer()
        
        if choice_idx >= len(self.choices):
             return await interaction.followup.send("❌ 유효하지 않은 선택입니다.", ephemeral=True)

        choice_type = self.choices[choice_idx]
        is_forced_item = len(self.choices) == 1 and choice_type == "item"
        # Old active runs did not store per-room shared turns. Credit any rooms
        # already traversed once, then count this newly selected room.
        uncounted_rooms = max(0, int(self.depth) - int(self.world_turns_counted))
        advance_world_turn(self.user_data, uncounted_rooms + 1)
        self.depth += 1
        self.world_turns_counted = self.depth
        self.choices = []
        self.choice_token = uuid.uuid4().hex
        
        # [신규] 실시간 랭킹 반영: 최고 기록 경신 시 즉시 저장
        myhome = self.user_data.setdefault("myhome", {})
        if self.depth > myhome.get("max_subjugation_depth", 0):
            myhome["max_subjugation_depth"] = self.depth
            myhome["max_subjugation_char"] = self.player.name
            myhome["max_subjugation_region"] = self.region_name
        
        # 스탯 아이템 지속시간 차감
        if self.dungeon_item and self.dungeon_item["type"] == "stat":
            self.dungeon_item["remaining"] -= 1
            if self.dungeon_item["remaining"] <= 0:
                self.remove_stat_item_effect()
                expired_name = self.dungeon_item["name"]
                self.dungeon_item = None
                await interaction.channel.send(f"📉 **{expired_name}**의 효과가 사라졌습니다.")

        # 방 진입 전 5% 확률 랜덤 디버프 (3스택)
        debuff_msg = ""
        if random.random() < 0.05:
            debuff = random.choice(["bleed", "paralysis"])
            self.player.status_effects[debuff] = self.player.status_effects.get(debuff, 0) + 3
            d_name = "출혈" if debuff == "bleed" else "마비"
            debuff_msg = f"\n⚠️ **함정 발동!** {d_name} 상태가 되었습니다. (3스택)"

        # 보스방/확정방은 주사위 굴림 없이 확정 진입
        if choice_type == "boss":
            self.pending_room = "boss"
            await self.save_dungeon_state()
            await self.enter_boss_room(interaction, debuff_msg)
            return
        elif is_forced_item: # 확정된 아이템방
            self.pending_room = None
            await self.save_dungeon_state()
            await self.enter_item_room(interaction, debuff_msg)
            return

        roll = random.random()
        room_map = {"monster": 0.7, "item": 0.7, "recovery": 0.7}
        other_choices = [c for c in room_map if c != choice_type]
        
        actual_room = choice_type if roll < room_map[choice_type] else random.choice(other_choices)
        self.pending_room = actual_room if actual_room == "monster" else None
        await self.save_dungeon_state()

        if actual_room == "monster": await self.enter_monster_room(interaction, debuff_msg)
        elif actual_room == "item": await self.enter_item_room(interaction, debuff_msg)
        else: await self.enter_recovery_room(interaction, debuff_msg)

    async def on_timeout(self):
        # Every valid room action is saved immediately. Writing the snapshot
        # again from an old timed-out view can trigger StaleUserDataError and
        # may remove the buttons from the user's current dungeon message.
        self.stop()

    def apply_monster_buffs(self, monsters, is_boss=False):
        buff_sets = self.depth // 10
        
        # 119번째 이후 보스 (2번째 3단계 보스)부터 추가 강화
        if is_boss and self.depth >= 119:
            buff_sets += (self.depth - 89) // 10 # 추가 보정
            
        if buff_sets > 0:
            for m in monsters:
                m.attack += buff_sets
                m.defense += buff_sets
                m.max_hp += buff_sets * 10
                m.current_hp += buff_sets * 10

    async def enter_boss_room(self, interaction: discord.Interaction, extra_msg=""):
        # [수정] monsters.py의 get_dungeon_boss 함수를 사용하여 보스 로드
        boss = get_dungeon_boss(self.region_name, self.depth)
        
        # get_dungeon_boss 내부에서 이미 기본 스케일링이 되었으나, 추가 버프 적용 가능
        self.apply_monster_buffs([boss], is_boss=True)

        view = BossEncounterView(self.author, self, boss, extra_msg)
        if interaction.response.is_done():
            view.message = await interaction.edit_original_response(embed=view.get_embed(), view=view)
        else:
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
            view.message = await interaction.original_response()

    async def start_boss_battle(self, interaction: discord.Interaction, boss):
        monsters = [boss]
        
        # [수정] 아티팩트 정보 강제 동기화 (특수 효과 미적용 방지)
        self.player.equipped_artifact = self.user_data["characters"][self.char_index].get("equipped_artifact")
        self.player.equipped_engraved_artifact = self.user_data["characters"][self.char_index].get("equipped_engraved_artifact")
            
        # [수정] 전투 시작 시에만 아티팩트 수치 적용
        self.player.apply_battle_start_buffs()

        async def on_victory(i, battle_results):
            self.player.current_hp = battle_results.get("player_hp", self.player.current_hp)
            self.player.current_mental = battle_results.get("player_mental", self.player.current_mental)
            self.accumulated_loot["money"] += battle_results.get("money", 0)
            self.accumulated_loot["pt"] += battle_results.get("pt", 0)
            
            self.forced_next_room = "item" # 보스 클리어 후 아이템방 확정
            self.pending_room = None
            await self.show_main_screen(i, f"🎉 {boss.name} 처치 완료! 보상 방이 열렸습니다.")

        async def on_defeat(i):
            await self.end_dungeon(i, f"{boss.name}에게 패배하여 쫓겨났습니다...", is_fail=True)

        view = BattleView(
            self.author, self.player, monsters, self.user_data, self.save_func,
            char_index=self.char_index, 
            victory_callback=on_victory, 
            defeat_callback=on_defeat, 
            is_dungeon_run=True,
            dungeon_item=self.dungeon_item, # 던전 아이템 전달
            timeout_callback=self.save_dungeon_state,
        )
        embed = discord.Embed(title=f"⚔️ {boss.name} 교전 개시!", description="전투가 시작됩니다!", color=discord.Color.dark_red())
        
        if interaction.response.is_done():
            view.message = await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)
            view.message = await interaction.original_response()

    async def enter_monster_room(self, interaction: discord.Interaction, extra_msg=""):
        monster_pool = self.get_monster_pool(self.region_name)
        monsters = [spawn_monster(random.choice(monster_pool)) for _ in range(random.randint(1, 3))]
        for i, m in enumerate(monsters):
            if len(monsters) > 1: m.name = f"{m.name} {chr(65+i)}"

        # [수정] 아티팩트 정보 강제 동기화 (특수 효과 미적용 방지)
        self.player.equipped_artifact = self.user_data["characters"][self.char_index].get("equipped_artifact")
        self.player.equipped_engraved_artifact = self.user_data["characters"][self.char_index].get("equipped_engraved_artifact")

        # [수정] 전투 시작 시에만 아티팩트 수치 적용
        self.player.apply_battle_start_buffs()

        self.apply_monster_buffs(monsters)

        async def on_victory(i, battle_results):
            self.player.current_hp = battle_results.get("player_hp", self.player.current_hp)
            self.player.current_mental = battle_results.get("player_mental", self.player.current_mental)
            for item, qty in battle_results.get("items", {}).items():
                self.accumulated_loot["items"][item] = self.accumulated_loot["items"].get(item, 0) + qty
            self.accumulated_loot["money"] += battle_results.get("money", 0)
            self.accumulated_loot["pt"] += battle_results.get("pt", 0)
            self.pending_room = None
            await self.show_main_screen(i, "전투에서 승리했습니다! 다음 선택지로 이동합니다.")

        async def on_defeat(i):
            await self.end_dungeon(i, "전투에서 패배하여 던전에서 쫓겨났습니다...", is_fail=True)

        view = BattleView(
            self.author, self.player, monsters, self.user_data, self.save_func,
            char_index=self.char_index, 
            victory_callback=on_victory, 
            defeat_callback=on_defeat, 
            is_dungeon_run=True,
            dungeon_item=self.dungeon_item,
            timeout_callback=self.save_dungeon_state,
        )
        embed = discord.Embed(title="⚔️ 몬스터 출현!", description=f"{len(monsters)}마리의 몬스터와 조우했습니다!{extra_msg}", color=discord.Color.red())
        
        if interaction.response.is_done():
            view.message = await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)
            view.message = await interaction.original_response()

    async def enter_item_room(self, interaction: discord.Interaction, extra_msg=""):
        # 일반 전리품 획득
        loot = self.calculate_item_room_loot()
        for item, qty in loot.items():
            self.accumulated_loot["items"][item] = self.accumulated_loot["items"].get(item, 0) + qty
        loot_str = "\n".join([f"획득: {item} x{qty}" for item, qty in loot.items()])
        
        # 던전 전용 아이템 생성
        new_d_item = generate_dungeon_item(self.depth)
        
        embed = discord.Embed(title="💎 보물 발견!", description=f"상자를 열어 아이템을 획득했습니다.\n\n{loot_str}{extra_msg}", color=discord.Color.gold())
        embed.add_field(name="🆕 발견한 던전 아이템", value=f"**{new_d_item['name']}**\n{new_d_item['desc']}", inline=False)
        
        if self.dungeon_item:
            embed.add_field(name="🎒 현재 소지 아이템", value=f"**{self.dungeon_item['name']}**\n{self.dungeon_item['desc']}", inline=False)
            embed.set_footer(text="던전 아이템은 하나만 소지할 수 있습니다.")
            view = DungeonItemSwapView(self.author, self, new_d_item)
        else:
            # 아이템이 없으면 자동 획득
            self.dungeon_item = new_d_item
            if new_d_item["type"] == "stat": self.apply_stat_item_effect()
            embed.set_footer(text=f"{new_d_item['name']}을(를) 획득했습니다!")
            
            view = discord.ui.View(timeout=180)
            continue_btn = discord.ui.Button(label="▶️ 탐사 계속하기", style=discord.ButtonStyle.success)
            async def continue_cb(i):
                if i.user.id != self.author.id: return
                await i.response.defer()
                await self.show_main_screen(i, "보물을 챙기고 다음으로 나아갑니다.")
            continue_btn.callback = continue_cb
            view.add_item(continue_btn)
        
        if interaction.response.is_done():
            msg = await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)
            msg = await interaction.original_response()
        if hasattr(view, 'message'): view.message = msg

    def calculate_item_room_loot(self):
        loot = {}
        if self.depth < 30:
            item_type, qty, rare_qty = random.choice(["낡은 보물상자", "낡은 열쇠"]), 10, 1
        elif self.depth < 60:
            item_type, qty, rare_qty = random.choice(["섬세한 보물상자", "섬세한 열쇠"]), 10, 3
        else:
            item_type, qty, rare_qty = random.choice(["깔끔한 보물상자", "깔끔한 열쇠"]), 10, 5
        
        region_rares = REGIONS.get(self.region_name, {}).get("rare", ["사랑나무 가지"])
        rare_item = random.choice(region_rares)

        bonus_item, bonus_qty = None, 0
        if self.region_name == "시간의 신전": qty += 5; bonus_item, bonus_qty = "하급 마력석", 2
        elif self.region_name == "일한산 중턱": qty += 5; bonus_item, bonus_qty = "천년얼음", 3
        elif self.region_name == "이루지 못한 꿈들의 별": qty += 7; bonus_item, bonus_qty = "별모양 별", 3
        elif self.region_name == "생명의 숲": qty += 7; bonus_item, bonus_qty = "뒤틀린 씨앗", 3
        elif self.region_name == "아르카워드 제도": qty += 10; bonus_item, bonus_qty = "부유석", 5
            
        loot[item_type] = qty
        loot[rare_item] = rare_qty
        if bonus_item: loot[bonus_item] = loot.get(bonus_item, 0) + bonus_qty
        return loot

    async def enter_recovery_room(self, interaction: discord.Interaction, extra_msg=""):
        view = DungeonRecoveryView(self.author, self.user_data, self.save_func, self)
        embed = view.get_embed()
        if extra_msg: embed.description += extra_msg
        
        if interaction.response.is_done():
            view.message = await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=embed, view=view)
            view.message = await interaction.original_response()

    async def end_dungeon(self, interaction: discord.Interaction, message: str, is_fail=False):
        if self._ending:
            if not interaction.response.is_done():
                await interaction.response.send_message("이미 던전 종료를 처리하고 있습니다.", ephemeral=True)
            return
        self._ending = True
        inv = self.user_data.setdefault("inventory", {})
        for item, qty in self.accumulated_loot["items"].items():
            inv[item] = inv.get(item, 0) + qty
        self.user_data["money"] += self.accumulated_loot["money"]
        self.user_data["pt"] += self.accumulated_loot["pt"]

        if hasattr(self.player, "remove_battle_buffs"):
            self.player.remove_battle_buffs()
        
        # 스탯 아이템 효과 제거 (저장 전)
        self.remove_stat_item_effect()

        self.user_data["characters"][self.char_index] = self.player.to_dict()
        if is_fail:
             self.user_data["characters"][self.char_index]["current_hp"] = 1

        myhome = self.user_data.setdefault("myhome", {})
        myhome["total_subjugations"] = myhome.get("total_subjugations", 0) + self.depth
        # Per-room turns are normally credited immediately. This fallback
        # covers an old active dungeon that is ended before another choice.
        uncounted_rooms = max(0, int(self.depth) - int(self.world_turns_counted))
        if uncounted_rooms:
            advance_world_turn(self.user_data, uncounted_rooms)
            self.world_turns_counted = self.depth
        if self.depth > myhome.get("max_subjugation_depth", 0):
            myhome["max_subjugation_depth"] = self.depth
            myhome["max_subjugation_char"] = self.player.name
            myhome["max_subjugation_region"] = self.region_name
            
        # [신규] 카페 의뢰 퀘스트 업데이트 (던전 층수)
        await update_cafe_quest_progress(interaction.user.id, self.user_data, self.save_func, "dungeon", self.depth)

        # [신규] 진행 중인 던전 정보 삭제 (데이터 누적 방지)
        self.user_data.pop("current_dungeon", None)

        await self.save_func(self.author.id, self.user_data)

        color = discord.Color.red() if is_fail else discord.Color.green()
        embed = discord.Embed(title="🏰 던전 탐사 종료", description=message, color=color)
        embed.add_field(name="최종 깊이", value=f"{self.depth}층", inline=False)
        loot_lines = [f"{item} x{qty}" for item, qty in self.accumulated_loot["items"].items()]
        loot_str = "\n".join(loot_lines) or "없음"
        if len(loot_str) > 1000:
            shown = []
            length = 0
            for line in loot_lines:
                if length + len(line) + 1 > 960:
                    break
                shown.append(line)
                length += len(line) + 1
            loot_str = "\n".join(shown) + f"\n… 외 {len(loot_lines) - len(shown)}종"
        embed.add_field(name="획득 아이템", value=loot_str, inline=False)
        if self.accumulated_loot["money"] > 0 or self.accumulated_loot["pt"] > 0:
            embed.add_field(name="추가 획득", value=f"💰 {self.accumulated_loot['money']}원\n⚡ {self.accumulated_loot['pt']}pt", inline=False)
        
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=None)
        else:
            await interaction.response.edit_message(embed=embed, view=None)

    def get_monster_pool(self, region_name):
        unlocked = self.user_data.get("unlocked_regions", [])
        pool = {"기원의 쌍성": ["길 잃은 바람비", "약한 원념", "커다란 별기구"], "시간의 신전": ["눈 감은 원념", "약한 원념"],
                "일한산 중턱": ["굴레늑대", "얼어붙은 원념", "경계꽃 골렘"], "이루지 못한 꿈들의 별": ["몽상행인", "살아난 발상", "구체화된 악몽"],
                "생명의 숲": ["뒤틀린 식충식물", "굶주린 포식자", "아름다운 나비"], "아르카워드 제도": ["아사한 원념", "변질된 바람", "폐허를 지키는 문지기"],
                "공간의 신전": ["취한 파티원", "겁쟁이 원념", "폭주 거대 짤똥이"]}
        
        base_pool = pool.get(region_name, ["약한 원념"])
        if region_name == "기원의 쌍성" and "시간의 신전" in unlocked: base_pool.extend(["주신의 눈물방울", "예민한 집요정"])
        if region_name == "시간의 신전" and "일한산 중턱" in unlocked: base_pool.extend(["시간의 방랑자", "과거의 망집"])
        if region_name == "일한산 중턱" and "이루지 못한 꿈들의 별" in unlocked: base_pool.extend(["굴레늑대 우두머리", "은하새"])
        if region_name == "생명의 숲" and "아르카워드 제도" in unlocked: base_pool.extend(["냉혹한 원념", "사나운 은하새"])
        return base_pool

# ==================================================================================
# 1. Entry Point View (Existing)
# ==================================================================================
class SubjugationRegionView(discord.ui.View):
    def __init__(self, author, p_data, save_func, timeout=600):
        super().__init__(timeout=timeout)
        self.author = author
        self.p_data = p_data        
        self.save_func = save_func
        self.selected_char_index = 0
        self.add_character_select()
        self.add_region_select()
        
        # [수정] 데이터가 있고(실제 뷰) 진행 중인 던전이 없을 때만 버튼 제거
        # 데이터가 없으면(등록 시점) 버튼을 유지하여 핸들러 등록
        if p_data and not p_data.get("current_dungeon"):
            self.remove_item(self.continue_btn)


    def add_character_select(self):
        char_list = self.p_data.get("characters", []) if self.p_data else []
        if not char_list: return
        options = []
        for i, c in enumerate(char_list):
            label = c.get("name", f"캐릭터 {i+1}")
            desc = f"HP: {c.get('hp')} | 공격력: {c.get('attack')}"
            options.append(discord.SelectOption(label=label, description=desc, value=str(i), default=(i == self.selected_char_index)))
        select = discord.ui.Select(placeholder="던전을 탐색할 캐릭터 선택", options=options, row=0, custom_id="dungeon:char_sel")
        select.callback = self.char_select_callback
        self.add_item(select)

    def add_region_select(self):
        unlocked = self.p_data.get("unlocked_regions", ["기원의 쌍성"]) if self.p_data else ["기원의 쌍성"]
        options = []
        region_order = list(REGIONS.keys())
        sorted_regions = sorted(unlocked, key=lambda x: region_order.index(x) if x in region_order else 999)

        for name in sorted_regions:
            if name == "노드 해역": continue
            if name in REGIONS:
                options.append(discord.SelectOption(label=name, description=f"{name} 지역 던전 ({SUBJUGATION_COST}pt 소모)", value=name))
        if not options: options.append(discord.SelectOption(label="해금된 탐사 지역 없음", value="none"))
        select = discord.ui.Select(placeholder="탐사할 지역을 선택하세요", options=options, row=1, custom_id="dungeon:region_sel")
        select.callback = self.region_select_callback
        self.add_item(select)

    async def char_select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer()
        self.p_data = await get_user_data(self.author.id, self.author.display_name)
        self.selected_char_index = int(interaction.data['values'][0])
        self.clear_items()
        self.add_character_select()
        self.add_region_select()
        char_list = self.p_data.get("characters", [])
        if self.selected_char_index < len(char_list):
            char_name = char_list[self.selected_char_index]["name"]
            await interaction.edit_original_response(content=f"⚔️ **{char_name}** (이)가 출전 준비를 마쳤습니다.", view=self)
        else:
            await interaction.edit_original_response(content="❌ 캐릭터 정보를 찾을 수 없습니다.", view=self)

    @discord.ui.button(label="▶️ 탐사 이어하기", style=discord.ButtonStyle.success, row=2, custom_id="dungeon:continue")
    @auto_defer(reload_data=True)
    async def continue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = self.user_data.get("current_dungeon")
        if not state:
            self.remove_item(self.continue_btn)
            return await interaction.edit_original_response(content="❌ 이어할 탐사 정보가 없습니다.", view=self)
            
        dungeon_view = DungeonMainView(self.author, self.user_data, self.save_func)
        if dungeon_view.pending_room == "boss":
            await dungeon_view.enter_boss_room(interaction, "\n♻️ 중단된 보스전을 다시 시작합니다.")
        elif dungeon_view.pending_room == "monster":
            await dungeon_view.enter_monster_room(interaction, "\n♻️ 중단된 전투를 다시 시작합니다.")
        else:
            await dungeon_view.show_main_screen(
                interaction,
                "중단했던 탐사를 재개합니다.",
                refresh_choices=not bool(dungeon_view.choices),
            )


    @discord.ui.button(label="🏆 랭킹 확인", style=discord.ButtonStyle.secondary, row=2, custom_id="dungeon:ranking")
    async def show_ranking(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id: return
        
        view = RankingFilterView(self.author)
        await interaction.response.send_message("📊 조회할 랭킹 범위를 선택하세요.", view=view, ephemeral=True)

    async def region_select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return
        region_name = interaction.data['values'][0]
        if region_name == "none": return

        await interaction.response.defer()
        lock = _dungeon_lock(self.author.id)
        if lock.locked():
            return await interaction.followup.send("⏳ 다른 던전 요청을 처리 중입니다.", ephemeral=True)
        async with lock:
            self.p_data = await get_user_data(self.author.id, self.author.display_name)
            if self.p_data.get("current_dungeon"):
                return await interaction.followup.send(
                    "❌ 이미 진행 중인 던전이 있습니다. 먼저 이어하기로 돌아가거나 기존 탐사를 종료해주세요.",
                    ephemeral=True,
                )
            characters = self.p_data.get("characters", [])
            if not (0 <= self.selected_char_index < len(characters)):
                return await interaction.followup.send("❌ 선택한 캐릭터를 찾을 수 없습니다.", ephemeral=True)
            current_pt = self.p_data.get("pt", 0)
            if current_pt < SUBJUGATION_COST:
                return await interaction.followup.send(f"❌ 포인트가 부족합니다! (현재: {current_pt}pt, 필요: {SUBJUGATION_COST}pt)", ephemeral=True)

            self.p_data["pt"] -= SUBJUGATION_COST
            dungeon_view = DungeonMainView(self.author, self.p_data, self.save_func, self.selected_char_index, region_name)
            await dungeon_view.show_main_screen(interaction, "던전 탐사를 시작합니다.")

class RankingFilterView(discord.ui.View):
    """랭킹 지역 필터 선택 뷰"""
    def __init__(self, author):
        super().__init__(timeout=60)
        self.author = author
        
        options = [discord.SelectOption(label="🌐 전체 지역", value="all")]
        for region in REGIONS.keys():
            options.append(discord.SelectOption(label=region, value=region))
            
        select = discord.ui.Select(placeholder="조회할 지역을 선택하세요", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return
        await interaction.response.defer(ephemeral=True)
        
        region_val = interaction.data['values'][0]
        filter_region = None if region_val == "all" else region_val
        
        ranking = await get_subjugation_ranking(10, filter_region)
        if not ranking:
            return await interaction.followup.send(f"📊 **[{region_val}]** 지역에 등록된 랭킹 데이터가 없습니다.", ephemeral=True)
            
        title = "⛓️ 던전 탐사 랭킹 (전체)" if not filter_region else f"⛓️ 던전 탐사 랭킹 ({filter_region})"
        embed = discord.Embed(title=title, color=discord.Color.gold())
        rank_text = ""
        for i, entry in enumerate(ranking):
            user_id = int(entry['user_id'])
            depth = entry['max_subjugation_depth']
            char_name = entry.get('max_subjugation_char') or "알 수 없음"
            region = entry.get('max_subjugation_region') or "알 수 없음"
            
            user = interaction.client.get_user(user_id)
            if not user:
                try: user = await interaction.client.fetch_user(user_id)
                except: user = None
            
            name = user.display_name if user else f"Unknown({user_id})"
            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"**{i+1}위**"
            rank_text += f"{medal} {name} : `{depth}층` ({region} | {char_name})\n"
            
        embed.description = rank_text
        await interaction.followup.send(embed=embed, ephemeral=True)
