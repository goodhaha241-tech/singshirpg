# investigation.py
import discord
import random
import json
import os
import asyncio
from items import REGIONS, RARE_ITEMS, LIMITED_ONE_TIME_ITEMS
from monsters import spawn_monster
from battle import BattleView
from character import Character
from story import update_quest_progress
# fishing.py에서 낚시 뷰와 물고기 등급 데이터를 가져옵니다.
from fishing import FishingGameView, FISH_TIERS 
from decorators import auto_defer

DATA_FILE = "user_data.json"

# [신규] 단일 조사 실행 시 1회만 획득 가능한 아이템 카테고리
LIMITED_CATEGORIES = {
    "chest": ["낡은 보물상자", "섬세한 보물상자", "깔끔한 보물상자"],
    "key": ["낡은 열쇠", "섬세한 열쇠", "깔끔한 열쇠", "장식용 열쇠"]
}



# ==================================================================================
# [신규] 낚시 종료 후 조사를 이어가기 위한 래퍼 클래스 & 뷰
# ==================================================================================
class ContinueInvestigationView(discord.ui.View):
    """낚시 결과 확인 후 남은 조사를 진행하는 버튼 뷰"""
    def __init__(self, author, remaining_runs, accumulated_loot, resume_callback):
        super().__init__(timeout=60)
        self.author = author
        self.remaining_runs = remaining_runs # 호환성을 위해 유지
        self.accumulated_loot = accumulated_loot
        self.resume_callback = resume_callback

    @discord.ui.button(label="🏃 남은 조사 계속하기", style=discord.ButtonStyle.success)
    async def continue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        await interaction.response.edit_message(view=None) # 버튼 제거
        await self.resume_callback(interaction, self.accumulated_loot)

class ResumableFishingGameView(FishingGameView):
    """
    기존 FishingGameView를 상속받아, 낚시 종료 시 조사 복귀 로직을 수행하도록 개조한 클래스.
    노드 해역일 경우 전용 물고기를 낚도록 오버라이딩합니다.
    """
    def __init__(self, author, user_data, save_func, remaining_runs, accumulated_loot, resume_callback, region_name):
        # 2. 부모 클래스(FishingGameView)에도 save_func 전달
        # FishingGameView의 생성자가 all_data를 요구한다면 None을 넘기거나 해당 클래스도 수정 필요
        # 여기서는 부모 클래스도 수정되었다고 가정하고 all_data 제거
        super().__init__(author, user_data, save_func) 
        
        self.remaining_runs = remaining_runs
        self.accumulated_loot = accumulated_loot
        self.resume_callback = resume_callback
        self.region_name = region_name


    async def catch_fish(self, i):
        # 1. 물고기 결정 로직 (노드 해역 분기 처리)
        tier_roll = random.random()
        fish_type = "common"
        caught = ""

        # [노드 해역 전용 로직]
        if self.region_name == "노드 해역":
            # 낚싯대 등급에 따른 희귀 확률 보정
            rare_chance = 0.2
            if self.rod_lvl == 1: rare_chance = 0.35
            elif self.rod_lvl == 2: rare_chance = 0.5
            
            if tier_roll < rare_chance:
                # fishing.py에 정의된 노드 해역 전용 희귀 물고기
                caught = random.choice(FISH_TIERS["node_rare"])
                fish_type = "rare"
            else:
                # fishing.py에 정의된 노드 해역 전용 일반 물고기
                caught = random.choice(FISH_TIERS["node_common"])
                fish_type = "common"
        else:
            # [일반 지역 로직]
            adv_chance = 0.0
            if self.rod_lvl == 1: adv_chance = 0.3
            elif self.rod_lvl == 2: adv_chance = 0.5
            
            if tier_roll > 0.6:
                if random.random() < adv_chance: fish_type = "advanced"
                else: fish_type = "rare"
            caught = random.choice(FISH_TIERS[fish_type])
        
        # 2. 인벤토리 저장
        inv = self.user_data.setdefault("inventory", {})
        inv[caught] = inv.get(caught, 0) + 1
        await self.save_func(self.author.id, self.user_data)
        
        # 3. 누적 보상(조사 결과)에 추가
        self.accumulated_loot["items"][caught] = self.accumulated_loot["items"].get(caught, 0) + 1

        # 4. 결과 메시지 및 복귀 버튼 출력
        emoji = "🐟" if fish_type == "common" else "✨" if fish_type == "rare" else "👑"
        type_str = "일반" if fish_type == "common" else "희귀" if fish_type == "rare" else "고급"
        
        embed = discord.Embed(title="🎉 낚시 성공!", color=discord.Color.green())
        embed.add_field(name="획득한 물고기", value=f"{emoji} **{caught}** ({type_str})", inline=False)
        embed.set_footer(text=f"남은 조사 횟수: {self.remaining_runs}회")
        
        view = ContinueInvestigationView(self.author, self.remaining_runs, self.accumulated_loot, self.resume_callback)
        await i.edit_original_response(content=None, embed=embed, view=view)

    async def fail_fishing(self, i, msg):
        # 실패 시에도 조사는 계속되어야 함
        embed = discord.Embed(title="🎣 낚시 실패", description=msg, color=discord.Color.red())
        embed.set_footer(text=f"남은 조사 횟수: {self.remaining_runs}회")
        view = ContinueInvestigationView(self.author, self.remaining_runs, self.accumulated_loot, self.resume_callback)
        await i.edit_original_response(content=None, embed=embed, view=view)


