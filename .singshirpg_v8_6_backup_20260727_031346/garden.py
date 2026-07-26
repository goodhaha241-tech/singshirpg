# garden.py
import discord
import random
from items import RARE_ITEMS, GUILD_ITEMS
from fishing import FISH_TIERS
from data_manager import get_user_data


class GardenView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.page = 0
        
        self._ensure_garden_data()
        self.update_components()

    def _ensure_garden_data(self):
        """텃밭 데이터 구조를 보장하고 기본 슬롯을 생성합니다."""
        myhome = self.user_data.setdefault("myhome", {})
        self.garden = myhome.setdefault("garden", {})
        self.garden.setdefault("slots", [])
        self.garden.setdefault("water_can", 0)
        self.garden.setdefault("level", 1)
        
        # 기본 슬롯 보장 (최소 3개)
        if len(self.garden["slots"]) < 3:
            for _ in range(3 - len(self.garden["slots"])):
                self.garden["slots"].append({"planted": False, "stage": 0, "last_invest_count": 0})

    def get_embed(self):
        embed = discord.Embed(title="🌱 마이홈 텃밭", color=discord.Color.green())
        
        inv = self.user_data.get("inventory", {})
        seed_count = inv.get("이상한 씨앗", 0)
        fert_list = self.user_data.get("fertilizers", [])
        fert_count = len(fert_list)
        
        can_fill = self.garden.get("water_can", 0)
        lvl = self.garden.get("level", 1)
        
        info_text = (
            f"🚿 물뿌리개: {can_fill}/20회\n"
            f"🌱 이상한 씨앗: {seed_count}개\n"
            f"🧪 보유 비료: {fert_count}개\n"
            f"⭐ 텃밭 등급: {lvl}강 (수확량: {2 + lvl}개)"
        )
        embed.add_field(name="상태 정보", value=info_text, inline=False)
        
        slots_desc = ""
        total_invest = self.user_data["myhome"].get("total_turns", 0)
        
        for i, slot in enumerate(self.garden["slots"]):
            state = "🟫 비어있음"
            if slot["planted"]:
                growth = slot["stage"]
                last = slot.get("last_invest_count", 0)
                diff = total_invest - last
                
                fert_info = ""
                target_item = slot.get("fertilizer")
                if target_item:
                    fert_info = f" (🧪 {target_item} 자라는 중)"

                if growth >= 3:
                    state = f"🌾 **수확 가능!**{fert_info}"
                else:
                    req_invest = 50
                    remaining = max(0, req_invest - diff)
                    if remaining == 0:
                        state = f"💧 **물 부족** (단계: {growth}/3){fert_info}"
                    else:
                        state = f"🌿 자라는 중 ({growth}/3){fert_info}\n   ┕ 진행: **{diff}/{req_invest}** 턴 (남은: **{remaining}**턴)"
            
            slots_desc += f"**[{i+1}번]** {state}\n"
        
        embed.description = slots_desc
        return embed

    def update_components(self):
        self.clear_items()
        
        all_buttons = [
            {"label": "🌱 씨앗 심기", "style": discord.ButtonStyle.primary, "custom_id": "plant"},
            {"label": "🚿 물주기", "style": discord.ButtonStyle.blurple, "custom_id": "water"},
            {"label": "🌾 수확", "style": discord.ButtonStyle.success, "custom_id": "harvest"},
            {"label": "🔄 씨앗 변환", "style": discord.ButtonStyle.secondary, "custom_id": "convert_seed"},
            {"label": "❄️ 물 충전", "style": discord.ButtonStyle.secondary, "custom_id": "refill"},
            {"label": "🧪 비료 사용", "style": discord.ButtonStyle.secondary, "custom_id": "use_fert"},
            {"label": "🔨 비료 제작", "style": discord.ButtonStyle.secondary, "custom_id": "make_fert"},
        ]

        if len(self.garden["slots"]) < 5:
            all_buttons.append({"label": "🏗️ 텃밭 확장", "style": discord.ButtonStyle.secondary, "custom_id": "expand"})

        if self.garden.get("level", 1) < 3:
            all_buttons.append({"label": "⭐ 텃밭 강화", "style": discord.ButtonStyle.primary, "custom_id": "upgrade"})

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
        
        await i.response.defer()
        # [DB 수정] DB에서 최신 데이터 로드
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        self._ensure_garden_data()

        cid = i.data.get("custom_id")
        
        if cid == "plant": await self.plant_seed(i)
        elif cid == "water": await self.water_plants(i)
        elif cid == "harvest": await self.harvest_plants(i)
        elif cid == "convert_seed": await self.convert_seed_menu(i)
        elif cid == "refill": await self.refill_water_menu(i)
        elif cid == "use_fert": await self.apply_fertilizer_menu(i)
        elif cid == "make_fert": await self.make_fertilizer_menu(i)
        elif cid == "expand": await self.expand_garden(i)
        elif cid == "upgrade": await self.upgrade_garden(i)
        elif cid == "go_home": await self.go_home(i)
        elif cid == "prev_page":
            self.page -= 1
            self.update_components()
            await i.edit_original_response(view=self)
        elif cid == "next_page":
            self.page += 1
            self.update_components()
            await i.edit_original_response(view=self)
        return True

    async def plant_seed(self, i):
        inv = self.user_data.get("inventory", {})
        if inv.get("이상한 씨앗", 0) <= 0:
            return await i.edit_original_response(content="❌ '이상한 씨앗'이 없습니다. (씨앗 변환으로 획득 가능)", embed=self.get_embed(), view=self)
        
        target = -1
        for idx, slot in enumerate(self.garden["slots"]):
            if not slot["planted"]: target = idx; break
        
        if target == -1: return await i.edit_original_response(content="❌ 빈 슬롯이 없습니다.", embed=self.get_embed(), view=self)
        
        inv["이상한 씨앗"] -= 1
        self.garden["slots"][target] = {
            "planted": True, "stage": 0, 
            "last_invest_count": self.user_data["myhome"].get("total_turns", 0),
            "fertilizer": None 
        }
        await self.save_func(self.author.id, self.user_data)
        await i.edit_original_response(content="🌱 씨앗을 심었습니다.", embed=self.get_embed(), view=self)

    async def water_plants(self, i):
        water = self.garden.get("water_can", 0)
        if water <= 0: return await i.edit_original_response(content="❌ 물뿌리개가 비었습니다.", embed=self.get_embed(), view=self)
        
        total_invest = self.user_data["myhome"].get("total_turns", 0)
        count = 0
        for slot in self.garden["slots"]:
            if water <= 0: break
            if slot["planted"] and slot["stage"] < 3:
                last = slot.get("last_invest_count", 0)
                if total_invest - last >= 50:
                    slot["stage"] += 1
                    slot["last_invest_count"] = total_invest
                    water -= 1
                    count += 1
        
        if count > 0:
            self.garden["water_can"] = water
            await self.save_func(self.author.id, self.user_data)
            await i.edit_original_response(content=f"🚿 {count}개 작물에 물을 주었습니다.", embed=self.get_embed(), view=self)
        else:
            await i.edit_original_response(content="❌ 물을 줄 작물이 없거나, 아직 물을 줄 시기가 아닙니다 (조사 성공 50턴 필요).", embed=self.get_embed(), view=self)

    async def harvest_plants(self, i):
        harvested = []
        inv = self.user_data.setdefault("inventory", {})
        lvl = self.garden.get("level", 1)
        drop_count = 2 + lvl
        
        # [수정] 수확 시 물고기 아이템이 나오지 않도록 필터링
        all_fish = set()
        for tier_list in FISH_TIERS.values():
            all_fish.update(tier_list)
        
        harvestable_rares = [item for item in RARE_ITEMS if item not in all_fish and item not in GUILD_ITEMS]
        if not harvestable_rares:
            harvestable_rares = ["사랑나무 가지", "무지개 열매", "설국 열매"]
        
        slots_reset_count = 0
        for idx, slot in enumerate(self.garden["slots"]):
            if slot["planted"] and slot["stage"] >= 3:
                target_item = slot.get("fertilizer")
                item_drops = []
                for _ in range(drop_count):
                    item = target_item if target_item else random.choice(harvestable_rares)
                    item_drops.append(item)
                    inv[item] = inv.get(item, 0) + 1
                
                harvested.extend(item_drops)
                self.garden["slots"][idx] = {"planted": False, "stage": 0, "last_invest_count": 0, "fertilizer": None}
                slots_reset_count += 1
        
        if harvested:
            await self.save_func(self.author.id, self.user_data)
            from collections import Counter
            counts = Counter(harvested)
            res_str = ", ".join([f"{k} x{v}" for k, v in counts.items()])
            await i.edit_original_response(content=f"🌾 {slots_reset_count}개 슬롯 수확 완료!\n획득: {res_str}", embed=self.get_embed(), view=self)
        else:
            await i.edit_original_response(content="❌ 수확할 작물이 없습니다.", embed=self.get_embed(), view=self)

    async def convert_seed_menu(self, i):
        view = SeedConvertView(self.author, self.user_data, self.save_func, self)
        await i.edit_original_response(embed=view.get_embed(), view=view)

    async def refill_water_menu(self, i):
        view = WaterRefillView(self.author, self.user_data, self.save_func, self)
        await i.edit_original_response(embed=view.get_embed(), view=view)

    async def make_fertilizer_menu(self, i):
        view = FertilizerCraftView(self.author, self.user_data, self.save_func, self)
        await i.edit_original_response(embed=view.get_embed(), view=view)

    async def apply_fertilizer_menu(self, i):
        ferts = self.user_data.get("fertilizers", [])
        if not ferts:
            return await i.edit_original_response(content="❌ 보유한 비료가 없습니다.", embed=self.get_embed(), view=self)
        view = FertilizerApplyView(self.author, self.user_data, self.save_func, self)
        await i.edit_original_response(embed=view.get_embed(), view=view)

    async def expand_garden(self, i):
        if len(self.garden["slots"]) >= 5: 
            return await i.edit_original_response(content="❌ 최대 5칸까지 확장 가능합니다.", embed=self.get_embed(), view=self)
        
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        
        if money < 20000 or pt < 2000:
            return await i.edit_original_response(content="❌ 비용 부족 (20,000원 + 2,000pt 필요)", embed=self.get_embed(), view=self)
        
        self.user_data["money"] -= 20000
        self.user_data["pt"] -= 2000
        self.garden["slots"].append({"planted": False, "stage": 0, "last_invest_count": 0})
        await self.save_func(self.author.id, self.user_data)
        
        await i.edit_original_response(content=f"🏗️ 텃밭 확장 완료! ({len(self.garden['slots'])}칸)", embed=self.get_embed(), view=self)

    async def upgrade_garden(self, i):
        lvl = self.garden.get("level", 1)
        if lvl >= 3:
            return await i.edit_original_response(content="❌ 최대 강화 상태입니다.", embed=self.get_embed(), view=self)
        
        cost = 50000 if lvl == 1 else 100000
        
        if self.user_data.get("money", 0) < cost:
            return await i.edit_original_response(content=f"❌ 비용 부족 ({cost:,}원 필요)", embed=self.get_embed(), view=self)
            
        self.user_data["money"] -= cost
        self.garden["level"] = lvl + 1
        await self.save_func(self.author.id, self.user_data)
        
        await i.edit_original_response(content=f"⭐ 텃밭 강화 완료! (수확량 {2+lvl} -> {3+lvl}개)", embed=self.get_embed(), view=self)

    async def go_home(self, interaction):
        # [중요] 순환 참조 방지를 위해 함수 내부에서 import
        from myhome import MyHomeView
        view = MyHomeView(self.author, self.user_data, self.save_func)
        await interaction.edit_original_response(content="🏠 마이홈으로 이동했습니다.", embed=view.get_embed(), view=view)


