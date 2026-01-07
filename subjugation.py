# subjugation.py
import discord
import random
from items import REGIONS, RARE_ITEMS, STAT_UP_ITEMS, ITEM_CATEGORIES
from monsters import spawn_monster
from battle import BattleView
from character import Character
from data_manager import get_user_data

SUBJUGATION_COST = 2000


# ==================================================================================
# 3. Dungeon Item Use View (Simplified & Self-contained)
# ==================================================================================
class DungeonItemUseView(discord.ui.View):
    """던전 내에서 아이템을 사용하기 위한 전용 뷰"""
    def __init__(self, author, user_data, save_func, char_index, dungeon_view, recovery_view):
        super().__init__(timeout=120)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.char_index = char_index
        self.dungeon_view = dungeon_view
        self.recovery_view = recovery_view
        
        self.item_page = 0
        self.PER_PAGE = 7
        self.update_components()

    def update_components(self):
        self.clear_items()
        inv = self.user_data.get("inventory", {})
        valid_items = []
        
        # 던전에서는 회복 및 버프 아이템만 사용 가능
        for item_name, count in inv.items():
            if count <= 0: continue
            
            desc = ""
            is_usable = False
            
            stat_map = {"hp": "최대 체력", "max_hp": "최대 체력", "max_mental": "최대 정신력", "attack": "공격력", "defense": "방어력", "defense_rate": "방어율", "success_rate": "조사 성공률"}

            if item_name in STAT_UP_ITEMS:
                info = STAT_UP_ITEMS[item_name]
                # 영구 스탯템은 던전에서 사용 불가
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

        back_btn = discord.ui.Button(label="⬅️ 쉼터로 돌아가기", style=discord.ButtonStyle.gray, row=4)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

    async def on_item_select(self, interaction: discord.Interaction):
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
            if eff == "hp":
                char_data["current_hp"] = min(char_data["hp"], char_data["current_hp"] + val)
                used = True
            elif eff == "mental":
                char_data["current_mental"] = min(char_data["max_mental"], char_data["current_mental"] + val)
                used = True

        if used:
            inv[item_name] -= 1
            if inv[item_name] <= 0: del inv[item_name]
            await self.save_func(self.author.id, self.user_data)
            self.update_components()
            
            embed = discord.Embed(title=f"✅ {item_name} 사용 완료", color=discord.Color.green())
            embed.add_field(name="현재 상태", value=f"❤️ HP: {char_data['current_hp']}/{char_data['hp']}\n🧠 멘탈: {char_data['current_mental']}/{char_data['max_mental']}")
            
            await interaction.edit_original_response(content=None, embed=embed, view=self)
        else:
            await interaction.followup.send("❌ 던전에서 사용할 수 없는 아이템입니다.", ephemeral=True)

    async def go_back(self, interaction: discord.Interaction):
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        self.dungeon_view.user_data = self.user_data
        self.recovery_view.user_data = self.user_data
        
        new_char_data = self.user_data["characters"][self.dungeon_view.char_index]
        self.dungeon_view.player = Character.from_dict(new_char_data)
        self.dungeon_view.player.apply_battle_start_buffs()

        await interaction.response.edit_message(embed=self.recovery_view.get_embed(), view=self.recovery_view)

