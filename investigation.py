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
        self.remaining_runs = remaining_runs
        self.accumulated_loot = accumulated_loot
        self.resume_callback = resume_callback

    @discord.ui.button(label="🏃 남은 조사 계속하기", style=discord.ButtonStyle.success)
    async def continue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        await interaction.response.edit_message(view=None) # 버튼 제거
        await self.resume_callback(interaction, self.remaining_runs, self.accumulated_loot)

class ResumableFishingGameView(FishingGameView):
    """
    기존 FishingGameView를 상속받아, 낚시 종료 시 조사 복귀 로직을 수행하도록 개조한 클래스.
    노드 해역일 경우 전용 물고기를 낚도록 오버라이딩합니다.
    """
    def __init__(self, author, user_data, save_func, remaining_runs, accumulated_loot, resume_callback, region_name):
        # 2. 부모 클래스(FishingGameView)에도 save_func 전달
        # FishingGameView의 생성자가 all_data를 요구한다면 None을 넘기거나 해당 클래스도 수정 필요
        # 여기서는 부모 클래스도 수정되었다고 가정하고 all_data 제거
        super().__init__(author, user_data, None, save_func) 
        
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
        await i.response.edit_message(content=None, embed=embed, view=view)

    async def fail_fishing(self, i, msg):
        # 실패 시에도 조사는 계속되어야 함
        embed = discord.Embed(title="🎣 낚시 실패", description=msg, color=discord.Color.red())
        embed.set_footer(text=f"남은 조사 횟수: {self.remaining_runs}회")
        view = ContinueInvestigationView(self.author, self.remaining_runs, self.accumulated_loot, self.resume_callback)
        await i.response.edit_message(content=None, embed=embed, view=view)


