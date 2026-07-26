# shop.py
import discord
import json
import os
from items import ITEM_PRICES, ITEM_CATEGORIES, REGIONS, CRAFT_RECIPES
from cards import CARD_PRICES
from artifacts import generate_artifact
from data_manager import get_user_data
from decorators import auto_defer

DATA_FILE = "user_data.json"

# [설정] 포인트 충전 가격
PT_PRICES = {
    "100pt": 1000,
    "500pt": 4500,
    "1000pt": 8000,
    "10000pt": 75000  # 신규 고액권
}

# [설정] 지역별 카드 해금 조건
# 여기에 정의된 카드는 해당 지역을 해금해야만 상점에 등장합니다.
CARD_REGION_MAP = {
    # 초반 지역
    "시간의 신전": ["복합공격", "복합반격", "숨고르기", "기본집중"],
    "일한산 중턱": ["깊은집중", "강한참격", "회전베기", "회피기동", "육참골단"],
    "이루지 못한 꿈들의 별": ["집중반격", "자각몽", "꿈꾸기", "중급회복"],
    
    # 중후반 지역 (기존 데이터 유지)
    "생명의 숲": ["더러운 공격", "상처 벌리기", "불안정한 재생", "연속내치기"],
    "아르카워드 제도": ["폭풍", "사이클론", "산들바람", "모닝 글로리"],
    "공간의 신전": ["순간이동", "차원베기", "방울연발", "방울방울"]
}



