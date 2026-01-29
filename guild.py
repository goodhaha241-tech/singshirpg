# guild.py
import discord
import random
import json
import datetime
from discord.ui import View, Select, Button, Modal, TextInput
from data_manager import get_user_data, get_db_pool, save_user_data
from items import COMMON_ITEMS, RARE_ITEMS, ITEM_PRICES, CRAFT_RECIPES, GUILD_ITEMS, REGIONS
from fishing import FISH_TIERS
from monsters import get_raid_boss, RAID_BOSS_DATA
from character import Character
import battle_engine
from decorators import auto_defer

# --- 설정 데이터 ---
GUILD_RANKS = ["Bronze", "Silver", "Gold", "Platinum", "Diamond"]
RANK_UP_COSTS = {
    "Bronze": {"money": 30000, "pt": 2000}, # Bronze -> Silver 비용
    "Silver": {"money": 50000, "pt": 3000},
    "Gold":   {"money": 100000, "pt": 5000},
    "Platinum": {"money": 200000, "pt": 10000}
}

RANK_TRANSLATION = {
    "Bronze": "브론즈", "Silver": "실버", "Gold": "골드", 
    "Platinum": "플래티넘", "Diamond": "다이아몬드", None: "미가입"
}
TOKEN_TRANSLATION = {
    "wood": "나무 토큰", "iron": "철 토큰", 
    "magic": "마법 토큰", "sorcery": "주술 토큰"
}
STATUS_TRANSLATION = {"OPEN": "모집중", "COMPLETED": "완료됨"}

# 승급 요구 조건 (누적 아님, 해당 등급에서 달성해야 할 횟수)
RANK_REQUIREMENTS = {
    "Bronze": {"process": 100, "refine": 20, "delivery": 20},
    "Silver": {"process": 100, "refine": 30, "delivery": 30, "host_coop": 3},
    "Gold":   {"host_coop": 10, "join_coop": 7, "delivery": 50, "shop_soldout": 20},
    "Platinum": {"shop_soldout": 20, "host_coop": 10, "delivery": 70}
}

