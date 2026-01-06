# subjugation.py
import discord
import random
import json
import os
from items import REGIONS
from monsters import spawn_monster
from battle import BattleView
from character import Character
from data_manager import get_user_data

DATA_FILE = "user_data.json"
SUBJUGATION_COST = 150



class SubjugationRegionView(discord.ui.View):
    def __init__(self, author, p_data, all_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.p_data = p_data        
        self.all_data = all_data    
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
            if i == self.selected_char_index:
                label = f"✅ {label}"
                desc += " (출전 대기)"
            
            options.append(discord.SelectOption(label=label, description=desc, value=str(i)))

        select = discord.ui.Select(placeholder="토벌을 수행할 캐릭터 선택", options=options, row=0)
        select.callback = self.char_select_callback
        self.add_item(select)

    def add_region_select(self):
        unlocked = self.p_data.get("unlocked_regions", ["기원의 쌍성"])
        options = []
        
        # items.py의 REGIONS 순서대로 정렬 (비용순 등)
        # 딕셔너리 순서가 보장되지 않을 수 있으므로 unlock_cost 등으로 정렬 권장
        sorted_regions = sorted(unlocked, key=lambda x: REGIONS.get(x, {}).get("unlock_cost", 0))

        for name in sorted_regions:
            # [수정] 노드 해역은 토벌 목록에서 제외 (조사/낚시 전용)
            if name == "노드 해역":
                continue

            if name in REGIONS:
                options.append(discord.SelectOption(
                    label=name, 
                    description=f"{name} 지역 토벌 ({SUBJUGATION_COST}pt 소모)", 
                    value=name
                ))

        if not options:
            options.append(discord.SelectOption(label="해금된 토벌 지역 없음", value="none"))

        select = discord.ui.Select(placeholder="출전할 지역을 선택하세요", options=options, row=1)
        select.callback = self.region_select_callback
        self.add_item(select)

    async def char_select_callback(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
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
        if interaction.user != self.author:
            return await interaction.response.send_message("본인의 토벌만 관리할 수 있어!", ephemeral=True)
            
        region_name = interaction.data['values'][0]
        if region_name == "none": return

        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        if not self.p_data:
            return await interaction.response.send_message("❌ 데이터 오류가 발생했습니다.", ephemeral=True)

        current_pt = self.p_data.get("pt", 0)
        if current_pt < SUBJUGATION_COST:
            return await interaction.response.send_message(f"❌ 포인트가 부족합니다! (현재: {current_pt}pt, 필요: {SUBJUGATION_COST}pt)", ephemeral=True)

        # 몬스터 풀 설정
        unlocked_list = self.p_data.get("unlocked_regions", [])
        monster_pool = []

        if region_name == "기원의 쌍성":
            monster_pool = ["길 잃은 바람비", "약한 원념", "커다란 별기구"]
            if "시간의 신전" in unlocked_list:
                monster_pool.extend(["주신의 눈물방울", "예민한 집요정"])
        elif region_name == "시간의 신전":
            monster_pool = ["눈 감은 원념", "약한 원념"]
            if "일한산 중턱" in unlocked_list:
                monster_pool.extend(["시간의 방랑자", "과거의 망집"])
        elif region_name == "일한산 중턱":
            monster_pool = ["굴레늑대", "얼어붙은 원념", "경계꽃 골렘"]
            if "이루지 못한 꿈들의 별" in unlocked_list:
                monster_pool.extend(["굴레늑대 우두머리", "은하새"])
        elif region_name == "이루지 못한 꿈들의 별":
            monster_pool = ["몽상행인", "살아난 발상", "구체화된 악몽"]
        elif region_name == "생명의 숲":
            monster_pool = ["뒤틀린 식충식물", "굶주린 포식자", "아름다운 나비"]
            
            if "아르카워드 제도" in unlocked_list:
                monster_pool.extend(["냉혹한 원념", "사나운 은하새"])
        elif region_name == "아르카워드 제도":
            monster_pool = ["아사한 원념", "변질된 바람", "폐허를 지키는 문지기"]
        # [신규] 공간의 신전 추가
        elif region_name == "공간의 신전":
            monster_pool = ["취한 파티원", "겁쟁이 원념", "폭주 거대 짤똥이"]    
        else:
            monster_pool = ["약한 원념"]

        monsters = []
        # 1~3마리 랜덤 출현
        monster_count = random.randint(1, 3)
        

        for i in range(monster_count):
            m_name = random.choice(monster_pool)
            # 르네아 같은 보스는 1마리만 나오게 처리
            if m_name == "르네아":
                monsters = [spawn_monster(m_name)]
                break
                
            monster = spawn_monster(m_name)
            if monster_count > 1:
                monster.name = f"{monster.name} {chr(65+i)}"
            monsters.append(monster)

        self.p_data["pt"] -= SUBJUGATION_COST
        
        char_list = self.p_data.get("characters", [])
        if not char_list:
            return await interaction.response.send_message("❌ 전투를 수행할 캐릭터가 없습니다.", ephemeral=True)
        
        if self.selected_char_index >= len(char_list):
            self.selected_char_index = 0
            
        player = Character.from_dict(char_list[self.selected_char_index])
        player.defense_rate = char_list[self.selected_char_index].get("defense_rate", 0)

        # 퀘스트 카운트 등을 위해 region_name 전달
        view = BattleView(
            self.author, player, monsters, 
            self.p_data, self.save_func, 
            char_index=self.selected_char_index,
            region_name=region_name
        )
        
        embed = view.make_embed(f"⚔️ **{region_name}** 토벌을 시작합니다!\n**{player.name}** vs 적 **{len(monsters)}명**")
        await interaction.response.edit_message(content=None, embed=embed, view=view)

async def start_subjugation(ctx, p_data, all_data, save_func):
    view = SubjugationRegionView(ctx.author, p_data, all_data, save_func)
    await ctx.send("🗺️ **토벌 지역 선택**\n해금된 지역에서만 토벌 파견이 가능합니다.", view=view)