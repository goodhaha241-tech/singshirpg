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
        self.last_rerolled_key = None
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
        targets = self.get_reroll_targets()
        filtered_keys = []
        for key, art in targets:
            p = art.get("prefix")
            if not p:
                name = art.get("name", "")
                p = name.split()[0] if " " in name else "기타"
            if self.filter_option != "all" and p != self.filter_option: continue
            filtered_keys.append(key)

        total_pages = (len(filtered_keys) - 1) // self.PER_PAGE + 1 if filtered_keys else 1

        if total_pages > 1:
            self.add_item(discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=2, disabled=(self.page == 0), custom_id="prev_page"))
            self.add_item(discord.ui.Button(label=f"{self.page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, row=2, disabled=True))
            self.add_item(discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=2, disabled=(self.page >= total_pages - 1), custom_id="next_page"))

        if self.last_rerolled_key is not None:
             self.add_item(discord.ui.Button(label="🎲 다시 리롤", style=discord.ButtonStyle.primary, row=3, custom_id="reroll_again"))

        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=3, custom_id="back"))

    def get_reroll_targets(self):
        """리롤 가능한 모든 아티팩트(일반 3성 + 각인)를 반환"""
        targets = []
        # 1. 일반 아티팩트 (3성만)
        for idx, art in enumerate(self.user_data.get("artifacts", [])):
            rank = art.get("rank") or art.get("grade") or 1
            if rank == 3:
                targets.append((f"art_{idx}", art))
        
        # 2. 각인 아티팩트 (캐릭터 장착)
        for idx, char in enumerate(self.user_data.get("characters", [])):
            eng = char.get("equipped_engraved_artifact")
            if eng and isinstance(eng, dict):
                targets.append((f"eng_{idx}", eng))
        
        return targets

    def add_filter_select(self):
        targets = self.get_reroll_targets()
        prefixes = set()
        for _, art in targets:
            p = art.get("prefix")
            if not p:
                name = art.get("name", "")
                p = name.split()[0] if " " in name else "기타"
            prefixes.add(p)
        
        sorted_prefixes = sorted(list(prefixes))
        
        options = [discord.SelectOption(label="전체 보기", value="all", default=(self.filter_option == "all"))]
        for p in sorted_prefixes[:24]:
            options.append(discord.SelectOption(label=p, value=p, default=(self.filter_option == p)))
            
        self.add_item(discord.ui.Select(placeholder="수식어 필터", options=options, row=0, custom_id="filter_sel"))

    def add_select(self):
        targets = self.get_reroll_targets()
        filtered_arts = []
        for key, art in targets:
            p = art.get("prefix")
            if not p:
                name = art.get("name", "")
                p = name.split()[0] if " " in name else "기타"
            
            if self.filter_option != "all" and p != self.filter_option: continue
            filtered_arts.append((key, art))
        
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_page = filtered_arts[start:end]
        
        opts = []
        for key, art in current_page:
            name = art["name"]
            if art.get("level", 0) > 0:
                name += f" (+{art['level']})"
            
            # 각인 아티팩트인 경우 캐릭터 이름 표시
            if key.startswith("eng_"):
                char_idx = int(key.split("_")[1])
                try:
                    char_name = self.user_data["characters"][char_idx]["name"]
                    name = f"[각인] {name} ({char_name})"
                except: pass
                
            opts.append(discord.SelectOption(label=name, value=key))
            
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
            self.last_rerolled_key = None
            self.update_components()
            await i.response.edit_message(view=self)
            return True
        elif i.data.get("custom_id") == "reroll_again":
            if self.last_rerolled_key is not None:
                await self.process_reroll(i, self.last_rerolled_key)
            return True
            
        if i.data.get("custom_id") == "art_sel" and "values" in i.data:
            val = i.data["values"][0]
            if val == "none": return True
            await self.process_reroll(i, val)
            return True
            
        return True

    async def process_reroll(self, i, key_val):
        # 최신 데이터 리로드
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        
        if money < 5000 or pt < 1000: return await i.response.send_message("❌ 비용 부족 (5000원 + 1000pt)", ephemeral=True)
        
        self.user_data["money"] -= 5000
        self.user_data["pt"] -= 1000
        
        target_art = None
        
        if key_val.startswith("art_"):
            idx = int(key_val.split("_")[1])
            if idx < len(self.user_data["artifacts"]):
                target_art = self.user_data["artifacts"][idx]
        elif key_val.startswith("eng_"):
            c_idx = int(key_val.split("_")[1])
            if c_idx < len(self.user_data["characters"]):
                target_art = self.user_data["characters"][c_idx].get("equipped_engraved_artifact")
        
        if not target_art:
            return await i.response.send_message("❌ 아티팩트 정보를 찾을 수 없습니다.", ephemeral=True)

        reroll_artifact_stats(target_art)
        
        # 일반 아티팩트인 경우 장착 중인 캐릭터 데이터 동기화
        if key_val.startswith("art_"):
            for c in self.user_data.get("characters", []):
                eq = c.get("equipped_artifact")
                if eq and eq.get("id") == target_art.get("id"):
                    c["equipped_artifact"] = target_art

        await self.save_func(self.author.id, self.user_data)
        
        self.last_rerolled_key = key_val
        self.update_components()
        
        await i.response.edit_message(content=f"🎲 리롤 완료! -> {target_art['description']}", embed=self.get_embed(), view=self)