class SeedConvertView(discord.ui.View):
    def __init__(self, author, user_data, save_func, parent):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func, self.parent = author, user_data, save_func, parent
        self.selected_recipe = None
        self.recipes = {
            "twisted": {"name": "뒤틀린 씨앗", "ratio": 3},
            "marble": {"name": "대리석 씨앗", "ratio": 3},
            "sprout": {"name": "새보눈 씨앗", "ratio": 1}
        }
        self.update_components()

    def get_embed(self):
        inv = self.user_data.get("inventory", {})
        embed = discord.Embed(title="🔄 씨앗 변환", description="보유한 씨앗을 **이상한 씨앗**으로 변환합니다.", color=discord.Color.green())
        embed.add_field(name="🌱 이상한 씨앗", value=f"{inv.get('이상한 씨앗', 0)}개", inline=False)
        
        stock_text = (
            f"🌑 뒤틀린 씨앗: {inv.get('뒤틀린 씨앗', 0)}개\n"
            f"⚪ 대리석 씨앗: {inv.get('대리석 씨앗', 0)}개\n"
            f"🐦 새보눈 씨앗: {inv.get('새보눈 씨앗', 0)}개"
        )
        embed.add_field(name="📦 재료 재고", value=stock_text, inline=False)
        return embed

    def update_components(self):
        self.clear_items()
        options = [
            discord.SelectOption(label="뒤틀린 씨앗 (1개 -> 3개)", value="twisted"),
            discord.SelectOption(label="대리석 씨앗 (1개 -> 3개)", value="marble"),
            discord.SelectOption(label="새보눈 씨앗 (1개 -> 1개)", value="sprout")
        ]
        sel = discord.ui.Select(placeholder="변환할 레시피 선택", options=options)
        sel.callback = self.select_callback
        self.add_item(sel)

        if self.selected_recipe:
            self.add_item(discord.ui.Button(label="1회 변환", style=discord.ButtonStyle.primary, custom_id="c1"))
            self.add_item(discord.ui.Button(label="3회 변환", style=discord.ButtonStyle.primary, custom_id="c3"))
            self.add_item(discord.ui.Button(label="5회 변환", style=discord.ButtonStyle.primary, custom_id="c5"))
        
        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=2, custom_id="back"))

    async def select_callback(self, i):
        if i.user != self.author: return
        self.selected_recipe = i.data['values'][0]
        self.update_components()
        await i.response.edit_message(embed=self.get_embed(), view=self)

    async def interaction_check(self, i):
        if i.user != self.author: return False
        
        # [DB 수정] 데이터 갱신 및 부모 뷰 동기화 준비
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
        cid = i.data.get("custom_id")
        if cid == "back":
            self.parent.user_data = self.user_data
            self.parent._ensure_garden_data()
            self.parent.update_components()
            await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)
        elif cid in ["c1", "c3", "c5"]:
            count = int(cid[1:])
            await self.process_convert(i, count)
        return True

    async def process_convert(self, i, count):
        recipe = self.recipes[self.selected_recipe]
        src_name = recipe["name"]
        ratio = recipe["ratio"]
        
        inv = self.user_data.get("inventory", {})
        if inv.get(src_name, 0) < count:
            return await i.response.edit_message(content=f"❌ '{src_name}'이 부족합니다.", embed=self.get_embed(), view=self)
        
        inv[src_name] -= count
        if inv[src_name] <= 0: del inv[src_name]
        
        inv["이상한 씨앗"] = inv.get("이상한 씨앗", 0) + (ratio * count)
        await self.save_func(self.author.id, self.user_data)
        
        await i.response.edit_message(embed=self.get_embed(), view=self)


