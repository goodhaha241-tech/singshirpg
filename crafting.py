# crafting.py
import discord
import json
import os
import random
from items import CRAFT_RECIPES, ITEM_CATEGORIES, ITEM_PRICES, COMMON_ITEMS, RARE_ITEMS, REGIONS
from fishing import FISH_TIERS
from story import update_quest_progress
from data_manager import get_user_data

DATA_FILE = "user_data.json"

# --- [1] 지역 선택 뷰 (메인 - 버튼식) ---
class CraftView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.page = 0
        self.ITEMS_PER_PAGE = 3 
        self.update_buttons()

    async def reload_data(self):
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
    

    def update_buttons(self):
        self.clear_items()
        
        unlocked = self.user_data.get("unlocked_regions", ["기원의 쌍성"])
        all_recipe_regions = set(info.get("region", "기원의 쌍성") for info in CRAFT_RECIPES.values())
        
        active_regions = []
        # items.py의 REGIONS 순서(해금 순서)대로 정렬하여 표시
        for region in REGIONS.keys():
            if region in unlocked:
                if region in all_recipe_regions or region == "기원의 쌍성":
                    active_regions.append(region)

        total_pages = (len(active_regions) - 1) // self.ITEMS_PER_PAGE + 1
        if self.page < 0: self.page = 0
        if self.page >= total_pages: self.page = max(0, total_pages - 1)
        
        start = self.page * self.ITEMS_PER_PAGE
        end = start + self.ITEMS_PER_PAGE
        current_regions = active_regions[start:end]
        
        for region_name in current_regions:
            btn = discord.ui.Button(label=region_name, style=discord.ButtonStyle.primary)
            btn.callback = self.make_region_callback(region_name)
            self.add_item(btn)
            
        box_btn = discord.ui.Button(label="📦 상자깡", style=discord.ButtonStyle.success)
        box_btn.callback = self.open_box_menu
        self.add_item(box_btn)

        if total_pages > 1:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            count_btn = discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, row=1, disabled=True)
            self.add_item(count_btn)

            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page == total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

        exit_btn = discord.ui.Button(label="👋 나가기", style=discord.ButtonStyle.danger, row=2)
        exit_btn.callback = self.exit_process
        self.add_item(exit_btn)

    def make_region_callback(self, region_name):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.author: return
            await self.reload_data()
            view = RegionCraftView(self.author, self.user_data, self.save_func, region_name)
            await interaction.response.edit_message(content=f"🔨 **[{region_name}]** 제작 목록", embed=None, view=view)
        return callback

    async def open_box_menu(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await self.reload_data()
        view = BoxOpenView(self.author, self.user_data, self.save_func, self)
        await interaction.response.edit_message(content="📦 **상자깡** 메뉴입니다.", embed=None, view=view)

    async def prev_page(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await self.reload_data()
        self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await self.reload_data()
        self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def exit_process(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.edit_message(content="👋 제작소를 나갔습니다.", embed=None, view=None)


# --- [2] 지역별 제작품 목록 뷰 ---
class RegionCraftView(discord.ui.View):
    def __init__(self, author, user_data, save_func, region_name):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.region_name = region_name
        self.page = 0
        self.PER_PAGE = 7 
        self.update_components()

    async def reload_data(self):
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
    

    def update_components(self):
        self.clear_items()
        inv = self.user_data.get("inventory", {})
        
        recipes = []
        for key, info in CRAFT_RECIPES.items():
            r_region = info.get("region", "기원의 쌍성")
            if r_region == self.region_name:
                recipes.append((key, info))
        
        total_pages = (len(recipes) - 1) // self.PER_PAGE + 1
        if self.page < 0: self.page = 0
        if self.page >= total_pages: self.page = max(0, total_pages - 1)
        
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_list = recipes[start:end]
        
        options = []
        for key, info in current_list:
            res_name = info["result"]
            current_count = inv.get(res_name, 0)
            
            can_craft = True
            mat_status = []
            
            for mat, req in info["need"].items():
                has = inv.get(mat, 0)
                mat_status.append(f"{mat}({has}/{req})")
                if has < req:
                    can_craft = False
            
            status_icon = "✅" if can_craft else "❌"
            label = f"{status_icon} {res_name} (보유: {current_count})"
            
            desc = ", ".join(mat_status)
            if len(desc) > 95: desc = desc[:95] + "..."
            
            options.append(discord.SelectOption(label=label, description=desc, value=key))
            
        if not options:
            options.append(discord.SelectOption(label="제작 가능한 아이템이 없습니다.", value="none"))

        select = discord.ui.Select(placeholder=f"제작할 아이템 선택 ({self.page+1}/{total_pages})", options=options, row=0)
        select.callback = self.on_select_recipe
        self.add_item(select)
            
        if total_pages > 1:
            if self.page > 0:
                prev = discord.ui.Button(label="◀️ 이전", style=discord.ButtonStyle.secondary, row=1)
                prev.callback = self.prev_page
                self.add_item(prev)
            if self.page < total_pages - 1:
                nxt = discord.ui.Button(label="다음 ▶️", style=discord.ButtonStyle.secondary, row=1)
                nxt.callback = self.next_page
                self.add_item(nxt)
                
        back_btn = discord.ui.Button(label="⬅️ 지역 선택", style=discord.ButtonStyle.gray, row=2)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

        exit_btn = discord.ui.Button(label="👋 나가기", style=discord.ButtonStyle.danger, row=2)
        exit_btn.callback = self.exit_process
        self.add_item(exit_btn)

    async def on_select_recipe(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        key = interaction.data['values'][0]
        if key == "none": return

        info = CRAFT_RECIPES.get(key)
        if not info:
            return await interaction.response.send_message("❌ 레시피 정보를 찾을 수 없습니다.", ephemeral=True)
        
        view = CraftAmountView(self.author, self.user_data, self.save_func, key, info, self)
        
        req_text = []
        inv = self.user_data.get("inventory", {})
        for item, count in info["need"].items():
            have = inv.get(item, 0)
            mark = "✅" if have >= count else "❌"
            req_text.append(f"{mark} {item}: {have}/{count}")
        
        res_name = info["result"]
        cur_stock = inv.get(res_name, 0)
        
        embed = discord.Embed(
            title=f"🔨 {res_name} 제작", 
            description=f"현재 보유량: **{cur_stock}개**\n\n**[필요 재료]**\n" + "\n".join(req_text), 
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(content=None, embed=embed, view=view)

    async def prev_page(self, i): 
        if i.user != self.author: return
        await self.reload_data()
        self.page-=1; self.update_components(); await i.response.edit_message(view=self)
        
    async def next_page(self, i): 
        if i.user != self.author: return
        await self.reload_data()
        self.page+=1; self.update_components(); await i.response.edit_message(view=self)
    
    async def go_back(self, interaction):
        if interaction.user != self.author: return
        await self.reload_data()
        view = CraftView(self.author, self.user_data, self.save_func)
        await interaction.response.edit_message(content="🔨 제작소 메인", embed=None, view=view)

    async def exit_process(self, interaction):
        if interaction.user != self.author: return
        await interaction.response.edit_message(content="👋 제작소를 나갔습니다.", embed=None, view=None)


# --- [3] 수량 선택 뷰 ---
class CraftAmountView(discord.ui.View):
    def __init__(self, author, user_data, save_func, recipe_key, recipe_info, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.key = recipe_key
        self.info = recipe_info
        self.parent_view = parent_view 
        
        self.add_item(discord.ui.Button(label="1개", style=discord.ButtonStyle.primary, custom_id="c1"))
        self.add_item(discord.ui.Button(label="5개", style=discord.ButtonStyle.primary, custom_id="c5"))
        self.add_item(discord.ui.Button(label="10개", style=discord.ButtonStyle.primary, custom_id="c10"))
        self.add_item(discord.ui.Button(label="최대", style=discord.ButtonStyle.success, custom_id="c_all"))
        self.add_item(discord.ui.Button(label="취소", style=discord.ButtonStyle.secondary, row=1, custom_id="cancel"))

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.author: return False
        
        cid = interaction.data.get("custom_id")
        if cid == "cancel":
            await self.parent_view.reload_data()
            self.parent_view.update_components()
            await interaction.response.edit_message(content=f"🔨 **[{self.parent_view.region_name}]** 제작 목록", embed=None, view=self.parent_view)
        elif cid == "c1": await self.process_craft(interaction, 1)
        elif cid == "c5": await self.process_craft(interaction, 5)
        elif cid == "c10": await self.process_craft(interaction, 10)
        elif cid == "c_all": await self.process_craft(interaction, "all")
        return True

    async def process_craft(self, interaction, amount):
        self.user_data = await get_user_data(self.author.id, self.author.display_name)

        inv = self.user_data.setdefault("inventory", {})
        needs = self.info["need"]
        
        max_craftable = 9999
        for item, req_count in needs.items():
            has = inv.get(item, 0)
            if req_count > 0:
                max_craftable = min(max_craftable, has // req_count)
        
        if amount == "all":
            count = max_craftable
        else:
            count = int(amount)

        if count <= 0:
            return await interaction.response.send_message("❌ 재료가 부족합니다.", ephemeral=True)
        
        if max_craftable < count:
            return await interaction.response.send_message(f"❌ 재료가 부족합니다. (최대 {max_craftable}개 가능)", ephemeral=True)

        for item, req_count in needs.items():
            inv[item] -= (req_count * count)
            if inv[item] <= 0: del inv[item]

        res_item = self.info["result"]
        res_count = self.info.get("count", 1) * count
        inv[res_item] = inv.get(res_item, 0) + res_count
        
        # [수정] save_func 호출 시 user_id와 user_data 전달 (wrapper가 아닌 경우 대비)
        await self.save_func(self.author.id, self.user_data)
        
        req_text = []
        for item, req_count in needs.items():
            have = inv.get(item, 0)
            mark = "✅" if have >= req_count else "❌"
            req_text.append(f"{mark} {item}: {have}/{req_count}")
        
        cur_stock = inv.get(res_item, 0)
        
        embed = discord.Embed(
            title=f"🔨 {res_item} 제작", 
            description=f"현재 보유량: **{cur_stock}개**\n\n**[필요 재료]**\n" + "\n".join(req_text), 
            color=discord.Color.blue()
        )
        
        await interaction.response.edit_message(
            content=f"✅ **{res_item}** {res_count}개 제작 완료!",
            embed=embed,
            view=self 
        )


# --- 상자깡 뷰 ---
class BoxOpenView(discord.ui.View):
    def __init__(self, author, user_data, save_func, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.parent_view = parent_view
        self.update_buttons()

    async def reload_data(self):
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
    
    def update_buttons(self):
        self.clear_items()
        box_types = [("낡은 보물상자", "낡은 열쇠"), ("섬세한 보물상자", "섬세한 열쇠"), ("깔끔한 보물상자", "깔끔한 열쇠")]
        inv = self.user_data.get("inventory", {})
        
        for box, key in box_types:
            box_count = inv.get(box, 0)
            btn = discord.ui.Button(label=f"{box} ({box_count})", style=discord.ButtonStyle.secondary)
            btn.callback = self.make_open_callback(box, key)
            self.add_item(btn)
            
        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=1, custom_id="back"))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        if i.data.get("custom_id") == "back":
            await self.parent_view.reload_data()
            await i.response.edit_message(content="🔨 제작소", embed=None, view=self.parent_view)
        return True

    def make_open_callback(self, box_name, key_name):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.author: return
            await self.reload_data()
            inv = self.user_data.get("inventory", {})
            if inv.get(box_name, 0) <= 0: return await interaction.response.send_message(f"❌ {box_name} 없음", ephemeral=True)
            if inv.get(key_name, 0) <= 0: return await interaction.response.send_message(f"❌ {key_name} 필요", ephemeral=True)
            
            view = BoxAmountView(self.author, self.user_data, self.save_func, box_name, key_name, self)
            await interaction.response.edit_message(content=f"🗝️ **{box_name}** 개봉", embed=None, view=view)
        return callback

class BoxAmountView(discord.ui.View):
    def __init__(self, author, user_data, save_func, box_name, key_name, parent_view):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.box, self.key = box_name, key_name
        self.parent_view = parent_view
        
        self.add_item(discord.ui.Button(label="1개", custom_id="b1"))
        self.add_item(discord.ui.Button(label="5개", custom_id="b5"))
        self.add_item(discord.ui.Button(label="10개", custom_id="b10"))
        self.add_item(discord.ui.Button(label="최대", style=discord.ButtonStyle.success, custom_id="ball"))
        self.add_item(discord.ui.Button(label="취소", style=discord.ButtonStyle.secondary, row=1, custom_id="cancel"))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        cid = i.data["custom_id"]
        if cid == "cancel": 
            await self.parent_view.reload_data()
            self.parent_view.update_buttons() 
            await i.response.edit_message(content="📦 상자 선택", embed=None, view=self.parent_view)
        elif cid == "b1": await self.open_box(i, 1)
        elif cid == "b5": await self.open_box(i, 5)
        elif cid == "b10": await self.open_box(i, 10)
        elif cid == "ball": await self.open_box(i, "all")
        return True

    async def open_box(self, interaction, amount):
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
        inv = self.user_data["inventory"]
        has_box = inv.get(self.box, 0)
        has_key = inv.get(self.key, 0)
        max_open = min(has_box, has_key)
        
        count = max_open if amount == "all" else int(amount)
        if count <= 0: return await interaction.response.send_message("❌ 개수 부족", ephemeral=True)
        if max_open < count: return await interaction.response.send_message(f"❌ 부족함 (최대 {max_open}개)", ephemeral=True)
        
        inv[self.box] -= count
        inv[self.key] -= count
        if inv[self.box] <= 0: del inv[self.box]
        if inv[self.key] <= 0: del inv[self.key]
        
        total_money = 0
        rewards = {}
        
        # [수정] 물고기 제외 로직 추가
        all_fish = set()
        for tier_list in FISH_TIERS.values():
            all_fish.update(tier_list)
        
        valid_rare_items = [item for item in RARE_ITEMS if item not in all_fish]
        if not valid_rare_items: valid_rare_items = ["사랑나무 가지"] # Fallback

        if "깔끔한" in self.box:
            money_range = (5000, 10000); prob = 0.3; pool = valid_rare_items + ["강화키트", "이름 변경권"]
        elif "섬세한" in self.box:
            money_range = (3000, 6000); prob = 0.15; pool = valid_rare_items
        else: # 낡은
            money_range = (1000, 3000); prob = 0.05; pool = valid_rare_items

        for _ in range(count):
            total_money += random.randint(money_range[0], money_range[1])
            if random.random() < prob:
                item = random.choice(pool)
                inv[item] = inv.get(item, 0) + 1
                rewards[item] = rewards.get(item, 0) + 1
        
        self.user_data["money"] += total_money
        
        await self.save_func(self.author.id, self.user_data)
        
        # [신규] 상자 개봉 퀘스트 업데이트
        await update_quest_progress(interaction.user.id, self.user_data, self.save_func, "open_box", count)
        
        res_desc = f"💰 **{total_money:,}원** 획득!"
        if rewards:
            res_desc += "\n\n**[획득 아이템]**\n" + "\n".join([f"{k} x{v}" for k,v in rewards.items()])
        else:
            res_desc += "\n(추가 아이템 없음)"
            
        new_box = inv.get(self.box, 0)
        new_key = inv.get(self.key, 0)
        res_desc += f"\n\n📦 남은 상자: {new_box} | 🗝️ 남은 열쇠: {new_key}"
        
        embed = discord.Embed(title=f"🎁 {self.box} {count}개 개봉 결과", description=res_desc, color=discord.Color.gold())
        
        await interaction.response.edit_message(content=None, embed=embed, view=self)