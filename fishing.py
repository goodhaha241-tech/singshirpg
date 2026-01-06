# fishing.py
import discord
import random
import asyncio
from items import COMMON_ITEMS, RARE_ITEMS

# --- 물고기 등급 데이터 ---
FISH_TIERS = {
    "common": ["빵잉어", "빵붕어", "민물배스", "피라미"],
    "rare": ["모래무지", "버들치", "쉬리", "각시붕어"],
    "advanced": ["어름치", "동사리", "송사리", "버들매치", "가는돌고기"],
    "node_common": ["메롱물고기", "꽁다리치", "쵸비고기", "밭갱어"],
    "node_rare": ["등불오징어", "명이태", "로운새우", "돔돌치"]
}

# [노드 해역 물고기 해체 보상]
NODE_FISH_REWARDS = {
    "메롱물고기": {"장식용 열쇠": 3, "하급 마력석": 2, "물고기 비늘": 1},
    "등불오징어": {"신전의 등불": 1, "빛구슬": 10, "물고기 비늘": 1},
    "꽁다리치": {"반짝가루": 3, "투명한 유리": 1, "물고기 비늘": 1},
    "명이태": {"기억 종이": 3, "천년얼음": 2, "물고기 비늘": 1},
    "로운새우": {"별모양 별": 3, "낡은 모래시계": 1, "물고기 비늘": 1},
    "쵸비고기": {"반짝가루": 2, "나뭇가지": 8, "물고기 비늘": 2},
    "돔돌치": {"악몽 파편": 2, "빛구슬": 10, "물고기 비늘": 1},
    "밭갱어": {"무지개 열매": 3, "맑은 생각": 1, "물고기 비늘": 1}
}

# 고급 물고기 해체 보상 풀
ADVANCED_REWARD_POOL = [
    "친절함 한 스푼", "다정함 한 스푼", "별자리 망원경", "태양 선글라스", 
    "악몽 프라페", "작은 테라리움", 
    "삶의 문장", "순환의 문장", "형상각인기", "생명의 정수", "정교한 나무조각상", "삶의 흔적", 
    "구름다리 스낵", "아르카워드의 영광", "자그마한 바람", "창공마크", "예쁜 선물상자", 
    "건승의 부적", "행복의 부적", "성공의 부적", "비늘 목걸이", "바닷물고기 회", "카이의 자비"
]

# --- 낚시 단계 정의 ---
FISHING_STAGES = {
    0: {"text": "찌가 잠잠하다...", "prob": 0},
    1: {"text": "조금씩 찌가 흔들린다.", "prob": 5},
    2: {"text": "물고기의 실루엣이 보인다!", "prob": 30},
    3: {"text": "물고기가 미끼를 물었다!", "prob": 75},
    4: {"text": "물고기가 제대로 걸린 듯 하다!", "prob": 100}
}

# --- 시각적 연출 ---
FISHING_SCENES = {
    0: ("☁️　　　　　　　☀️\n　　　　　　　　\n🌊......📍......🌊\n　　(고요함...)"),
    1: ("　　☁️　🌬️　☁️\n　　　　　　　　\n🌊..~...📍...~..🌊\n　　(찰랑찰랑)"),
    2: ("　　　　👀　　　\n　　　　　　　　\n🌊...🐟..📍......🌊\n　(검은 그림자!)"),
    3: ("　　❗　❗　❗　\n　　　　　　　　\n🌊..🐟💥📍......🌊\n　 (강렬한 입질!)"),
    4: ("　✨　🎣　✨　\n　　　　　　　　\n🌊<(((🐟)))=📍/🌊\n　(낚싯대가 휘어진다!)")
}