# ==================================================================================
# 메인 조사 뷰
# ==================================================================================
class InvestigationView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.unlocked = self.user_data.setdefault("unlocked_regions", ["기원의 쌍성"])

        # 마이홈에서 설정한 조사원 인덱스 로드
        self.selected_char_index = self.user_data.get("investigator_index", 0)
        # 인덱스 유효성 검사
        if self.selected_char_index >= len(self.user_data.get("characters", [])):
            self.selected_char_index = 0
            self.user_data["investigator_index"] = 0
            # [수정] __init__에서는 비동기 함수를 await할 수 없으므로, save_func 호출을 제거합니다.

        self.selected_region = None
        self.page = 0
        self.ITEMS_PER_PAGE = 4 # 페이지 당 지역 수
        self.setup_initial_view()

    def get_embed(self):
        embed = discord.Embed(title="🔍 조사 지역 선택", description="조사를 떠날 지역을 선택해주세요.", color=discord.Color.blue())
        embed.set_footer(text=f"현재 포인트: {self.user_data.get('pt', 0)}pt")
        return embed

    def setup_initial_view(self):
        self.clear_items()
        self.add_region_buttons()

    def add_region_buttons(self):
        all_regions = []
        for name in REGIONS.keys():
            is_locked = name not in self.unlocked
            if name == "아르카워드 제도" and is_locked: continue
            if name == "공간의 신전" and is_locked: continue
            all_regions.append(name)

        total_pages = (len(all_regions) - 1) // self.ITEMS_PER_PAGE + 1
        if self.page < 0: self.page = 0
        if self.page >= total_pages: self.page = max(0, total_pages - 1)

        start = self.page * self.ITEMS_PER_PAGE
        end = start + self.ITEMS_PER_PAGE
        current_regions = all_regions[start:end]

        for region_name in current_regions:
            is_locked = region_name not in self.unlocked
            label = f"{region_name} {'🔒' if is_locked else '✅'}"
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
            btn.callback = self.make_region_callback(region_name)
            self.add_item(btn)

        if total_pages > 1:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            count_btn = discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, row=1, disabled=True)
            self.add_item(count_btn)

            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page == total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

    async def prev_page(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.defer()
        self.page -= 1
        self.setup_initial_view()
        await interaction.edit_original_response(view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.defer()
        self.page += 1
        self.setup_initial_view()
        await interaction.edit_original_response(view=self)

    def add_count_buttons(self):
        self.clear_items()
        btn_1 = discord.ui.Button(label="1회 (10턴)", style=discord.ButtonStyle.primary)
        btn_1.callback = lambda i: self.start_turn_investigation(i, 1)
        btn_3 = discord.ui.Button(label="3회 (30턴)", style=discord.ButtonStyle.success)
        btn_3.callback = lambda i: self.start_turn_investigation(i, 3)
        btn_5 = discord.ui.Button(label="5회 (50턴)", style=discord.ButtonStyle.danger)
        btn_5.callback = lambda i: self.start_turn_investigation(i, 5)
        btn_back = discord.ui.Button(label="지역 다시 선택", style=discord.ButtonStyle.secondary, row=1)
        btn_back.callback = self.back_to_region

        self.add_item(btn_1); self.add_item(btn_3); self.add_item(btn_5); self.add_item(btn_back)

    async def back_to_region(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.defer()
        self.selected_region = None
        self.setup_initial_view()
        await interaction.edit_original_response(content="다시 지역을 선택해줘.", view=self)

    def make_region_callback(self, region_name):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.author: return await interaction.response.send_message("본인의 조사만 관리할 수 있어!", ephemeral=True)
            await interaction.response.defer()

            # self.user_data는 이미 __init__에서 설정됨

            if region_name not in self.user_data["unlocked_regions"]:
                region_info = REGIONS[region_name]
                req_pt = region_info.get("pt_cost", 0)
                req_money = region_info["unlock_cost"]

                if self.user_data.get("money", 0) < req_money: return await interaction.response.send_message(f"❌ 돈 부족! ({req_money}원 필요)", ephemeral=True)
                if self.user_data.get("pt", 0) < req_pt: return await interaction.response.send_message(f"❌ 포인트 부족! ({req_pt}pt 필요)", ephemeral=True)

                self.user_data["money"] -= req_money
                self.user_data["pt"] -= req_pt
                self.user_data["unlocked_regions"].append(region_name)
                await self.save_func(self.author.id, self.user_data)
                await update_quest_progress(interaction.user.id, self.user_data, self.save_func, "region_unlock", 1, region_name)

                self.setup_initial_view()
                return await interaction.edit_original_response(content=f"🔓 **{region_name}** 해금 완료! 다시 선택해줘.", view=self)

            self.selected_region = region_name
            self.add_count_buttons()

            char_name = "알 수 없음"
            chars = self.user_data.get("characters", [])
            idx = self.user_data.get("investigator_index", 0)
            if 0 <= idx < len(chars):
                char_name = chars[idx]["name"]

            await interaction.edit_original_response(content=f"🗺️ **{region_name}**에서 몇 번 조사할까?\n(현재 담당 조사원: **{char_name}**)", view=self)
        return callback

    async def start_turn_investigation(self, interaction, total_runs):
        if interaction.user != self.author: return
        await interaction.response.defer()
        
        region_info = REGIONS[self.selected_region]
        cost = region_info.get("energy_cost", 2)
        if self.user_data.get("pt", 0) < cost:
            return await interaction.followup.send("❌ 포인트가 부족해!", ephemeral=True)

        view = TurnInvestigationView(self.author, self.user_data, self.save_func, self.selected_region, total_runs)
        await view.start_run(interaction)

    def add_loot(self, inventory, acc_loot, item_name, count):
        # [수정] 보물상자/열쇠는 종류 불문하고 1개만 나오도록 제한
        for category, items_in_category in LIMITED_CATEGORIES.items():
            if item_name in items_in_category:
                # 이 카테고리의 아이템을 이미 얻었는지 확인
                for item in items_in_category:
                    if acc_loot["items"].get(item, 0) > 0:
                        return  # 이미 획득했으므로 추가하지 않고 종료
                # 이 카테고리의 첫 아이템이면 수량을 1로 고정
                count = 1
                break

        if item_name in LIMITED_ONE_TIME_ITEMS:
            if acc_loot["items"].get(item_name, 0) > 0: return 
            count = 1 
        inventory[item_name] = inventory.get(item_name, 0) + count
        acc_loot["items"][item_name] = acc_loot["items"].get(item_name, 0) + count

    def get_monster_pool(self, region_name):
        unlocked = self.user_data.get("unlocked_regions", [])
        pool = ["약한 원념"]

        if region_name == "기원의 쌍성":
            pool = ["길 잃은 바람비", "약한 원념", "커다란 별기구"]
            if "시간의 신전" in unlocked: pool.extend(["주신의 눈물방울", "예민한 집요정"])
        elif region_name == "시간의 신전":
            pool = ["눈 감은 원념", "약한 원념"]
            if "일한산 중턱" in unlocked: pool.extend(["시간의 방랑자", "과거의 망집"])
        elif region_name == "일한산 중턱":
            pool = ["굴레늑대", "얼어붙은 원념", "경계꽃 골렘"]
            if "이루지 못한 꿈들의 별" in unlocked: pool.extend(["굴레늑대 우두머리", "은하새"])
        elif region_name == "이루지 못한 꿈들의 별":
            pool = ["몽상행인", "살아난 발상", "구체화된 악몽"]
        elif region_name == "생명의 숲":
            pool = ["뒤틀린 식충식물", "굶주린 포식자", "아름다운 나비"]
            if "아르카워드 제도" in unlocked: pool.extend(["냉혹한 원념", "사나운 은하새"])
        elif region_name == "아르카워드 제도":
            pool = ["아사한 원념", "변질된 바람", "폐허를 지키는 문지기"]
        elif region_name == "공간의 신전":
            pool = ["취한 파티원", "겁쟁이 원념", "폭주 거대 짤똥이"]
        
        # 노드 해역은 여기서 몬스터 풀이 필요 없지만(전투 없음), 안전을 위해 더미 반환
        elif region_name == "노드 해역":
            pool = ["약한 원념"] 

        return pool
# (이후의 잘못된 들여쓰기 코드는 모두 삭제되었습니다)

# ==================================================================================
# [신규] 턴 기반 조사 뷰
# ==================================================================================
class TurnInvestigationView(discord.ui.View):
    def __init__(self, author, user_data, save_func, region_name, total_runs, 
                 current_run=1, current_turn=1, accumulated_loot=None):
        super().__init__(timeout=180)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.region_name = region_name
        self.total_runs = total_runs
        self.current_run = current_run
        self.current_turn = current_turn
        self.accumulated_loot = accumulated_loot or {"money": 0, "pt": 0, "items": {}}
        self.region_info = REGIONS[region_name]
        self.last_log = "조사를 시작합니다."
        self.embed_color = discord.Color.blue()

    def create_embed(self):
        embed = discord.Embed(
            title=f"🔍 {self.region_name} 조사 ({self.current_run}/{self.total_runs}회차)",
            description=f"**현재 턴: {self.current_turn} / 10**\n\n{self.last_log}",
            color=self.embed_color
        )
        embed.set_footer(text=f"남은 포인트: {self.user_data.get('pt', 0)}pt")
        return embed

    async def start_run(self, interaction):
        # 회차 시작 시 비용 차감 및 통계 업데이트
        cost = self.region_info.get("energy_cost", 2)
        self.user_data["pt"] -= cost
        
        await self.save_func(self.author.id, self.user_data)
        await interaction.edit_original_response(content=None, embed=self.create_embed(), view=self)

    @discord.ui.button(label="턴 넘기기", style=discord.ButtonStyle.primary)
    @auto_defer()
    async def turn_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process_turn(interaction)

    async def process_turn(self, interaction):
        # 1. 실패 확률 계산 (버프 포함)
        char_idx = self.user_data.get("investigator_index", 0)
        chars = self.user_data.get("characters", [])
        investigator_name = chars[char_idx]["name"] if chars and char_idx < len(chars) else None

        buffs = self.user_data.setdefault("buffs", {})
        base_fail = self.region_info["fail_rate"]
        buff_bonus = 0.0
        for b_info in buffs.values():
            if b_info.get("target") == investigator_name and b_info.get("stat") == "success_rate":
                buff_bonus += b_info.get("value", 0) / 100.0
            
        # [신규] 행운의 부적 효과 적용 (인벤토리에 보유 시 패시브로 성공 확률 +5% 증가)
        inv = self.user_data.get("inventory", {})
        if inv.get("행운의 부적", 0) > 0:
            buff_bonus += 0.05
        
        final_fail_rate = max(0.0, base_fail - buff_bonus)
        
        if random.random() < final_fail_rate:
            # 실패 시 이벤트 판정 (50% 확률)
            if random.random() < 0.5:
                if self.region_name == "노드 해역":
                    await self.trigger_fishing(interaction)
                    return
                else:
                    await self.trigger_battle(interaction)
                    return
            
            self.last_log = "❌ 조사에 실패했습니다. 아무것도 발견하지 못했습니다."
            self.embed_color = discord.Color.red()
        else:
            # 성공 시 보상 판정
            is_great = random.random() < 0.2
            loot_summary = self.generate_loot(is_great)
            
            # [수정] 성공한 조사 턴 횟수 증가 및 퀘스트 업데이트
            self.user_data.setdefault("myhome", {})["total_investigations"] = self.user_data["myhome"].get("total_investigations", 0) + 1
            char_idx = self.user_data.get("investigator_index", 0)
            chars = self.user_data.get("characters", [])
            char_name = chars[char_idx]["name"] if chars and char_idx < len(chars) else None
            await update_quest_progress(interaction.user.id, self.user_data, self.save_func, "investigate", 1, self.region_name, extra_info=char_name)

            if is_great:
                self.last_log = f"✨ **대성공!** 희귀한 재료들을 발견했습니다!\n획득: {loot_summary}"
                self.embed_color = discord.Color.gold()
            else:
                self.last_log = f"✅ **성공!** 재료들을 발견했습니다.\n획득: {loot_summary}"
                self.embed_color = discord.Color.green()

        # [수정] 모든 조사 관련 버프(성공 확률) 매 턴 동시 차감 로직
        for b_name, b_info in list(buffs.items()):
            target = b_info.get("target")
            # 해당 캐릭터의 버프이거나 타겟 정보가 없는 경우 차감
            if (target == investigator_name or target is None) and b_info.get("stat") == "success_rate":
                if "duration" in b_info:
                    b_info["duration"] -= 1
                    if b_info["duration"] <= 0:
                        del buffs[b_name]
                        self.last_log += f"\n📉 **{b_name}** 효과가 만료되었습니다."

        await self.advance_turn_and_update(interaction)

    async def advance_turn_and_update(self, interaction):
        if self.current_turn >= 10:
            if self.current_run >= self.total_runs:
                await self.show_final_result(interaction)
                return
            else:
                # 다음 회차 준비
                self.current_run += 1
                self.current_turn = 1
                
                cost = self.region_info.get("energy_cost", 2)
                if self.user_data.get("pt", 0) < cost:
                    await self.show_final_result(interaction, "포인트가 부족하여 조사가 중단되었습니다.")
                    return
                self.user_data["pt"] -= cost
                
                self.last_log += f"\n\n🔄 {self.current_run}회차 조사를 시작합니다."
                self.embed_color = discord.Color.blue()
        else:
            self.current_turn += 1

        await self.save_func(self.author.id, self.user_data)
        await interaction.edit_original_response(embed=self.create_embed(), view=self)

    def generate_loot(self, is_great):
        inv = self.user_data.setdefault("inventory", {})
        common_pool = self.region_info["common"]
        rare_pool = self.region_info.get("rare", [])
        
        loot_summary = []
        
        if is_great:
            # 대성공: 희귀 2종(1~5개), 일반 2종(1~5개)
            selected_rares = random.sample(rare_pool, min(2, len(rare_pool)))
            for item in selected_rares:
                qty = random.randint(1, 5)
                if self.add_loot_internal(inv, item, qty):
                    loot_summary.append(f"{item} x{qty}")
            
            selected_commons = random.sample(common_pool, min(2, len(common_pool)))
            for item in selected_commons:
                qty = random.randint(1, 5)
                if self.add_loot_internal(inv, item, qty):
                    loot_summary.append(f"{item} x{qty}")
        else:
            # 일반 성공: 일반 3종(5~10개)
            selected_commons = random.sample(common_pool, min(3, len(common_pool)))
            for item in selected_commons:
                qty = random.randint(5, 10)
                if self.add_loot_internal(inv, item, qty):
                    loot_summary.append(f"{item} x{qty}")

        if random.random() < 0.02:
            if self.add_loot_internal(inv, "신화의 발자취", 1):
                loot_summary.append("신화의 발자취 x1")
            
        return ", ".join(loot_summary)

    def add_loot_internal(self, inventory, item_name, count):
        # LIMITED_CATEGORIES 및 LIMITED_ONE_TIME_ITEMS 규칙 적용
        for category, items_in_category in LIMITED_CATEGORIES.items():
            if item_name in items_in_category:
                for item in items_in_category:
                    if self.accumulated_loot["items"].get(item, 0) > 0:
                        return False
                count = 1
                break
        if item_name in LIMITED_ONE_TIME_ITEMS:
            if self.accumulated_loot["items"].get(item_name, 0) > 0: return False
            count = 1 
        inventory[item_name] = inventory.get(item_name, 0) + count
        self.accumulated_loot["items"][item_name] = self.accumulated_loot["items"].get(item_name, 0) + count
        return True

    async def trigger_fishing(self, interaction):
        async def fishing_resume_callback(i, acc_loot):
            self.accumulated_loot = acc_loot
            self.last_log = "🎣 낚시를 마쳤습니다."
            self.embed_color = discord.Color.blue()
            await self.advance_turn_and_update(i)

        fishing_view = ResumableFishingGameView(
            self.author, self.user_data, self.save_func,
            0, self.accumulated_loot, fishing_resume_callback,
            self.region_name
        )
        
        embed = discord.Embed(
            title="🎣 물고기 발견!",
            description=f"**{self.region_name}** 조사 중 낚시 기회가 찾아왔습니다.\n낚시를 시도하시겠습니까?",
            color=discord.Color.blue()
        )
        await interaction.edit_original_response(embed=embed, view=fishing_view)

    async def trigger_battle(self, interaction):
        monster_pool = self.get_monster_pool(self.region_name)
        monsters = []
        
        # 1~3마리 랜덤 스폰
        monster_count = random.randint(1, 3)
        for i in range(monster_count):
            m_name = random.choice(monster_pool)
            monster = spawn_monster(m_name)
            if monster_count > 1:
                monster.name = f"{monster.name} {chr(65+i)}" # 여러 마리일 때만 접미사 추가
            monsters.append(monster)
        
        char_idx = self.user_data.get("investigator_index", 0)
        chars = self.user_data.get("characters", [])
        if not chars:
            from character import DEFAULT_PLAYER_DATA
            c = DEFAULT_PLAYER_DATA.copy()
            c.update({"name": self.author.display_name})
            self.user_data["characters"] = [c]
            char_idx = 0
        
        player_data = self.user_data["characters"][char_idx]
        player = Character.from_dict(player_data)
        player.defense_rate = player_data.get("defense_rate", 0)

        async def battle_resume_callback(i, battle_results):
            self.accumulated_loot["money"] += battle_results.get("money", 0)
            self.accumulated_loot["pt"] += battle_results.get("pt", 0)
            for item, qty in battle_results.get("items", {}).items():
                self.accumulated_loot["items"][item] = self.accumulated_loot["items"].get(item, 0) + qty
            
            self.last_log = f"⚔️ **전투 승리!** 몬스터 무리를 소탕했습니다."
            self.embed_color = discord.Color.blue()
            await self.advance_turn_and_update(i)

        view = BattleView(
            self.author, player, monsters, 
            self.user_data, self.save_func, 
            char_index=char_idx,
            victory_callback=battle_resume_callback,
            region_name=self.region_name 
        )
        
        embed = discord.Embed(
            title="⚠️ 적 출현!", 
            description=f"**몬스터 무리({len(monsters)}마리)**가 나타났습니다!\n승리 시 조사를 계속 진행합니다.", 
            color=discord.Color.red()
        )
        await interaction.edit_original_response(embed=embed, view=view)

    async def show_final_result(self, interaction, msg=None):
        embed = discord.Embed(title=f"📝 {self.region_name} 조사 최종 결과", color=discord.Color.green())
        desc = f"{msg}\n\n" if msg else ""
        if self.accumulated_loot["items"]:
            desc += "**[📦 획득 아이템]**\n"
            for item, amount in self.accumulated_loot["items"].items():
                icon = "🔹"
                if item == "신화의 발자취": icon = "💫"
                elif item in RARE_ITEMS: icon = "✨"
                elif item in LIMITED_ONE_TIME_ITEMS: icon = "🗝️"
                desc += f"{icon} {item} x{amount}\n"
        else:
            desc += "획득한 아이템이 없습니다.\n"
            
        if self.accumulated_loot["money"] > 0 or self.accumulated_loot["pt"] > 0:
            desc += f"\n**[💰 추가 획득]**\n돈: {self.accumulated_loot['money']}원\n포인트: {self.accumulated_loot['pt']}pt\n"

        embed.description = desc
        embed.set_footer(text=f"현재 남은 포인트: {self.user_data.get('pt', 0)}pt")
        
        await interaction.edit_original_response(embed=embed, view=None)

    def get_monster_pool(self, region_name):
        unlocked = self.user_data.get("unlocked_regions", [])
        pool = ["약한 원념"]

        if region_name == "기원의 쌍성":
            pool = ["길 잃은 바람비", "약한 원념", "커다란 별기구"]
            if "시간의 신전" in unlocked: pool.extend(["주신의 눈물방울", "예민한 집요정"])
        elif region_name == "시간의 신전":
            pool = ["눈 감은 원념", "약한 원념"]
            if "일한산 중턱" in unlocked: pool.extend(["시간의 방랑자", "과거의 망집"])
        elif region_name == "일한산 중턱":
            pool = ["굴레늑대", "얼어붙은 원념", "경계꽃 골렘"]
            if "이루지 못한 꿈들의 별" in unlocked: pool.extend(["굴레늑대 우두머리", "은하새"])
        elif region_name == "이루지 못한 꿈들의 별":
            pool = ["몽상행인", "살아난 발상", "구체화된 악몽"]
        elif region_name == "생명의 숲":
            pool = ["뒤틀린 식충식물", "굶주린 포식자", "아름다운 나비"]
            if "아르카워드 제도" in unlocked: pool.extend(["냉혹한 원념", "사나운 은하새"])
        elif region_name == "아르카워드 제도":
            pool = ["아사한 원념", "변질된 바람", "폐허를 지키는 문지기"]
        elif region_name == "공간의 신전":
            pool = ["취한 파티원", "겁쟁이 원념", "폭주 거대 짤똥이"]
        
        elif region_name == "노드 해역":
            pool = ["약한 원념"] 

        return pool