class WaterRefillView(discord.ui.View):
    def __init__(self, author, user_data, save_func, parent):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func, self.parent = author, user_data, save_func, parent
        self.selected_material = None
        self.update_components()

    def get_embed(self):
        inv = self.user_data.get("inventory", {})
        water = self.user_data["myhome"]["garden"].get("water_can", 0)
        embed = discord.Embed(title="💧 물뿌리개 충전", color=discord.Color.blue())
        embed.add_field(name="현재 물 양", value=f"{water}/20", inline=False)
        embed.add_field(name="재료 재고", value=f"❄️ 눈덩이: {inv.get('눈덩이', 0)}개\n🧊 천년얼음: {inv.get('천년얼음', 0)}개", inline=False)
        return embed

    def update_components(self):
        self.clear_items()
        options = [
            discord.SelectOption(label="눈덩이 3개 (물 +1)", value="snow"),
            discord.SelectOption(label="천년얼음 1개 (물 +5)", value="ice")
        ]
        sel = discord.ui.Select(placeholder="충전 재료 선택", options=options)
        sel.callback = self.select_callback
        self.add_item(sel)

        if self.selected_material:
            self.add_item(discord.ui.Button(label="1회 충전", style=discord.ButtonStyle.primary, custom_id="r1"))
            self.add_item(discord.ui.Button(label="3회 충전", style=discord.ButtonStyle.primary, custom_id="r3"))
            self.add_item(discord.ui.Button(label="5회 충전", style=discord.ButtonStyle.primary, custom_id="r5"))
        
        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=2, custom_id="back"))

    async def select_callback(self, i):
        if i.user != self.author: return
        self.selected_material = i.data['values'][0]
        self.update_components()
        await i.response.edit_message(embed=self.get_embed(), view=self)

    async def interaction_check(self, i):
        if i.user != self.author: return False
        
        # [DB 수정] 데이터 갱신
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
        cid = i.data.get("custom_id")
        if cid == "back":
            self.parent.user_data = self.user_data
            self.parent._ensure_garden_data()
            self.parent.update_components()
            await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)
        elif cid in ["r1", "r3", "r5"]:
            count = int(cid[1:])
            await self.process_refill(i, count)
        return True

    async def process_refill(self, i, count):
        inv = self.user_data.get("inventory", {})
        current = self.user_data["myhome"]["garden"]["water_can"]
        
        if self.selected_material == "snow":
            cost = 3 * count
            gain = 1 * count
            item = "눈덩이"
        else:
            cost = 1 * count
            gain = 5 * count
            item = "천년얼음"
            
        if inv.get(item, 0) < cost:
            return await i.response.edit_message(content=f"❌ {item}이 부족합니다.", embed=self.get_embed(), view=self)
        if current + gain > 20:
            # 초과하더라도 최대치까지만 충전하고 재료 소모 (혹은 막을 수도 있음, 여기선 막음)
            # 반복 횟수를 줄여서 처리하는 로직은 복잡하므로 단순 차단
            return await i.response.edit_message(content="❌ 물뿌리개가 넘칩니다.", embed=self.get_embed(), view=self)
            
        inv[item] -= cost
        if inv[item] <= 0: del inv[item]
        self.user_data["myhome"]["garden"]["water_can"] = min(20, current + gain)
        
        await self.save_func(self.author.id, self.user_data)
        await i.response.edit_message(embed=self.get_embed(), view=self)


