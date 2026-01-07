# workshop.py
import discord
import json
import os
import random
from items import RARE_ITEMS
from artifacts import generate_artifact, reroll_artifact_stats, PREFIXES
from data_manager import get_user_data

DATA_FILE = "user_data.json"



class WorkshopView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.page = 0
        # [DB 호환 수정] self.workshop 대신 myhome, workshop_slots 직접 사용
        self.myhome = self.user_data.setdefault("myhome", {})
        self.workshop_slots = self.myhome.setdefault("workshop_slots", [])
        # [수정] DB에 저장되는 workshop_level을 사용하여 최대 슬롯 수 계산 (1레벨=3슬롯)
        self.workshop_level = self.myhome.get("workshop_level", 1)
        self.max_slots = 2 + self.workshop_level
        self.update_components()

    def get_embed(self):
        embed = discord.Embed(title="⚒️ 마이홈 작업실", color=discord.Color.orange())
        inv = self.user_data.get("inventory", {})
        kit = inv.get("아티팩트 제작키트", 0)
        
        embed.add_field(name="자원", value=f"📦 제작키트: {kit}개", inline=False)
        
        slots_desc = ""
        total_sub = self.user_data["myhome"].get("total_subjugations", 0)
        
        for i, slot in enumerate(self.workshop_slots):
            req = slot.get("required_count", 10)
            prog = total_sub - slot.get("start_count", 0)
            if prog >= req:
                state = "✅ **완료!**"
            else:
                state = f"🔨 제작 중 ({prog}/{req})"
            slots_desc += f"**[{i+1}]** {state}\n"
            
        if not slots_desc: slots_desc = "제작 중인 아이템이 없습니다."
        embed.description = slots_desc
        
        embed.set_footer(text=f"슬롯: {len(self.workshop_slots)}/{self.max_slots}")
        return embed

    def update_components(self):
        self.clear_items()
        
        all_buttons = [
            {"label": "🔨 제작 시작", "style": discord.ButtonStyle.primary, "custom_id": "craft"},
            {"label": "🎁 수령", "style": discord.ButtonStyle.success, "custom_id": "claim"},
            {"label": "🎲 옵션 리롤", "style": discord.ButtonStyle.secondary, "custom_id": "reroll"},
            {"label": "🔮 각인", "style": discord.ButtonStyle.secondary, "custom_id": "imprint"},
            {"label": "🏷️ 수식어", "style": discord.ButtonStyle.secondary, "custom_id": "modifier"},
        ]
        
        if self.max_slots < 5:
            all_buttons.append({"label": "🏗️ 확장", "style": discord.ButtonStyle.secondary, "custom_id": "expand"})

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
        if cid == "craft": await self.start_craft(i)
        elif cid == "claim": await self.claim_craft(i)
        elif cid == "reroll": await self.go_reroll(i)
        elif cid == "expand": await self.expand_shop(i)
        elif cid == "imprint": await self.go_imprint(i)
        elif cid == "modifier": await self.go_modifier(i)
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

    async def start_craft(self, i):
        inv = self.user_data.get("inventory", {})
        if inv.get("아티팩트 제작키트", 0) <= 0: return await i.response.send_message("❌ 제작키트가 없습니다.", ephemeral=True)
        if len(self.workshop_slots) >= self.max_slots: return await i.response.send_message("❌ 슬롯 가득 참", ephemeral=True)
        
        inv["아티팩트 제작키트"] -= 1
        self.workshop_slots.append({
            "craft_item": "random_3star", 
            "start_count": self.myhome.get("total_subjugations", 0),
            "required_count": 10
        })
        await self.save_func(self.author.id, self.user_data)
        await i.response.edit_message(embed=self.get_embed(), view=self)

    async def claim_craft(self, i):
        total_sub = self.user_data["myhome"].get("total_subjugations", 0)
        completed = [idx for idx, s in enumerate(self.workshop_slots) if total_sub - s.get("start_count", 0) >= s.get("required_count", 10)]
        
        if not completed: return await i.response.send_message("❌ 완료된 아이템 없음", ephemeral=True)
        
        got = []
        for idx in sorted(completed, reverse=True):
            del self.workshop_slots[idx]
            art = generate_artifact(rank=3)
            self.user_data.setdefault("artifacts", []).append(art)
            got.append(art["name"])
            
        await self.save_func(self.author.id, self.user_data)
        await i.response.edit_message(content=f"🎁 획득: {', '.join(got)}", embed=self.get_embed(), view=self)

    async def expand_shop(self, i):
        if self.max_slots >= 5:
            return await i.response.edit_message(content="❌ 최대 5칸까지 확장 가능합니다.", embed=self.get_embed(), view=self)
        
        cost = 50000
        if self.user_data.get("money", 0) < cost:
            return await i.response.edit_message(content=f"❌ 비용 부족 ({cost:,}원 필요)", embed=self.get_embed(), view=self)
            
        self.user_data["money"] -= cost
        self.workshop_level += 1
        self.myhome["workshop_level"] = self.workshop_level
        self.max_slots = 2 + self.workshop_level
        await self.save_func(self.author.id, self.user_data)
        self.update_components()
        await i.response.edit_message(content=f"🏗️ 작업실 확장 완료! (슬롯 {self.max_slots-1} -> {self.max_slots})", embed=self.get_embed(), view=self)

    async def go_reroll(self, i):
        view = WorkshopRerollView(self.author, self.user_data, self.save_func)
        await i.response.edit_message(embed=view.get_embed(), view=view)

    async def go_imprint(self, i):
        view = ImprintView(self.author, self.user_data, self.save_func)
        await i.response.edit_message(embed=view.get_embed(), view=view)

    async def go_modifier(self, i):
        view = ModifierView(self.author, self.user_data, self.save_func)
        await i.response.edit_message(embed=view.get_embed(), view=view)

    async def go_home(self, interaction):
        # [중요] 순환 참조 방지를 위해 함수 내부에서 import
        from myhome import MyHomeView
        view = MyHomeView(self.author, self.user_data, self.save_func)
        await interaction.response.edit_message(content="🏠 마이홈으로 이동했습니다.", embed=view.get_embed(), view=view)