# --- 1. 메인 길드 뷰 ---
class GuildMainView(View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self._init_guild_data()
        self.update_buttons()

    def _init_guild_data(self):
        # 길드 데이터 초기화
        if "guild_data" not in self.user_data or not isinstance(self.user_data["guild_data"], dict):
            self.user_data["guild_data"] = {}
        
        g_data = self.user_data["guild_data"]
        
        # 필수 데이터 구조 보장 (누락된 키가 있으면 초기화)
        if "tokens" not in g_data:
            g_data["tokens"] = {"wood": 0, "iron": 0, "magic": 0, "sorcery": 0}
        if "activities" not in g_data:
            g_data["activities"] = {"process": 0, "refine": 0, "delivery": 0, "host_coop": 0, "join_coop": 0, "shop_soldout": 0}
        if "daily_delivery" not in g_data:
            g_data["daily_delivery"] = {"date": "", "count": 0, "refresh_count": 0, "items": {}}
        # [신규] 구버전 데이터 호환 (done -> count)
        if "done" in g_data["daily_delivery"]:
            if g_data["daily_delivery"]["done"]:
                g_data["daily_delivery"]["count"] = 2
            else:
                g_data["daily_delivery"]["count"] = 0
            del g_data["daily_delivery"]["done"]
        # [신규] refresh_count 호환
        if "refresh_count" not in g_data["daily_delivery"]:
            g_data["daily_delivery"]["refresh_count"] = 0
        if "daily_shop" not in g_data:
            g_data["daily_shop"] = {"date": "", "stock": {}}
        
        # 오늘 날짜 체크 및 일일 데이터 리셋
        today = str(datetime.date.today())
        
        if g_data["daily_delivery"].get("date") != today:
            g_data["daily_delivery"] = {
                "date": today, "count": 0, "refresh_count": 0,
                "items": self._generate_daily_delivery()
            }
        # [신규] 납품 완료 후 목록이 비었으면 새로 생성
        elif not g_data["daily_delivery"].get("items") and g_data["daily_delivery"].get("count", 0) < 2:
             g_data["daily_delivery"]["items"] = self._generate_daily_delivery()
        if g_data["daily_shop"].get("date") != today:
             g_data["daily_shop"] = {
                "date": today,
                "stock": self._generate_daily_shop()
             }

    def _generate_daily_delivery(self):
        # 랜덤 납품 목록 생성 (일반템 2종, 희귀템 1종)
        req = {}
        # 일반 아이템 풀 (길드 자재, 상자, 열쇠 제외)
        common_pool = [i for i in COMMON_ITEMS if "토큰" not in i and "목재" not in i and "철괴" not in i and "상자" not in i and "열쇠" not in i]
        for _ in range(2):
            item = random.choice(common_pool)
            req[item] = random.randint(5, 15)
        
        rare_pool = [i for i in RARE_ITEMS if "토큰" not in i and "열쇠" not in i]
        req[random.choice(rare_pool)] = random.randint(1, 3)
        return req

    def _generate_daily_shop(self):
        # 상점 목록 생성 (7종류)
        stock = {}
        pool = []
        
        # 1. 물고기
        for tier_list in FISH_TIERS.values():
            pool.extend(tier_list)
        # 2. 제작 아이템
        for recipe in CRAFT_RECIPES.values():
            pool.append(recipe["result"])
        # 3. 비료
        pool.append("신비한 비료")
        
        selected = random.sample(list(set(pool)), min(7, len(pool)))
        for item in selected:
            # {아이템명: 구매가능횟수}
            stock[item] = 5 
        return stock

    def update_buttons(self):
        self.clear_items()
        rank = self.user_data.get("guild_rank")

        if not rank:
            # 미가입 상태
            btn = Button(label="📝 길드 가입 신청", style=discord.ButtonStyle.success, custom_id="join")
            btn.callback = self.join_callback
            self.add_item(btn)
        else:
            # 메인 메뉴
            self.add_item(self.create_btn("📦 납품/제작", "work", discord.ButtonStyle.primary))
            self.add_item(self.create_btn("🛒 길드 상점", "shop", discord.ButtonStyle.secondary))
            self.add_item(self.create_btn("🤝 협동 제작", "coop", discord.ButtonStyle.success))
            self.add_item(self.create_btn("🏚️ 길드 창고", "warehouse", discord.ButtonStyle.success))
            
            if rank in ["Gold", "Platinum", "Diamond"]:
                self.add_item(self.create_btn("⚔️ 훈련소", "training", discord.ButtonStyle.danger))
                self.add_item(self.create_btn("👹 레이드", "raid", discord.ButtonStyle.danger))

            self.add_item(self.create_btn("⬆️ 등급 승급", "rankup", discord.ButtonStyle.secondary))
            self.add_item(self.create_btn("내 정보", "info", discord.ButtonStyle.secondary))

    def create_btn(self, label, cid, style):
        btn = Button(label=label, custom_id=cid, style=style)
        btn.callback = self.menu_callback
        return btn

    async def join_callback(self, interaction: discord.Interaction):
        # 가입 조건 확인
        inv = self.user_data.get("inventory", {})
        reqs = [
            ("무지개 한조각", 10), ("부유석", 10), ("경계꽃 꽃잎", 10)
        ]
        money_req = 1000000
        pt_req = 100000

        if self.user_data.get("money", 0) < money_req or self.user_data.get("pt", 0) < pt_req:
            return await interaction.response.send_message("❌ 돈(100만) 또는 포인트(10만)가 부족합니다.", ephemeral=True)
        
        for item, count in reqs:
            if inv.get(item, 0) < count:
                return await interaction.response.send_message(f"❌ 재료가 부족합니다: {item} {count}개 필요", ephemeral=True)

        # 차감 및 가입
        self.user_data["money"] -= money_req
        self.user_data["pt"] -= pt_req
        for item, count in reqs:
            inv[item] -= count
            if inv[item] <= 0: del inv[item]
        
        self.user_data["guild_rank"] = "Bronze"
        await self.save_func(self.author.id, self.user_data)
        
        self.update_buttons()
        await interaction.response.edit_message(content="🎉 **여행자 길드**에 가입하신 것을 환영합니다! (등급: 브론즈)", view=self)

    async def menu_callback(self, interaction: discord.Interaction):
        cid = interaction.data["custom_id"]
        rank = self.user_data.get("guild_rank")
        
        if cid == "work":
            view = GuildWorkView(self.author, self.user_data, self.save_func)
            await interaction.response.send_message("🛠️ 작업 항목을 선택하세요.", view=view, ephemeral=True)
        elif cid == "shop":
            if rank == "Bronze":
                return await interaction.response.send_message("❌ 길드 상점은 Silver 등급부터 이용 가능합니다.", ephemeral=True)
            view = GuildShopView(self.author, self.user_data, self.save_func)
            await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)
        elif cid == "coop":
            if rank == "Bronze":
                return await interaction.response.send_message("❌ 협동 제작은 Silver 등급부터 이용 가능합니다.", ephemeral=True)
            view = GuildCoopMainView(self.author, self.user_data, self.save_func)
            await interaction.response.send_message("🤝 협동 제작 게시판입니다.", view=view, ephemeral=True)
        elif cid == "warehouse":
            view = GuildWarehouseView(self.author, self.user_data, self.save_func)
            await view.refresh_ui(interaction)
        elif cid == "training":
            view = GuildTrainingView(self.author, self.user_data, self.save_func)
            await interaction.response.send_message("⚔️ 훈련소에 오신 것을 환영합니다.", view=view, ephemeral=True)
        elif cid == "raid":
            if rank not in ["Gold", "Platinum", "Diamond"]:
                 return await interaction.response.send_message("❌ 레이드는 Gold 등급부터 이용 가능합니다.", ephemeral=True)
            view = GuildRaidLobbyView(self.author, self.user_data, self.save_func)
            await interaction.response.send_message("👹 레이드 로비입니다.", view=view, ephemeral=True)
        elif cid == "info":
            g_data = self.user_data["guild_data"]
            tokens = g_data["tokens"]
            acts = g_data["activities"]
            embed = discord.Embed(title="💳 길드 회원 정보", color=discord.Color.gold())
            embed.add_field(name="등급", value=RANK_TRANSLATION.get(rank, "미가입"))
            embed.add_field(name="보유 토큰", value=f"🌲 {tokens.get('wood',0)} | ⛓️ {tokens.get('iron',0)} | 🔮 {tokens.get('magic',0)} | 🧿 {tokens.get('sorcery',0)}", inline=False)
            embed.add_field(name="활동 내역", value=f"가공: {acts['process']} | 정제: {acts['refine']} | 납품: {acts['delivery']}\n주최: {acts['host_coop']} | 참여: {acts['join_coop']} | 매진: {acts['shop_soldout']}", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        elif cid == "rankup":
            await self.process_rankup(interaction)

    async def process_rankup(self, interaction):
        rank = self.user_data.get("guild_rank")
        if rank == "Diamond":
            return await interaction.response.send_message("💎 이미 최고 등급입니다.", ephemeral=True)
        
        next_ranks = {"Bronze": "Silver", "Silver": "Gold", "Gold": "Platinum", "Platinum": "Diamond"}
        next_rank = next_ranks.get(rank)
        
        rank_kr = RANK_TRANSLATION.get(rank, rank)
        next_rank_kr = RANK_TRANSLATION.get(next_rank, next_rank)
        req = RANK_REQUIREMENTS.get(rank, {})
        cost = RANK_UP_COSTS.get(rank, {})
        acts = self.user_data["guild_data"]["activities"]
        
        # 조건 확인
        conditions_met = True
        msg_lines = [f"**[{rank_kr} ➔ {next_rank_kr} 승급 조건]**"]
        
        key_map = {
            "process": "자재 가공",
            "refine": "자재 고급화",
            "delivery": "오늘의 자재 납품",
            "host_coop": "협동 제작 주최",
            "join_coop": "협동 제작 참여",
            "shop_soldout": "길드 상점 매진 품목 수"
        }
        
        for key, val in req.items():
            current = acts.get(key, 0)
            mark = "✅" if current >= val else "❌"
            k_name = key_map.get(key, key)
            msg_lines.append(f"{mark} {k_name}: {current}/{val}")
            if current < val: conditions_met = False
            
        # 비용 확인
        cur_money = self.user_data.get("money", 0)
        cur_pt = self.user_data.get("pt", 0)
        m_mark = "✅" if cur_money >= cost.get("money", 0) else "❌"
        p_mark = "✅" if cur_pt >= cost.get("pt", 0) else "❌"
        
        msg_lines.append(f"\n{m_mark} 비용: {cost.get('money', 0)}원")
        msg_lines.append(f"{p_mark} 포인트: {cost.get('pt', 0)}pt")
        
        if conditions_met and cur_money >= cost.get("money", 0) and cur_pt >= cost.get("pt", 0):
            self.user_data["money"] -= cost["money"]
            self.user_data["pt"] -= cost["pt"]
            self.user_data["guild_rank"] = next_rank
            
            # 활동 내역 리셋 (해당 등급에서의 활동이므로)
            self.user_data["guild_data"]["activities"] = {k:0 for k in acts} 
            
            await self.save_func(self.author.id, self.user_data)
            await interaction.response.send_message(f"🎉 **{next_rank_kr}** 등급으로 승급했습니다!\n" + "\n".join(msg_lines), ephemeral=True)
        else:
            await interaction.response.send_message("\n".join(msg_lines), ephemeral=True)

# --- 2. 작업/납품 뷰 ---
class GuildWorkView(View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func

    def _generate_daily_delivery(self):
        # 랜덤 납품 목록 생성 (일반템 2종, 희귀템 1종)
        req = {}
        # 일반 아이템 풀 (길드 자재, 상자, 열쇠 제외)
        common_pool = [i for i in COMMON_ITEMS if "토큰" not in i and "목재" not in i and "철괴" not in i and "상자" not in i and "열쇠" not in i]
        for _ in range(2):
            item = random.choice(common_pool)
            req[item] = random.randint(5, 15)
        
        rare_pool = [i for i in RARE_ITEMS if "토큰" not in i and "열쇠" not in i]
        req[random.choice(rare_pool)] = random.randint(1, 3)
        return req
    
    @discord.ui.button(label="📦 오늘의 자재 납품", style=discord.ButtonStyle.primary)
    async def daily_delivery(self, interaction: discord.Interaction, button: discord.ui.Button):
        g_data = self.user_data["guild_data"]
        delivery = g_data["daily_delivery"]
        
        if delivery.get("count", 0) >= 2:
            return await interaction.response.send_message("✅ 오늘은 납품을 모두 완료했습니다.", ephemeral=True)
        
        if not delivery.get("items"):
            return await interaction.response.send_message("❌ 납품 목록을 불러올 수 없습니다. 길드 메인 화면을 다시 열어주세요.", ephemeral=True)
        
        # 등급별 추가 요구사항 (간소화: 기본 생성된 items에 추가 로직은 생략하고 보상만 차등 지급)
        rank = self.user_data.get("guild_rank")
        
        # 아이템 확인
        inv = self.user_data.get("inventory", {})
        missing = []
        for item, count in delivery["items"].items():
            if inv.get(item, 0) < count:
                missing.append(f"{item} ({inv.get(item, 0)}/{count})")
        
        if missing:
            req_str = "\n".join([f"- {k} x{v}" for k,v in delivery["items"].items()])
            return await interaction.response.send_message(f"❌ 재료가 부족합니다.\n**[필요 품목]**\n{req_str}\n\n**[부족]**\n" + ", ".join(missing), ephemeral=True)
        
        # 납품 처리
        for item, count in delivery["items"].items():
            inv[item] -= count
            if inv[item] <= 0: del inv[item]
            
        delivery["count"] = delivery.get("count", 0) + 1
        delivery["items"] = {} # 목록 비우기 -> 다음에 길드창 열 때 재생성됨
        g_data["activities"]["delivery"] += 1
        
        # 보상 지급
        tokens = g_data["tokens"]
        bonus = 5 if rank == "Diamond" else 0
        
        # 기본 보상 + 등급 보상
        tokens["wood"] += 30 + bonus
        msg = "📦 납품 완료! (나무 토큰 +30)"
        
        if rank in ["Silver", "Gold", "Platinum", "Diamond"]:
            tokens["iron"] += 30 + bonus
            msg += ", (철 토큰 +30)"
        if rank in ["Gold", "Platinum", "Diamond"]:
            tokens["magic"] += 30 + bonus
            msg += ", (마법 토큰 +30)"
        if rank in ["Platinum", "Diamond"]:
            tokens["sorcery"] += 30 + bonus
            msg += ", (주술 토큰 +30)"
        
        if delivery["count"] < 2:
            msg += f"\n\n✅ 다음 납품이 생성되었습니다! ({delivery['count']}/2)"
        else:
            msg += "\n\n✅ 오늘의 납품을 모두 완료했습니다!"

        await self.save_func(self.author.id, self.user_data)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="🔄 납품 새로고침 (300pt)", style=discord.ButtonStyle.danger)
    async def refresh_delivery(self, interaction: discord.Interaction, button: discord.ui.Button):
        g_data = self.user_data["guild_data"]
        delivery_data = g_data["daily_delivery"]
        
        if delivery_data.get("refresh_count", 0) >= 2:
            return await interaction.response.send_message("❌ 오늘은 더 이상 새로고침할 수 없습니다.", ephemeral=True)
            
        if self.user_data.get("pt", 0) < 300:
            return await interaction.response.send_message("❌ 포인트가 부족합니다. (300pt 필요)", ephemeral=True)
            
        if delivery_data.get("count", 0) >= 2:
            return await interaction.response.send_message("✅ 오늘은 납품을 모두 완료하여 새로고침할 수 없습니다.", ephemeral=True)

        self.user_data["pt"] -= 300
        delivery_data["refresh_count"] = delivery_data.get("refresh_count", 0) + 1
        delivery_data["items"] = self._generate_daily_delivery()

        await self.save_func(self.author.id, self.user_data)
        
        req_str = "\n".join([f"- {k} x{v}" for k,v in delivery_data["items"].items()])
        await interaction.response.send_message(
            f"🔄 납품 목록을 새로고침했습니다! (남은 횟수: {2 - delivery_data['refresh_count']}회)\n\n**[신규 납품 목록]**\n{req_str}", 
            ephemeral=True
        )

    @discord.ui.button(label="🪵 자재 가공/정제", style=discord.ButtonStyle.secondary)
    async def process_material(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = MaterialProcessView(self.author, self.user_data, self.save_func)
        await interaction.response.send_message("가공할 레시피를 선택하세요.", view=view, ephemeral=True)

    @discord.ui.button(label="🔄 토큰 환전", style=discord.ButtonStyle.success)
    async def exchange_token(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TokenExchangeView(self.author, self.user_data, self.save_func)
        await interaction.response.send_message("환전할 토큰을 선택하세요.", view=view, ephemeral=True)

class MaterialProcessView(View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.add_recipe_select()

    def add_recipe_select(self):
        # 가공 레시피
        recipes = [
            ("목재", "평범한 나무판자", 10),
            ("철괴", "녹슨 철", 10),
            ("중급 마력석", "하급 마력석", 10),
            ("구름 블럭", "구름 한 줌", 10),
            # 정제 레시피
            ("양질 목재", "목재 1 + 사랑나무 가지 5", 0),
            ("강화 철강", "철괴 1 + 부유석 5", 0),
            ("상급 마력석", "중급 마력석 1 + 창공의 은혜 5", 0),
            ("고급 주술석", "주술석 1 + 별모양 별 5", 0),
            ("응결 구름 블럭", "구름 블럭 1 + 혹한의 눈꽃 5", 0)
        ]
        
        options = []
        for res, req, count in recipes:
            label = f"제작: {res}"
            desc = f"재료: {req}"
            options.append(discord.SelectOption(label=label, description=desc, value=res))
            
        select = Select(placeholder="레시피 선택", options=options)
        select.callback = self.process_callback
        self.add_item(select)

    async def process_callback(self, interaction: discord.Interaction):
        target = interaction.data['values'][0]
        # 모달로 수량 입력 받기
        await interaction.response.send_modal(ProcessAmountModal(self.author, self.user_data, self.save_func, target))

class ProcessAmountModal(Modal):
    def __init__(self, author, user_data, save_func, target_item):
        super().__init__(title=f"{target_item} 제작")
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.target_item = target_item
        self.amount = TextInput(label="수량", placeholder="숫자 입력", required=True)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.amount.value)
            if count <= 0: raise ValueError
        except:
            return await interaction.response.send_message("❌ 올바른 숫자를 입력하세요.", ephemeral=True)

        inv = self.user_data.get("inventory", {})
        reqs = {}
        
        # 레시피 정의
        if self.target_item == "목재": reqs = {"평범한 나무판자": 10 * count}
        elif self.target_item == "철괴": reqs = {"녹슨 철": 10 * count}
        elif self.target_item == "중급 마력석": reqs = {"하급 마력석": 10 * count}
        elif self.target_item == "구름 블럭": reqs = {"구름 한 줌": 10 * count}
        elif self.target_item == "주술석": reqs = {"부유석": 7 * count, "무지개 한조각": 3 * count}
        
        elif self.target_item == "양질 목재": reqs = {"목재": 1 * count, "사랑나무 가지": 5 * count}
        elif self.target_item == "강화 철강": reqs = {"철괴": 1 * count, "부유석": 5 * count}
        elif self.target_item == "상급 마력석": reqs = {"중급 마력석": 1 * count, "창공의 은혜": 5 * count}
        elif self.target_item == "고급 주술석": reqs = {"주술석": 1 * count, "별모양 별": 5 * count}
        elif self.target_item == "응결 구름 블럭": reqs = {"구름 블럭": 1 * count, "혹한의 눈꽃": 5 * count}

        # 재료 확인
        for item, req_count in reqs.items():
            if inv.get(item, 0) < req_count:
                return await interaction.response.send_message(f"❌ 재료 부족: {item} ({inv.get(item,0)}/{req_count})", ephemeral=True)

        # 차감 및 지급
        for item, req_count in reqs.items():
            inv[item] -= req_count
            if inv[item] <= 0: del inv[item]
            
        inv[self.target_item] = inv.get(self.target_item, 0) + count
        
        # 활동 카운트
        act_type = "refine" if self.target_item in ["양질 목재", "강화 철강", "상급 마력석", "고급 주술석", "응결 구름 블럭"] else "process"
        self.user_data["guild_data"]["activities"][act_type] += count
        
        await self.save_func(self.author.id, self.user_data)
        await interaction.response.send_message(f"✅ **{self.target_item}** {count}개 제작 완료!", ephemeral=True)

class TokenExchangeView(View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        
        options = [
            discord.SelectOption(label="나무 토큰 10 -> 철 토큰 1", value="wood_to_iron"),
            discord.SelectOption(label="철 토큰 10 -> 마법 토큰 1", value="iron_to_magic"),
            discord.SelectOption(label="마법 토큰 10 -> 주술 토큰 1", value="magic_to_sorcery")
        ]
        select = Select(placeholder="환전 선택", options=options)
        select.callback = self.exchange_callback
        self.add_item(select)

    async def exchange_callback(self, interaction: discord.Interaction):
        val = interaction.data['values'][0]
        tokens = self.user_data["guild_data"]["tokens"]
        
        if val == "wood_to_iron":
            if tokens.get("wood", 0) < 10: return await interaction.response.send_message("❌ 나무 토큰 부족", ephemeral=True)
            tokens["wood"] -= 10; tokens["iron"] = tokens.get("iron", 0) + 1
        elif val == "iron_to_magic":
            if tokens.get("iron", 0) < 10: return await interaction.response.send_message("❌ 철 토큰 부족", ephemeral=True)
            tokens["iron"] -= 10; tokens["magic"] = tokens.get("magic", 0) + 1
        elif val == "magic_to_sorcery":
            if tokens.get("magic", 0) < 10: return await interaction.response.send_message("❌ 마법 토큰 부족", ephemeral=True)
            tokens["magic"] -= 10; tokens["sorcery"] = tokens.get("sorcery", 0) + 1
            
        await self.save_func(self.author.id, self.user_data)
        await interaction.response.send_message("✅ 환전 완료!", ephemeral=True)

# --- 3. 협동 제작 뷰 ---
class GuildCoopMainView(View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func

    @discord.ui.button(label="📢 제작 주최하기", style=discord.ButtonStyle.success)
    async def host_coop(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = CoopRegionSelectView(self.author, self.user_data, self.save_func)
        await interaction.response.send_message("제작할 아이템의 지역을 선택하세요.", view=view, ephemeral=True)

    @discord.ui.button(label="📋 제작 게시판 보기", style=discord.ButtonStyle.primary)
    async def view_board(self, interaction: discord.Interaction, button: discord.ui.Button):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM coop_sessions WHERE status='OPEN' ORDER BY id DESC LIMIT 5")
                rows = await cur.fetchall()
        
        if not rows:
            return await interaction.response.send_message("📭 현재 진행 중인 협동 제작이 없습니다.", ephemeral=True)
        
        embed = discord.Embed(title="🔨 협동 제작 게시판", color=discord.Color.blue())
        view = View()
        
        for row in rows:
            # row: (id, host_id, host_name, item, target, current, status, participants, time)
            session_id = row[0]
            item_key = row[3]
            recipe = CRAFT_RECIPES.get(item_key, {})
            item_name = recipe.get("result", item_key)
            progress = f"{row[5]}/{row[4]}"
            embed.add_field(name=f"#{session_id} {item_name} 제작 ({row[2]})", value=f"진행도: {progress}회\n참가비: 나무 토큰 1개", inline=False)
            
            join_btn = Button(label=f"#{session_id} 조회", style=discord.ButtonStyle.secondary, custom_id=f"view_{session_id}")
            join_btn.callback = self.make_view_callback(session_id)
            view.add_item(join_btn)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def make_view_callback(self, session_id):
        async def callback(interaction: discord.Interaction):
            view = CoopSessionView(self.author, session_id, self.save_func)
            await view.refresh_status(interaction)
        return callback

class CoopSessionView(View):
    def __init__(self, author, session_id, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.session_id = session_id
        self.save_func = save_func
        self.session_data = None

    async def refresh_status(self, interaction: discord.Interaction):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM coop_sessions WHERE id=%s", (self.session_id,))
                self.session_data = await cur.fetchone()
        
        if not self.session_data:
            return await interaction.response.send_message("❌ 존재하지 않는 세션입니다.", ephemeral=True)

        # session_data: (id, host_id, host_name, item, target, current, status, participants, time)
        item_key = self.session_data[3]
        target = self.session_data[4]
        current = self.session_data[5]
        status = self.session_data[6]
        try: participants = json.loads(self.session_data[7])
        except: participants = []
        
        recipe = CRAFT_RECIPES.get(item_key, {})
        item_name = recipe.get("result", item_key)
        is_participant = self.author.id in participants
        
        embed = discord.Embed(title=f"🔨 협동 제작: {item_name}", color=discord.Color.blue())
        embed.add_field(name="진행 상황", value=f"**{current} / {target}** 회 제작", inline=True)
        embed.add_field(name="참여자", value=f"{len(participants)}명", inline=True)
        embed.add_field(name="상태", value=STATUS_TRANSLATION.get(status, status), inline=True)
        
        req_str = "\n".join([f"- {k} x{v}" for k, v in recipe.get("need", {}).items()])
        embed.add_field(name="1회 제작 재료", value=req_str or "없음", inline=False)
        
        embed.set_footer(text="참가비: 나무 토큰 1개 | 보상: 전체 결과물 1/N 분배")

        self.clear_items()
        
        if status == 'OPEN':
            if not is_participant:
                btn = Button(label="참가하기 (나무 토큰 1개)", style=discord.ButtonStyle.success, custom_id="join")
                btn.callback = self.join_callback
                self.add_item(btn)
            else:
                btn = Button(label="재료 납품 (제작)", style=discord.ButtonStyle.primary, custom_id="contribute")
                btn.callback = self.contribute_callback
                self.add_item(btn)
        else:
            self.add_item(Button(label="종료됨", disabled=True))

        refresh_btn = Button(label="새로고침", style=discord.ButtonStyle.secondary, custom_id="refresh")
        refresh_btn.callback = self.refresh_callback
        self.add_item(refresh_btn)

        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    async def refresh_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.refresh_status(interaction)

    async def join_callback(self, interaction: discord.Interaction):
        user_data = await get_user_data(self.author.id, self.author.display_name)
        tokens = user_data["guild_data"]["tokens"]
        
        if tokens.get("wood", 0) < 1:
            return await interaction.response.send_message("❌ 나무 토큰이 부족합니다.", ephemeral=True)
        
        tokens["wood"] -= 1
        user_data["guild_data"]["activities"]["join_coop"] += 1
        await self.save_func(self.author.id, user_data)
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                # 참가자 목록 갱신
                try: participants = json.loads(self.session_data[7])
                except: participants = []
                
                if self.author.id not in participants:
                    participants.append(self.author.id)
                    await cur.execute("UPDATE coop_sessions SET participants=%s WHERE id=%s", (json.dumps(participants), self.session_id))
                    await conn.commit()
        
        await interaction.response.send_message("✅ 참가 완료! 이제 재료를 납품하여 제작에 기여할 수 있습니다.", ephemeral=True)
        await self.refresh_status(interaction)

    async def contribute_callback(self, interaction: discord.Interaction):
        view = CoopContributeView(self.author, self.session_id, self.session_data, self.save_func, self)
        await interaction.response.send_message("몇 번 제작하시겠습니까?", view=view, ephemeral=True)

class CoopContributeView(View):
    def __init__(self, author, session_id, session_data, save_func, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.session_id = session_id
        self.session_data = session_data
        self.save_func = save_func
        self.parent_view = parent_view
        
        self.add_item(Button(label="1회", style=discord.ButtonStyle.primary, custom_id="c1"))
        self.add_item(Button(label="5회", style=discord.ButtonStyle.primary, custom_id="c5"))
        self.add_item(Button(label="10회", style=discord.ButtonStyle.primary, custom_id="c10"))
        self.add_item(Button(label="최대", style=discord.ButtonStyle.success, custom_id="c_max"))
        self.add_item(Button(label="취소", style=discord.ButtonStyle.secondary, custom_id="cancel"))

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return False
        
        cid = interaction.data.get("custom_id")
        if cid == "cancel":
            await interaction.response.edit_message(content="납품을 취소했습니다.", view=None)
            return False
        
        count = 0
        if cid == "c1": count = 1
        elif cid == "c5": count = 5
        elif cid == "c10": count = 10
        elif cid == "c_max": count = "max"
        
        await self.process_contribute(interaction, count)
        return False

    async def process_contribute(self, interaction, count_input):
        await interaction.response.defer(ephemeral=True)

        # DB에서 최신 세션 데이터 확인
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM coop_sessions WHERE id=%s", (self.session_id,))
                self.session_data = await cur.fetchone()

        if not self.session_data:
             return await interaction.followup.send("❌ 세션이 존재하지 않습니다.", ephemeral=True)

        item_key = self.session_data[3]
        target = self.session_data[4]
        current = self.session_data[5]
        status = self.session_data[6]

        if status != 'OPEN':
             return await interaction.followup.send("❌ 이미 종료된 세션입니다.", ephemeral=True)
        
        remaining = target - current
        if remaining <= 0:
             return await interaction.followup.send("❌ 이미 목표를 달성했습니다.", ephemeral=True)

        recipe = CRAFT_RECIPES.get(item_key)
        if not recipe: return await interaction.followup.send("❌ 레시피 오류.", ephemeral=True)

        user_data = await get_user_data(self.author.id, self.author.display_name)
        inv = user_data.get("inventory", {})

        # 최대 제작 가능 횟수 계산
        max_craftable = 999999
        for mat, req in recipe["need"].items():
            if req > 0:
                max_craftable = min(max_craftable, inv.get(mat, 0) // req)
            else:
                max_craftable = 0
        
        if count_input == "max":
            count = min(max_craftable, remaining)
        else:
            count = int(count_input)
        
        if count <= 0:
            return await interaction.followup.send("❌ 제작 가능한 재료가 없거나 수량이 올바르지 않습니다.", ephemeral=True)
        
        if count > remaining:
            return await interaction.followup.send(f"❌ 남은 횟수({remaining}회)보다 많이 제작할 수 없습니다.", ephemeral=True)

        if count > max_craftable:
             return await interaction.followup.send(f"❌ 재료가 부족합니다. (최대 {max_craftable}회 가능)", ephemeral=True)

        # 재료 차감
        for mat, req in recipe["need"].items():
            inv[mat] -= (req * count)
            if inv[mat] <= 0: del inv[mat]
            
        await self.save_func(self.author.id, user_data)
        
        # DB 업데이트
        new_current = current + count
        is_completed = (new_current >= target)
        new_status = 'COMPLETED' if is_completed else 'OPEN'
        
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE coop_sessions SET current_count=%s, status=%s WHERE id=%s", (new_current, new_status, self.session_id))
                await conn.commit()

        msg = f"✅ **{count}회** 제작 기여 완료! (현재: {new_current}/{target})"
        
        if is_completed:
            msg += "\n🎉 **목표 달성!** 보상이 분배됩니다."
            await self.distribute_rewards(interaction, item_key, target, recipe)
        
        await interaction.followup.send(msg, ephemeral=True)
        await self.parent_view.refresh_status(interaction)

    async def distribute_rewards(self, interaction, item_name, target_count, recipe):
        # 보상 분배 로직
        try: participants = json.loads(self.session_data[7])
        except: participants = []
        
        if not participants: return
        
        # 총 결과물 수 = (목표 제작 횟수) * (1회당 결과물 수)
        total_items = target_count * recipe.get("count", 1)
        share = total_items // len(participants)
        
        if share <= 0: return

        result_name = recipe.get("result", item_name)
        for uid in participants:
            try:
                # 오프라인 유저 데이터 로드 및 저장
                u_data = await get_user_data(uid) # 이름은 생략 가능
                inv = u_data.setdefault("inventory", {})
                inv[result_name] = inv.get(result_name, 0) + share
                await save_user_data(uid, u_data)

                # [신규] DM 알림 전송
                try:
                    user = interaction.client.get_user(uid)
                    if not user:
                        user = await interaction.client.fetch_user(uid)
                    
                    if user:
                        embed = discord.Embed(
                            title="🔨 협동 제작 완료 알림",
                            description=f"참여하신 **[{result_name}]** 제작 세션이 완료되었습니다!\n보상으로 **{share}개**가 인벤토리에 지급되었습니다.",
                            color=discord.Color.green()
                        )
                        await user.send(embed=embed)
                except Exception as e:
                    print(f"DM send failed for {uid}: {e}")
            except Exception as e:
                print(f"Reward distribution failed for {uid}: {e}")

        await interaction.followup.send(f"📢 **[협동 제작 완료]** 참여자 {len(participants)}명에게 각각 **{result_name} {share}개**가 지급되었습니다!", ephemeral=False)

# --- [신규] 협동 제작 주최 뷰 (지역 -> 아이템 -> 수량) ---
class CoopRegionSelectView(View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.add_region_select()

    def add_region_select(self):
        # 제작 가능한 아이템이 있는 지역만 필터링
        craft_regions = set()
        for recipe in CRAFT_RECIPES.values():
            craft_regions.add(recipe.get("region", "기원의 쌍성"))
        
        sorted_regions = [r for r in REGIONS.keys() if r in craft_regions]
        # REGIONS에 없는 지역(기타 등) 처리
        for r in craft_regions:
            if r not in sorted_regions: sorted_regions.append(r)

        options = []
        for region in sorted_regions:
            options.append(discord.SelectOption(label=region, value=region))

        if not options:
            options.append(discord.SelectOption(label="제작 가능 지역 없음", value="none"))

        select = Select(placeholder="지역 선택", options=options[:25])
        select.callback = self.region_callback
        self.add_item(select)

    async def region_callback(self, interaction: discord.Interaction):
        region = interaction.data['values'][0]
        if region == "none": return
        
        view = CoopItemSelectView(self.author, self.user_data, self.save_func, region)
        await interaction.response.edit_message(content=f"🔨 **[{region}]** 제작할 아이템을 선택하세요.", view=view)

class CoopItemSelectView(View):
    def __init__(self, author, user_data, save_func, region):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.region = region
        self.add_item_select()

    def add_item_select(self):
        options = []
        for key, recipe in CRAFT_RECIPES.items():
            if recipe.get("region", "기원의 쌍성") == self.region:
                res_name = recipe["result"]
                options.append(discord.SelectOption(label=res_name, value=key)) # value는 레시피 키
        
        if not options:
            options.append(discord.SelectOption(label="아이템 없음", value="none"))

        select = Select(placeholder="아이템 선택", options=options[:25])
        select.callback = self.item_callback
        self.add_item(select)
        self.add_item(Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.secondary, custom_id="back"))

    async def interaction_check(self, interaction):
        if interaction.data.get("custom_id") == "back":
            view = CoopRegionSelectView(self.author, self.user_data, self.save_func)
            await interaction.response.edit_message(content="제작할 아이템의 지역을 선택하세요.", view=view)
            return False
        return True

    async def item_callback(self, interaction: discord.Interaction):
        recipe_key = interaction.data['values'][0]
        if recipe_key == "none": return
        
        view = CoopAmountSelectView(self.author, self.user_data, self.save_func, recipe_key)
        res_name = CRAFT_RECIPES[recipe_key]["result"]
        await interaction.response.edit_message(content=f"🔨 **{res_name}** 목표 수량을 선택하세요.", view=view)

class CoopAmountSelectView(View):
    def __init__(self, author, user_data, save_func, recipe_key):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.recipe_key = recipe_key
        
        # 50개 단위 버튼
        for amount in [50, 100, 150, 200]:
            btn = Button(label=f"{amount}개", style=discord.ButtonStyle.primary, custom_id=f"amt_{amount}")
            btn.callback = self.make_callback(amount)
            self.add_item(btn)
            
        self.add_item(Button(label="취소", style=discord.ButtonStyle.danger, custom_id="cancel"))

    def make_callback(self, amount):
        async def callback(interaction: discord.Interaction):
            await self.process_host(interaction, amount)
        return callback

    async def process_host(self, interaction, count):
        # 비용 계산 (주최비: 나무 토큰 5개 고정)
        tokens = self.user_data["guild_data"]["tokens"]
        cost_wood = 5
        
        if tokens.get("wood", 0) < cost_wood:
            return await interaction.response.send_message(f"❌ 주최 비용 부족 (나무 토큰 {cost_wood}개 필요)", ephemeral=True)
            
        tokens["wood"] -= cost_wood
        self.user_data["guild_data"]["activities"]["host_coop"] += 1
        
        await self.save_func(self.author.id, self.user_data)
        
        # DB 등록
        # 호스트도 자동으로 참가자로 등록
        item_name = CRAFT_RECIPES[self.recipe_key]["result"]
        participants = json.dumps([self.author.id])
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO coop_sessions (host_id, host_name, item_name, target_count, current_count, status, participants)
                    VALUES (%s, %s, %s, %s, 0, 'OPEN', %s)
                """, (self.author.id, self.author.display_name, self.recipe_key, count, participants))
                await conn.commit()
                
        await interaction.response.edit_message(content=f"📢 **{item_name}** {count}회 제작 세션을 열었습니다! (주최자 자동 참가)", view=None)

    async def interaction_check(self, interaction):
        if interaction.data.get("custom_id") == "cancel":
            await interaction.response.edit_message(content="협동 제작 주최가 취소되었습니다.", view=None)
            return False
        return True

# --- 4. 길드 상점 뷰 ---
class GuildShopView(View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.shop_data = self.user_data["guild_data"]["daily_shop"]
        self.update_select()

    def get_embed(self):
        embed = discord.Embed(title="🛒 길드 상점", description="매일 갱신됩니다.", color=discord.Color.gold())
        for item, count in self.shop_data["stock"].items():
            price_text = self.get_price_text(item)
            status = f"(남은 수량: {count})" if count > 0 else "❌ **매진**"
            embed.add_field(name=item, value=f"{price_text}\n{status}", inline=True)
        return embed

    def calculate_price(self, item):
        cost = {}
        rank = self.user_data.get("guild_rank")
        
        # 1. 물고기 가격
        fish_tier = None
        for tier, fishes in FISH_TIERS.items():
            if item in fishes:
                fish_tier = tier
                break
        
        if fish_tier:
            if fish_tier in ["common", "node_common"]: cost = {"wood": 7}
            elif fish_tier in ["rare", "node_rare"]: cost = {"iron": 5}
            elif fish_tier == "advanced": cost = {"iron": 9}
        
        # 2. 비료 가격
        elif item == "신비한 비료":
            cost = {"iron": 3}
            
        # 3. 제작 아이템 가격
        else:
            recipe = next((r for r in CRAFT_RECIPES.values() if r["result"] == item), None)
            if recipe:
                region = recipe.get("region", "기원의 쌍성")
                if region in ["기원의 쌍성", "시간의 신전", "일한산 중턱"]: cost = {"wood": 9, "iron": 4}
                elif region in ["이루지 못한 꿈들의 별", "생명의 숲", "아르카워드 제도"]: cost = {"iron": 9, "magic": 4}
                elif region in ["노드 해역", "공간의 신전"]: cost = {"magic": 9, "sorcery": 4}
        
        # 다이아몬드 등급 보너스 (가장 낮은 등급 토큰 -2)
        if rank == "Diamond" and cost:
            for token in ["wood", "iron", "magic", "sorcery"]:
                if token in cost:
                    cost[token] = max(1, cost[token] - 2)
                    break
        return cost

    def get_price_text(self, item):
        cost = self.calculate_price(item)
        if not cost: return "가격 정보 없음"
        
        txt = []
        if "wood" in cost: txt.append(f"🌲 {cost['wood']}")
        if "iron" in cost: txt.append(f"⛓️ {cost['iron']}")
        if "magic" in cost: txt.append(f"🔮 {cost['magic']}")
        if "sorcery" in cost: txt.append(f"🧿 {cost['sorcery']}")
        return " | ".join(txt)

    def update_select(self):
        options = []
        for item, count in self.shop_data["stock"].items():
            if count > 0:
                options.append(discord.SelectOption(label=item, value=item))
        
        if not options:
            self.add_item(Select(placeholder="모두 매진되었습니다", options=[discord.SelectOption(label="X", value="none")], disabled=True))
        else:
            select = Select(placeholder="구매할 물품 선택", options=options)
            select.callback = self.buy_callback
            self.add_item(select)

    async def buy_callback(self, interaction: discord.Interaction):
        item = interaction.data['values'][0]
        cost = self.calculate_price(item)
        tokens = self.user_data["guild_data"]["tokens"]
        
        # 비용 확인
        for t_type, amount in cost.items():
            if tokens.get(t_type, 0) < amount:
                t_name = TOKEN_TRANSLATION.get(t_type, t_type)
                return await interaction.response.send_message(f"❌ 토큰이 부족합니다. ({t_name} {amount}개 필요)", ephemeral=True)
        
        # 차감
        for t_type, amount in cost.items():
            tokens[t_type] -= amount
            
        self.shop_data["stock"][item] -= 1
        if self.shop_data["stock"][item] == 0:
            self.user_data["guild_data"]["activities"]["shop_soldout"] += 1
            
        # 아이템 지급 (비료는 특수 처리)
        if item == "신비한 비료":
            # 랜덤 희귀 재료 속성 부여
            # RARE_ITEMS 중 물고기/길드템 제외
            all_fish = set()
            for tier_list in FISH_TIERS.values():
                all_fish.update(tier_list)
            
            valid_rares = [r for r in RARE_ITEMS if r not in all_fish and r not in GUILD_ITEMS and "토큰" not in r]
            if not valid_rares: valid_rares = ["사랑나무 가지"]
            
            target_attr = random.choice(valid_rares)
            self.user_data.setdefault("fertilizers", []).append({"target": target_attr})
            msg_extra = f"(속성: {target_attr})"
        else:
            inv = self.user_data.setdefault("inventory", {})
            inv[item] = inv.get(item, 0) + 1
            msg_extra = ""
        
        await self.save_func(self.author.id, self.user_data)
        self.update_select()
        await interaction.response.edit_message(content=f"✅ **{item}** 구매 완료! {msg_extra}", embed=self.get_embed(), view=self)

# --- 5. 훈련소 뷰 ---
class GuildTrainingView(View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        
        self.trainers = [
            {"name": "기본기 강사", "cost": {"wood": 4}, "stats": {"hp": 300, "mental": 250, "atk": 45, "def": 40}},
            {"name": "초급 강사", "cost": {"wood": 8}, "stats": {"hp": 350, "mental": 300, "atk": 60, "def": 33}},
            {"name": "중급 강사", "cost": {"iron": 1, "wood": 6}, "stats": {"hp": 420, "mental": 400, "atk": 75, "def": 55}},
        ]
        # 플래티넘 이상
        if user_data.get("guild_rank") in ["Platinum", "Diamond"]:
            self.trainers.append({"name": "고급 강사", "cost": {"iron": 3}, "stats": {"hp": 500, "mental": 370, "atk": 87, "def": 67}})
            self.trainers.append({"name": "호화 강사", "cost": {"iron": 9}, "stats": {"hp": 570, "mental": 450, "atk": 95, "def": 75}})
        
        # 다이아몬드 전용
        if user_data.get("guild_rank") == "Diamond":
            self.trainers.append({"name": "다이아몬드 강사", "cost": {"sorcery": 1}, "stats": "dynamic"})
        
        self.add_char_select()

    def add_char_select(self):
        chars = self.user_data.get("characters", [])
        options = [discord.SelectOption(label=c["name"], value=str(i)) for i, c in enumerate(chars)]
        select = Select(placeholder="훈련할 캐릭터 선택", options=options)
        select.callback = self.char_selected
        self.add_item(select)

    async def char_selected(self, interaction: discord.Interaction):
        idx = int(interaction.data['values'][0])
        self.target_char_idx = idx
        self.clear_items()
        
        # 강사 선택
        options = []
        for i, t in enumerate(self.trainers):
            cost_str = ", ".join([f"{TOKEN_TRANSLATION.get(k, k)} {v}개" for k,v in t["cost"].items()])
            options.append(discord.SelectOption(label=t["name"], description=f"비용: {cost_str}", value=str(i)))
            
        select = Select(placeholder="강사 선택", options=options)
        select.callback = self.trainer_selected
        self.add_item(select)
        await interaction.response.edit_message(content="훈련 강사를 선택하세요.", view=self)

    async def trainer_selected(self, interaction: discord.Interaction):
        t_idx = int(interaction.data['values'][0])
        trainer = self.trainers[t_idx]
        tokens = self.user_data["guild_data"]["tokens"]
        
        # 비용 체크
        for k, v in trainer["cost"].items():
            if tokens.get(k, 0) < v:
                t_name = TOKEN_TRANSLATION.get(k, k)
                return await interaction.response.send_message(f"❌ 토큰 부족 ({t_name} {v}개 필요)", ephemeral=True)
        
        # 차감
        for k, v in trainer["cost"].items():
            tokens[k] -= v
            
        # 스탯 상승 로직
        char = self.user_data["characters"][self.target_char_idx]
        t_stats = trainer["stats"]
        
        # 성장 한계치 설정
        if t_stats == "dynamic":
            # 다이아몬드 강사: 현재 스탯의 1.5배까지 성장 가능 (방어율은 35% 고정)
            limits = {
                "hp": int(char.get("hp", 100) * 1.5),
                "max_mental": int(char.get("max_mental", 50) * 1.5),
                "attack": int(char.get("attack", 5) * 1.5),
                "defense": int(char.get("defense", 0) * 1.5),
                "defense_rate": 35
            }
        else:
            # 일반 강사: 강사의 능력치까지만 성장 가능
            limits = t_stats

        # 스탯 증가 (한계치 확인)
        increased = []
        
        # 1. 체력
        if char.get("hp", 0) < limits.get("hp", 0):
            char["hp"] = char.get("hp", 0) + 10
            increased.append("체력")
        # 2. 정신력
        if char.get("max_mental", 0) < limits.get("mental", limits.get("max_mental", 0)):
            char["max_mental"] = char.get("max_mental", 0) + 10
            increased.append("정신력")
        # 3. 공격력
        if char.get("attack", 0) < limits.get("atk", limits.get("attack", 0)):
            char["attack"] = char.get("attack", 0) + 1
            increased.append("공격력")
        # 4. 방어력
        if char.get("defense", 0) < limits.get("def", limits.get("defense", 0)):
            char["defense"] = char.get("defense", 0) + 1
            increased.append("방어력")
        # 5. 방어율 (다이아몬드 강사 전용)
        if t_stats == "dynamic" and char.get("defense_rate", 0) < limits.get("defense_rate", 0):
            char["defense_rate"] = char.get("defense_rate", 0) + 1
            increased.append("방어율")

        if not increased:
            # 비용 환불 (성장할 스탯이 없는 경우)
            for k, v in trainer["cost"].items():
                tokens[k] += v
            return await interaction.response.send_message("⚠️ 해당 강사에게서 더 이상 배울 것이 없습니다. (비용 반환됨)", ephemeral=True)
        
        await self.save_func(self.author.id, self.user_data)
        await interaction.response.edit_message(content=f"💪 **{char['name']}** 훈련 완료! ({', '.join(increased)} 상승)", view=None)

# --- 6. 레이드 시스템 ---
class GuildRaidLobbyView(View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func

    @discord.ui.button(label="🚩 파티 생성", style=discord.ButtonStyle.success)
    async def create_party(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 파티 생성 (메모리 상에만 존재, 봇 재시작 시 사라짐)
        view = RaidPartyView(self.author, self.user_data, self.save_func)
        await interaction.response.send_message(embed=view.get_embed(), view=view)

class RaidPartyView(View):
    def __init__(self, host, host_data, save_func):
        super().__init__(timeout=300)
        self.host = host
        self.save_func = save_func
        self.members = {host.id: {"user": host, "data": host_data, "ready": True}} # {id: {user, data, ready}}
        self.rank = host_data.get("guild_rank", "Gold")
        self.boss = get_raid_boss(self.rank)
        self.message = None

    def get_embed(self):
        rank_kr = RANK_TRANSLATION.get(self.rank, self.rank)
        embed = discord.Embed(title=f"👹 길드 레이드 파티 ({rank_kr})", description=f"보스: **{self.boss.name}**\n(HP: {self.boss.max_hp:,})", color=discord.Color.dark_red())
        
        member_text = ""
        for uid, info in self.members.items():
            status = "👑 파티장" if uid == self.host.id else "✅ 준비완료"
            char_name = info["data"]["characters"][info["data"].get("investigator_index", 0)]["name"]
            member_text += f"• {info['user'].display_name} ({char_name}) - {status}\n"
            
        embed.add_field(name=f"파티원 ({len(self.members)}/4)", value=member_text, inline=False)
        embed.set_footer(text="2~4명이 모여야 시작할 수 있습니다.")
        return embed

    @discord.ui.button(label="참가하기", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.members:
            return await interaction.response.send_message("이미 참가 중입니다.", ephemeral=True)
        if len(self.members) >= 4:
            return await interaction.response.send_message("파티가 꽉 찼습니다.", ephemeral=True)
            
        # 데이터 로드
        new_user_data = await get_user_data(interaction.user.id, interaction.user.display_name)
        if new_user_data.get("guild_rank") not in ["Gold", "Platinum", "Diamond"]:
             return await interaction.response.send_message("❌ Gold 등급 이상만 참가 가능합니다.", ephemeral=True)

        self.members[interaction.user.id] = {"user": interaction.user, "data": new_user_data, "ready": True}
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="⚔️ 레이드 시작", style=discord.ButtonStyle.danger)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.host.id:
            return await interaction.response.send_message("파티장만 시작할 수 있습니다.", ephemeral=True)
        if len(self.members) < 2:
            return await interaction.response.send_message("최소 2명이 필요합니다.", ephemeral=True)
            
        # 전투 뷰로 전환
        battle_view = RaidBattleView(self.members, self.boss, self.save_func, self.rank)
        await interaction.response.edit_message(content="⚔️ **레이드 전투 시작!**", embed=battle_view.get_embed(), view=battle_view)

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.host.id:
            await interaction.response.edit_message(content="파티장이 파티를 해산했습니다.", embed=None, view=None)
            self.stop()
        else:
            if interaction.user.id in self.members:
                del self.members[interaction.user.id]
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

class RaidBattleView(View):
    def __init__(self, members, boss, save_func, rank):
        super().__init__(timeout=None)
        self.members = members # {uid: {user, data, ready}}
        self.boss = boss
        self.save_func = save_func
        self.rank = rank
        self.turn = 1
        self.logs = []
        
        # 플레이어 객체 초기화
        self.players = {} # {uid: CharacterObj}
        for uid, info in self.members.items():
            idx = info["data"].get("investigator_index", 0)
            char_data = info["data"]["characters"][idx]
            char = Character.from_dict(char_data)
            if "equipped_engraved_artifact" in char_data:
                char.equipped_engraved_artifact = char_data["equipped_engraved_artifact"]
            char.apply_battle_start_buffs()
            char.runtime_cooldowns = {}
            self.players[uid] = char
            
        self.selections = {} # {uid: card_obj}
        self.update_buttons()

    def get_embed(self):
        embed = discord.Embed(title=f"👹 레이드: {self.boss.name} (Turn {self.turn})", color=discord.Color.dark_red())
        embed.add_field(name="BOSS", value=f"❤️ {self.boss.current_hp}/{self.boss.max_hp}\n🛡️ 방어력: {self.boss.defense}", inline=False)
        
        p_status = ""
        for uid, char in self.players.items():
            hp_per = int(char.current_hp / char.max_hp * 10)
            bar = "🟩"*hp_per + "⬛"*(10-hp_per)
            state = "✅ 선택완료" if uid in self.selections else "💭 고민중..."
            if char.current_hp <= 0: state = "💀 사망"
            p_status += f"**{char.name}**: {bar} ({char.current_hp}) | {state}\n"
            
        embed.add_field(name="파티원", value=p_status, inline=False)
        
        if self.logs:
            log_text = "\n".join(self.logs[-5:]) # 최근 5줄만
            embed.add_field(name="전투 로그", value=log_text, inline=False)
            
        return embed

    def update_buttons(self):
        self.clear_items()
        btn = Button(label="카드 선택", style=discord.ButtonStyle.primary, custom_id="select_card")
        btn.callback = self.open_selector
        self.add_item(btn)

    async def open_selector(self, interaction: discord.Interaction):
        uid = interaction.user.id
        if uid not in self.players:
            return await interaction.response.send_message("파티원이 아닙니다.", ephemeral=True)
        
        char = self.players[uid]
        if char.current_hp <= 0:
            return await interaction.response.send_message("사망하여 행동할 수 없습니다.", ephemeral=True)
            
        if uid in self.selections:
            return await interaction.response.send_message("이미 카드를 선택했습니다.", ephemeral=True)

        # 개인용 선택 뷰
        from pvp import PVPSelectView # 재사용
        # PVPSelectView는 battle_view.receive_action을 호출함. 호환성을 위해 래퍼 필요하거나 수정 필요.
        # 여기서는 간단히 직접 구현
        view = RaidCardSelector(self, uid, char)
        await interaction.response.send_message("사용할 카드를 선택하세요.", view=view, ephemeral=True)

    async def receive_selection(self, uid, card):
        self.selections[uid] = card
        
        # 모든 생존 플레이어가 선택했는지 확인
        alive_count = sum(1 for p in self.players.values() if p.current_hp > 0)
        if len(self.selections) >= alive_count:
            await self.process_turn()
        else:
            # 갱신 (누가 선택했는지 보여주기 위해)
            # 메시지 객체를 저장해두지 않았으므로 interaction을 통해 갱신해야 하는데,
            # 여기서는 마지막 interaction을 저장하거나 해야 함. 
            # 간단히: receive_selection은 interaction context가 없으므로 
            # open_selector의 interaction을 저장해두거나, process_turn에서 일괄 처리.
            pass

    async def process_turn(self):
        # 턴 처리 로직
        self.logs = [f"--- Turn {self.turn} ---"]
        
        # 1. 보스 행동 결정
        boss_card = self.boss.decide_action()
        self.logs.append(f"👾 **{self.boss.name}**의 공격: `{boss_card.name}`")
        
        # 2. 각 플레이어와 합 진행
        total_dmg_to_boss = 0
        
        for uid, char in self.players.items():
            if char.current_hp <= 0: continue
            
            player_card = self.selections.get(uid)
            if not player_card: continue # 혹시 모를 예외
            
            # 주사위 굴리기
            p_res = player_card.use_card(char.attack, char.defense, char.current_mental, character=char)
            p_res = battle_engine.apply_stat_scaling(p_res, char)
            
            b_res = boss_card.use_card(self.boss.attack, self.boss.defense)
            
            # 합 진행 (1vs1 로직 재사용)
            # 보스가 광역 공격이면 각 플레이어마다 별도로 주사위를 굴린 셈 침
            log, p_dmg, b_dmg = battle_engine.process_clash_loop(
                char, self.boss, p_res, b_res, [], [], self.turn
            )
            
            # 로그 요약
            self.logs.append(f"👤 **{char.name}** vs 👾: {char.name} 피해 {p_dmg}, 보스 피해 {b_dmg}")
            total_dmg_to_boss += b_dmg
            
            # 플레이어 사망 체크
            if char.current_hp <= 0:
                self.logs.append(f"💀 **{char.name}** 리타이어!")

        # 보스 체력 감소 (누적)
        self.boss.current_hp = max(0, self.boss.current_hp - total_dmg_to_boss)
        
        # 3. 결과 판정
        if self.boss.current_hp <= 0:
            await self.end_raid(win=True)
            return
            
        alive_count = sum(1 for p in self.players.values() if p.current_hp > 0)
        if alive_count == 0:
            await self.end_raid(win=False)
            return
            
        # 다음 턴 준비
        self.turn += 1
        self.selections = {}
        # 메시지 갱신은 interaction이 필요함. 
        # Discord UI 한계상, 마지막으로 상호작용한 interaction을 저장해두거나, 
        # 채널에 새 메시지를 보내는 방식을 써야 함. 여기서는 채널에 새 메시지 전송.
        # (self.message를 업데이트하려면 interaction.message.edit 필요)
        # 편의상 process_turn을 호출한 interaction이 없으므로, 
        # RaidCardSelector에서 process_turn을 호출할 때 interaction을 넘겨받도록 구조 변경 필요.
        # 하지만 코드 복잡도를 줄이기 위해 생략하고, 실제로는 interaction을 전달받아야 함.

    async def end_raid(self, win):
        embed = discord.Embed(title="레이드 종료", color=discord.Color.gold() if win else discord.Color.dark_grey())
        if win:
            embed.description = f"🎉 **{self.boss.name}** 토벌 성공!"
            # 보상 지급
            rewards = RAID_BOSS_DATA[self.rank]["reward_tokens"]
            for uid, info in self.members.items():
                tokens = info["data"]["guild_data"]["tokens"]
                for k, v in rewards.items():
                    tokens[k] += v
                await self.save_func(uid, info["data"])
            
            r_text = ", ".join([f"{k} {v}개" for k,v in rewards.items()])
            embed.add_field(name="보상 (전원 지급)", value=r_text)
        else:
            embed.description = "☠️ 전멸했습니다..."
            
        # 채널에 전송 (self.message가 있다면 edit, 아니면 send)
        # 여기서는 구현 생략
        pass

class RaidCardSelector(View):
    def __init__(self, battle_view, uid, char):
        super().__init__(timeout=60)
        self.battle_view = battle_view
        self.uid = uid
        
        for card_name in char.equipped_cards:
            btn = Button(label=card_name, style=discord.ButtonStyle.primary)
            btn.callback = self.make_cb(card_name)
            self.add_item(btn)
            
    def make_cb(self, name):
        async def cb(interaction):
            from cards import get_card
            card = get_card(name)
            await self.battle_view.receive_selection(self.uid, card)
            await interaction.response.edit_message(content=f"✅ **{name}** 선택 완료! 다른 파티원을 기다립니다.", view=None)
            
            # 마지막 선택자였다면 턴 진행 (여기서 interaction을 넘겨서 갱신 가능하게 함)
            alive = sum(1 for p in self.battle_view.players.values() if p.current_hp > 0)
            if len(self.battle_view.selections) >= alive:
                await self.battle_view.process_turn()
                # 턴 처리 후 메인 메시지 갱신
                try:
                    # battle_view가 메시지 객체를 가지고 있다고 가정하거나, 
                    # interaction.message.edit은 ephemeral 메시지라 안됨.
                    # 원래 메시지를 찾아서 수정해야 함.
                    pass 
                except: pass
        return cb

# --- 7. 길드 창고 ---
class GuildWarehouseView(View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.page = 0
        self.items = [] # (id, depositor_id, depositor_name, item_name, quantity, artifact_data, created_at)
        self.PER_PAGE = 7

    async def refresh_ui(self, interaction: discord.Interaction):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM guild_warehouse ORDER BY id DESC")
                self.items = await cur.fetchall()
        
        self.update_components()
        embed = self.get_embed()
        
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.send_message(embed=embed, view=self, ephemeral=True)

    def get_embed(self):
        embed = discord.Embed(title="🏚️ 길드 창고", description="길드원들과 아이템을 공유하는 공간입니다.", color=discord.Color.dark_green())
        
        if not self.items:
            embed.add_field(name="비어있음", value="창고에 아이템이 없습니다.", inline=False)
        else:
            total_pages = (len(self.items) - 1) // self.PER_PAGE + 1
            self.page = max(0, min(self.page, total_pages - 1))
            
            start = self.page * self.PER_PAGE
            end = start + self.PER_PAGE
            current_items = self.items[start:end]
            
            for item in current_items:
                # item: (id, dep_id, dep_name, name, qty, artifact_data, time)
                item_name = item[3]
                item_value = f"기증자: {item[2]}"
                is_artifact = item[5] is not None
                if is_artifact:
                    try:
                        art_data = json.loads(item[5])
                        level = art_data.get('level', 0)
                        item_name = f"🔮 {art_data.get('name', item_name)}"
                        if level > 0:
                            item_name += f" (+{level})"
                        
                        stats = art_data.get('stats', {})
                        desc_parts = []
                        stat_map = {"max_hp": "체력", "max_mental": "정신력", "attack": "공격력", "defense": "방어력", "defense_rate": "피해감소"}
                        for k, v in stats.items():
                            if v > 0:
                                unit = "%" if k == "defense_rate" else ""
                                desc_parts.append(f"{stat_map.get(k, k)} +{v}{unit}")
                        if desc_parts:
                            item_value += "\n" + " | ".join(desc_parts)
                    except (json.JSONDecodeError, TypeError):
                        item_name = f"🔮 {item_name} (데이터 오류)"
                embed.add_field(
                    name=f"📦 {item_name} x{item[4]}",
                    value=item_value,
                    inline=False
                )
            embed.set_footer(text=f"페이지 {self.page+1}/{total_pages}")
            
        return embed

    def update_components(self):
        self.clear_items()
        
        # 입고 버튼
        self.add_item(Button(label="📥 아이템 넣기", style=discord.ButtonStyle.primary, custom_id="deposit"))
        
        # 출고 메뉴 (현재 페이지 아이템)
        if self.items:
            start = self.page * self.PER_PAGE
            end = start + self.PER_PAGE
            current_items = self.items[start:end]
            
            options = []
            for item in current_items:
                item_name = item[3]
                item_desc = f"기증자: {item[2]}"
                is_artifact = item[5] is not None
                if is_artifact:
                    try:
                        art_data = json.loads(item[5])
                        level = art_data.get('level', 0)
                        item_name = f"🔮 {art_data.get('name', item_name)}"
                        if level > 0:
                            item_name += f" (+{level})"
                        
                        stats = art_data.get('stats', {})
                        desc_parts = []
                        stat_map = {"max_hp": "체", "max_mental": "정", "attack": "공", "defense": "방", "defense_rate": "피감"}
                        for k, v in stats.items():
                            if v > 0:
                                unit = "%" if k == "defense_rate" else ""
                                desc_parts.append(f"{stat_map.get(k, k)}{v}{unit}")
                        if desc_parts:
                            item_desc += " | " + " ".join(desc_parts)
                    except (json.JSONDecodeError, TypeError):
                        item_name = f"🔮 {item_name} (데이터 오류)"
                options.append(discord.SelectOption(
                    label=f"{item_name} x{item[4]}",
                    description=item_desc[:100], # description has a 100 character limit
                    value=str(item[0])
                ))
            
            # Allow multi-select for withdrawing items
            select = Select(placeholder="꺼낼 아이템 선택 (여러 개 선택 가능)", options=options, custom_id="withdraw", max_values=min(25, len(options)))
            select.callback = self.withdraw_callback
            self.add_item(select)
            
            # 페이지 이동
            if len(self.items) > self.PER_PAGE:
                self.add_item(Button(label="◀️", style=discord.ButtonStyle.secondary, custom_id="prev"))
                self.add_item(Button(label="▶️", style=discord.ButtonStyle.secondary, custom_id="next"))

    async def interaction_check(self, interaction: discord.Interaction):
        cid = interaction.data.get("custom_id")
        if cid == "deposit":
            await interaction.response.send_message("📥 넣을 아이템을 선택하세요.", view=WarehouseDepositSelectView(self.author, self.user_data, self.save_func, self), ephemeral=True)
        elif cid == "prev":
            self.page -= 1
            await self.refresh_ui(interaction)
        elif cid == "next":
            self.page += 1
            await self.refresh_ui(interaction)
        return True

    async def withdraw_callback(self, interaction: discord.Interaction):
        item_ids = interaction.data['values'] # This is now a list
        
        pool = await get_db_pool()
        withdrawn_items = []
        failed_items = 0

        for item_id_str in item_ids:
            item_id = int(item_id_str)
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # 아이템 존재 확인 및 삭제 (동시성 처리)
                    await cur.execute("SELECT item_name, quantity, artifact_data FROM guild_warehouse WHERE id=%s FOR UPDATE", (item_id,))
                    row = await cur.fetchone()
                    
                    if not row:
                        failed_items += 1
                        continue
                    
                    await cur.execute("DELETE FROM guild_warehouse WHERE id=%s", (item_id,))
                    await conn.commit()
                    
                    name, qty, artifact_data = row
                    
                    # 인벤토리/아티팩트 지급
                    if artifact_data:
                        try:
                            art = json.loads(artifact_data)
                            self.user_data.setdefault("artifacts", []).append(art)
                            withdrawn_items.append(f"🔮 {art['name']}")
                        except json.JSONDecodeError:
                            failed_items += 1
                            continue
                    else:
                        inv = self.user_data.setdefault("inventory", {})
                        inv[name] = inv.get(name, 0) + qty
                        withdrawn_items.append(f"📦 {name} x{qty}")

        if withdrawn_items:
            await self.save_func(self.author.id, self.user_data)

        msg_parts = []
        if withdrawn_items:
            msg_parts.append(f"✅ 다음 아이템을 창고에서 꺼냈습니다:\n" + "\n".join(withdrawn_items))
        if failed_items > 0:
            msg_parts.append(f"❌ {failed_items}개의 아이템은 다른 사람이 먼저 가져갔거나 오류가 발생했습니다.")
            
        final_msg = "\n\n".join(msg_parts)
        if not final_msg:
            final_msg = "❌ 아이템을 꺼내지 못했습니다."

        await interaction.response.send_message(final_msg, ephemeral=True)
        await self.refresh_ui(interaction)

class WarehouseDepositAmountModal(Modal):
    def __init__(self, author, user_data, save_func, parent_view, item_name):
        super().__init__(title=f"'{item_name}' 수량 입력")
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.parent_view = parent_view # This is WarehouseDepositSelectView
        self.item_name = item_name

        self.quantity = TextInput(label="수량", placeholder="숫자 또는 '전부'", required=True)
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction):
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        inv = self.user_data.get("inventory", {})
        current_qty = inv.get(self.item_name, 0)
        
        qty_str = self.quantity.value.strip().lower()
        try:
            qty = current_qty if qty_str in ['all', '전부'] else int(qty_str)
        except ValueError:
            return await interaction.response.send_message("❌ 수량은 숫자 또는 '전부'여야 합니다.", ephemeral=True)
        
        if qty <= 0: return await interaction.response.send_message("❌ 1개 이상 넣어야 합니다.", ephemeral=True)
        if current_qty < qty: return await interaction.response.send_message(f"❌ 아이템이 부족합니다. (보유: {current_qty}개)", ephemeral=True)
            
        inv[self.item_name] -= qty
        if inv[self.item_name] <= 0: del inv[self.item_name]
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO guild_warehouse (depositor_id, depositor_name, item_name, quantity, artifact_data) VALUES (%s, %s, %s, %s, %s)", (self.author.id, self.author.display_name, self.item_name, qty, None))
                await conn.commit()
        
        await self.save_func(self.author.id, self.user_data)
        await interaction.response.send_message(f"✅ **{self.item_name} x{qty}**을(를) 창고에 넣었습니다.", ephemeral=True)
        await self.parent_view.parent_view.refresh_ui(interaction)

class WarehouseDepositSelectView(View):
    def __init__(self, author, user_data, save_func, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.parent_view = parent_view
        self.page = 0
        self.PER_PAGE = 7
        self.item_type = "item"
        self.update_components()

    def update_components(self):
        self.clear_items()
        self.add_item(discord.ui.Button(label="일반 아이템", style=discord.ButtonStyle.primary if self.item_type == "item" else discord.ButtonStyle.secondary, custom_id="switch_item", row=0))
        self.add_item(discord.ui.Button(label="아티팩트", style=discord.ButtonStyle.primary if self.item_type == "artifact" else discord.ButtonStyle.secondary, custom_id="switch_artifact", row=0))

        options = []
        total_pages = 1
        max_vals = 1

        if self.item_type == "item":
            items = sorted(self.user_data.get("inventory", {}).items())
            total_pages = (len(items) - 1) // self.PER_PAGE + 1 if items else 1
            start, end = self.page * self.PER_PAGE, (self.page + 1) * self.PER_PAGE
            paged_items = items[start:end]
            for name, qty in paged_items:
                options.append(discord.SelectOption(label=f"{name} (x{qty})", value=name))
            placeholder = f"넣을 아이템 선택 ({self.page+1}/{total_pages})"
            max_vals = 1
        else:
            artifacts = self.user_data.get("artifacts", [])
            equipped_ids = {c.get("equipped_artifact", {}).get("id") for c in self.user_data.get("characters", []) if c.get("equipped_artifact")}
            depositable_artifacts = [(idx, art) for idx, art in enumerate(artifacts) if art.get("id") not in equipped_ids]
            total_pages = (len(depositable_artifacts) - 1) // self.PER_PAGE + 1 if depositable_artifacts else 1
            start, end = self.page * self.PER_PAGE, (self.page + 1) * self.PER_PAGE
            paged_artifacts = depositable_artifacts[start:end]
            for idx, art in paged_artifacts:
                level = art.get('level', 0)
                label = f"🔮 {art['name']}"
                if level > 0:
                    label += f" (+{level})"
                
                stats = art.get('stats', {})
                desc_parts = []
                stat_map = {"max_hp": "체", "max_mental": "정", "attack": "공", "defense": "방", "defense_rate": "피감"}
                for k, v in stats.items():
                    if v > 0:
                        unit = "%" if k == "defense_rate" else ""
                        desc_parts.append(f"{stat_map.get(k, k)}{v}{unit}")
                
                desc = " | ".join(desc_parts)
                options.append(discord.SelectOption(label=label, value=f"art_{idx}", description=desc[:100]))
            placeholder = f"넣을 아티팩트 선택 ({self.page+1}/{total_pages})"
            max_vals = min(25, len(paged_artifacts))

        if not options:
            options.append(discord.SelectOption(label="넣을 수 있는 아이템이 없습니다.", value="none"))
            max_vals = 1
        
        self.add_item(discord.ui.Select(
            placeholder=placeholder, 
            options=options[:25], 
            custom_id="deposit_select", 
            row=1,
            max_values=max_vals
        ))

        if total_pages > 1:
            self.add_item(discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=2, disabled=(self.page == 0), custom_id="prev_page"))
            self.add_item(discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=2, disabled=(self.page >= total_pages - 1), custom_id="next_page"))

        self.add_item(discord.ui.Button(label="⬅️ 창고로", style=discord.ButtonStyle.gray, row=3, custom_id="back"))

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id: return False
        cid = interaction.data.get("custom_id")
        
        if cid == "switch_item": self.item_type = "item"; self.page = 0
        elif cid == "switch_artifact": self.item_type = "artifact"; self.page = 0
        elif cid == "prev_page": self.page -= 1
        elif cid == "next_page": self.page += 1
        elif cid == "back": return await self.parent_view.refresh_ui(interaction)
        
        self.update_components()
        await interaction.response.edit_message(view=self)
        return True

    @discord.ui.select(custom_id="deposit_select")
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        item_keys = select.values
        if not item_keys or "none" in item_keys:
            await interaction.response.defer()
            return

        # To prevent race conditions and ensure data consistency
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
        # Separate keys for artifacts and regular items
        art_keys = [k for k in item_keys if k.startswith("art_")]
        item_names = [k for k in item_keys if not k.startswith("art_")]

        if item_names:
            await interaction.response.send_modal(WarehouseDepositAmountModal(self.author, self.user_data, self.save_func, self, item_names[0]))
            return

        if art_keys:
            deposited_items_log = []
            pool = await get_db_pool()
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    art_indices_to_pop = sorted([int(k.replace("art_", "")) for k in art_keys], reverse=True)
                    original_artifacts = self.user_data.get("artifacts", [])
                    for art_idx in art_indices_to_pop:
                        if art_idx < len(original_artifacts):
                            artifact = original_artifacts.pop(art_idx)
                            await cur.execute("INSERT INTO guild_warehouse (depositor_id, depositor_name, item_name, quantity, artifact_data) VALUES (%s, %s, %s, %s, %s)", (self.author.id, self.author.display_name, artifact['name'], 1, json.dumps(artifact)))
                            deposited_items_log.append(f"🔮 {artifact['name']}")
                    await conn.commit()

            if deposited_items_log:
                await self.save_func(self.author.id, self.user_data)
                msg = "✅ 다음 아이템을 창고에 넣었습니다:\n" + "\n".join(deposited_items_log)
                await interaction.response.send_message(msg, ephemeral=True)
                await self.parent_view.refresh_ui(interaction)
            else:
                await interaction.response.send_message("❌ 아티팩트를 넣지 못했습니다.", ephemeral=True)