class ShopView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.page = 0
        self._rebuild_menu()

    def _rebuild_menu(self):
        self.clear_items()
        entries = [self.buy_consumable, self.buy_card, self.pt_shop_tab, self.sell_tab, self.exit_shop]
        for item in entries[self.page * 3:self.page * 3 + 3]:
            self.add_item(item)
        page_button = discord.ui.Button(
            label="이전 메뉴" if self.page else "다음 메뉴",
            style=discord.ButtonStyle.secondary,
            row=3,
        )
        page_button.callback = self._toggle_page
        self.add_item(page_button)

    async def _toggle_page(self, interaction):
        self.page = 0 if self.page else 1
        self._rebuild_menu()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    def create_shop_embed(self, title="🛒 상점", desc="원하시는 항목을 선택해주세요."):
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        
        embed = discord.Embed(title=title, description=desc, color=discord.Color.gold())
        embed.add_field(name="💰 보유 머니", value=f"{money:,}원", inline=True)
        embed.add_field(name="⚡ 보유 포인트", value=f"{pt:,}pt", inline=True)
        return embed

    def get_embed(self):
        return self.create_shop_embed()

    # --- [1] 구매 섹션 ---
    @discord.ui.button(label="🧪 소모품 구매", style=discord.ButtonStyle.success, row=0)
    @auto_defer()
    async def buy_consumable(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_buy_dropdown(interaction, "consumable", "🧪 **[소모품]** 구매 목록입니다.", use_pt=False)

    @discord.ui.button(label="🃏 카드 구매", style=discord.ButtonStyle.danger, row=0)
    @auto_defer()
    async def buy_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.open_buy_dropdown(interaction, "card", "🃏 **[기술 카드]** 구매 목록입니다.\n(해금된 지역의 카드만 등장합니다)", use_pt=True)

    # --- [2] 포인트 상점 (통합) ---
    @discord.ui.button(label="⚡ 포인트 상점", style=discord.ButtonStyle.secondary, row=1)
    @auto_defer(reload_data=True)
    async def pt_shop_tab(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PointShopView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(content="⚡ **[포인트 상점]** 충전이나 뽑기를 할 수 있어!", embed=self.create_shop_embed(), view=view)

    # --- [3] 판매 섹션 (지역별) ---
    @discord.ui.button(label="💰 아이템 판매", style=discord.ButtonStyle.primary, row=1)
    @auto_defer(reload_data=True)
    async def sell_tab(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = SellRegionView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(content="💵 **[판매]** 판매할 아이템의 지역을 선택해줘.", embed=self.create_shop_embed(), view=view)

    @discord.ui.button(label="👋 나가기", style=discord.ButtonStyle.gray, row=2)
    @auto_defer()
    async def exit_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.edit_original_response(content="👋 상점을 나갔습니다.", embed=None, view=None)

    # --- Helper Methods ---
    async def open_buy_dropdown(self, interaction, category, text, use_pt=False):
        # 모든 제작 아이템 식별 (구매 불가 리스트)
        excluded_crafts = {r_data["result"] for r_data in CRAFT_RECIPES.values()}

        unlocked_regions = self.user_data.get("unlocked_regions", [])
        options = []

        if use_pt: # [카드 구매 로직]
            for card, price in CARD_PRICES.items():
                # 이미 보유한 카드는 제외
                if card in self.user_data.get("cards", []):
                    continue 

                # 지역 해금 조건 확인
                is_locked = False
                for region, region_cards in CARD_REGION_MAP.items():
                    if card in region_cards and region not in unlocked_regions:
                        is_locked = True
                        break
                
                if not is_locked:
                    options.append(discord.SelectOption(label=f"{card} ({price}pt)", value=card))
        
        else: # [아이템 구매 로직]
            for item, price in ITEM_PRICES.items():
                info = ITEM_CATEGORIES.get(item, {})
                
                # 지역 제한 및 제작 전용 아이템 필터링
                if info.get("area") in ["생명의 숲", "아르카워드 제도", "공간의 신전"]: continue
                if item in excluded_crafts: continue

                # [수정] 소모품 구매 시 부적, 비료, 씨앗 등 비매품 제외 (회복 아이템만 표시)
                if category == "consumable" and any(x in item for x in ["부적", "비료", "씨앗"]):
                    continue

                if info.get("type") == category:
                    p = price * 2 if category == "rare_mat" else price
                    options.append(discord.SelectOption(label=f"{item} ({p:,}원)", value=item))
        
        if not options:
            return await interaction.followup.send("❌ 현재 구매 가능한 상품이 없습니다. (지역 해금 필요)", ephemeral=True)
        
        view = BuyDropdownView(self.author, self.user_data, self.save_func, options, use_pt)
        await interaction.edit_original_response(content=text, embed=self.create_shop_embed(), view=view)


# --- [포인트 상점] 뷰 (충전 & 뽑기) ---
class PointShopView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        
        # 1. 충전 버튼 생성
        for label, price in PT_PRICES.items():
            style = discord.ButtonStyle.green
            if label == "10000pt": style = discord.ButtonStyle.blurple # 고액권 강조
            btn = discord.ui.Button(label=f"{label} ({price:,}원)", style=style)
            btn.callback = self.make_pt_callback(label, price)
            self.add_item(btn)
        
        # 2. 뽑기 버튼
        gacha_btn = discord.ui.Button(label="🎲 아티팩트 뽑기 (1,000pt)", style=discord.ButtonStyle.primary, row=1)
        gacha_btn.callback = self.artifact_gacha_callback
        self.add_item(gacha_btn)
        
        # 3. 뒤로가기
        back_btn = discord.ui.Button(label="⬅️ 메인으로", style=discord.ButtonStyle.secondary, row=2)
        back_btn.callback = self.back_callback
        self.add_item(back_btn)

    

    def create_shop_embed(self, desc="포인트를 충전하거나 아티팩트를 뽑아보세요."):
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        embed = discord.Embed(title="⚡ 포인트 상점", description=desc, color=discord.Color.green())
        embed.add_field(name="💰 보유 머니", value=f"{money:,}원", inline=True)
        embed.add_field(name="⚡ 보유 포인트", value=f"{pt:,}pt", inline=True)
        return embed

    @auto_defer(reload_data=True)
    async def artifact_gacha_callback(self, interaction: discord.Interaction):
        COST = 1000
        current_pt = self.user_data.get("pt", 0)
        
        if current_pt < COST:
            return await interaction.followup.send(f"❌ 포인트가 부족합니다! (보유: {current_pt}pt)", ephemeral=True)
        
        self.user_data["pt"] -= COST
        new_artifact = generate_artifact()
        if "artifacts" not in self.user_data:
            self.user_data["artifacts"] = []
        self.user_data["artifacts"].append(new_artifact)
        
        await self.save_func(self.author.id, self.user_data)
        
        res_embed = discord.Embed(title="🎉 아티팩트 획득!", color=discord.Color.purple())
        res_embed.add_field(name=new_artifact["name"], value=new_artifact["description"], inline=False)
        res_embed.set_footer(text=f"남은 포인트: {self.user_data['pt']}pt")
        
        # 화면 유지
        await interaction.edit_original_response(content="🎲 뽑기 완료!", embed=res_embed, view=self)

    @auto_defer()
    async def back_callback(self, interaction: discord.Interaction):
        main_v = ShopView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(content="🛒 상점 메인", embed=main_v.create_shop_embed(), view=main_v)

    def make_pt_callback(self, label, price):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.author.id:
                return await interaction.response.send_message("❌ 본인의 메뉴만 조작할 수 있습니다.", ephemeral=True)
            
            await interaction.response.defer()
            self.user_data = await get_user_data(self.author.id, self.author.display_name)
            
            if self.user_data.get("money", 0) < price:
                return await interaction.followup.send("❌ 머니 부족!", ephemeral=True)
            
            self.user_data["money"] -= price
            pt_val = int(label.replace("pt", ""))
            self.user_data["pt"] = self.user_data.get("pt", 0) + pt_val
            
            await self.save_func(self.author.id, self.user_data)
            
            # 충전 후 화면 유지 및 갱신
            await interaction.edit_original_response(content=f"✅ **{label}** 충전 완료!", embed=self.create_shop_embed(), view=self)
        return callback


# --- [구매] 드롭다운 뷰 (페이지네이션 적용) ---
class BuyDropdownView(discord.ui.View):
    def __init__(self, author, user_data, save_func, all_options, use_pt):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.use_pt = use_pt
        self.selected_item = None
        self.all_options = all_options
        self.page = 0
        self.PER_PAGE = 7
        self.buy_amount = 1
        
        self.update_view()

    def create_shop_embed(self, title_suffix=""):
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        currency = "PT" if self.use_pt else "머니"
        embed = discord.Embed(title=f"🛒 구매{title_suffix}", description=f"보유한 {currency}로 아이템을 구매합니다.", color=discord.Color.blue())
        embed.add_field(name="💰 보유 머니", value=f"{money:,}원", inline=True)
        embed.add_field(name="⚡ 보유 포인트", value=f"{pt:,}pt", inline=True)
        return embed

    def update_view(self):
        self.clear_items()
        
        total_pages = (len(self.all_options) - 1) // self.PER_PAGE + 1
        if self.page < 0: self.page = 0
        if self.page >= total_pages: self.page = max(0, total_pages - 1)
        
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_opts = self.all_options[start:end]
        
        # 목록이 비어있으면 뒤로가기만 표시
        if not current_opts:
            self.add_item(discord.ui.Button(label="구매 가능한 아이템이 없습니다", disabled=True))
        else:
            self.select = discord.ui.Select(placeholder=f"구매할 아이템 선택 ({self.page+1}/{total_pages})", options=current_opts, row=0)
            self.select.callback = self.item_callback
            self.add_item(self.select)
            
            amount_options = [discord.SelectOption(label="1개", value="1", default=self.buy_amount == 1)]
            if not self.use_pt:
                amount_options.extend([
                    discord.SelectOption(label="5개", value="5", default=self.buy_amount == 5),
                    discord.SelectOption(label="10개", value="10", default=self.buy_amount == 10),
                    discord.SelectOption(label="최대", value="all", default=self.buy_amount == "all"),
                ])
            amount_select = discord.ui.Select(placeholder="구매 수량", options=amount_options, row=1)
            amount_select.callback = self.select_amount
            self.add_item(amount_select)
            self.add_item(discord.ui.Button(label="구매", style=discord.ButtonStyle.success, row=2, custom_id="buy"))
        
        if total_pages > 1:
            self.add_item(discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=2, custom_id="prev", disabled=(self.page==0)))
            self.add_item(discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=2, custom_id="next", disabled=(self.page==total_pages-1)))
            
        self.add_item(discord.ui.Button(label="⬅️ 상점으로", style=discord.ButtonStyle.secondary, row=3, custom_id="back"))

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.author: return False
        await interaction.response.defer()
        cid = interaction.data.get("custom_id")
        if cid == "prev": self.page -= 1; self.update_view(); await interaction.edit_original_response(view=self)
        elif cid == "next": self.page += 1; self.update_view(); await interaction.edit_original_response(view=self)
        elif cid == "back":
            v = ShopView(self.author, self.user_data, self.save_func)
            await interaction.edit_original_response(content="🛒 상점 메인", embed=v.create_shop_embed(), view=v)
        elif cid == "buy": await self.process_buy(interaction, self.buy_amount)
        return True

    

    async def item_callback(self, i: discord.Interaction):
        self.selected_item = self.select.values[0]
        # 선택 UI 반영
        for option in self.select.options:
            option.default = (option.value == self.selected_item)
        
        await i.edit_original_response(content=f"🛍️ **[{self.selected_item}]** 선택됨. 수량을 골라주세요.", view=self)

    async def select_amount(self, interaction: discord.Interaction):
        value = interaction.data["values"][0]
        self.buy_amount = value if value == "all" else int(value)
        await interaction.response.defer()

    async def process_buy(self, i, amount):
        if not self.selected_item: 
            return await i.followup.send("❌ 먼저 아이템을 선택해주세요.", ephemeral=True)
        
        self.user_data = await get_user_data(self.author.id, self.author.display_name)

        # [특수] 강화키트: 돈+포인트 복합 결제
        if self.selected_item == "강화키트":
            if amount == "all":
                max_by_money = self.user_data.get("money", 0) // 50000
                max_by_pt = self.user_data.get("pt", 0) // 3000
                amount = max(1, min(max_by_money, max_by_pt))
            
            total_money = 50000 * amount
            total_pt = 3000 * amount
            
            if self.user_data.get("money", 0) < total_money:
                return await i.followup.send(f"❌ 돈이 부족합니다! ({total_money:,}원 필요)", ephemeral=True)
            if self.user_data.get("pt", 0) < total_pt:
                return await i.followup.send(f"❌ 포인트가 부족합니다! ({total_pt:,}pt 필요)", ephemeral=True)
            
            self.user_data["money"] -= total_money
            self.user_data["pt"] -= total_pt
            
            inv = self.user_data.setdefault("inventory", {})
            inv["강화키트"] = inv.get("강화키트", 0) + amount
            
            await self.save_func(self.author.id, self.user_data)
            
            # [UI 유지] 임베드 갱신
            self.update_view()
            embed = self.create_shop_embed(title_suffix=" - 완료")
            
            return await i.edit_original_response(
                content=f"✅ **강화키트** {amount}개 구매 성공! (💰{total_money:,} / ⚡{total_pt:,} 소모)",
                embed=embed,
                view=self
            )

        # [일반] 가격 계산
        base_p = CARD_PRICES[self.selected_item] if self.use_pt else ITEM_PRICES[self.selected_item]
        if not self.use_pt and ITEM_CATEGORIES.get(self.selected_item,{}).get("type") == "rare_mat": base_p *= 2
        
        cur = "pt" if self.use_pt else "money"
        if amount == "all":
            amount = max(1, self.user_data.get(cur, 0) // base_p)
            if self.use_pt: amount = 1 
            if amount < 1: amount = 1 
            
        total = base_p * amount
        if self.user_data.get(cur, 0) < total: return await i.followup.send("❌ 잔액 부족", ephemeral=True)

        # [특수] 이름 변경권
        if self.selected_item == "이름 변경권":
            pt_cost = 4000 * amount
            if self.user_data.get("pt", 0) < pt_cost:
                return await i.followup.send(f"❌ 포인트 부족! ({pt_cost}pt 필요)", ephemeral=True)
            self.user_data["pt"] -= pt_cost
            total = 0 # 위에서 차감함

        # 구매 처리
        if self.use_pt: # 카드
            if self.selected_item in self.user_data.get("cards", []):
                return await i.followup.send("❌ 이미 보유한 카드입니다.", ephemeral=True)
            self.user_data.setdefault("cards", []).append(self.selected_item)
            
            # 카드는 1회성 구매이므로 목록에서 사라짐 -> 옵션 갱신 필요
            # 현재 옵션 리스트에서 제거
            self.all_options = [opt for opt in self.all_options if opt.value != self.selected_item]
            self.selected_item = None
        else: # 아이템
            inv = self.user_data.setdefault("inventory", {})
            inv[self.selected_item] = inv.get(self.selected_item, 0) + amount

        if total > 0:
            self.user_data[cur] -= total
            
        await self.save_func(self.author.id, self.user_data)
        
        # [UI 유지] 뷰 리프레시 및 결과 표시
        self.update_view()
        embed = self.create_shop_embed(title_suffix=" - 완료")
        
        await i.edit_original_response(
            content=f"✅ **{self.selected_item if self.selected_item else '카드'}** {amount}개 구매 성공!",
            embed=embed,
            view=self
        )


# --- [판매] 지역 선택 뷰 ---
class SellRegionView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.page = 0
        self.items_per_page = 3
        self.update_buttons()

    def create_shop_embed(self, title="🛒 상점", desc="원하시는 항목을 선택해주세요."):
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        
        embed = discord.Embed(title=title, description=desc, color=discord.Color.gold())
        embed.add_field(name="💰 보유 머니", value=f"{money:,}원", inline=True)
        embed.add_field(name="⚡ 보유 포인트", value=f"{pt:,}pt", inline=True)
        return embed

    def update_buttons(self):
        self.clear_items()
        unlocked_list = self.user_data.get("unlocked_regions", ["기원의 쌍성"])
        all_regions = list(REGIONS.keys())
        visible_regions = [r for r in all_regions if r in unlocked_list]
        
        total_pages = (len(visible_regions) - 1) // self.items_per_page + 1
        if self.page < 0: self.page = 0
        if self.page >= total_pages: self.page = max(0, total_pages - 1)
        
        start = self.page * self.items_per_page
        end = start + self.items_per_page
        current_regions = visible_regions[start:end]

        for region in current_regions:
            btn = discord.ui.Button(label=region, style=discord.ButtonStyle.primary, custom_id=f"sell_{region}")
            self.add_item(btn)

        etc_btn = discord.ui.Button(label="📦 기타/제작품", style=discord.ButtonStyle.secondary, custom_id="sell_etc")
        self.add_item(etc_btn)

        if total_pages > 1:
            self.add_item(discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1, custom_id="prev", disabled=(self.page==0)))
            self.add_item(discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1, custom_id="next", disabled=(self.page==total_pages-1)))

        self.add_item(discord.ui.Button(label="⬅️ 상점으로", style=discord.ButtonStyle.gray, row=2, custom_id="back"))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        await i.response.defer()
        cid = i.data.get("custom_id")
        
        if cid == "prev": self.page -= 1; self.update_buttons(); await i.edit_original_response(view=self)
        elif cid == "next": self.page += 1; self.update_buttons(); await i.edit_original_response(view=self)
        elif cid == "back":
            v = ShopView(self.author, self.user_data, self.save_func)
            await i.edit_original_response(content="🛒 상점 메인", embed=v.create_shop_embed(), view=v)
        elif str(cid).startswith("sell_"):
            region = cid.replace("sell_", "")
            await self.open_sell_item_view(i, region)
        return True

    async def open_sell_item_view(self, interaction, region_key):
        view = SellItemView(self.author, self.user_data, self.save_func, region_key)
        
        if not view.all_options:
             return await interaction.followup.send(f"❌ 해당 지역에 판매 가능한 아이템이 없습니다.", ephemeral=True)
             
        await interaction.edit_original_response(content=f"💰 **[{region_key}]** 판매할 아이템을 선택하세요.", embed=view.create_shop_embed(), view=view)