class FishingView(discord.ui.View):
    def __init__(self, author, user_data, all_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.all_data = all_data
        self.save_func = save_func
        self.page = 0
        
        # [수정] data_manager.py의 DB 필드명(fishing_slots)과 일치하도록 키 관리 권장
        # DB 로드 시 'fishing_slots'로 들어오지만, 여기서는 편의상 fishing 딕셔너리 사용
        if "fishing" not in self.user_data["myhome"]:
             self.user_data["myhome"]["fishing"] = {}
        
        self.fishing_data = self.user_data["myhome"]["fishing"]
        self.fishing_data.setdefault("rod", 0)
        self.fishing_data.setdefault("spot_level", 0)
        # 중요: DB에는 'fishing_slots' 테이블로 저장되므로, save_user_data 호출 전 동기화 필요
        # 여기서는 인메모리 동작을 위해 dismantle_slots 키 사용
        self.fishing_data.setdefault("dismantle_slots", [])
        self.fishing_data.setdefault("max_dismantle_slots", 3)

        self.update_components()

    def get_embed(self):
        rod_names = ["낡은 낚싯대", "고급 낚싯대", "전설의 낚싯대"]
        rod_lvl = self.fishing_data["rod"]
        spot_lvl = self.fishing_data["spot_level"]
        
        rod_desc = rod_names[rod_lvl]
        if rod_lvl == 1: rod_desc += " (고급어종 확률 UP)"
        elif rod_lvl == 2: rod_desc += " (고급어종 확률 대폭 UP, 도망 1회 방지)"
        
        fail_reduce = spot_lvl * 2
        
        embed = discord.Embed(title="🎣 마이홈 낚시터", color=discord.Color.blue())
        embed.add_field(name="시설 정보", 
                        value=f"🎣 장비: **{rod_desc}**\n🌊 낚시터 등급: **{spot_lvl}강** (도망 확률 -{fail_reduce}%)", 
                        inline=False)
        
        slots = self.fishing_data["dismantle_slots"]
        total_invest = self.user_data["myhome"].get("total_investigations", 0)
        
        slots_desc = ""
        for i, slot in enumerate(slots):
            fish_name = slot["fish"]
            prog = total_invest - slot["start_count"]
            req = 50
            
            if prog >= req:
                state = f"✅ **{fish_name}** 해체 완료! (수령 가능)"
            else:
                state = f"🔪 {fish_name} 해체 중... ({prog}/{req})"
            slots_desc += f"**[{i+1}]** {state}\n"
            
        if not slots_desc: slots_desc = "해체 중인 물고기가 없습니다."
        
        max_slots = self.fishing_data.get("max_dismantle_slots", 3)
        embed.add_field(name=f"해체 작업대 ({len(slots)}/{max_slots})", value=slots_desc, inline=False)
        return embed

    def update_components(self):
        self.clear_items()
        
        all_buttons = [
            {"label": "🎣 낚시하기", "style": discord.ButtonStyle.primary, "custom_id": "fish_start"},
            {"label": "🔪 해체 등록", "style": discord.ButtonStyle.secondary, "custom_id": "dismantle"},
            {"label": "🎁 보상 수령", "style": discord.ButtonStyle.success, "custom_id": "claim"},
            {"label": "⬆️ 낚싯대 강화", "style": discord.ButtonStyle.secondary, "custom_id": "up_rod"},
            {"label": "🌊 낚시터 강화", "style": discord.ButtonStyle.secondary, "custom_id": "up_spot"},
        ]
        
        max_slots = self.fishing_data.get("max_dismantle_slots", 3)
        if max_slots < 5:
            all_buttons.append({"label": "🏗️ 작업대 확장", "style": discord.ButtonStyle.secondary, "custom_id": "expand_slot"})

        PER_PAGE = 4
        total_pages = (len(all_buttons) - 1) // PER_PAGE + 1
        if self.page >= total_pages: self.page = max(0, total_pages - 1)

        start_idx = self.page * PER_PAGE
        end_idx = start_idx + PER_PAGE
        current_page_buttons = all_buttons[start_idx:end_idx]

        for btn_info in current_page_buttons:
            self.add_item(discord.ui.Button(label=btn_info["label"], style=btn_info["style"], custom_id=btn_info["custom_id"]))

        if total_pages > 1:
            row = 1
            self.add_item(discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=row, disabled=(self.page == 0), custom_id="prev_page"))
            self.add_item(discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, row=row, disabled=True))
            self.add_item(discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=row, disabled=(self.page >= total_pages - 1), custom_id="next_page"))

        self.add_item(discord.ui.Button(label="🏠 홈으로", style=discord.ButtonStyle.gray, row=2, custom_id="go_home"))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        cid = i.data["custom_id"]
        
        if cid == "fish_start": await self.start_fishing(i)
        elif cid == "dismantle": await self.dismantle_menu(i)
        elif cid == "claim": await self.claim_rewards(i)
        elif cid == "up_rod": await self.upgrade_rod(i)
        elif cid == "up_spot": await self.upgrade_spot(i)
        elif cid == "expand_slot": await self.expand_slots(i)
        elif cid == "go_home": await self.go_home(i)
        elif cid == "prev_page":
            self.page -= 1
            self.update_components()
            await i.response.edit_message(view=self)
        elif cid == "next_page":
            self.page += 1
            self.update_components()
            await i.response.edit_message(view=self)
        return True

    async def start_fishing(self, i):
        view = FishingGameView(self.author, self.user_data, self.all_data, self.save_func)
        await i.response.edit_message(content=None, embed=view.get_embed(), view=view)

    async def dismantle_menu(self, i):
        slots = self.fishing_data["dismantle_slots"]
        max_s = self.fishing_data.get("max_dismantle_slots", 3)
        if len(slots) >= max_s:
            return await i.response.edit_message(content="❌ 해체 작업대가 가득 찼습니다.", embed=self.get_embed(), view=self)
        view = FishSelectView(self.author, self.user_data, self.all_data, self.save_func, self)
        await i.response.edit_message(embed=view.get_embed(), view=view)

    async def claim_rewards(self, i):
        slots = self.fishing_data["dismantle_slots"]
        total_invest = self.user_data["myhome"].get("total_investigations", 0)
        
        completed_idx = [idx for idx, s in enumerate(slots) if total_invest - s["start_count"] >= 50]
        
        if not completed_idx:
            return await i.response.edit_message(content="❌ 완료된 작업이 없습니다. (조사 50회 필요)", embed=self.get_embed(), view=self)
        
        msg = "🎁 **해체 완료 보상**\n"
        inv = self.user_data.setdefault("inventory", {})
        
        all_fish = set()
        for tier_list in FISH_TIERS.values():
            all_fish.update(tier_list)
        
        valid_rare_rewards = [item for item in RARE_ITEMS if item not in all_fish]
        if not valid_rare_rewards: valid_rare_rewards = ["사랑나무 가지"]

        valid_common_rewards = [item for item in COMMON_ITEMS if item not in all_fish]
        if not valid_common_rewards: valid_common_rewards = ["녹슨 철"]

        for idx in sorted(completed_idx, reverse=True):
            fish = slots[idx]["fish"]
            del slots[idx]
            
            rewards = {}
            pt_gain = 0
            money_gain = 0
            
            if fish in NODE_FISH_REWARDS:
                for k, v in NODE_FISH_REWARDS[fish].items():
                    rewards[k] = rewards.get(k, 0) + v
            elif fish in FISH_TIERS["common"]:
                for _ in range(5): 
                    item = random.choice(valid_common_rewards)
                    rewards[item] = rewards.get(item, 0) + 1
                r_item = random.choice(valid_rare_rewards)
                rewards[r_item] = rewards.get(r_item, 0) + 1
            elif fish in FISH_TIERS["rare"]:
                pt_gain = random.randint(100, 500)
                for _ in range(10): 
                    item = random.choice(valid_common_rewards)
                    rewards[item] = rewards.get(item, 0) + 1
                for _ in range(3): 
                    r_item = random.choice(valid_rare_rewards)
                    rewards[r_item] = rewards.get(r_item, 0) + 1
            elif fish in FISH_TIERS["advanced"]:
                money_gain = random.randint(3000, 4000)
                pt_gain = random.randint(200, 550)
                for _ in range(20): 
                    item = random.choice(valid_common_rewards)
                    rewards[item] = rewards.get(item, 0) + 1
                for _ in range(6): 
                    r_item = random.choice(valid_rare_rewards)
                    rewards[r_item] = rewards.get(r_item, 0) + 1
                crafted = random.choice(ADVANCED_REWARD_POOL)
                rewards[crafted] = rewards.get(crafted, 0) + 1
            
            if pt_gain: self.user_data["pt"] += pt_gain
            if money_gain: self.user_data["money"] += money_gain
            
            for k, v in rewards.items():
                inv[k] = inv.get(k, 0) + v
            
            reward_str = ", ".join([f"{k} x{v}" for k, v in rewards.items()])
            extra = ""
            if money_gain: extra += f"{money_gain}원 "
            if pt_gain: extra += f"{pt_gain}pt "
            msg += f"🔹 **{fish}**: {extra}{reward_str}\n"

        # [수정] await 추가 및 인자 전달 수정
        # DB의 fishing_slots와 동기화를 위해 myhome['fishing_slots']에도 반영 필요 시 로직 추가
        # 여기서는 fishing_data가 myhome['fishing']을 참조하고 있다고 가정
        await self.save_func(self.author.id, self.user_data)
        await i.response.edit_message(content=msg, embed=self.get_embed(), view=self)

    async def upgrade_rod(self, i):
        rod = self.fishing_data["rod"]
        inv = self.user_data.get("inventory", {})
        
        if rod >= 2: return await i.response.edit_message(content="❌ 이미 최고 등급입니다.", embed=self.get_embed(), view=self)
        
        if rod == 0: 
            if inv.get("부서진 스틱", 0) < 30 or inv.get("나뭇가지", 0) < 10:
                return await i.response.edit_message(content="❌ 재료 부족 (부서진 스틱 30, 나뭇가지 10)", embed=self.get_embed(), view=self)
            inv["부서진 스틱"] -= 30; inv["나뭇가지"] -= 10
            self.fishing_data["rod"] = 1
        elif rod == 1:
            if inv.get("부서진 스틱", 0) < 100 or inv.get("나뭇가지", 0) < 100:
                return await i.response.edit_message(content="❌ 재료 부족 (부서진 스틱 100, 나뭇가지 100)", embed=self.get_embed(), view=self)
            inv["부서진 스틱"] -= 100; inv["나뭇가지"] -= 100
            self.fishing_data["rod"] = 2
            
        # [수정] await 추가 및 인자 전달 수정
        await self.save_func(self.author.id, self.user_data)
        await i.response.edit_message(content="🎉 낚싯대 강화 성공!", embed=self.get_embed(), view=self)

    async def upgrade_spot(self, i):
        spot = self.fishing_data["spot_level"]
        if spot >= 3: return await i.response.edit_message(content="❌ 낚시터가 최대 레벨입니다.", embed=self.get_embed(), view=self)
        if self.user_data.get("money", 0) < 300000 or self.user_data.get("pt", 0) < 5000:
            return await i.response.edit_message(content="❌ 비용 부족 (300,000원 + 5,000pt)", embed=self.get_embed(), view=self)
        
        self.user_data["money"] -= 300000; self.user_data["pt"] -= 5000
        self.fishing_data["spot_level"] += 1
        # [수정] await 추가 및 인자 전달 수정
        await self.save_func(self.author.id, self.user_data)
        await i.response.edit_message(content="🎉 낚시터 강화 성공!", embed=self.get_embed(), view=self)

    async def expand_slots(self, i):
        cur = self.fishing_data.get("max_dismantle_slots", 3)
        if cur >= 5: return await i.response.edit_message(content="❌ 최대 확장 상태입니다.", embed=self.get_embed(), view=self)
        if self.user_data.get("money", 0) < 50000: return await i.response.edit_message(content="❌ 비용 부족 (50,000원)", embed=self.get_embed(), view=self)
        
        self.user_data["money"] -= 50000
        self.fishing_data["max_dismantle_slots"] = cur + 1
        # [수정] await 추가 및 인자 전달 수정
        await self.save_func(self.author.id, self.user_data)
        await i.response.edit_message(content="🏗️ 작업대 확장 완료!", embed=self.get_embed(), view=self)

    async def go_home(self, interaction):
        # [수정] 순환 참조 방지를 위해 내부 import
        from myhome import MyHomeView
        view = MyHomeView(self.author, self.user_data, self.all_data, self.save_func)
        await interaction.response.edit_message(content="🏠 마이홈으로 이동했습니다.", embed=view.get_embed(), view=view)