class FertilizerCraftView(discord.ui.View):
    def __init__(self, author, user_data, save_func, parent):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func, self.parent = author, user_data, save_func, parent
        self.update_components()

    def update_components(self):
        self.clear_items()
        self.add_select()
        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=1, custom_id="back"))

    def get_embed(self):
        inv = self.user_data.get("inventory", {})
        embed = discord.Embed(title="🧪 비료 제작", description="희귀 재료를 사용하여 비료를 만듭니다.", color=discord.Color.purple())
        embed.add_field(name="필요 재료 (1개당)", value="선택한 희귀재료 1개\n나뭇가지 7개\n버려진 장갑 2개", inline=False)
        embed.add_field(name="보유 재고", value=f"나뭇가지: {inv.get('나뭇가지', 0)}\n버려진 장갑: {inv.get('버려진 장갑', 0)}", inline=False)
        return embed

    def add_select(self):
        inv = self.user_data.get("inventory", {})
        options = []

        # 물고기 아이템 목록을 가져와서 필터링
        all_fish = set()
        for tier_list in FISH_TIERS.values():
            all_fish.update(tier_list)

        for item in RARE_ITEMS:
            if item in all_fish:
                continue
            if inv.get(item, 0) > 0:
                options.append(discord.SelectOption(label=f"{item} ({inv[item]}개 보유)", value=item))
        
        if not options:
            options.append(discord.SelectOption(label="제작 가능한 희귀재료 없음", value="none"))
        
        self.add_item(discord.ui.Select(placeholder="비료 속성으로 부여할 재료 선택", options=options[:25], custom_id="craft_select"))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        
        # [DB 수정] 데이터 갱신
        self.user_data = await get_user_data(self.author.id, self.author.display_name)

        if i.data.get("custom_id") == "back":
            # [FIX] 부모 뷰(GardenView) 데이터 동기화
            self.parent.user_data = self.user_data
            self.parent._ensure_garden_data()
            self.parent.update_components()
            
            await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)
            return True
            
        if i.data.get("custom_id") == "craft_select":
            val = i.data['values'][0]
            if val == "none": return await i.response.edit_message(content="❌ 제작 가능한 희귀재료가 없습니다.", view=self)

            inv = self.user_data.get("inventory", {})
            if inv.get("나뭇가지", 0) < 7 or inv.get("버려진 장갑", 0) < 2:
                return await i.response.edit_message(content="❌ 보조 재료 부족 (나뭇가지 7개, 버려진 장갑 2개 필요)", view=self)

            if inv.get(val, 0) < 1:
                return await i.response.edit_message(content=f"❌ 재료가 부족합니다: {val}", view=self)

            inv[val] -= 1
            if inv[val] <= 0: del inv[val]
            
            inv["나뭇가지"] -= 7
            if inv["나뭇가지"] <= 0: del inv["나뭇가지"]
            
            inv["버려진 장갑"] -= 2
            if inv["버려진 장갑"] <= 0: del inv["버려진 장갑"]
            
            self.user_data.setdefault("fertilizers", []).append({"target": val})
            
            await self.save_func(self.author.id, self.user_data)
            self.update_components()
            await i.response.edit_message(content=f"🧪 **{val}** 속성의 신비한 비료를 제작했습니다!", embed=self.get_embed(), view=self)
        return True