# ==================================================================================
# 메인 조사 뷰
# ==================================================================================
class InvestigationView(discord.ui.View):
    def __init__(self, author, user_data, all_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        # self.all_data = all_data # 사용하지 않음
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
        self.page -= 1
        self.setup_initial_view()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.page += 1
        self.setup_initial_view()
        await interaction.response.edit_message(view=self)

    def add_count_buttons(self):
        self.clear_items()
        btn_1 = discord.ui.Button(label="1회 조사", style=discord.ButtonStyle.primary)
        btn_1.callback = lambda i: self.run_investigation(i, 1)
        btn_5 = discord.ui.Button(label="5회 연속", style=discord.ButtonStyle.success)
        btn_5.callback = lambda i: self.run_investigation(i, 5)
        btn_10 = discord.ui.Button(label="10회 연속", style=discord.ButtonStyle.danger)
        btn_10.callback = lambda i: self.run_investigation(i, 10)
        btn_back = discord.ui.Button(label="지역 다시 선택", style=discord.ButtonStyle.secondary, row=1)
        btn_back.callback = self.back_to_region

        self.add_item(btn_1); self.add_item(btn_5); self.add_item(btn_10); self.add_item(btn_back)

    async def back_to_region(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.selected_region = None
        self.setup_initial_view()
        await interaction.response.edit_message(content="다시 지역을 선택해줘.", view=self)

    def make_region_callback(self, region_name):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.author: return await interaction.response.send_message("본인의 조사만 관리할 수 있어!", ephemeral=True)

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
                return await interaction.response.edit_message(content=f"🔓 **{region_name}** 해금 완료! 다시 선택해줘.", view=self)

            self.selected_region = region_name
            self.add_count_buttons()

            char_name = "알 수 없음"
            chars = self.user_data.get("characters", [])
            idx = self.user_data.get("investigator_index", 0)
            if 0 <= idx < len(chars):
                char_name = chars[idx]["name"]

            await interaction.response.edit_message(content=f"🗺️ **{region_name}**에서 몇 번 조사할까?\n(현재 담당 조사원: **{char_name}**)", view=self)
        return callback

    async def run_investigation(self, interaction: discord.Interaction, count: int, accumulated_loot=None):
        """연속 조사 로직 (전투, 낚시 후 복귀 포함)"""
        if hasattr(interaction, "user") and interaction.user != self.author: return
        
        # JSON 리로드 제거 (DB 사용 시 불필요/오류 원인)
        # self.user_data는 계속 갱신된 상태를 유지한다고 가정

        if accumulated_loot is None:
            accumulated_loot = {"money": 0, "pt": 0, "items": {}}

        region_info = REGIONS[self.selected_region]
        current_pt = self.user_data.get("pt", 0)
        cost_per_run = region_info.get("energy_cost", 2)
        
        max_possible = current_pt // cost_per_run
        actual_runs = min(count, max_possible)
        
        if actual_runs <= 0:
            if accumulated_loot["items"] or accumulated_loot["money"] > 0:
                await self.show_final_result(interaction, accumulated_loot)
                return
            return await interaction.response.send_message("❌ 포인트가 부족해!", ephemeral=True)

        try: await interaction.response.defer()
        except: pass

        battle_triggered = False
        fishing_triggered = False
        target_monster = None
        inv = self.user_data.setdefault("inventory", {})
        buffs = self.user_data.setdefault("buffs", {})

        runs_done_in_this_batch = 0
        
        for i in range(actual_runs):
            runs_done_in_this_batch += 1
            self.user_data["pt"] -= cost_per_run
            
            # [수정] myhome 데이터 안전하게 초기화 (KeyError 방지)
            if not isinstance(self.user_data.get("myhome"), dict):
                self.user_data["myhome"] = {}
            self.user_data["myhome"]["total_investigations"] = self.user_data["myhome"].get("total_investigations", 0) + 1
            
            # 퀘스트 업데이트
            char_idx = self.user_data.get("investigator_index", 0)
            chars = self.user_data.get("characters", [])
            char_name = chars[char_idx]["name"] if chars and char_idx < len(chars) else None
            await update_quest_progress(interaction.user.id, self.user_data, self.save_func, "investigate", 1, self.selected_region, extra_info=char_name)
            
            # [버프 적용] 성공률 계산
            base_fail = region_info["fail_rate"]
            buff_bonus = 0.0
            if "success_rate" in buffs:
                val = buffs["success_rate"].get("value", 0)
                buff_bonus = val / 100.0
                buffs["success_rate"]["duration"] -= 1
                if buffs["success_rate"]["duration"] <= 0: del buffs["success_rate"]
            
            final_fail_rate = max(0.0, base_fail - buff_bonus)
            
            if random.random() > final_fail_rate:
                # 성공
                common_types = random.randint(1, 2)
                for _ in range(common_types):
                    item = random.choice(region_info["common"])
                    self.add_loot(inv, accumulated_loot, item, random.randint(1, 5))

                if "rare" in region_info and random.random() < 0.2:
                    self.add_loot(inv, accumulated_loot, random.choice(region_info["rare"]), random.randint(1, 2))

                if random.random() < 0.02: self.add_loot(inv, accumulated_loot, "신화의 발자취", 1)
            else:
                # 실패 -> 이벤트 분기
                # [수정] 노드 해역: 50% 확률 낚시, 실패 시 전투 없음(조용히 실패)
                if self.selected_region == "노드 해역":
                    if random.random() < 0.5:
                        fishing_triggered = True
                        break 
                    # 낚시가 안 걸리면 그냥 꽝 (루프 계속)
                
                # [수정] 그 외 지역: 50% 확률로 전투 발생
                elif random.random() < 0.5:
                    battle_triggered = True
                    m_name = random.choice(self.get_monster_pool(self.selected_region))
                    target_monster = spawn_monster(m_name)
                    break 

        await self.save_func(self.author.id, self.user_data)
        remaining_runs = count - runs_done_in_this_batch

        # === 이벤트 처리 및 복귀 로직 ===
        
        # 1. 낚시 발생
        if fishing_triggered:
            async def fishing_resume_callback(i, rem_runs, acc_loot):
                msg = f"🎣 **낚시 종료!** 남은 {rem_runs}회 조사를 이어갑니다..."
                await i.channel.send(msg)
                await self.run_investigation(i, rem_runs, acc_loot)

            fishing_view = ResumableFishingGameView(
                interaction.user, self.user_data, 
                self.save_func,
                remaining_runs, accumulated_loot, fishing_resume_callback,
                region_name=self.selected_region 
            )
            
            embed = discord.Embed(
                title=f"🎣 {runs_done_in_this_batch}회차: 물고기 발견!",
                description=f"**{self.selected_region}** 조사에 실패했지만, 낚시 기회가 찾아왔습니다.\n낚시를 시도하시겠습니까?",
                color=discord.Color.blue()
            )
            await interaction.edit_original_response(embed=embed, view=fishing_view)

        # 2. 전투 발생 (노드 해역 제외)
        elif battle_triggered and target_monster:
            if not self.user_data.get("characters"):
                from character import DEFAULT_PLAYER_DATA
                c = DEFAULT_PLAYER_DATA.copy()
                c.update({"name": self.author.display_name})
                self.user_data["characters"] = [c]; self.user_data["investigator_index"] = 0
                await self.save_func(self.author.id, self.user_data)
            
            char_idx = self.user_data.get("investigator_index", 0)
            if char_idx >= len(self.user_data["characters"]): char_idx = 0
            
            player_data = self.user_data["characters"][char_idx]
            player = Character.from_dict(player_data)
            player.defense_rate = player_data.get("defense_rate", 0)
            
            async def battle_resume_callback(i, battle_results):
                accumulated_loot["money"] += battle_results.get("money", 0)
                accumulated_loot["pt"] += battle_results.get("pt", 0)
                for item, qty in battle_results.get("items", {}).items():
                    accumulated_loot["items"][item] = accumulated_loot["items"].get(item, 0) + qty
                
                msg = f"⚔️ **전투 승리!**\n🏃 남은 {remaining_runs}회 조사를 이어갑니다..."
                await i.channel.send(msg)
                
                if remaining_runs > 0:
                    await self.run_investigation(i, remaining_runs, accumulated_loot)
                else:
                    await self.show_final_result(i, accumulated_loot)

            view = BattleView(
                self.author, player, [target_monster], 
                self.user_data, self.save_func, 
                char_index=char_idx,
                victory_callback=battle_resume_callback,
                region_name=self.selected_region 
            )
            
            embed = discord.Embed(
                title=f"⚠️ {runs_done_in_this_batch}회차: 적 출현!", 
                description=f"**{target_monster.name}**이(가) 나타났습니다!\n승리 시 조사를 계속 진행합니다.", 
                color=discord.Color.red()
            )
            await interaction.edit_original_response(embed=embed, view=view)

        # 3. 이벤트 없음 (조사 종료)
        else:
            await self.show_final_result(interaction, accumulated_loot)

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

    async def show_final_result(self, interaction, accumulated_loot):
        embed = discord.Embed(title=f"📝 {self.selected_region} 조사 최종 결과", color=discord.Color.green())
        desc = ""
        if accumulated_loot["items"]:
            desc += "**[📦 획득 아이템]**\n"
            for item, amount in accumulated_loot["items"].items():
                icon = "🔹"
                if item == "신화의 발자취": icon = "💫"
                elif item in RARE_ITEMS: icon = "✨"
                elif item in LIMITED_ONE_TIME_ITEMS: icon = "🗝️"
                desc += f"{icon} {item} x{amount}\n"
        else:
            desc += "획득한 아이템이 없습니다.\n"
            
        if accumulated_loot["money"] > 0 or accumulated_loot["pt"] > 0:
            desc += f"\n**[💰 추가 획득]**\n돈: {accumulated_loot['money']}원\n포인트: {accumulated_loot['pt']}pt\n"

        embed.description = desc
        embed.set_footer(text=f"현재 남은 포인트: {self.user_data.get('pt', 0)}pt")
        
        try: await interaction.edit_original_response(embed=embed, view=None)
        except: await interaction.response.send_message(embed=embed, ephemeral=True)

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