# myhome.py
import discord
import json
import os
import random
from items import ITEM_CATEGORIES, REGIONS, CRAFT_RECIPES, RARE_ITEMS
from character import Character

# [중요] 각 기능별 모듈에서 View 클래스 임포트
from garden import GardenView
from workshop import WorkshopView
from fishing import FishingView
from recruitment import RecruitSelectView
from use_item import ItemUseView
from card_manager import CardManageView
from navigation_v7 import attach_navigation
try:
    from artifact_manager import ArtifactManageView
except ImportError:
    ArtifactManageView = None 

DATA_FILE = "user_data.json"
from data_manager import get_user_data

# --- 마이홈 건설 단계별 요구 조건 (총 5단계) ---
CONSTRUCTION_DATA = {
    1: {
        "pt": 3000, "money": 10000,
        "items": {"시간의 모래": 30, "버려진 장갑": 20, "사과": 40, "평범한 나무판자": 10, "녹슨 철": 10}
    },
    2: {
        "pt": 3000, "money": 10000,
        "items": {"시간의 모래": 40, "버려진 장갑": 20, "사과": 40, "굴레늑대 털": 50, "평범한 나무판자": 20, "녹슨 철": 20}
    },
    3: {
        "pt": 6000, "money": 20000,
        "items": {"시간의 모래": 50, "버려진 장갑": 20, "간단한 다과": 20, "굴레늑대 털": 50, "다정함 한 스푼": 5, "평범한 나무판자": 20, "녹슨 철": 20}
    },
    4: {
        "pt": 6000, "money": 20000,
        "items": {"녹슨 철": 50, "버려진 장갑": 20, "투명한 조화": 30, "허술한 장식품": 20, "별자리 망원경": 5, "평범한 나무판자": 50}
    },
    5: {
        "pt": 12000, "money": 40000,
        "items": {"녹슨 철": 50, "평범한 나무판자": 50, "버려진 장갑": 20, "흐린 꿈": 10, "투명한 조화": 30, "따스한 목도리": 60}
    }
}

LIMITED_CATEGORIES = {
    "chest": ["낡은 보물상자", "섬세한 보물상자", "깔끔한 보물상자"],
    "key": ["낡은 열쇠", "섬세한 열쇠", "깔끔한 열쇠", "장식용 열쇠"]
}