# ==================================================================================
# 2. Dungeon Core Views
# ==================================================================================
class DungeonRecoveryView(discord.ui.View):
    """던전 내 회복방 뷰"""
    def __init__(self, author, user_data, save_func, dungeon_view):
        super().__init__(timeout=180)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.dungeon_view = dungeon_view

    def get_embed(self):
        return discord.Embed(title="쉼터", description="안전한 공간을 발견했습니다. 잠시 정비할 수 있습니다.", color=discord.Color.green())

    @discord.ui.button(label="🔧 정비 (아이템 사용)", style=discord.ButtonStyle.primary)
    async def use_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 아이템 사용 뷰로 넘어가기 전, 현재 던전의 플레이어 상태(HP/멘탈)를 DB에 동기화
        char_data = self.user_data["characters"][self.dungeon_view.char_index]
        char_data["current_hp"] = self.dungeon_view.player.current_hp
        char_data["current_mental"] = self.dungeon_view.player.current_mental
        await self.save_func(self.author.id, self.user_data)
        
        view = DungeonItemUseView(self.author, self.user_data, self.save_func, self.dungeon_view.char_index, self.dungeon_view, self)
        await interaction.response.edit_message(content="사용할 아이템을 선택하세요.", embed=None, view=view)

    @discord.ui.button(label="▶️ 탐사 계속하기", style=discord.ButtonStyle.success)
    async def continue_dungeon(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.dungeon_view.show_main_screen(interaction, "회복을 마치고 다시 탐사를 시작합니다.")

    @discord.ui.button(label="🚪 던전 나가기", style=discord.ButtonStyle.danger)
    async def exit_dungeon(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.dungeon_view.end_dungeon(interaction, "탐사를 중단하고 던전에서 나왔습니다.")

class DungeonMainView(discord.ui.View):
    """던전 탐사 메인 뷰"""
    def __init__(self, author, user_data, save_func, char_index, region_name):
        super().__init__(timeout=300)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.char_index = char_index
        self.region_name = region_name
        
        self.depth = 0
        self.accumulated_loot = {"items": {}, "money": 0, "pt": 0}

        self.player = Character.from_dict(user_data["characters"][char_index])
        self.player.apply_battle_start_buffs()
        
        self.choices = []

    async def show_main_screen(self, interaction: discord.Interaction, message: str):
        self.setup_choices()
        embed = self.create_embed(message)
        
        if not interaction.response.is_done():
            await interaction.response.edit_message(content=None, embed=embed, view=self)
        else:
            await interaction.edit_original_response(content=None, embed=embed, view=self)

    def create_embed(self, description: str):
        embed = discord.Embed(title=f"⛓️ {self.region_name} 던전", description=description, color=discord.Color.dark_purple())
        embed.add_field(name="탐사 정보", value=f"현재 깊이: {self.depth}층", inline=True)
        embed.add_field(name="캐릭터", value=f"{self.player.name}", inline=True)
        
        hp_bar = "🟩" * int(self.player.current_hp / self.player.max_hp * 10) + "⬛" * (10 - int(self.player.current_hp / self.player.max_hp * 10))
        mental_bar = "🟦" * int(self.player.current_mental / self.player.max_mental * 10) + "⬛" * (10 - int(self.player.current_mental / self.player.max_mental * 10))
        embed.add_field(name="상태", value=f"❤️ HP: {hp_bar} ({self.player.current_hp}/{self.player.max_hp})\n🧠 멘탈: {mental_bar} ({self.player.current_mental}/{self.player.max_mental})", inline=False)

        choice_texts = {"monster": "불길한 기운이 느껴진다.", "item": "반짝거림이 보인다.", "recovery": "고요하다."}
        choices_str = [f"{i+1}. {choice_texts[c]}" for i, c in enumerate(self.choices)]
        embed.add_field(name="선택지", value="\n".join(choices_str), inline=False)
        return embed

    def setup_choices(self):
        self.clear_items()
        # 몬스터 40%, 휴식 35%, 아이템 25%
        self.choices = random.choices(["monster", "recovery", "item"], weights=[40, 35, 25], k=3)
        for i, choice_type in enumerate(self.choices):
            btn = discord.ui.Button(label=f"선택 {i+1}", style=discord.ButtonStyle.secondary)
            btn.callback = self.make_choice_callback(choice_type)
            self.add_item(btn)

    def make_choice_callback(self, choice_type):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.author.id: return
            self.depth += 1
            
            roll = random.random()
            room_map = {"monster": 0.7, "item": 0.7, "recovery": 0.7}
            other_choices = [c for c in room_map if c != choice_type]
            
            actual_room = choice_type if roll < room_map[choice_type] else random.choice(other_choices)

            if actual_room == "monster": await self.enter_monster_room(interaction)
            elif actual_room == "item": await self.enter_item_room(interaction)
            else: await self.enter_recovery_room(interaction)
        return callback

    def apply_monster_buffs(self, monsters):
        buff_sets = self.depth // 10
        if buff_sets > 0:
            for m in monsters:
                m.attack += buff_sets
                m.defense += buff_sets
                m.max_hp += buff_sets * 10
                m.current_hp += buff_sets * 10

    async def enter_monster_room(self, interaction: discord.Interaction):
        monster_pool = self.get_monster_pool(self.region_name)
        monsters = [spawn_monster(random.choice(monster_pool)) for _ in range(random.randint(1, 3))]
        for i, m in enumerate(monsters):
            if len(monsters) > 1: m.name = f"{m.name} {chr(65+i)}"

        # [Bug Fix 2] 전투 진입 시 아티팩트 정보 재로드 (두 번째 전투부터 누락 방지)
        original_char = self.user_data["characters"][self.char_index]
        self.player.equipped_artifact = original_char.get("equipped_artifact")
        self.player.equipped_engraved_artifact = original_char.get("equipped_engraved_artifact")

        self.apply_monster_buffs(monsters)

        async def on_victory(i, battle_results):
            self.player.current_hp = battle_results.get("player_hp", self.player.current_hp)
            self.player.current_mental = battle_results.get("player_mental", self.player.current_mental)
            for item, qty in battle_results.get("items", {}).items():
                self.accumulated_loot["items"][item] = self.accumulated_loot["items"].get(item, 0) + qty
            self.accumulated_loot["money"] += battle_results.get("money", 0)
            self.accumulated_loot["pt"] += battle_results.get("pt", 0)
            await self.show_main_screen(i, "전투에서 승리했습니다! 다음 선택지로 이동합니다.")

        # BattleView는 is_dungeon_run=True일 때 캐릭터 데이터를 저장하지 않고,
        # 승리 콜백으로 플레이어의 최종 HP/멘탈을 반환하도록 수정되어야 합니다.
        view = BattleView(self.author, self.player, monsters, self.user_data, self.save_func,
                          char_index=self.char_index, victory_callback=on_victory, is_dungeon_run=True)
        embed = discord.Embed(title="⚔️ 몬스터 출현!", description=f"{len(monsters)}마리의 몬스터와 조우했습니다!", color=discord.Color.red())
        await interaction.response.edit_message(embed=embed, view=view)

    async def enter_item_room(self, interaction: discord.Interaction):
        loot = self.calculate_item_room_loot()
        for item, qty in loot.items():
            self.accumulated_loot["items"][item] = self.accumulated_loot["items"].get(item, 0) + qty

        loot_str = "\n".join([f"획득: {item} x{qty}" for item, qty in loot.items()])
        embed = discord.Embed(title="💎 보물 발견!", description=f"상자를 열어 아이템을 획득했습니다.\n\n{loot_str}", color=discord.Color.gold())
        
        continue_view = discord.ui.View(timeout=180)
        continue_btn = discord.ui.Button(label="▶️ 탐사 계속하기", style=discord.ButtonStyle.success)
        continue_btn.callback = lambda i: self.show_main_screen(i, "보물을 챙기고 다음으로 나아갑니다.")
        continue_view.add_item(continue_btn)
        await interaction.response.edit_message(embed=embed, view=continue_view)

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

    async def enter_recovery_room(self, interaction: discord.Interaction):
        view = DungeonRecoveryView(self.author, self.user_data, self.save_func, self)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    async def end_dungeon(self, interaction: discord.Interaction, message: str):
        inv = self.user_data.setdefault("inventory", {})
        for item, qty in self.accumulated_loot["items"].items():
            inv[item] = inv.get(item, 0) + qty
        self.user_data["money"] += self.accumulated_loot["money"]
        self.user_data["pt"] += self.accumulated_loot["pt"]

        self.player.remove_battle_buffs()
        self.user_data["characters"][self.char_index] = self.player.to_dict()
        self.user_data.setdefault("myhome", {})["total_subjugations"] = self.user_data["myhome"].get("total_subjugations", 0) + self.depth
        await self.save_func(self.author.id, self.user_data)

        embed = discord.Embed(title="🏰 던전 탐사 완료", description=message, color=discord.Color.green())
        embed.add_field(name="탐사 깊이", value=f"{self.depth}층", inline=False)
        loot_str = "\n".join([f"{item} x{qty}" for item, qty in self.accumulated_loot["items"].items()]) or "없음"
        embed.add_field(name="획득 아이템", value=loot_str, inline=False)
        if self.accumulated_loot["money"] > 0 or self.accumulated_loot["pt"] > 0:
            embed.add_field(name="추가 획득", value=f"💰 {self.accumulated_loot['money']}원\n⚡ {self.accumulated_loot['pt']}pt", inline=False)
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
# 1. Entry Point View
# ==================================================================================
class SubjugationRegionView(discord.ui.View):
    def __init__(self, author, p_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.p_data = p_data        
        self.save_func = save_func
        self.selected_char_index = 0
        self.add_character_select()
        self.add_region_select()

    def add_character_select(self):
        char_list = self.p_data.get("characters", [])
        if not char_list: return
        options = []
        for i, c in enumerate(char_list):
            label = c.get("name", f"캐릭터 {i+1}")
            desc = f"HP: {c.get('hp')} | 공격력: {c.get('attack')}"
            options.append(discord.SelectOption(label=label, description=desc, value=str(i), default=(i == self.selected_char_index)))
        select = discord.ui.Select(placeholder="던전을 탐색할 캐릭터 선택", options=options, row=0)
        select.callback = self.char_select_callback
        self.add_item(select)

    def add_region_select(self):
        unlocked = self.p_data.get("unlocked_regions", ["기원의 쌍성"])
        options = []
        region_order = list(REGIONS.keys())
        sorted_regions = sorted(unlocked, key=lambda x: region_order.index(x) if x in region_order else 999)

        for name in sorted_regions:
            if name == "노드 해역": continue
            if name in REGIONS:
                options.append(discord.SelectOption(label=name, description=f"{name} 지역 던전 ({SUBJUGATION_COST}pt 소모)", value=name))
        if not options: options.append(discord.SelectOption(label="해금된 탐사 지역 없음", value="none"))
        select = discord.ui.Select(placeholder="탐사할 지역을 선택하세요", options=options, row=1)
        select.callback = self.region_select_callback
        self.add_item(select)

    async def char_select_callback(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.p_data = await get_user_data(self.author.id, self.author.display_name)
        self.selected_char_index = int(interaction.data['values'][0])
        self.clear_items()
        self.add_character_select()
        self.add_region_select()
        char_list = self.p_data.get("characters", [])
        if self.selected_char_index < len(char_list):
            char_name = char_list[self.selected_char_index]["name"]
            await interaction.response.edit_message(content=f"⚔️ **{char_name}** (이)가 출전 준비를 마쳤습니다.", view=self)
        else:
            await interaction.response.edit_message(content="❌ 캐릭터 정보를 찾을 수 없습니다.", view=self)

    async def region_select_callback(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        region_name = interaction.data['values'][0]
        if region_name == "none": return

        self.p_data = await get_user_data(self.author.id, self.author.display_name)
        current_pt = self.p_data.get("pt", 0)
        if current_pt < SUBJUGATION_COST:
            return await interaction.response.send_message(f"❌ 포인트가 부족합니다! (현재: {current_pt}pt, 필요: {SUBJUGATION_COST}pt)", ephemeral=True)

        self.p_data["pt"] -= SUBJUGATION_COST
        dungeon_view = DungeonMainView(self.author, self.p_data, self.save_func, self.selected_char_index, region_name)
        await dungeon_view.show_main_screen(interaction, "던전 탐사를 시작합니다.")