# --- 리롤 뷰 ---
class WorkshopRerollView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.page = 0
        self.PER_PAGE = 7
        self.filter_option = "all"
        self.last_rerolled_idx = None
        self.update_components()

    def get_embed(self):
        return discord.Embed(title="🎲 아티팩트 리롤", description="3성 아티팩트의 옵션을 재설정합니다. (비용: 5000원 + 1000pt)", color=discord.Color.blue())

    def update_components(self):
        self.clear_items()
        
        # 1. 필터 선택 메뉴 (Row 0)
        self.add_filter_select()
        
        # 2. 아티팩트 선택 메뉴 (Row 1)
        self.add_select()
        
        # 페이지네이션 계산을 위한 필터링된 리스트 재구성
        all_arts = self.user_data.get("artifacts", [])
        filtered_arts = []
        for idx, art in enumerate(all_arts):
            rank = art.get("rank") or art.get("grade") or 1
            if rank != 3: continue
            if self.filter_option != "all" and art.get("prefix") != self.filter_option: continue
            filtered_arts.append(idx)

        total_pages = (len(filtered_arts) - 1) // self.PER_PAGE + 1 if filtered_arts else 1

        if total_pages > 1:
            self.add_item(discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=2, disabled=(self.page == 0), custom_id="prev_page"))
            self.add_item(discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, row=2, disabled=True))
            self.add_item(discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=2, disabled=(self.page >= total_pages - 1), custom_id="next_page"))

        if self.last_rerolled_idx is not None:
             self.add_item(discord.ui.Button(label="🎲 다시 리롤", style=discord.ButtonStyle.primary, row=3, custom_id="reroll_again"))

        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=3, custom_id="back"))

    def add_filter_select(self):
        arts = [art for art in self.user_data.get("artifacts", []) if (art.get("rank") or art.get("grade") or 1) == 3]
        prefixes = sorted(list(set(art.get("prefix", "Unknown") for art in arts if art.get("prefix"))))
        
        options = [discord.SelectOption(label="전체 보기", value="all", default=(self.filter_option == "all"))]
        for p in prefixes[:24]:
            options.append(discord.SelectOption(label=p, value=p, default=(self.filter_option == p)))
            
        self.add_item(discord.ui.Select(placeholder="수식어 필터", options=options, row=0, custom_id="filter_sel"))

    def add_select(self):
        all_arts = self.user_data.get("artifacts", [])
        filtered_arts = []
        for idx, art in enumerate(all_arts):
            rank = art.get("rank") or art.get("grade") or 1
            if rank != 3: continue
            if self.filter_option != "all" and art.get("prefix") != self.filter_option: continue
            filtered_arts.append((idx, art))
        
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_page = filtered_arts[start:end]
        
        opts = []
        for original_idx, art in current_page:
            name = art["name"]
            if art.get("level", 0) > 0:
                name += f" (+{art['level']})"
            opts.append(discord.SelectOption(label=name, value=str(original_idx)))
            
        if not opts:
            self.add_item(discord.ui.Select(placeholder="조건에 맞는 아티팩트 없음", options=[discord.SelectOption(label="없음", value="none")], disabled=True, row=1, custom_id="art_sel"))
        else:
            self.add_item(discord.ui.Select(placeholder=f"아티팩트 선택 ({self.page+1})", options=opts, row=1, custom_id="art_sel"))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        if i.data.get("custom_id") == "back":
            view = WorkshopView(self.author, self.user_data, self.save_func)
            await i.response.edit_message(embed=view.get_embed(), view=view)
            return True
        elif i.data.get("custom_id") == "prev_page":
            self.page -= 1
            self.update_components()
            await i.response.edit_message(view=self)
            return True
        elif i.data.get("custom_id") == "next_page":
            self.page += 1
            self.update_components()
            await i.response.edit_message(view=self)
            return True
        elif i.data.get("custom_id") == "filter_sel":
            self.filter_option = i.data["values"][0]
            self.page = 0
            self.last_rerolled_idx = None
            self.update_components()
            await i.response.edit_message(view=self)
            return True
        elif i.data.get("custom_id") == "reroll_again":
            if self.last_rerolled_idx is not None:
                await self.process_reroll(i, self.last_rerolled_idx)
            return True
            
        if i.data.get("custom_id") == "art_sel" and "values" in i.data:
            val = i.data["values"][0]
            if val == "none": return True
            await self.process_reroll(i, int(val))
            return True
            
        return True

    async def process_reroll(self, i, idx):
        # 최신 데이터 리로드
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        
        if money < 5000 or pt < 1000: return await i.response.send_message("❌ 비용 부족 (5000원 + 1000pt)", ephemeral=True)
        
        self.user_data["money"] -= 5000
        self.user_data["pt"] -= 1000
        
        if idx >= len(self.user_data["artifacts"]):
            return await i.response.send_message("❌ 아티팩트 정보를 찾을 수 없습니다.", ephemeral=True)

        target_art = self.user_data["artifacts"][idx]
        reroll_artifact_stats(target_art)
        
        # 장착 중인 캐릭터 데이터 동기화 (중요)
        for c in self.user_data.get("characters", []):
            eq = c.get("equipped_artifact")
            if eq and eq.get("id") == target_art.get("id"):
                c["equipped_artifact"] = target_art

        await self.save_func(self.author.id, self.user_data)
        
        self.last_rerolled_idx = idx
        self.update_components()
        
        await i.response.edit_message(content=f"🎲 리롤 완료! -> {target_art['description']}", embed=self.get_embed(), view=self)