# --- [판매] 아이템 선택 및 실행 뷰 ---
class SellItemView(discord.ui.View):
    def __init__(self, author, user_data, save_func, region_key):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.region_key = region_key
        self.selected_item = None
        self.page = 0
        self.PER_PAGE = 7
        
        # 초기 옵션 로드
        self.all_options = self.generate_options()
        self.update_view()

    def generate_options(self):
        """현재 인벤토리와 지역 키를 기반으로 판매 옵션 생성"""
        inv = self.user_data.get("inventory", {})
        options = []
        
        for item, count in inv.items():
            if count <= 0: continue
            if item not in ITEM_PRICES: continue 
            
            info = ITEM_CATEGORIES.get(item, {})

            item_area = info.get("area") 
            if not item_area:
                for r_name, r_data in REGIONS.items():
                    if item in r_data.get("common", []) or item in r_data.get("rare", []):
                        item_area = r_name
                        break
            
            if not item_area:
                for recipe in CRAFT_RECIPES.values():
                    if recipe.get("result") == item:
                        item_area = recipe.get("region", "기원의 쌍성")
                        break

            if not item_area: item_area = "etc"
            
            is_match = (item_area == self.region_key) if self.region_key != "etc" else (item_area not in REGIONS)
            
            if is_match:
                price = ITEM_PRICES.get(item, 0) // 2
                options.append(discord.SelectOption(label=f"{item} ({count}개 | {price:,}원)", value=item))
        
        return options

    def create_shop_embed(self, title_suffix=""):
        money = self.user_data.get("money", 0)
        embed = discord.Embed(title=f"💰 판매{title_suffix}", description=f"**[{self.region_key}]** 아이템 판매\n보유 잔액: {money:,}원", color=discord.Color.green())
        return embed

    def update_view(self):
        self.clear_items()
        
        total_pages = (len(self.all_options) - 1) // self.PER_PAGE + 1
        if self.page < 0: self.page = 0
        if self.page >= total_pages: self.page = max(0, total_pages - 1)
        
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_opts = self.all_options[start:end]
        
        if not current_opts:
            self.add_item(discord.ui.Button(label="판매 가능한 아이템이 없습니다", disabled=True))
        else:
            self.select = discord.ui.Select(placeholder=f"판매 아이템 선택 ({self.page+1}/{total_pages})", options=current_opts, row=0)
            self.select.callback = self.on_select
            self.add_item(self.select)
            
            # 수량 버튼
            self.add_item(discord.ui.Button(label="1개", style=discord.ButtonStyle.primary, row=1, custom_id="s1"))
            self.add_item(discord.ui.Button(label="5개", style=discord.ButtonStyle.primary, row=1, custom_id="s5"))
            self.add_item(discord.ui.Button(label="10개", style=discord.ButtonStyle.primary, row=1, custom_id="s10"))
            self.add_item(discord.ui.Button(label="전부", style=discord.ButtonStyle.danger, row=1, custom_id="sall"))
        
        if total_pages > 1:
            self.add_item(discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=2, custom_id="prev", disabled=(self.page==0)))
            self.add_item(discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=2, custom_id="next", disabled=(self.page==total_pages-1)))
            
        self.add_item(discord.ui.Button(label="⬅️ 지역 선택으로", style=discord.ButtonStyle.gray, row=3, custom_id="cancel"))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        await i.response.defer()
        cid = i.data.get("custom_id")
        if cid == "prev": self.page -= 1; self.update_view(); await i.edit_original_response(view=self)
        elif cid == "next": self.page += 1; self.update_view(); await i.edit_original_response(view=self)
        elif cid == "cancel":
            v = SellRegionView(self.author, self.user_data, self.save_func)
            await i.edit_original_response(content="판매 지역 선택", embed=v.create_shop_embed(), view=v)
        elif cid == "s1": await self.process_sell(i, 1)
        elif cid == "s5": await self.process_sell(i, 5)
        elif cid == "s10": await self.process_sell(i, 10)
        elif cid == "sall": await self.process_sell(i, "all")
        return True

    @auto_defer()
    async def on_select(self, interaction: discord.Interaction):
        self.selected_item = self.select.values[0]
        # 선택 UI 반영
        for opt in self.select.options:
            opt.default = (opt.value == self.selected_item)
        await interaction.edit_original_response(content=f"💰 **[{self.selected_item}]** 몇 개 판매할까요?", view=self)

    async def process_sell(self, interaction, amount):
        if not self.selected_item: 
            return await interaction.followup.send("❌ 먼저 아이템을 선택해주세요.", ephemeral=True)
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
        inv = self.user_data.setdefault("inventory", {})
        current = inv.get(self.selected_item, 0)
        num = current if amount == "all" else amount
        
        if current < num or num <= 0:
            return await interaction.followup.send("❌ 판매할 수량이 부족합니다.", ephemeral=True)
            
        price_unit = ITEM_PRICES.get(self.selected_item, 0) // 2
        total_price = price_unit * num
        
        inv[self.selected_item] -= num
        if inv[self.selected_item] <= 0:
            del inv[self.selected_item]
            
        self.user_data["money"] += total_price
        await self.save_func(self.author.id, self.user_data)
        
        # [수정] 판매 후 화면 유지 (목록 갱신)
        if amount == "all" or inv.get(self.selected_item, 0) <= 0:
            self.selected_item = None # 다 팔았으면 선택 해제
            
        self.all_options = self.generate_options()
        self.update_view()
        
        await interaction.edit_original_response(
            content=f"✅ **{self.selected_item if self.selected_item else '아이템'}** {num}개를 **{total_price:,}원**에 판매했습니다!",
            embed=self.create_shop_embed(title_suffix=" - 완료"),
            view=self
        )