# --- 각인 시스템 뷰 ---
class ImprintView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author, self.user_data, self.save_func = author, user_data, save_func
        self.selected_char_idx = None
        self.update_components()

    def get_embed(self):
        desc = "캐릭터에게 전용 아티팩트를 각인합니다.\n**[조건]** 5강(Lv.5) 아티팩트를 제물로 바쳐야 합니다.\n(제물로 사용된 아티팩트는 **파괴**됩니다.)"
        if self.selected_char_idx is not None:
            try:
                char_name = self.user_data["characters"][self.selected_char_idx]["name"]
                desc += f"\n\n선택된 캐릭터: **{char_name}**\n제물로 사용할 5강 아티팩트를 선택해주세요."
            except IndexError:
                self.selected_char_idx = None
        return discord.Embed(title="🔮 캐릭터 각인", description=desc, color=discord.Color.purple())

    def update_components(self):
        self.clear_items()
        
        # 1. 캐릭터 선택
        chars = self.user_data.get("characters", [])
        char_opts = []
        for idx, c in enumerate(chars):
            label = c["name"]
            if idx == self.selected_char_idx: label = f"✅ {label}"
            char_opts.append(discord.SelectOption(label=label, value=str(idx)))
        
        if char_opts:
            self.add_item(discord.ui.Select(placeholder="각인할 캐릭터 선택", options=char_opts, custom_id="char_sel", row=0))
        else:
            self.add_item(discord.ui.Button(label="캐릭터 없음", disabled=True, row=0))

        # 2. 제물 아티팩트 선택 (캐릭터 선택 시)
        if self.selected_char_idx is not None:
            artifacts = self.user_data.get("artifacts", [])
            art_opts = []
            
            # 5강 이상만 필터링
            for idx, art in enumerate(artifacts):
                if art.get("level", 0) >= 5:
                    label = f"{art['name']} (+{art.get('level', 0)})"
                    # 장착 중인 경우 표시
                    is_equipped = False
                    for c in self.user_data.get("characters", []):
                        eq = c.get("equipped_artifact")
                        if eq and eq.get("id") == art.get("id"):
                            is_equipped = True
                            label += f" (장착중: {c['name']})"
                            break
                    
                    art_opts.append(discord.SelectOption(label=label, value=str(idx)))
            
            if not art_opts:
                self.add_item(discord.ui.Select(placeholder="제물 가능한 5강 아티팩트 없음", options=[discord.SelectOption(label="없음", value="none")], disabled=True, row=1))
            else:
                self.add_item(discord.ui.Select(placeholder="제물 아티팩트 선택 (파괴됨)", options=art_opts[:25], custom_id="art_sel", row=1))

            # [신규] 각인 강화 버튼 (각인 아티팩트 보유 시)
            char_data = self.user_data["characters"][self.selected_char_idx]
            if char_data.get("equipped_engraved_artifact"):
                self.add_item(discord.ui.Button(label="✨ 각인 강화", style=discord.ButtonStyle.success, row=2, custom_id="enhance_imprint"))

        self.add_item(discord.ui.Button(label="⬅️ 뒤로가기", style=discord.ButtonStyle.gray, row=2, custom_id="back"))

    async def interaction_check(self, i):
        if i.user != self.author: return False
        
        cid = i.data.get("custom_id")
        
        if cid == "back":
            view = WorkshopView(self.author, self.user_data, self.save_func)
            await i.response.edit_message(embed=view.get_embed(), view=view)
            return True
            
        if cid == "char_sel":
            self.selected_char_idx = int(i.data["values"][0])
            self.update_components()
            await i.response.edit_message(embed=self.get_embed(), view=self)
            return True
            
        if cid == "art_sel":
            val = i.data["values"][0]
            if val == "none": return True
            await self.process_imprint(i, int(val))
            return True
            
        if cid == "enhance_imprint":
            await self.go_enhance_imprint(i)
            return True
            
        return True

    async def go_enhance_imprint(self, i):
        from artifact_manager import ArtifactManageView
        view = ArtifactManageView(self.author, self.user_data, self.save_func)
        view.mode = "enhance"
        view.char_index = self.selected_char_idx
        view.load_character()
        view.selected_artifact_idx = "engraved_art"
        view.update_view_components()
        
        embed = view.make_enhance_preview_embed("engraved_art")
        await i.response.edit_message(embed=embed, view=view)

    async def process_imprint(self, i, art_idx):
        # 데이터 리로드 (안전성)
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
        if self.selected_char_idx is None or self.selected_char_idx >= len(self.user_data["characters"]):
            return await i.response.send_message("❌ 캐릭터 정보가 변경되었습니다.", ephemeral=True)
            
        if art_idx >= len(self.user_data["artifacts"]):
            return await i.response.send_message("❌ 아티팩트 정보가 변경되었습니다.", ephemeral=True)

        target_art = self.user_data["artifacts"][art_idx]
        
        # 5강 체크 (이중 확인)
        if target_art.get("level", 0) < 5:
            return await i.response.send_message("❌ 5강 이상의 아티팩트만 제물로 사용할 수 있습니다.", ephemeral=True)

        char_data = self.user_data["characters"][self.selected_char_idx]
        
        # 각인 로직
        imprint_art = None
        if "영산" in char_data["name"]:
            imprint_art = {
                "name": "황금의 아티팩트",
                "rank": 3,
                "stats": {"attack": 5, "defense": 5}, 
                "special": "youngsan_gold",
                "description": "[각인] 기술카드 연장 비용 반절 감소"
            }
        elif "루우데" in char_data["name"]:
            imprint_art = {
                "name": "악몽의 아티팩트",
                "rank": 3,
                "stats": {"attack": 7, "max_mental": 30},
                "special": "luude_imprint",
                "description": "[각인] 주사위 파괴 시, 파괴한 개수당 10% 정신력 회복 또는 적에게 피해"
            }
        elif "어즈렉" in char_data["name"]:
            imprint_art = {
                "name": "믿음어린 아티팩트",
                "rank": 3,
                "stats": {"attack": 3, "defense": 7},
                "special": "earthreg_faith",
                "description": "[각인] 첫 합에서 방어 사용 시, 마지막 합에서 그 턴 전체 방어값의 25% 체력/정신력 회복"
            }

        elif "센쇼" in char_data["name"]:
            imprint_art = {
                "name": "별똥별의 아티팩트",
                "rank": 3,
                "stats": {"attack": 7, "max_mental": 30},
                "special": "sensho_star",
                "description": "[각인] '별의 은총' 사용 시 1/8 확률로 방어 효과 대신 체력 전체 회복"
            }
        else:
            return await i.response.send_message("❌ 해당 캐릭터의 전용 각인 로직이 없습니다. (현재 '영산', '루우데', '어즈렉', '센쇼'만 가능)", ephemeral=True)

        # 제물 아티팩트 제거
        # 장착 해제 처리
        art_id = target_art.get("id")
        for c in self.user_data["characters"]:
            eq = c.get("equipped_artifact")
            if eq and eq.get("id") == art_id:
                c["equipped_artifact"] = None
                break
        
        # 리스트에서 삭제
        del self.user_data["artifacts"][art_idx]
        
        # 각인 장착 (기존 각인 덮어쓰기 = 파괴)
        char_data["equipped_engraved_artifact"] = imprint_art
        
        await self.save_func(self.author.id, self.user_data)
        
        # 뷰 갱신 (아티팩트 인덱스가 바뀌었으므로 초기화)
        self.selected_char_idx = None
        self.update_components()
        
        res_embed = discord.Embed(title="🔮 각인 성공!", description=f"**{char_data['name']}**에게 **{imprint_art['name']}**를 각인하고 장착했습니다!\n(제물: {target_art['name']} 파괴됨)", color=discord.Color.purple())
        res_embed.add_field(name="📜 효과 및 스탯", value=imprint_art['description'], inline=False)

        await i.response.edit_message(
            content=None,
            embed=res_embed, 
            view=self
        )

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