# --- 각인 시스템 뷰 ---
class ImprintView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.add_char_select()
        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=1, custom_id="back"))

    def get_embed(self):
        return discord.Embed(title="🔮 캐릭터 각인", description="캐릭터에게 전용 아티팩트를 각인합니다.", color=discord.Color.purple())

    def add_char_select(self):
        chars = self.user_data.get("characters", [])
        opts = []
        for idx, c in enumerate(chars):
            opts.append(discord.SelectOption(label=c["name"], value=str(idx)))
        self.add_item(discord.ui.Select(placeholder="각인할 캐릭터 선택", options=opts))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        if i.data.get("custom_id") == "back":
            view = WorkshopView(self.author, self.user_data, self.save_func)
            await i.response.edit_message(embed=view.get_embed(), view=view)
            return True
            
        idx = int(i.data["values"][0])
        char_data = self.user_data["characters"][idx]
        
        # 영산 각인 예시 (실제 구현 시 선택한 아티팩트를 반감하여 각인하도록 확장 가능)
        if "영산" in char_data["name"]:
            imprint_art = {
                "name": "황금의 아티팩트",
                "rank": 3,
                "stats": {"attack": 5, "defense": 5}, 
                "special": "youngsan_gold",
                "description": "[각인] 기술카드 연장 비용 반절 감소"
            }
            # [중요] Character.py와 키 이름 통일
            char_data["equipped_engraved_artifact"] = imprint_art
            await self.save_func(self.author.id, self.user_data)
            await i.response.edit_message(content=f"🔮 **{char_data['name']}**에게 각인 아티팩트를 장착했습니다!", embed=self.get_embed(), view=self)
        else:
            await i.response.edit_message(content="❌ 해당 캐릭터의 전용 각인 로직이 없습니다. (현재 '영산'만 가능)", embed=self.get_embed(), view=self)
        return True