class FertilizerApplyView(discord.ui.View):
    def __init__(self, author, user_data, save_func, parent):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func, self.parent = author, user_data, save_func, parent
        self.selected_slot = None
        self.add_slot_select()
        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=2, custom_id="back"))

    def get_embed(self):
        ferts = self.user_data.get("fertilizers", [])
        embed = discord.Embed(title="🧪 비료 사용", description=f"보유 비료: {len(ferts)}개", color=discord.Color.green())
        return embed

    def add_slot_select(self):
        options = []
        garden = self.user_data["myhome"]["garden"]["slots"]
        for i, slot in enumerate(garden):
            if slot["planted"] and not slot.get("fertilizer"):
                options.append(discord.SelectOption(label=f"{i+1}번 슬롯 (성장단계: {slot['stage']})", value=str(i)))
        
        if not options:
            options.append(discord.SelectOption(label="적용 가능한 작물 없음", value="none"))
        
        self.add_item(discord.ui.Select(placeholder="비료를 줄 작물 선택", options=options, custom_id="slot_sel"))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        
        # [DB 수정] 데이터 갱신
        self.user_data = await get_user_data(self.author.id, self.author.display_name)

        if i.data.get("custom_id") == "back":
            # [FIX] 부모 뷰 데이터 동기화
            self.parent.user_data = self.user_data
            self.parent._ensure_garden_data()
            self.parent.update_components()
            
            await i.response.edit_message(embed=self.parent.get_embed(), view=self.parent)
            return True
        
        if i.data["custom_id"] == "slot_sel":
            val = i.data["values"][0]
            if val == "none": return await i.response.edit_message(content="❌ 비료를 적용할 작물이 없습니다.", view=self)
            self.selected_slot = int(val)
            
            ferts = self.user_data.get("fertilizers", [])
            if not ferts: return await i.response.edit_message(content="❌ 보유한 비료가 없습니다.", view=self)
            
            self.clear_items()
            opt = []
            for idx, f in enumerate(ferts):
                opt.append(discord.SelectOption(label=f"대상: {f['target']}", value=str(idx), description="수확 시 이 재료 획득"))
            
            self.add_item(discord.ui.Select(placeholder="사용할 비료 선택", options=opt[:25], custom_id="fert_sel"))
            self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=2, custom_id="back"))
            await i.response.edit_message(content=f"🌱 {self.selected_slot+1}번 작물에 줄 비료를 선택하세요.", embed=self.get_embed(), view=self)
            
        elif i.data["custom_id"] == "fert_sel":
            f_idx = int(i.data["values"][0])
            ferts = self.user_data.get("fertilizers", [])
            
            if f_idx >= len(ferts):
                return await i.response.edit_message(content="❌ 비료 데이터 오류.", view=self)

            target_item = ferts[f_idx]["target"]
            del ferts[f_idx]
            
            self.user_data["myhome"]["garden"]["slots"][self.selected_slot]["fertilizer"] = target_item
            await self.save_func(self.author.id, self.user_data)
            
            await i.response.edit_message(content=f"🧪 **{target_item}** 비료를 {self.selected_slot+1}번 작물에 주었습니다!", embed=self.parent.get_embed(), view=self.parent)
        
        return True