class FishingGameView(discord.ui.View):
    def __init__(self, author, user_data, all_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.all_data = all_data
        self.save_func = save_func
        
        self.stage = 0
        self.log = "낚시를 시작했습니다."
        
        f_data = self.user_data["myhome"]["fishing"]
        self.rod_lvl = f_data["rod"]
        self.spot_lvl = f_data["spot_level"]
        self.protection = 1 if self.rod_lvl == 2 else 0

    def get_embed(self):
        info = FISHING_STAGES[self.stage]
        scene = FISHING_SCENES[self.stage]
        
        color = discord.Color.blue()
        bar = "⬛" * 5
        if self.stage == 1: bar = "⬜⬛⬛⬛⬛"
        elif self.stage == 2: bar = "⬜⬜⬛⬛⬛"; color = discord.Color.teal()
        elif self.stage == 3: bar = "⬜⬜⬜⬛⬛"; color = discord.Color.orange()
        elif self.stage == 4: bar = "⬜⬜⬜⬜⬛"; color = discord.Color.red()
        
        embed = discord.Embed(title="🎣 낚시 중...", description=f"```\n{scene}\n```", color=color)
        embed.add_field(name="상태", value=f"{bar}\n**{info['text']}**", inline=False)
        embed.add_field(name="성공 확률", value=f"🎯 **{info['prob']}%**", inline=True)
        
        fail_prob = max(0, 10 - (self.spot_lvl * 2))
        embed.add_field(name="기다리기 정보", value=f"유지 40% / 진전 50% / 도망 {fail_prob}%", inline=True)
        
        if self.protection > 0:
            embed.set_footer(text="🛡️ 전설의 낚싯대가 물고기의 도망을 1회 방지합니다!")
        
        return embed

    @discord.ui.button(label="🎣 낚는다!", style=discord.ButtonStyle.danger)
    async def pull(self, i, b):
        if i.user != self.author: return
        
        success_prob = FISHING_STAGES[self.stage]["prob"]
        roll = random.randint(1, 100)
        
        if roll <= success_prob:
            await self.catch_fish(i)
        else:
            if self.protection > 0:
                self.protection -= 1
                self.log = "⚠️ 물고기가 미끼를 뱉으려 했지만, 전설의 낚싯대가 붙잡았습니다!"
                await i.response.edit_message(embed=self.get_embed(), view=self)
            else:
                await self.fail_fishing(i, "❌ **낚시 실패...** 물고기가 도망갔습니다.")

    @discord.ui.button(label="⏳ 기다린다", style=discord.ButtonStyle.primary)
    async def wait_btn(self, i, b):
        if i.user != self.author: return
        
        fail_base = 10
        fail_prob = max(0, fail_base - (self.spot_lvl * 2))
        next_prob = 50
        
        roll = random.randint(1, 100)
        
        if roll <= fail_prob:
            if self.protection > 0:
                self.protection -= 1
                self.log = "⚠️ 물고기가 눈치채고 도망가려 했지만, 전설의 낚싯대가 막았습니다!"
                await i.response.edit_message(embed=self.get_embed(), view=self)
            else:
                await self.fail_fishing(i, "❌ **낚시 실패...** 너무 오래 기다려서 물고기가 도망갔습니다.")
        elif roll <= fail_prob + next_prob:
            if self.stage < 4:
                self.stage += 1
                self.log = "🌊 찌의 움직임이 변했습니다!"
            else:
                self.log = "❗ 이미 최고조 상태입니다! 낚아야 합니다!"
            await i.response.edit_message(embed=self.get_embed(), view=self)
        else:
            self.log = "...상태가 변하지 않았습니다."
            await i.response.edit_message(embed=self.get_embed(), view=self)

    async def catch_fish(self, i):
        tier_roll = random.random()
        fish_type = "common"
        
        adv_chance = 0.0
        if self.rod_lvl == 1: adv_chance = 0.3
        elif self.rod_lvl == 2: adv_chance = 0.5
        
        if tier_roll > 0.6:
            if random.random() < adv_chance: fish_type = "advanced"
            else: fish_type = "rare"
        
        caught = random.choice(FISH_TIERS[fish_type])
        inv = self.user_data.setdefault("inventory", {})
        inv[caught] = inv.get(caught, 0) + 1
        
        # [수정] await 추가 및 인자 전달 수정
        await self.save_func(self.author.id, self.user_data)
        
        emoji = "🐟" if fish_type == "common" else "✨" if fish_type == "rare" else "👑"
        type_str = "일반" if fish_type == "common" else "희귀" if fish_type == "rare" else "고급"
        
        embed = discord.Embed(title="🎉 낚시 성공!", color=discord.Color.green())
        embed.add_field(name="획득한 물고기", value=f"{emoji} **{caught}** ({type_str})", inline=False)
        embed.set_footer(text=f"현재 보유: {inv.get(caught, 0)}마리")
        
        view = FishingResultView(self.author, self.user_data, self.all_data, self.save_func)
        await i.response.edit_message(content=None, embed=embed, view=view)

    async def fail_fishing(self, i, msg):
        embed = discord.Embed(title="🎣 낚시 실패", description=msg, color=discord.Color.red())
        view = FishingResultView(self.author, self.user_data, self.all_data, self.save_func)
        await i.response.edit_message(content=None, embed=embed, view=view)


class FishingResultView(discord.ui.View):
    def __init__(self, author, user_data, all_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.all_data = all_data
        self.save_func = save_func

    @discord.ui.button(label="🎣 다시 낚기", style=discord.ButtonStyle.success)
    async def retry(self, i, b):
        if i.user != self.author: return
        view = FishingGameView(self.author, self.user_data, self.all_data, self.save_func)
        await i.response.edit_message(content=None, embed=view.get_embed(), view=view)

    @discord.ui.button(label="🏠 낚시터 메인", style=discord.ButtonStyle.secondary)
    async def home(self, i, b):
        if i.user != self.author: return
        view = FishingView(self.author, self.user_data, self.all_data, self.save_func)
        await i.response.edit_message(content=None, embed=view.get_embed(), view=view)


class FishSelectView(discord.ui.View):
    def __init__(self, author, user_data, all_data, save_func, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.all_data = all_data
        self.save_func = save_func
        self.parent = parent_view
        self.add_select()
        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=1, custom_id="back"))

    def get_embed(self):
        return discord.Embed(title="🔪 물고기 해체", description="해체할 물고기를 선택하세요.", color=discord.Color.red())

    def add_select(self):
        inv = self.user_data.get("inventory", {})
        opts = []
        
        all_fish = []
        for tier_list in FISH_TIERS.values():
            all_fish.extend(tier_list)
        
        all_fish = sorted(list(set(all_fish)))
        
        count_opts = 0
        for f in all_fish:
            if inv.get(f, 0) > 0:
                opts.append(discord.SelectOption(label=f"{f} ({inv[f]}마리)", value=f))
                count_opts += 1
                if count_opts >= 25: break 
        
        if not opts: opts.append(discord.SelectOption(label="물고기 없음", value="none"))
        self.add_item(discord.ui.Select(placeholder="물고기 선택", options=opts))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        if i.data.get("custom_id") == "back":
            self.parent.all_data = self.all_data
            self.parent.user_data = self.user_data
            self.parent.fishing_data = self.user_data["myhome"].setdefault("fishing", {})
            self.parent.update_components()
            await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)
            return True
            
        val = i.data["values"][0]
        if val == "none": return
        
        slots = self.user_data["myhome"]["fishing"]["dismantle_slots"]
        inv = self.user_data["inventory"]
        inv[val] -= 1
        if inv[val] <= 0: del inv[val]
        
        slots.append({
            "fish": val,
            "start_count": self.user_data["myhome"].get("total_investigations", 0)
        })
        # [수정] await 추가 및 인자 전달 수정
        await self.save_func(self.author.id, self.user_data)
        
        await i.response.edit_message(content=f"🔪 **{val}** 해체 작업을 시작했습니다!", embed=self.parent.get_embed(), view=self.parent)