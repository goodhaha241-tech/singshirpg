import discord
from discord.ui import View, Button, Select, Modal, TextInput
from discord import SelectOption, ButtonStyle
import aiomysql
import random
import datetime
# [수정] DB 연결 풀을 공유하기 위해 data_manager에서 import
from data_manager import get_db_pool
from decorators import auto_defer
from items import REGIONS, ITEM_CATEGORIES, CRAFT_RECIPES, COMMON_ITEMS, RARE_ITEMS

# --- 카페 메뉴 데이터 설정 ---
CAFE_MENU = [
    {"name": "에스프레소", "price": 3000, "stat": "attack", "value": 3, "duration": 3, "desc": "3회 전투동안 공격력 +3"},
    {"name": "아메리카노", "price": 3500, "stat": "attack", "value": 5, "duration": 3, "desc": "3회 전투동안 공격력 +5"},
    {"name": "카페라떼", "price": 3000, "stat": "defense", "value": 3, "duration": 3, "desc": "3회 전투동안 방어력 +3"},
    {"name": "바닐라라떼", "price": 3500, "stat": "defense", "value": 5, "duration": 3, "desc": "3회 전투동안 방어력 +5"},
    {"name": "카페모카", "price": 3000, "stat": "defense_rate", "value": 2, "duration": 3, "desc": "3회 전투동안 방어율 +2%"},
    {"name": "아이스티", "price": 3500, "stat": "defense_rate", "value": 5, "duration": 3, "desc": "3회 전투동안 방어율 +5%"},
    {"name": "샌드위치", "price": 3500, "stat": "max_hp", "value": 100, "duration": 3, "desc": "3회 전투동안 체력 +100"},
    {"name": "허니브레드", "price": 3500, "stat": "max_mental", "value": 100, "duration": 3, "desc": "3회 전투동안 정신력 +100"},
]