# --- 수식어 변경 뷰 (3성 전용) ---
class ModifierView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.page = 0
        self.PER_PAGE = 7
        self.update_components()

    def get_embed(self):
        return discord.Embed(title="🏷️ 수식어 변경", description="3성 아티팩트의 접두사를 변경합니다. (비용: 1000pt)", color=discord.Color.gold())

    def update_components(self):
        self.clear_items()
        self.add_art_select()
        
        # 3성 필터링된 리스트로 페이지 계산
        arts = [art for art in self.user_data.get("artifacts", []) if (art.get("rank") or art.get("grade") or 1) == 3]
        total_pages = (len(arts) - 1) // self.PER_PAGE + 1 if arts else 1

        if total_pages > 1:
            self.add_item(discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page == 0), custom_id="prev_page"))
            self.add_item(discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, row=1, disabled=True))
            self.add_item(discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page >= total_pages - 1), custom_id="next_page"))

        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=2, custom_id="back"))

    def add_art_select(self):
        all_arts = self.user_data.get("artifacts", [])
        filtered_arts = [(idx, art) for idx, art in enumerate(all_arts) if (art.get("rank") or art.get("grade") or 1) == 3]
        
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_page = filtered_arts[start:end]
        
        opts = []
        for original_idx, art in current_page:
            name = art["name"]
            if art.get("level", 0) > 0:
                name += f" (+{art['level']})"
            opts.append(discord.SelectOption(label=name, value=str(original_idx)))
        
        if not opts:
            self.add_item(discord.ui.Select(placeholder="3성 아티팩트 없음", options=[discord.SelectOption(label="없음", value="none")], disabled=True))
        else:
            self.add_item(discord.ui.Select(placeholder=f"아티팩트 선택 ({self.page+1})", options=opts, custom_id="sel"))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        if i.data.get("custom_id") == "back":
            view = WorkshopView(self.author, self.user_data, self.save_func)
            await i.response.edit_message(embed=view.get_embed(), view=view)
            return True
        elif i.data.get("custom_id") == "prev_page":
            self.page -= 1
            self.update_components()
            await i.response.edit_message(view=self)
            return True
        elif i.data.get("custom_id") == "next_page":
            self.page += 1
            self.update_components()
            await i.response.edit_message(view=self)
            return True
            
        if "values" not in i.data: return True
        idx = int(i.data["values"][0])
        self.user_data = await get_user_data(self.author.id, self.author.display_name)

        target_art = self.user_data["artifacts"][idx]
        
        if (target_art.get("rank") or target_art.get("grade") or 1) < 3:
            return await i.response.send_message("❌ 1, 2성 아티팩트는 수식어를 변경할 수 없습니다.", ephemeral=True)

        if self.user_data.get("pt", 0) < 1000:
            return await i.response.send_message("❌ 1000pt가 필요합니다.", ephemeral=True)
            
        self.user_data["pt"] -= 1000
        
        # 3성 전용 접두사 랜덤 변경
        rank = 3
        new_prefix = random.choice(PREFIXES[rank])
        
        parts = target_art["name"].split()
        if len(parts) >= 2:
            parts[1] = new_prefix
            target_art["name"] = " ".join(parts)
            target_art["prefix"] = new_prefix
            
            from artifacts import SPECIAL_EFFECTS, _make_description
            target_art["special"] = SPECIAL_EFFECTS.get(new_prefix)
            target_art["description"] = _make_description(target_art["stats"], target_art["special"])
            
        # 장착 중인 캐릭터 데이터 동기화
        for c in self.user_data.get("characters", []):
            eq = c.get("equipped_artifact")
            if eq and eq.get("id") == target_art.get("id"):
                c["equipped_artifact"] = target_art

        await self.save_func(self.author.id, self.user_data)
        await i.response.edit_message(content=f"🏷️ 수식어가 **{new_prefix}**로 변경되었습니다!", embed=self.get_embed(), view=self)
        return True