class MyHomeView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.page = 0
        self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("❌ 본인의 마이홈만 관리할 수 있습니다.", ephemeral=True)
            return False
        await interaction.response.defer() # defer_update() -> defer()
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        return True

    def update_components(self):
        self.clear_items()
        level = self.user_data.get("myhome", {}).get("construction_step", 0)
        
        all_buttons = []

        # 캐릭터 정비 버튼 (항상 표시)
        all_buttons.append({"label": "🔧 캐릭터 정비", "style": discord.ButtonStyle.secondary, "callback": self.maintenance_callback})
        all_buttons.append({"label": "🌿 생활 관리", "style": discord.ButtonStyle.success, "callback": self.life_callback})

        if level < 5:
            label = "🏠 마이홈 건설" if level == 0 else f"🏗️ 마이홈 증축 ({level}lv -> {level+1}lv)"
            all_buttons.append({"label": label, "style": discord.ButtonStyle.success, "callback": self.construct_callback})

        if level >= 1:
            all_buttons.append({"label": "🌱 텃밭", "style": discord.ButtonStyle.primary, "callback": self.garden_callback})
        
        if level >= 2:
            all_buttons.append({"label": "⚒️ 작업실", "style": discord.ButtonStyle.primary, "callback": self.workshop_callback})
            
        if level >= 3:
            all_buttons.append({"label": "🎣 낚시터", "style": discord.ButtonStyle.primary, "callback": self.fishing_callback})

        if level >= 4:
            all_buttons.append({"label": "🕵️ 영입소", "style": discord.ButtonStyle.primary, "callback": self.recruit_callback})

        if level >= 5:
            all_buttons.append({"label": "🚀 원격 파견", "style": discord.ButtonStyle.danger, "callback": self.dispatch_callback})
            all_buttons.append({"label": "🛏️ 휴식", "style": discord.ButtonStyle.success, "callback": self.rest_callback})

        # 페이지네이션
        PER_PAGE = 4
        total_pages = (len(all_buttons) - 1) // PER_PAGE + 1
        if self.page >= total_pages: self.page = max(0, total_pages - 1)

        start_idx = self.page * PER_PAGE
        end_idx = start_idx + PER_PAGE
        current_page_buttons = all_buttons[start_idx:end_idx]

        for btn_info in current_page_buttons:
            btn = discord.ui.Button(label=btn_info["label"], style=btn_info["style"])
            btn.callback = btn_info["callback"]
            self.add_item(btn)

        if total_pages > 1:
            row = 1 # 페이지네이션 버튼은 항상 두 번째 줄에 표시
            
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=row, disabled=(self.page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            page_indicator = discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, row=row, disabled=True)
            self.add_item(page_indicator)

            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=row, disabled=(self.page >= total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

        exit_btn = discord.ui.Button(
            label="마이홈 나가기",
            emoji="🚪",
            style=discord.ButtonStyle.danger,
            row=4,
        )
        exit_btn.callback = self.exit_callback
        self.add_item(exit_btn)

    async def prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        self.update_components()
        await interaction.edit_original_response(view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        self.update_components()
        await interaction.edit_original_response(view=self)

    async def construct_callback(self, interaction: discord.Interaction):
        level = self.user_data.get("myhome", {}).get("construction_step", 0)
        req = CONSTRUCTION_DATA[level + 1]
        
        # 자원 체크
        if self.user_data.get("pt", 0) < req["pt"] or self.user_data.get("money", 0) < req["money"]:
            return await interaction.edit_original_response(content="❌ 포인트나 머니가 부족합니다.", embed=self.get_embed(), view=self)
        
        inv = self.user_data.get("inventory", {})
        for item, count in req["items"].items():
            if inv.get(item, 0) < count:
                return await interaction.edit_original_response(content=f"❌ 재료가 부족합니다: {item} ({inv.get(item, 0)}/{count})", embed=self.get_embed(), view=self)

        # 자원 차감
        self.user_data["pt"] -= req["pt"]
        self.user_data["money"] -= req["money"]
        for item, count in req["items"].items():
            inv[item] -= count
            if inv[item] <= 0: del inv[item]
            
        # 레벨 업
        new_level = level + 1
        self.user_data.setdefault("myhome", {})["construction_step"] = new_level
        
        if new_level >= 5:
            self.user_data["myhome"]["constructed"] = True
        
        # 초기 데이터 설정
        myhome_data = self.user_data.setdefault("myhome", {})
        if new_level == 2: # 작업실 해금 시, workshop_level 설정
            myhome_data["workshop_level"] = 1
            
        await self.save_func(self.author.id, self.user_data)
        self.update_components()
        await interaction.edit_original_response(content=f"🎉 마이홈 증축 완료! ({new_level}레벨)", embed=self.get_embed(), view=self)

    async def maintenance_callback(self, interaction: discord.Interaction):
        view = CharacterMaintenanceView(self.author, self.user_data, self.save_func, self)
        await interaction.edit_original_response(content="캐릭터 정비 메뉴입니다.", embed=None, view=view)

    async def life_callback(self, interaction: discord.Interaction):
        from life_overhaul_v5 import LifeHubView
        view = LifeHubView(self.author, self.user_data, self.save_func)
        try:
            await self.save_func(self.author.id, self.user_data)
        except TypeError:
            await self.save_func(self.user_data)
        await interaction.edit_original_response(content=None, embed=view.get_embed(), view=view)

    async def garden_callback(self, interaction: discord.Interaction):
        view = GardenView(self.author, self.user_data, self.save_func)
        attach_navigation(
            view,
            self.author,
            lambda: MyHomeView(self.author, self.user_data, self.save_func),
        )
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    async def workshop_callback(self, interaction: discord.Interaction):
        view = WorkshopView(self.author, self.user_data, self.save_func)
        attach_navigation(
            view,
            self.author,
            lambda: MyHomeView(self.author, self.user_data, self.save_func),
        )
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    async def fishing_callback(self, interaction: discord.Interaction):
        view = FishingView(self.author, self.user_data, self.save_func)
        attach_navigation(
            view,
            self.author,
            lambda: MyHomeView(self.author, self.user_data, self.save_func),
        )
        await interaction.edit_original_response(embed=view.get_embed(), view=view)

    async def exit_callback(self, interaction: discord.Interaction):
        await interaction.edit_original_response(
            content="🏠 마이홈을 나왔습니다.",
            embed=None,
            view=None,
        )

    async def recruit_callback(self, interaction: discord.Interaction):
        async def back_cb(i):
            view = MyHomeView(self.author, self.user_data, self.save_func)
            await i.response.edit_message(content=None, embed=view.get_embed(), view=view)
        view = RecruitSelectView(self.author, self.user_data, self.save_func, back_cb)
        embed = discord.Embed(title="🕵️ 영입소", description="함께할 동료를 찾아보세요.", color=discord.Color.blue())
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    async def dispatch_callback(self, interaction: discord.Interaction):
        unlocked = self.user_data.get("unlocked_regions", ["기원의 쌍성"])
        options = []
        for r_name in REGIONS.keys():
            if r_name in unlocked:
                options.append(discord.SelectOption(label=r_name, value=r_name))
        
        if not options:
            return await interaction.response.send_message("❌ 파견 가능한 지역이 없습니다.", ephemeral=True)
        
        select = discord.ui.Select(placeholder="파견 보낼 지역 선택", options=options)
        
        async def select_cb(i: discord.Interaction):
            region = i.data['values'][0]
            view = DispatchView(self.author, self.user_data, self.save_func, region)
            await i.response.edit_message(content=f"🚀 **{region}** 파견 설정을 선택하세요.", view=view, embed=None)

        select.callback = select_cb
        view = discord.ui.View(); view.add_item(select)
        await interaction.followup.send("🚀 원격 파견지를 선택하세요.", view=view, ephemeral=True)

    async def rest_callback(self, interaction: discord.Interaction):
        recovered_count = 0
        characters = self.user_data.get("characters", [])
        
        for i, c_data in enumerate(characters):
            char = Character.from_dict(c_data)
            # 아티팩트 스탯 적용하여 최대 체력 계산
            char.apply_battle_start_buffs()
            
            # 회복
            char.current_hp = char.max_hp
            char.current_mental = char.max_mental
            char.is_down = False
            
            # 저장 전 버프 해제 (베이스 스탯만 저장하기 위함)
            char.remove_battle_buffs()
            
            characters[i] = char.to_dict()
            recovered_count += 1
            
        await self.save_func(self.author.id, self.user_data)
        await interaction.edit_original_response(content=f"🛏️ **휴식 완료!**\n모든 캐릭터({recovered_count}명)의 체력과 정신력이 완전히 회복되었습니다.", embed=self.get_embed(), view=self)

    def get_embed(self):
        level = self.user_data.get("myhome", {}).get("construction_step", 0)
        embed = discord.Embed(title=f"🏠 {self.author.display_name}의 마이홈", color=discord.Color.green())
        
        desc = f"**현재 레벨:** {level} lv\n"
        if level == 0:
            desc += "아직 집이 없습니다. 마이홈을 건설하여 다양한 기능을 해금하세요!"
        else:
            desc += "평화로운 당신의 안식처입니다."
            
        embed.description = desc
        
        if level < 5:
            req = CONSTRUCTION_DATA[level + 1]
            req_text = f"💰 {req['money']:,}원 / ⚡ {req['pt']:,}pt\n📦 " + ", ".join([f"{k} {v}개" for k, v in req['items'].items()])
            embed.add_field(name="🏗️ 다음 증축 요구 사항", value=req_text, inline=False)
            
        return embed

class DispatchView(discord.ui.View):
    def __init__(self, author, user_data, save_func, region):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.region = region

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author: return False
        await interaction.response.defer()
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        return True

    async def run_dispatch(self, interaction, count):
        region_info = REGIONS.get(self.region)
        if not region_info:
            return await interaction.edit_original_response(content="❌ 지역 데이터 오류.", view=self)

        energy_cost = region_info.get("energy_cost", 2)
        total_cost = count * (energy_cost * 2)

        if self.user_data.get("pt", 0) < total_cost:
            return await interaction.edit_original_response(content=f"❌ 포인트가 부족합니다. ({total_cost}pt 필요)", view=self)
        
        self.user_data["pt"] -= total_cost
        acquired = {}
        
        # 파견 로직: 무조건 성공, 일반 재료만 획득
        common_items = region_info.get("common", [])
        if common_items:
            for _ in range(count):
                drop_types = random.randint(1, 2)
                for _ in range(drop_types):
                    item_to_add = random.choice(common_items)
                    
                    is_limited_item = False
                    for category, items_in_category in LIMITED_CATEGORIES.items():
                        if item_to_add in items_in_category:
                            already_has = any(cat_item in acquired for cat_item in items_in_category)
                            if already_has:
                                is_limited_item = True
                                break
                            else:
                                acquired[item_to_add] = acquired.get(item_to_add, 0) + 1
                                is_limited_item = True
                                break
                    
                    if not is_limited_item:
                        qty = random.randint(1, 5)
                        acquired[item_to_add] = acquired.get(item_to_add, 0) + qty
            
        inv = self.user_data.setdefault("inventory", {})
        for k, v in acquired.items():
            inv[k] = inv.get(k, 0) + v
            
        myhome = self.user_data.setdefault("myhome", {})
        myhome["total_investigations"] = myhome.get("total_investigations", 0) + (count * 10)
        
        await self.save_func(self.author.id, self.user_data)
        
        res_text = "\n".join([f"{k} x{v}" for k, v in acquired.items()])
        if not res_text: res_text = "획득한 아이템이 없습니다."
        embed = discord.Embed(title=f"🚀 {self.region} 파견 완료 ({count}회)", color=discord.Color.blue())
        embed.description = f"**소모 포인트:** {total_cost}pt\n\n**[획득 결과]**\n{res_text}"
        await interaction.edit_original_response(content=None, embed=embed, view=None)

    @discord.ui.button(label="10회 파견", style=discord.ButtonStyle.primary)
    async def d10(self, i, b): await self.run_dispatch(i, 10)
    @discord.ui.button(label="20회 파견", style=discord.ButtonStyle.primary)
    async def d20(self, i, b): await self.run_dispatch(i, 20)
    @discord.ui.button(label="30회 파견", style=discord.ButtonStyle.primary)
    async def d30(self, i, b): await self.run_dispatch(i, 30)

async def open_myhome(ctx, load_func, save_func):
    # [수정] DB 모드에 맞춰 데이터 로드 방식 변경
    user_data = await get_user_data(ctx.author.id, ctx.author.display_name)
    
    # save_func 래퍼 (View들이 save_func(all_data) 형태로 호출하는 것을 호환)
    async def save_wrapper(data_ignored):
        await save_func(ctx.author.id, user_data)
    
    view = MyHomeView(ctx.author, user_data, save_wrapper)
    await ctx.send(embed=view.get_embed(), view=view)

class SetInvestigatorView(discord.ui.View):
    """조사 전담 요원을 설정하는 뷰"""
    def __init__(self, author, user_data, save_func, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.parent_view = parent_view
        
        self.current_idx = self.user_data.get("investigator_index", 0)
        self.add_char_select()

    def add_char_select(self):
        self.clear_items()
        char_list = self.user_data.get("characters", [])
        if not char_list: return

        options = []
        for i, c in enumerate(char_list):
            label = c.get("name", f"캐릭터 {i+1}")
            desc = f"HP: {c.get('hp')} | 공격력: {c.get('attack')}"
            if i == self.current_idx:
                label = f"✅ {label}"
                desc += " (현재 담당)"
            
            options.append(discord.SelectOption(label=label, description=desc, value=str(i)))

        select = discord.ui.Select(placeholder="조사를 담당할 요원을 선택하세요", options=options)
        select.callback = self.select_callback
        self.add_item(select)

        back_btn = discord.ui.Button(label="⬅️ 정비 메뉴로", style=discord.ButtonStyle.gray, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.defer()
        idx = int(interaction.data['values'][0])
        self.user_data["investigator_index"] = idx
        await self.save_func(self.author.id, self.user_data)
        
        char_name = self.user_data["characters"][idx]["name"]
        await interaction.edit_original_response(content=f"✅ 조사 담당이 **[{char_name}]**(으)로 변경되었습니다.", embed=None, view=self.parent_view)

    async def go_back(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.defer()
        await interaction.edit_original_response(content="캐릭터 정비 메뉴입니다.", embed=None, view=self.parent_view)

# --- 캐릭터 정비 관련 뷰 ---

class CharacterSelectViewForCards(discord.ui.View):
    """카드 관리를 위해 캐릭터를 선택하는 뷰 (main.py에서 복사)"""
    def __init__(self, author, user_data, save_func, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.parent_view = parent_view
        self.page = 0
        self.PER_PAGE = 7 
        self.update_view()

    def update_view(self):
        self.clear_items()
        char_list = self.user_data.get("characters", [])
        
        if not char_list:
            self.add_item(discord.ui.Button(label="캐릭터 없음", disabled=True))
            return

        total_pages = (len(char_list) - 1) // self.PER_PAGE + 1
        if self.page < 0: self.page = 0
        if self.page >= total_pages: self.page = max(0, total_pages - 1)
        
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_list = char_list[start:end]

        options = []
        for index, char_info in enumerate(current_list):
            real_index = start + index
            options.append(discord.SelectOption(
                label=char_info.get('name', f'캐릭터 {real_index+1}'),
                description=f"HP: {char_info.get('hp')} | 공격: {char_info.get('attack')}",
                value=str(real_index)
            ))

        placeholder = f"캐릭터 선택 ({self.page+1}/{total_pages})"
        select = discord.ui.Select(placeholder=placeholder, options=options, custom_id="select")
        select.callback = self.select_callback
        self.add_item(select)
        
        if total_pages > 1:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page==0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page==total_pages-1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)
        
        back_btn = discord.ui.Button(label="⬅️ 정비 메뉴로", style=discord.ButtonStyle.gray, row=2)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

    async def prev_page(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.defer()
        self.page -= 1
        self.update_view()
        await interaction.edit_original_response(view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.defer()
        self.page += 1
        self.update_view()
        await interaction.edit_original_response(view=self)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        await interaction.response.defer()
        char_index = int(interaction.data['values'][0])
        
        view = CardManageView(self.author, self.user_data, self.save_func, char_index=char_index)
        await interaction.edit_original_response(
            content=f"🎴 **[{view.char.name}]** 덱 구성 중...", 
            embed=view.create_embed(), 
            view=view
        )
    
    async def go_back(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.parent_view.user_data = self.user_data
        await interaction.response.defer()
        await interaction.edit_original_response(content="캐릭터 정비 메뉴입니다.", embed=None, view=self.parent_view)

class CharacterMaintenanceView(discord.ui.View):
    """캐릭터 정비 메인 메뉴 뷰"""
    def __init__(self, author, user_data, save_func, parent_view):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.parent_view = parent_view

        self.add_item(discord.ui.Button(label="🎒 아이템 사용", style=discord.ButtonStyle.primary, custom_id="use_item"))
        self.add_item(discord.ui.Button(label="🎴 카드 관리", style=discord.ButtonStyle.primary, custom_id="manage_cards"))
        if ArtifactManageView:
            self.add_item(discord.ui.Button(label="💍 아티팩트 관리", style=discord.ButtonStyle.primary, custom_id="manage_artifacts"))
        self.add_item(discord.ui.Button(label="🕵️ 조사원 설정", style=discord.ButtonStyle.primary, custom_id="set_investigator"))
        
        self.add_item(discord.ui.Button(label="🏠 마이홈으로", style=discord.ButtonStyle.gray, row=1, custom_id="back_to_myhome"))

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.author: return False
        await interaction.response.defer()
        cid = interaction.data.get("custom_id")

        # 데이터 리로드 (DB 사용)
        # self.all_data는 DB 모드에서 사용하지 않으므로 무시하거나 None 유지
        self.user_data = await get_user_data(self.author.id, self.author.display_name)

        if cid == "use_item":
            view = ItemUseView(self.author, self.user_data, self.save_func)
            await interaction.edit_original_response(content="사용할 아이템을 선택하세요.", embed=None, view=view)

        elif cid == "manage_cards":
            view = CharacterSelectViewForCards(self.author, self.user_data, self.save_func, self)
            await interaction.edit_original_response(content="카드를 관리할 캐릭터를 선택하세요.", embed=None, view=view)

        elif cid == "manage_artifacts":
            if ArtifactManageView:
                view = ArtifactManageView(self.author, self.user_data, self.save_func)
                embed = view.make_base_embed("💍 아티팩트 관리", "아티팩트를 장착/분해/강화합니다.")
                await interaction.edit_original_response(content=None, embed=embed, view=view)

        elif cid == "set_investigator":
            view = SetInvestigatorView(self.author, self.user_data, self.save_func, self)
            await interaction.edit_original_response(content="조사를 담당할 요원을 선택하세요.", embed=None, view=view)

        elif cid == "back_to_myhome":
            self.parent_view.user_data = self.user_data
            self.parent_view.page = 0 # 페이지 초기화
            self.parent_view.update_components()
            await interaction.edit_original_response(content=None, embed=self.parent_view.get_embed(), view=self.parent_view)
        
        # 모든 상호작용을 이 함수 내에서 처리했으므로 False를 반환하여 추가 콜백 실행을 막습니다.
        return False