async def check_global_tables():
    """거래 및 퀘스트 테이블 확인/생성"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # 거래 테이블
                await cursor.execute("SHOW TABLES LIKE 'global_trades'")
                if not await cursor.fetchone():
                    await cursor.execute("""
                        CREATE TABLE global_trades (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            seller_id BIGINT NOT NULL,
                            seller_name VARCHAR(100),
                            item_name VARCHAR(100),
                            quantity INT,
                            price INT,
                            currency VARCHAR(10),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                # [신규] 글로벌 퀘스트 테이블
                await cursor.execute("SHOW TABLES LIKE 'global_quests'")
                if not await cursor.fetchone():
                    await cursor.execute("""
                        CREATE TABLE global_quests (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            q_type VARCHAR(50),
                            q_rank INT,
                            target VARCHAR(100),
                            count INT,
                            current INT DEFAULT 0,
                            description VARCHAR(255),
                            accepted_by BIGINT,
                            accepted_name VARCHAR(100),
                            completed BOOLEAN DEFAULT FALSE,
                            claimed BOOLEAN DEFAULT FALSE,
                            created_date DATE
                        )
                    """)
    except Exception as e:
        print(f"⚠️ 테이블 확인 중 오류: {e}")

# ==================================================================================
# [신규] 카페 미니 퀘스트 시스템
# ==================================================================================

async def update_cafe_quest_progress(user_id, user_data, save_func, q_type, value, target=None):
    """
    퀘스트 진행도를 업데이트하는 함수 (외부 모듈에서 호출 가능)
    q_type: 'investigation', 'dungeon', 'delivery' (delivery는 UI에서 직접 처리)
    value: 증가시킬 값 (조사 횟수, 던전 층수 등)
    target: 조사 지역 이름 등 (조건 확인용)
    """
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # 내가 수락한 진행중인 퀘스트 검색
            await cur.execute("""
                SELECT id, q_type, target, `count`, current 
                FROM global_quests 
                WHERE accepted_by = %s AND completed = 0 AND created_date = CURDATE()
            """, (user_id,))
            
            my_quests = await cur.fetchall()
            updated = False
            
            for q in my_quests:
                qid, qt, qt_target, qcount, qcurr = q
                
                if qt != q_type: continue
                
                new_curr = qcurr
                is_complete = False
                
                if q_type == "investigation":
                    if qt_target and qt_target != target: continue
                    new_curr += value
                    if new_curr >= qcount:
                        new_curr = qcount
                        is_complete = True
                    
                elif q_type == "dungeon":
                    if value >= qcount:
                        new_curr = qcount
                        is_complete = True
                    else:
                        continue
                
                if new_curr != qcurr or is_complete:
                    await cur.execute(
                        "UPDATE global_quests SET current=%s, completed=%s WHERE id=%s", 
                        (new_curr, 1 if is_complete else 0, qid)
                    )
                    updated = True
            
            if updated:
                await conn.commit()

async def refresh_global_quests(user_data):
    """일일 퀘스트 갱신 (DB 기반)"""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            today = datetime.date.today()
            await cur.execute("SELECT COUNT(*) FROM global_quests WHERE created_date = %s", (today,))
            count = (await cur.fetchone())[0]
            
            if count > 0: return # 이미 생성됨
            
            # 퀘스트 생성 로직
            unlocked_regions = user_data.get("unlocked_regions", ["기원의 쌍성"])
            craft_items = [r["result"] for r in CRAFT_RECIPES.values()]
            
            quests_to_insert = []
            for _ in range(10):
                roll = random.random()
                if roll < 0.45: rank = 1
                elif roll < 0.75: rank = 2
                else: rank = 3
                
                q_type = random.choice(["investigation", "dungeon", "delivery"])
                target = ""
                count_val = 0
                desc = ""
                
                if q_type == "investigation":
                    target = random.choice(unlocked_regions)
                    if rank == 1: count_val = random.randint(1, 5)
                    elif rank == 2: count_val = random.randint(6, 10)
                    else: count_val = random.randint(11, 15)
                    desc = f"{target} 지역 조사 {count_val}회 성공"
                    
                elif q_type == "dungeon":
                    if rank == 1: count_val = random.randint(10, 30)
                    elif rank == 2: count_val = random.randint(31, 60)
                    else: count_val = random.randint(61, 90)
                    desc = f"던전 {count_val}층 돌파 (단일 탐사)"
                    
                elif q_type == "delivery":
                    count_val = 10
                    if rank == 1:
                        pool = [i for i in COMMON_ITEMS if i in ITEM_CATEGORIES]
                        target = random.choice(pool) if pool else "사과"
                    elif rank == 2:
                        pool = [i for i in RARE_ITEMS if i in ITEM_CATEGORIES]
                        target = random.choice(pool) if pool else "무지개 열매"
                    else:
                        target = random.choice(craft_items) if craft_items else "열매 샐러드"
                    desc = f"{target} {count_val}개 납품"
                
                quests_to_insert.append((q_type, rank, target, count_val, desc, today))
            
            await cur.executemany("""
                INSERT INTO global_quests (q_type, q_rank, target, `count`, description, created_date)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, quests_to_insert)
            await conn.commit()

class RewardChoiceView(discord.ui.View):
    """공통 보상 상자 선택 뷰"""
    def __init__(self, author, user_data, save_func, rank, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.rank = rank
        self.parent_view = parent_view
        
        # 보상 데이터 정의
        self.rewards = {
            1: [("3000pt", "pt", 3000), ("40000원", "money", 40000), ("녹슨 철 100개", "item", ("녹슨 철", 100)), ("신전의 등불 2개", "item", ("신전의 등불", 2))],
            2: [("5000pt", "pt", 5000), ("70000원", "money", 70000), ("눈덩이 100개", "item", ("눈덩이", 100)), ("형상각인기 2개", "item", ("형상각인기", 2))],
            3: [("12000pt", "pt", 12000), ("100000원", "money", 100000), ("하급 마력석 30개", "item", ("하급 마력석", 30)), ("악몽 프라페 5개", "item", ("악몽 프라페", 5))]
        }
        
        self.add_buttons()

    def add_buttons(self):
        options = self.rewards.get(self.rank, [])
        for idx, (label, r_type, val) in enumerate(options):
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, custom_id=f"rew_{idx}")
            btn.callback = self.make_callback(r_type, val, label)
            self.add_item(btn)

    def make_callback(self, r_type, val, label):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.author: return
            
            if r_type == "pt":
                self.user_data["pt"] += val
            elif r_type == "money":
                self.user_data["money"] += val
            elif r_type == "item":
                name, qty = val
                inv = self.user_data.setdefault("inventory", {})
                inv[name] = inv.get(name, 0) + qty
            
            await self.save_func(self.author.id, self.user_data)
            await interaction.response.edit_message(content=f"🎁 **{label}**을(를) 수령했습니다!", view=None, embed=None)
            # 부모 뷰 갱신은 여기서 하지 않음 (이미 완료 처리됨)
        return callback

class CafeQuestView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=300)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.quests = []

    async def async_init(self):
        await check_global_tables()
        await refresh_global_quests(self.user_data)
        await self.fetch_quests()
        self.update_buttons()

    async def fetch_quests(self):
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # [수정] 번호 떼고 등급별 오름차순 정렬
                await cur.execute("""
                    SELECT * FROM global_quests 
                    WHERE created_date = CURDATE() 
                    ORDER BY q_rank ASC, id ASC
                """)
                self.quests = await cur.fetchall()

    def get_embed(self):
        embed = discord.Embed(title="📜 의뢰 게시판 (전체 연동)", description="함께하는 의뢰들입니다. 먼저 수락한 사람이 임자!", color=discord.Color.gold())
        
        for q in self.quests:
            rank_str = "⭐" * q['q_rank']
            
            status = "🟢 가능"
            if q['claimed']:
                status = "🏁 종료됨"
            elif q['completed']:
                if q['accepted_by'] == self.author.id:
                    status = "🎁 보상 수령 가능"
                else:
                    status = f"🔒 {q['accepted_name']}님이 완료함"
            elif q['accepted_by']:
                if q['accepted_by'] == self.author.id:
                    status = f"▶️ 진행중 ({q['current']}/{q['count']})"
                else:
                    status = f"🔒 {q['accepted_name']}님이 수행중"
            
            # 번호 제거하고 등급과 설명 표시
            embed.add_field(name=f"{rank_str} {q['description']}", value=f"상태: {status}", inline=False)
            
        return embed

    def update_buttons(self):
        self.clear_items()
        
        options = []
        for q in self.quests:
            if q['claimed']: continue
            
            # 다른 사람이 수락한 퀘스트는 선택 불가 (목록에서 제외)
            if q['accepted_by'] and q['accepted_by'] != self.author.id: continue
            
            label = f"{'⭐'*q['q_rank']} {q['description'][:15]}..."
            val_id = str(q['id'])
            
            if not q['accepted_by']:
                options.append(SelectOption(label=f"✅ 수락: {label}", value=f"accept_{val_id}"))
            elif q['completed']:
                options.append(SelectOption(label=f"🎁 보상: {label}", value=f"claim_{val_id}"))
            elif q['q_type'] == "delivery":
                options.append(SelectOption(label=f"📦 납품: {label}", value=f"deliver_{val_id}"))
        
        if options:
            select = discord.ui.Select(placeholder="퀘스트 선택", options=options[:25])
            select.callback = self.quest_action
            self.add_item(select)
            
        refresh_btn = Button(label="새로고침", style=ButtonStyle.secondary)
        refresh_btn.callback = self.refresh_callback
        self.add_item(refresh_btn)

        close_btn = discord.ui.Button(label="닫기", style=discord.ButtonStyle.gray)
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("❌ 본인의 메뉴만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    async def refresh_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.fetch_quests()
        self.update_buttons()
        await interaction.edit_original_response(embed=self.get_embed(), view=self)

    async def close_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await interaction.edit_original_response(content="카페를 나갔습니다.👋", embed=None, view=None)

    async def quest_action(self, interaction: discord.Interaction):
        val = interaction.data['values'][0]
        action, qid_str = val.split("_")
        qid = int(qid_str)
        
        # DB에서 최신 상태 확인
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT * FROM global_quests WHERE id = %s", (qid,))
                quest = await cur.fetchone()
        
        if not quest:
            return await interaction.response.send_message("❌ 퀘스트 정보를 찾을 수 없습니다.", ephemeral=True)

        # 0. 수락 처리
        if action == "accept":
            if quest['accepted_by']:
                return await interaction.response.send_message("❌ 이미 다른 사람이 수락한 의뢰입니다.", ephemeral=True)
            
            # 진행 중인 퀘스트 수 확인 (최대 3개 제한)
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT COUNT(*) FROM global_quests WHERE accepted_by = %s AND completed = 0", (self.author.id,))
                    res = await cur.fetchone()
                    active_count = list(res.values())[0] if isinstance(res, dict) else res[0]
            
            if active_count >= 3:
                return await interaction.response.send_message("❌ 동시에 진행할 수 있는 의뢰는 최대 3개입니다. 기존 의뢰를 완료해주세요.", ephemeral=True)
            
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("UPDATE global_quests SET accepted_by=%s, accepted_name=%s WHERE id=%s AND accepted_by IS NULL", 
                                      (self.author.id, self.author.display_name, qid))
                    await conn.commit()
            
            await interaction.response.send_message("✅ 의뢰를 수락했습니다! 열심히 수행해주세요.", ephemeral=True)
            await self.fetch_quests()
            self.update_buttons()
            await interaction.message.edit(embed=self.get_embed(), view=self)
            return

        inv = self.user_data.setdefault("inventory", {})
        
        # 1. 납품 처리
        if action == "deliver":
            if quest['accepted_by'] != self.author.id:
                return await interaction.response.send_message("❌ 먼저 의뢰를 수락해야 합니다.", ephemeral=True)
                
            target = quest["target"]
            req = quest["count"]
            if inv.get(target, 0) >= req:
                inv[target] -= req
                if inv[target] <= 0: del inv[target]
                
                async with pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("UPDATE global_quests SET current=%s, completed=1 WHERE id=%s", (req, qid))
                        await conn.commit()
                        
                await self.save_func(self.author.id, self.user_data)
                await interaction.response.send_message(f"✅ **{target}** 납품 완료! 보상을 수령하세요.", ephemeral=True)
                
                await self.fetch_quests()
                self.update_buttons()
                await interaction.message.edit(embed=self.get_embed(), view=self)
            else:
                await interaction.response.send_message(f"❌ 재료가 부족합니다. ({inv.get(target,0)}/{req})", ephemeral=True)
            return

        # 2. 보상 수령
        if action == "claim":
            if quest['accepted_by'] != self.author.id:
                return await interaction.response.send_message("❌ 본인이 수행한 의뢰가 아닙니다.", ephemeral=True)
            if quest['claimed']:
                return await interaction.response.send_message("❌ 이미 보상을 수령했습니다.", ephemeral=True)

            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("UPDATE global_quests SET claimed=1 WHERE id=%s", (qid,))
                    await conn.commit()
            
            # 종류별 보상 지급
            msg = "🎁 **퀘스트 보상 획득!**\n"
            rank = quest["q_rank"]
            
            if quest["q_type"] == "investigation":
                # 조사 지역 희귀 재료
                region = quest.get("target", "기원의 쌍성")
                rares = REGIONS.get(region, {}).get("rare", ["사랑나무 가지"])
                
                if rank == 1: count=5; money=10000; types=2
                elif rank == 2: count=5; money=30000; types=3
                else: count=10; money=70000; types=3
                
                self.user_data["money"] += money
                msg += f"💰 {money}원\n"
                
                selected_rares = random.choices(rares, k=types)
                for r in selected_rares:
                    inv[r] = inv.get(r, 0) + count
                    msg += f"📦 {r} x{count}\n"
                    
            elif quest["q_type"] == "dungeon":
                # 회복 아이템
                if rank == 1: pt=500; count=30
                elif rank == 2: pt=1500; count=50
                else: pt=4000; count=100
                
                self.user_data["pt"] += pt
                inv["일반 회복약"] = inv.get("일반 회복약", 0) + 1
                inv["일반 비타민"] = inv.get("일반 비타민", 0) + count
                msg += f"⚡ {pt}pt\n🧪 일반 회복약 x1\n💊 일반 비타민 x{count}\n"
                
            elif quest["q_type"] == "delivery":
                # 납품 보상 (의뢰품 제외)
                target = quest["target"]
                if rank == 1:
                    pool = [i for i in COMMON_ITEMS if i != target and i in ITEM_CATEGORIES]
                    rew_item = random.choice(pool) if pool else "사과"
                    inv[rew_item] = inv.get(rew_item, 0) + 15
                    self.user_data["money"] += 10000
                    msg += f"💰 10000원\n📦 {rew_item} x15\n"
                elif rank == 2:
                    pool = [i for i in RARE_ITEMS if i != target and i in ITEM_CATEGORIES]
                    rew_item = random.choice(pool) if pool else "무지개 열매"
                    inv[rew_item] = inv.get(rew_item, 0) + 15
                    self.user_data["money"] += 20000
                    self.user_data["pt"] += 500
                    msg += f"💰 20000원, ⚡ 500pt\n📦 {rew_item} x15\n"
                else:
                    crafts = [r["result"] for r in CRAFT_RECIPES.values()]
                    pool = [i for i in crafts if i != target]
                    rew_item = random.choice(pool) if pool else "열매 샐러드"
                    inv[rew_item] = inv.get(rew_item, 0) + 15
                    self.user_data["money"] += 50000
                    self.user_data["pt"] += 1500
                    msg += f"💰 50000원, ⚡ 1500pt\n📦 {rew_item} x15\n"

            await self.save_func(self.author.id, self.user_data)
            await interaction.response.send_message(msg, ephemeral=True)
            
            # 공통 보상 상자 선택 뷰 호출
            box_view = RewardChoiceView(self.author, self.user_data, self.save_func, rank, self)
            await interaction.followup.send(f"🎁 **{rank}성 보상 상자**를 선택하세요!", view=box_view, ephemeral=True)
            
            await self.fetch_quests()
            self.update_buttons()
            await interaction.message.edit(embed=self.get_embed(), view=self)

class CafeView(View):
    """카페 메인 화면 뷰"""
    def __init__(self, author, user_data, get_user_data_func, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.get_user_data_func = get_user_data_func
        self.save_func = save_func

    @discord.ui.button(label="거래 게시판", style=ButtonStyle.primary, emoji="📜")
    @auto_defer()
    async def trade_board(self, interaction: discord.Interaction, button: Button):
        # 뷰 진입 시 테이블 체크
        await check_global_tables()
        view = TradeBoardView(self.author, self.user_data, self.get_user_data_func, self.save_func)
        await view.update_message(interaction)

    @discord.ui.button(label="카페 주문", style=ButtonStyle.success, emoji="☕")
    @auto_defer()
    async def order_cafe(self, interaction: discord.Interaction, button: Button):
        view = CafeOrderView(self.author, self.user_data, self.get_user_data_func, self.save_func)
        await view.update_message(interaction)

    @discord.ui.button(label="의뢰 게시판", style=ButtonStyle.secondary, emoji="📋")
    @auto_defer(reload_data=True)
    async def quest_board(self, interaction: discord.Interaction, button: Button):
        view = CafeQuestView(self.author, self.user_data, self.save_func)
        # [수정] 비동기 초기화 호출
        await view.async_init()
        await interaction.edit_original_response(content=None, embed=view.get_embed(), view=view)

# ---------------------------------------------------------
# 1. 거래 게시판 (송금 및 거래 목록)
# ---------------------------------------------------------
class TradeBoardView(View):
    def __init__(self, author, user_data, get_user_data_func, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.get_user_data_func = get_user_data_func
        self.save_func = save_func
        self.page = 0
        self.PER_PAGE = 5

    async def update_message(self, interaction: discord.Interaction):
        embed = discord.Embed(title="📜 거래 게시판", description="유저 간 거래 및 송금을 할 수 있습니다.", color=discord.Color.blue())
        
        # [수정] 비동기 DB 연결 사용
        trades = []
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM global_trades ORDER BY id DESC")
                trades = await cursor.fetchall()
        
        if not trades:
            embed.add_field(name="안내", value="현재 등록된 거래 매물이 없습니다.", inline=False)
        else:
            total_pages = max(1, (len(trades) - 1) // self.PER_PAGE + 1)
            self.page = max(0, min(self.page, total_pages - 1))
            start = self.page * self.PER_PAGE
            current_trades = trades[start:start+self.PER_PAGE]
            
            for i, trade in enumerate(current_trades):
                idx = start + i + 1
                seller = trade.get('seller_name', '알수없음')
                item = trade.get('item_name', '아이템')
                qty = trade.get('quantity', 1)
                price = trade.get('price', 0)
                currency = "원" if trade.get('currency') == 'money' else "pt"
                
                embed.add_field(
                    name=f"#{idx} {item} x{qty}", 
                    value=f"판매자: {seller} | 가격: {price}{currency}", 
                    inline=False
                )
            
            embed.set_footer(text=f"페이지 {self.page+1}/{total_pages}")

        self.clear_items()
        
        # 송금 버튼
        send_btn = Button(label="송금하기", style=ButtonStyle.secondary, emoji="💸")
        send_btn.callback = self.send_money_callback
        self.add_item(send_btn)

        # 판매 등록 버튼
        sell_btn = Button(label="판매 등록", style=ButtonStyle.primary, emoji="📤")
        sell_btn.callback = self.register_trade_callback
        self.add_item(sell_btn)

        # 구매하기 메뉴 (현재 페이지 아이템)
        if trades:
            start = self.page * self.PER_PAGE
            current_trades = trades[start:start+self.PER_PAGE]
            
            options = []
            for i, trade in enumerate(current_trades):
                idx = start + i + 1
                item_name = trade['item_name']
                price = trade['price']
                currency = "원" if trade['currency'] == 'money' else "pt"
                
                # 본인 물건은 구매 불가 표시 (선택은 가능하되 콜백에서 막음)
                desc = f"판매자: {trade['seller_name']} | {price}{currency}"
                if trade['seller_id'] == self.author.id:
                    desc += " (본인)"
                
                options.append(SelectOption(
                    label=f"#{idx} {item_name} x{trade['quantity']}",
                    description=desc,
                    value=str(trade['id'])
                ))
            
            if options:
                select = Select(placeholder="구매할 아이템 선택", options=options, row=1)
                select.callback = self.buy_callback
                self.add_item(select)

        # 페이지 이동 버튼
        if trades and len(trades) > self.PER_PAGE:
            prev_btn = Button(label="◀️", style=ButtonStyle.secondary, row=2, disabled=(self.page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            total_pages = max(1, (len(trades) - 1) // self.PER_PAGE + 1)
            next_btn = Button(label="▶️", style=ButtonStyle.secondary, row=2, disabled=(self.page >= total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

        if interaction.response.is_done():
            await interaction.edit_original_response(content="", embed=embed, view=self)
        else:
            await interaction.response.edit_message(content="", embed=embed, view=self)

    @auto_defer()
    async def prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        await self.update_message(interaction)

    @auto_defer()
    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        await self.update_message(interaction)

    
class SendMoneyView(discord.ui.View):
    def __init__(self, user_data, get_user_data_func, save_func):
        super().__init__(timeout=60)
        self.user_data = user_data
        self.get_user_data_func = get_user_data_func
        self.save_func = save_func

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="💸 송금할 상대를 선택하세요")
    async def select_user(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        target_user = select.values[0]


    @auto_defer()
    async def buy_callback(self, interaction: discord.Interaction):
        trade_id = int(interaction.data['values'][0])
        
        # [수정] 비동기 DB 연결 사용
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 1. 거래 정보 확인
                    await cursor.execute("SELECT * FROM global_trades WHERE id = %s", (trade_id,))
                    trade = await cursor.fetchone()
                    
                    if not trade:
                        return await interaction.response.send_message("❌ 이미 판매되었거나 존재하지 않는 매물입니다.", ephemeral=True)
                    
                    if trade['seller_id'] == self.author.id:
                        # 본인 물건이면 회수 로직
                        await cursor.execute("DELETE FROM global_trades WHERE id = %s", (trade_id,))
                        await conn.commit()
                        
                        inv = self.user_data.setdefault("inventory", {})
                        inv[trade['item_name']] = inv.get(trade['item_name'], 0) + trade['quantity']
                        await self.save_func(self.author.id, self.user_data)
                        
                        await interaction.followup.send(f"✅ **{trade['item_name']}** 판매를 취소하고 회수했습니다.", ephemeral=True)
                        await self.update_message(interaction)
                        return

                    # 2. 구매자 자산 확인
                    price = trade['price']
                    currency = trade['currency']
                    user_balance = self.user_data.get(currency, 0)
                    
                    if user_balance < price:
                        return await interaction.followup.send(f"❌ 잔액이 부족합니다. (필요: {price}{currency})", ephemeral=True)
                    
                    # 3. 거래 실행 (트랜잭션)
                    # 3-1. 구매자 차감 및 아이템 지급
                    self.user_data[currency] -= price
                    inv = self.user_data.setdefault("inventory", {})
                    inv[trade['item_name']] = inv.get(trade['item_name'], 0) + trade['quantity']
                    
                    # 3-2. 판매자에게 돈 지급 (DB 직접 업데이트)
                    update_sql = f"UPDATE users SET {currency} = {currency} + %s WHERE user_id = %s"
                    await cursor.execute(update_sql, (price, trade['seller_id']))
                    
                    # 3-3. 거래 삭제
                    await cursor.execute("DELETE FROM global_trades WHERE id = %s", (trade_id,))
                    await conn.commit()
                    
                    # 3-4. 구매자 데이터 저장
                    await self.save_func(self.author.id, self.user_data)
                    
                    await interaction.followup.send(f"✅ **{trade['item_name']}** 구매 완료!", ephemeral=True)
                    await self.update_message(interaction)

        except Exception as e:
            print(f"Trade Error: {e}")
            await interaction.followup.send("❌ 거래 처리 중 오류가 발생했습니다.", ephemeral=True)


class RegisterTradeModal(Modal):
    def __init__(self, user_data, save_func, parent_view):
        super().__init__(title="📤 판매 등록")
        self.user_data = user_data
        self.save_func = save_func
        self.parent_view = parent_view

        self.item_name = TextInput(label="아이템 이름 (정확히 입력)", placeholder="예: 사과", required=True)
        self.quantity = TextInput(label="수량", placeholder="숫자만 입력", required=True)
        self.price = TextInput(label="가격", placeholder="숫자만 입력", required=True)
        self.currency = TextInput(label="화폐 (돈/pt)", placeholder="돈 또는 pt", required=True)

        self.add_item(self.item_name)
        self.add_item(self.quantity)
        self.add_item(self.price)
        self.add_item(self.currency)

    async def on_submit(self, interaction: discord.Interaction):
        item = self.item_name.value.strip()
        qty_str = self.quantity.value.strip()
        price_str = self.price.value.strip()
        curr_str = self.currency.value.strip()

        if not qty_str.isdigit() or not price_str.isdigit():
            return await interaction.response.send_message("❌ 수량과 가격은 숫자여야 합니다.", ephemeral=True)
        
        qty = int(qty_str)
        price = int(price_str)
        
        if qty <= 0 or price < 0:
            return await interaction.response.send_message("❌ 올바른 수량/가격을 입력하세요.", ephemeral=True)

        # 화폐 확인
        if curr_str in ["돈", "money", "원"]: currency = "money"
        elif curr_str in ["pt", "포인트", "PT"]: currency = "pt"
        else: return await interaction.response.send_message("❌ 화폐는 '돈' 또는 'pt'여야 합니다.", ephemeral=True)

        # 인벤토리 확인
        inv = self.user_data.get("inventory", {})
        if inv.get(item, 0) < qty:
            return await interaction.response.send_message(f"❌ 아이템이 부족합니다. (보유: {inv.get(item, 0)}개)", ephemeral=True)

        # DB 등록 [수정] 비동기 처리
        pool = await get_db_pool()
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        INSERT INTO global_trades (seller_id, seller_name, item_name, quantity, price, currency)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (interaction.user.id, interaction.user.display_name, item, qty, price, currency))
                    await conn.commit()
            
            # 아이템 차감 및 저장
            inv[item] -= qty
            if inv[item] <= 0: del inv[item]
            await self.save_func(interaction.user.id, self.user_data)
            
            await interaction.response.send_message(f"✅ **{item} x{qty}** 판매 등록 완료!", ephemeral=True)
            await self.parent_view.update_message(interaction)
            
        except Exception as e:
            print(f"Register Error: {e}")
            await interaction.response.send_message("❌ 등록 중 오류가 발생했습니다.", ephemeral=True)


class SendMoneyView(discord.ui.View):
    def __init__(self, user_data, get_user_data_func, save_func):
        super().__init__(timeout=60)
        self.user_data = user_data
        self.get_user_data_func = get_user_data_func
        self.save_func = save_func

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="💸 송금할 상대를 선택하세요")
    async def select_user(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        target_user = select.values[0]
        
        if target_user.id == interaction.user.id:
            return await interaction.response.send_message("❌ 자신에게는 송금할 수 없습니다.", ephemeral=True)
        if target_user.bot:
            return await interaction.response.send_message("❌ 봇에게는 송금할 수 없습니다.", ephemeral=True)
            
        await interaction.response.send_modal(SendMoneyAmountModal(self.user_data, self.get_user_data_func, self.save_func, target_user))


class SendMoneyAmountModal(Modal):
    def __init__(self, user_data, get_user_data_func, save_func, target_user):
        super().__init__(title=f"💸 {target_user.display_name}님에게 송금")
        self.user_data = user_data
        self.get_user_data_func = get_user_data_func
        self.save_func = save_func
        self.target_user = target_user

        self.amount = TextInput(label="보낼 금액", placeholder="숫자만 입력 (예: 5000)", required=True)
        self.currency = TextInput(label="화폐 종류 (돈/pt)", placeholder="'돈' 또는 'pt' 입력", required=True)

        self.add_item(self.amount)
        self.add_item(self.currency)

    async def on_submit(self, interaction: discord.Interaction):
        amount_str = self.amount.value.strip()
        currency_str = self.currency.value.strip()
        target_id = self.target_user.id

        # [수정] get_user_data_func는 비동기이므로 await 필수
        try:
            target_data = await self.get_user_data_func(target_id, self.target_user.display_name)
        except:
            await interaction.response.send_message("❌ 유효하지 않은 유저 ID입니다.", ephemeral=True)
            return

        if not amount_str.isdigit():
            await interaction.response.send_message("❌ 보낼 금액은 숫자여야 합니다.", ephemeral=True)
            return
        
        amount = int(amount_str)
        
        if currency_str in ["돈", "money", "원"]:
            key = "money"
            unit = "원"
        elif currency_str in ["pt", "포인트", "PT"]:
            key = "pt"
            unit = "pt"
        else:
            await interaction.response.send_message("❌ 화폐 종류는 '돈' 또는 'pt'여야 합니다.", ephemeral=True)
            return

        if self.user_data[key] < amount:
            await interaction.response.send_message(f"❌ 잔액이 부족합니다. (보유: {self.user_data[key]}{unit})", ephemeral=True)
            return

        # 송금 실행
        self.user_data[key] -= amount
        target_data[key] += amount
        
        # [수정] save_func 비동기 호출
        await self.save_func(interaction.user.id, self.user_data)
        await self.save_func(int(target_id), target_data)

        await interaction.response.send_message(f"✅ **송금 완료!**\n<@{target_id}>님에게 {amount}{unit}을 보냈습니다.", ephemeral=True)
        await interaction.response.send_message(f"✅ **송금 완료!**\n{self.target_user.mention}님에게 {amount}{unit}을 보냈습니다.", ephemeral=True)

# ---------------------------------------------------------
# 2. 카페 주문 (버프 음식)
# ---------------------------------------------------------
class CafeOrderView(View):
    def __init__(self, author, user_data, get_user_data_func, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.get_user_data_func = get_user_data_func
        self.save_func = save_func
        self.page = 0
        self.PER_PAGE = 7
        self.selected_indices = []
        self.target_char_index = 0

    async def update_message(self, interaction: discord.Interaction):
        total_price = sum(CAFE_MENU[i]['price'] for i in self.selected_indices)
        chars = self.user_data.get("characters", [])
        target_char_name = chars[self.target_char_index]["name"] if chars else "알 수 없음"

        embed = discord.Embed(title="☕ 카페 주문", description=f"**음식을 먹을 캐릭터:** {target_char_name}\n(최대 2개, 같은 효과 중복 불가)", color=discord.Color.gold())
        embed.add_field(name="내 지갑", value=f"💰 {self.user_data['money']}원", inline=False)
        
        if self.selected_indices:
            names = [CAFE_MENU[i]['name'] for i in self.selected_indices]
            embed.add_field(name="선택된 메뉴", value=", ".join(names) + f"\n**총 합계: {total_price}원**", inline=False)
        else:
            embed.add_field(name="선택된 메뉴", value="없음", inline=False)

        total_pages = (len(CAFE_MENU) - 1) // self.PER_PAGE + 1
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_menu = CAFE_MENU[start:end]

        menu_text = ""
        for i, item in enumerate(current_menu):
            real_idx = start + i
            mark = "✅" if real_idx in self.selected_indices else "▪️"
            menu_text += f"{mark} **{item['name']}** ({item['price']}원)\n   └ {item['desc']}\n"
        
        embed.add_field(name=f"메뉴판 ({self.page+1}/{total_pages})", value=menu_text, inline=False)

        self.clear_items()

        # 1. 캐릭터 선택 드롭다운 (Row 0)
        char_options = []
        for idx, c in enumerate(chars):
            char_options.append(SelectOption(
                label=c['name'], value=str(idx), 
                default=(idx == self.target_char_index)
            ))
        char_select = Select(placeholder="음식을 먹을 캐릭터 선택", options=char_options, row=0)
        char_select.callback = self.char_select_callback
        self.add_item(char_select)

        # 2. 메뉴 선택 드롭다운 (Row 1)
        options = []
        for i, item in enumerate(current_menu):
            real_idx = start + i
            options.append(SelectOption(
                label=f"{item['name']} ({item['price']}원)",
                description=item['desc'][:50],
                value=str(real_idx),
                default=(real_idx in self.selected_indices)
            ))
        
        select = Select(placeholder="메뉴를 선택하세요 (클릭하여 추가/제거)", min_values=1, max_values=min(len(current_menu), 2), options=options, row=1)
        select.callback = self.select_callback
        self.add_item(select)

        if total_pages > 1:
            prev_btn = Button(label="◀️", style=ButtonStyle.secondary, row=2, disabled=(self.page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            next_btn = Button(label="▶️", style=ButtonStyle.secondary, row=2, disabled=(self.page >= total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

        order_btn = Button(label="주문하기", style=ButtonStyle.primary, row=3, disabled=(not self.selected_indices))
        order_btn.callback = self.order_callback
        self.add_item(order_btn)

        cancel_btn = Button(label="취소", style=ButtonStyle.danger, row=3)
        cancel_btn.callback = self.cancel_callback
        self.add_item(cancel_btn)

        if interaction.response.is_done():
            await interaction.edit_original_response(content="", embed=embed, view=self)
        else:
            await interaction.response.edit_message(content="", embed=embed, view=self)

    @auto_defer()
    async def prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        await self.update_message(interaction)

    @auto_defer()
    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        await self.update_message(interaction)

    @auto_defer()
    async def char_select_callback(self, interaction: discord.Interaction):
        self.target_char_index = int(interaction.data['values'][0])
        await self.update_message(interaction)

    @auto_defer()
    async def select_callback(self, interaction: discord.Interaction):
        current_page_selection = [int(v) for v in interaction.data['values']]
        
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        other_page_selection = [idx for idx in self.selected_indices if not (start <= idx < end)]
        
        new_selection = other_page_selection + current_page_selection
        
        if len(new_selection) > 2:
            await interaction.followup.send("❌ 한 번에 최대 2개까지만 주문할 수 있습니다.", ephemeral=True)
            return

        stats = []
        for idx in new_selection:
            stat = CAFE_MENU[idx]['stat']
            if stat in stats:
                await interaction.followup.send(f"❌ 같은 효과({stat})를 가진 메뉴는 동시에 주문할 수 없습니다.", ephemeral=True)
                return
            stats.append(stat)

        self.selected_indices = new_selection
        await self.update_message(interaction)

    @auto_defer()
    async def order_callback(self, interaction: discord.Interaction):
        total_price = sum(CAFE_MENU[i]['price'] for i in self.selected_indices)
        if self.user_data['money'] < total_price:
            await interaction.followup.send("❌ 돈이 부족합니다.", ephemeral=True)
            return

        self.user_data['money'] -= total_price
        
        if 'buffs' not in self.user_data:
            self.user_data['buffs'] = {}
            
        chars = self.user_data.get("characters", [])
        target_char_name = chars[self.target_char_index]["name"] if chars else "Unknown"

        applied_names = []
        for idx in self.selected_indices:
            item = CAFE_MENU[idx]
            self.user_data['buffs'][item['name']] = {
                "stat": item['stat'],
                "value": item['value'],
                "duration": item['duration'],
                "target": target_char_name
            }
            applied_names.append(item['name'])
            
        # [신규] 버프 개수 제한 (최대 2개, 오래된 순으로 삭제)
        while len(self.user_data['buffs']) > 2:
            oldest_key = next(iter(self.user_data['buffs']))
            del self.user_data['buffs'][oldest_key]
            
        # [수정] save_func 비동기 호출 및 인자 수정
        await self.save_func(self.author.id, self.user_data)
        
        embed = discord.Embed(title="🧾 주문 완료", description=f"**{target_char_name}**님, 맛있게 드세요! 버프가 적용되었습니다.", color=discord.Color.green())
        embed.add_field(name="주문 메뉴", value=", ".join(applied_names), inline=False)
        embed.add_field(name="지불 금액", value=f"{total_price}원", inline=False)
        embed.add_field(name="남은 돈", value=f"{self.user_data['money']}원", inline=False)
        
        await interaction.edit_original_response(content="", embed=embed, view=None)

    @auto_defer()
    async def cancel_callback(self, interaction: discord.Interaction):
        await interaction.edit_original_response(content="주문을 취소했습니다.", embed=None, view=None)