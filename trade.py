import discord
from discord.ui import View, Button, Select, Modal, TextInput
from discord import SelectOption, ButtonStyle
import aiomysql
# [수정] DB 연결 풀을 공유하기 위해 data_manager에서 import
from data_manager import get_db_pool
from decorators import auto_defer

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

async def check_trade_table():
    """거래 테이블이 없으면 생성 (비동기 처리)"""
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("""
                    CREATE TABLE IF NOT EXISTS global_trades (
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
    except Exception as e:
        print(f"⚠️ 거래 테이블 확인 중 오류: {e}")

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
        await check_trade_table()
        view = TradeBoardView(self.author, self.user_data, self.get_user_data_func, self.save_func)
        await view.update_message(interaction)

    @discord.ui.button(label="카페 주문", style=ButtonStyle.success, emoji="☕")
    @auto_defer()
    async def order_cafe(self, interaction: discord.Interaction, button: Button):
        view = CafeOrderView(self.author, self.user_data, self.get_user_data_func, self.save_func)
        await view.update_message(interaction)

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

    async def send_money_callback(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.send_modal(SendMoneyModal(self.user_data, self.get_user_data_func, self.save_func))

    async def register_trade_callback(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.send_modal(RegisterTradeModal(self.user_data, self.save_func, self))

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

class SendMoneyModal(Modal):
    def __init__(self, user_data, get_user_data_func, save_func):
        super().__init__(title="💸 송금하기")
        self.user_data = user_data
        self.get_user_data_func = get_user_data_func
        self.save_func = save_func

        self.target_id = TextInput(label="받을 사람 ID (우클릭 -> ID 복사)", placeholder="예: 123456789012345678", required=True)
        self.amount = TextInput(label="보낼 금액", placeholder="숫자만 입력", required=True)
        self.currency = TextInput(label="화폐 종류 (돈/pt)", placeholder="돈 또는 pt 입력", required=True)

        self.add_item(self.target_id)
        self.add_item(self.amount)
        self.add_item(self.currency)

    async def on_submit(self, interaction: discord.Interaction):
        target_id = self.target_id.value.strip()
        amount_str = self.amount.value.strip()
        currency_str = self.currency.value.strip()

        # [수정] get_user_data_func는 비동기이므로 await 필수
        try:
            target_data = await self.get_user_data_func(int(target_id), "Unknown")
        except:
            await interaction.response.send_message("❌ 유효하지 않은 유저 ID입니다.", ephemeral=True)
            return

        if not amount_str.isdigit() or int(amount_str) <= 0:
            await interaction.response.send_message("❌ 올바른 금액을 입력해주세요.", ephemeral=True)
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