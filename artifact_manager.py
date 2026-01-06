# artifact_manager.py
import discord
import random
import re
import json
import os
from character import Character
from items import RARE_ITEMS
from artifacts import _make_description, apply_upgrade_bonus
from fishing import FISH_TIERS
from data_manager import get_user_data

DATA_FILE = "user_data.json"

# 접두사 키워드
PREFIX_KEYWORDS = [
    "맹렬한", "견고한", "꼼꼼한", "앙심품은", "고조된", "불멸의"
]

# --- 강화 비용 테이블 ---
# level: (0->1, 1->2, 2->3, 3->4, 4->5)
UPGRADE_COSTS = {
    1: [
        {"money": 3000, "pt": 0, "items": {}}, 
        {"money": 10000, "pt": 0, "items": {}},
        {"money": 20000, "pt": 0, "items": {}},
        {"money": 40000, "pt": 0, "items": {}},
        {"money": 55000, "pt": 0, "items": {"추억사진첩": 3}}
    ],
    2: [
        {"money": 3000, "pt": 300, "items": {}},
        {"money": 10000, "pt": 600, "items": {}},
        {"money": 20000, "pt": 1200, "items": {}},
        {"money": 40000, "pt": 2400, "items": {}},
        {"money": 55000, "pt": 4800, "items": {"일한산의 정수": 3}}
    ],
    3: [
        {"money": 3000, "pt": 300, "items": {"열매 샐러드": 10}},
        {"money": 10000, "pt": 600, "items": {"기억 종이": 30}},
        {"money": 20000, "pt": 1200, "items": {"눈사람": 20}},
        {"money": 40000, "pt": 2400, "items": {"악몽 프라페": 10}},
        {"money": 55000, "pt": 4800, "items": {"친절함 한 스푼": 10}}
    ]
}

class ArtifactManageView(discord.ui.View):
    def __init__(self, author, user_data, all_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.all_data = all_data
        self.save_func = save_func
        
        self.mode = "equip" # equip, dismantle, enhance
        self.filter_option = "all" 
        
        # 페이지 상태 변수들
        self.filter_page = 0
        self.artifact_page = 0 
        self.char_page = 0 
        self.PER_PAGE = 7 # 7개 제한
        
        self.char_index = 0
        self.selected_artifact_idx = None
        
        self.load_character() 
        self.update_view_components()

    

    def load_character(self):
        char_list = self.user_data.get("characters", [])
        if char_list and 0 <= self.char_index < len(char_list):
            self.char = Character.from_dict(char_list[self.char_index])
        else:
            self.char = Character("모험가", 100, 10, 5)

    def get_artifact_rank(self, art):
        if "rank" in art: return art["rank"]
        name = art.get("name", "")
        desc = art.get("description", "")
        if "[3성]" in name or "⭐⭐⭐" in desc: return 3
        if "[2성]" in name or "⭐⭐" in desc: return 2
        return 1

    def get_prefix(self, name):
        for keyword in PREFIX_KEYWORDS:
            if keyword in name:
                return keyword
        clean_name = re.sub(r'[\[\]\(\)]', '', name).strip()
        if " " in clean_name:
            return clean_name.split(" ")[0]
        return "기타"

    def update_view_components(self):
        self.clear_items()
        
        if self.mode == "equip":
            self.add_character_select()
            
        self.add_filter_select()
        self.add_artifact_select() 

        # 모드 전환 버튼들 (Row 3, 4)
        if self.mode == "equip":
            btn = discord.ui.Button(label="🔨 분해 모드", style=discord.ButtonStyle.secondary, row=3)
            btn.callback = self.switch_to_dismantle
            self.add_item(btn)
            
            enhance_btn = discord.ui.Button(label="✨ 강화 모드", style=discord.ButtonStyle.success, row=3)
            enhance_btn.callback = self.switch_to_enhance
            self.add_item(enhance_btn)

        elif self.mode == "dismantle":
            btn = discord.ui.Button(label="💍 장착 모드", style=discord.ButtonStyle.primary, row=3)
            btn.callback = self.switch_to_equip
            self.add_item(btn)
            
            bulk_btn = discord.ui.Button(label="🗑️ 1~2성 일괄 분해", style=discord.ButtonStyle.danger, row=3)
            bulk_btn.callback = self.bulk_dismantle
            self.add_item(bulk_btn)

        elif self.mode == "enhance":
            if self.selected_artifact_idx is not None:
                confirm_btn = discord.ui.Button(label="🔨 강화 개시", style=discord.ButtonStyle.success, row=3)
                confirm_btn.callback = self.confirm_enhance_callback
                self.add_item(confirm_btn)
                
                cancel_sel = discord.ui.Button(label="선택 취소", style=discord.ButtonStyle.secondary, row=3)
                cancel_sel.callback = self.cancel_enhance_selection
                self.add_item(cancel_sel)
            
            btn = discord.ui.Button(label="💍 장착 모드", style=discord.ButtonStyle.primary, row=4)
            btn.callback = self.switch_to_equip
            self.add_item(btn)

    # --- Mode Switching ---
    async def switch_to_equip(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        self.mode = "equip"
        self.selected_artifact_idx = None
        self.artifact_page = 0
        self.update_view_components()
        await interaction.response.edit_message(embed=self.make_base_embed("💍 장착 모드", "캐릭터에게 아티팩트를 장착합니다."), view=self)

    async def switch_to_dismantle(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        self.mode = "dismantle"
        self.selected_artifact_idx = None
        self.artifact_page = 0
        self.update_view_components()
        await interaction.response.edit_message(embed=self.make_base_embed("🔨 분해 모드", "아티팩트를 분해하여 재료를 얻습니다."), view=self)

    async def switch_to_enhance(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        self.mode = "enhance"
        self.selected_artifact_idx = None
        self.artifact_page = 0
        self.update_view_components()
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        kit = self.user_data.get("inventory", {}).get("강화키트", 0)
        desc = (f"아티팩트를 강화합니다. (최대 5강)\n"
                f"**[보유 자원]**\n💰 {money:,}원 | ⚡ {pt:,}pt | 📦 강화키트: {kit}개")
        await interaction.response.edit_message(embed=self.make_base_embed("✨ 강화 모드", desc), view=self)

    # --- Select Components (Pagination) ---
    def add_character_select(self):
        char_list = self.user_data.get("characters", [])
        if not char_list: return
        
        total_pages = (len(char_list) - 1) // self.PER_PAGE + 1
        
        if self.char_page < 0: self.char_page = 0
        if self.char_page >= total_pages: self.char_page = max(0, total_pages - 1)
        
        start = self.char_page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_chars = char_list[start:end]
        
        options = []
        if self.char_page > 0:
            options.append(discord.SelectOption(label="⬅️ 이전 캐릭터 목록", value="prev_char_page"))
            
        for i, c in enumerate(current_chars):
            real_index = start + i
            label = c.get("name", f"캐릭터 {real_index+1}")
            desc = f"HP: {c.get('hp')}"
            if real_index == self.char_index: label = f"✅ {label}"
            options.append(discord.SelectOption(label=label, description=desc, value=str(real_index)))
            
        if end < len(char_list):
            options.append(discord.SelectOption(label="➡️ 다음 캐릭터 목록", value="next_char_page"))

        select = discord.ui.Select(placeholder=f"관리할 캐릭터 선택 ({self.char_page+1}/{total_pages})", options=options, row=0)
        select.callback = self.on_char_select
        self.add_item(select)

    def add_filter_select(self):
        artifacts = self.user_data.get("artifacts", [])
        prefixes = set()
        for art in artifacts:
            if self.get_artifact_rank(art) >= 3:
                prefixes.add(self.get_prefix(art.get("name", "")))
        
        sorted_prefixes = sorted(list(prefixes))
        total_pages = (len(sorted_prefixes) - 1) // self.PER_PAGE + 1
        if self.filter_page < 0: self.filter_page = 0
        if self.filter_page >= total_pages: self.filter_page = max(0, total_pages - 1)

        start = self.filter_page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_page_prefixes = sorted_prefixes[start:end]
        
        options = [
            discord.SelectOption(label="📂 전체 보기", value="all"),
            discord.SelectOption(label="⭐ 1성 모아보기", value="rank_1"),
            discord.SelectOption(label="⭐⭐ 2성 모아보기", value="rank_2"),
        ]
        if self.filter_page > 0:
            options.append(discord.SelectOption(label="⬅️ 이전 접두사 목록", value="prev_page"))
        for p in current_page_prefixes:
            if p == "기타": continue
            options.append(discord.SelectOption(label=f"✨ [{p}] 계열 (3성)", value=f"prefix_{p}"))
        if end < len(sorted_prefixes):
            options.append(discord.SelectOption(label="➡️ 다음 접두사 목록", value="next_page"))

        # 선택 상태 유지
        found = False
        for opt in options:
            if opt.value == self.filter_option:
                opt.default = True
                found = True
        if not found and not self.filter_option.endswith("_page"):
            self.filter_option = "all"
            options[0].default = True

        select = discord.ui.Select(placeholder="🔍 아티팩트 필터", options=options[:25], row=1)
        select.callback = self.on_filter_select
        self.add_item(select)

    def add_artifact_select(self):
        all_artifacts = self.user_data.get("artifacts", [])
        filtered_artifacts = []
        
        for idx, art in enumerate(all_artifacts):
            rank = self.get_artifact_rank(art)
            prefix = self.get_prefix(art.get("name", ""))
            
            if self.filter_option == "all": pass
            elif self.filter_option == "rank_1" and rank == 1: pass
            elif self.filter_option == "rank_2" and rank == 2: pass
            elif self.filter_option.startswith("prefix_") and rank >= 3:
                if prefix == self.filter_option.replace("prefix_", ""): pass
                else: continue
            else: continue
            
            filtered_artifacts.append((idx, art))

        total_pages = (len(filtered_artifacts) - 1) // self.PER_PAGE + 1
        if total_pages < 1: total_pages = 1
        
        if self.artifact_page < 0: self.artifact_page = 0
        if self.artifact_page >= total_pages: self.artifact_page = total_pages - 1
        
        start = self.artifact_page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_page_artifacts = filtered_artifacts[start:end]

        options = []
        if self.mode == "equip":
            if self.char.equipped_artifact:
                eq_name = self.char.equipped_artifact.get("name", "Unknown")
                options.append(discord.SelectOption(label="❌ 장착 해제", description=f"[{eq_name}] 해제", value="unequip"))
            placeholder = f"장착할 아티팩트 선택 ({self.artifact_page+1}/{total_pages})"
        elif self.mode == "dismantle":
            placeholder = f"분해할 아티팩트 선택 ({self.artifact_page+1}/{total_pages})"
        else: # enhance
            placeholder = f"강화할 아티팩트 선택 ({self.artifact_page+1}/{total_pages})"

        for original_idx, art in current_page_artifacts:
            rank = self.get_artifact_rank(art)
            lvl = art.get("level", 0)
            
            label = f"[{'⭐'*rank}] {art['name']}"
            if lvl > 0: label += f" (+{lvl})"
            
            is_equipped = False
            owner_name = ""
            for c in self.user_data.get("characters", []):
                eq = c.get("equipped_artifact")
                if eq and eq.get("id") == art.get("id"):
                    is_equipped = True
                    owner_name = c["name"]
                    break
            
            if is_equipped: label += f" (⛔ {owner_name})"
            desc = art.get('description', '')[:90]
            
            opt = discord.SelectOption(label=label, description=desc, value=str(original_idx))
            if self.mode == "enhance" and self.selected_artifact_idx == original_idx:
                opt.default = True
            
            options.append(opt)

        if not options:
            options.append(discord.SelectOption(label="표시할 아티팩트 없음", value="none"))

        select = discord.ui.Select(placeholder=placeholder, options=options, row=2)
        select.callback = self.on_artifact_select
        self.add_item(select)

        if total_pages > 1:
            prev_btn = discord.ui.Button(label="◀️ 이전 목록", style=discord.ButtonStyle.secondary, row=4, disabled=(self.artifact_page == 0))
            prev_btn.callback = self.prev_art_page
            self.add_item(prev_btn)
            
            next_btn = discord.ui.Button(label="다음 목록 ▶️", style=discord.ButtonStyle.secondary, row=4, disabled=(self.artifact_page == total_pages - 1))
            next_btn.callback = self.next_art_page
            self.add_item(next_btn)

    async def prev_art_page(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.artifact_page -= 1
        self.update_view_components()
        await interaction.response.edit_message(view=self)

    async def next_art_page(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.artifact_page += 1
        self.update_view_components()
        await interaction.response.edit_message(view=self)

    # --- Callbacks ---
    async def on_char_select(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        val = interaction.data['values'][0]
        
        if val == "next_char_page":
            self.char_page += 1
            self.update_view_components()
            return await interaction.response.edit_message(view=self)
        elif val == "prev_char_page":
            self.char_page -= 1
            self.update_view_components()
            return await interaction.response.edit_message(view=self)
            
        self.char_index = int(val)
        self.load_character()
        self.update_view_components()
        await interaction.response.edit_message(view=self)

    async def on_filter_select(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        val = interaction.data['values'][0]
        if val == "next_page": self.filter_page += 1
        elif val == "prev_page": self.filter_page = max(0, self.filter_page - 1)
        else: self.filter_option = val
        
        self.selected_artifact_idx = None
        self.artifact_page = 0
        self.update_view_components()
        await interaction.response.edit_message(view=self)

    # --- ACTION HANDLER ---
    async def on_artifact_select(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        val = interaction.data['values'][0]
        if val == "none": return await interaction.response.defer()

        # [중요] 행동 전 데이터 리로드 (동시성 문제 및 롤백 방지)
        self.user_data = await get_user_data(self.author.id, self.author.display_name)

        if self.mode == "equip":
            if val == "unequip":
                self.char.equipped_artifact = None
                msg = f"✅ **{self.char.name}**: 장착 해제 완료."
            else:
                idx = int(val)
                # 인덱스 유효성 체크
                if idx >= len(self.user_data["artifacts"]):
                    return await interaction.response.send_message("❌ 아티팩트 정보가 변경되었습니다. 다시 선택해주세요.", ephemeral=True)
                art = self.user_data["artifacts"][idx]
                
                # 중복 장착 체크
                for i, c in enumerate(self.user_data.get("characters", [])):
                    if i == self.char_index: continue
                    eq = c.get("equipped_artifact")
                    if eq and eq.get("id") == art.get("id"):
                        return await interaction.response.send_message(f"❌ 이미 **{c['name']}**에게 장착되어 있습니다.", ephemeral=True)
                
                self.char.equipped_artifact = art
                msg = f"💍 **{self.char.name}**: **{art['name']}** 장착 완료!"
            
            self.user_data["characters"][self.char_index] = self.char.to_dict()
            await self.save_func(self.author.id, self.user_data)
            self.update_view_components()
            await interaction.response.edit_message(content=msg, embed=self.make_base_embed("💍 장착 모드", msg), view=self)

        elif self.mode == "dismantle":
            idx = int(val)
            if idx >= len(self.user_data["artifacts"]):
                return await interaction.response.send_message("❌ 아티팩트 정보가 변경되었습니다.", ephemeral=True)
            art = self.user_data["artifacts"][idx]
            
            # 장착 체크
            is_equipped = False
            for c in self.user_data.get("characters", []):
                eq = c.get("equipped_artifact")
                if eq and eq.get("id") == art.get("id"):
                    is_equipped = True
                    break
            if is_equipped:
                return await interaction.response.send_message("❌ 장착 중인 아티팩트는 분해할 수 없습니다.", ephemeral=True)

            del self.user_data["artifacts"][idx]
            rank = self.get_artifact_rank(art)
            rewards = []
            inv = self.user_data.setdefault("inventory", {})
            
            # [수정] 분해 시 물고기 제외
            all_fish = set()
            for tier_list in FISH_TIERS.values():
                all_fish.update(tier_list)
            valid_rewards = [i for i in RARE_ITEMS if i not in all_fish]
            if not valid_rewards: valid_rewards = ["사랑나무 가지"]

            for _ in range(rank):
                mat = random.choice(valid_rewards)
                inv[mat] = inv.get(mat, 0) + 1
                rewards.append(mat)
            
            await self.save_func(self.author.id, self.user_data)
            self.update_view_components()
            msg = f"🔨 **{art['name']}** 분해 완료! (획득: {', '.join(rewards)})"
            await interaction.response.edit_message(content=msg, embed=self.make_base_embed("🔨 분해 모드", msg), view=self)

        elif self.mode == "enhance":
            idx = int(val)
            if idx >= len(self.user_data["artifacts"]):
                return await interaction.response.send_message("❌ 아티팩트 정보가 변경되었습니다.", ephemeral=True)
            
            self.selected_artifact_idx = idx
            embed = self.make_enhance_preview_embed(idx)
            self.update_view_components() 
            await interaction.response.edit_message(embed=embed, view=self)

    async def cancel_enhance_selection(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.selected_artifact_idx = None
        self.update_view_components()
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        kit = self.user_data.get("inventory", {}).get("강화키트", 0)
        desc = (f"아티팩트를 강화합니다. (최대 5강)\n"
                f"**[보유 자원]**\n💰 {money:,}원 | ⚡ {pt:,}pt | 📦 강화키트: {kit}개")
        await interaction.response.edit_message(embed=self.make_base_embed("✨ 강화 모드", desc), view=self)

    async def confirm_enhance_callback(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        if self.selected_artifact_idx is None:
            return await interaction.response.send_message("❌ 선택된 아티팩트가 없습니다.", ephemeral=True)
        
        # [중요] 강화 직전 데이터 리로드
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
            
        try:
            art = self.user_data["artifacts"][self.selected_artifact_idx]
        except IndexError:
            self.selected_artifact_idx = None
            self.update_view_components()
            return await interaction.response.edit_message(content="❌ 아티팩트 정보를 찾을 수 없습니다.", view=self)

        await self.process_enhance(interaction, art, self.selected_artifact_idx)

    async def process_enhance(self, interaction, art, idx):
        rank = self.get_artifact_rank(art)
        level = art.get("level", 0)
        
        if level >= 5:
            return await interaction.response.send_message("⚠️ 이미 최대 레벨(5강)입니다.", ephemeral=True)

        inv = self.user_data.setdefault("inventory", {})
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)

        if inv.get("강화키트", 0) < 1:
            return await interaction.response.send_message("❌ **강화키트**가 부족합니다.", ephemeral=True)

        cost_data = UPGRADE_COSTS[rank][level]
        req_money = cost_data["money"]
        req_pt = cost_data["pt"]
        req_items = cost_data["items"]

        if money < req_money:
            return await interaction.response.send_message(f"❌ 돈이 부족합니다. ({req_money:,}원 필요)", ephemeral=True)
        if pt < req_pt:
            return await interaction.response.send_message(f"❌ 포인트가 부족합니다. ({req_pt:,}pt 필요)", ephemeral=True)
        
        missing_items = []
        for item, count in req_items.items():
            if inv.get(item, 0) < count:
                missing_items.append(f"{item} ({inv.get(item,0)}/{count})")
        
        if missing_items:
            return await interaction.response.send_message(f"❌ 재료가 부족합니다: {', '.join(missing_items)}", ephemeral=True)

        inv["강화키트"] -= 1
        if inv["강화키트"] <= 0: del inv["강화키트"]
        
        self.user_data["money"] -= req_money
        self.user_data["pt"] -= req_pt
        for item, count in req_items.items():
            inv[item] -= count
            if inv[item] <= 0: del inv[item]

        # [수정] artifacts.py의 apply_upgrade_bonus 사용하여 로직 통일
        stats = art.get("stats", {})
        old_stats = stats.copy()
        
        apply_upgrade_bonus(stats) # 공통 강화 함수 호출
        
        log_lines = []
        for key in stats:
            if key in old_stats and stats[key] > old_stats[key]:
                increase = stats[key] - old_stats[key]
                k_name = {"max_hp":"체력","max_mental":"정신력","attack":"공격","defense":"방어","defense_rate":"방어율"}.get(key, key)
                log_lines.append(f"**{k_name}**: {old_stats[key]} ➔ **{stats[key]}** (+{increase} 🔺)")

        art["level"] = level + 1
        special = art.get("special")
        art["description"] = _make_description(stats, special)
        
        self.user_data["artifacts"][idx] = art 
        
        # 장착 중인 모든 캐릭터 데이터 동기화
        for c in self.user_data.get("characters", []):
            eq = c.get("equipped_artifact")
            if eq and eq.get("id") == art.get("id"):
                c["equipped_artifact"] = art 

        await self.save_func(self.author.id, self.user_data)
        
        self.selected_artifact_idx = None
        self.update_view_components()
        
        embed = discord.Embed(title=f"✨ 강화 성공! (+{art['level']})", color=discord.Color.gold())
        embed.description = f"**{art['name']}**\n\n" + "\n".join(log_lines)
        embed.set_footer(text=f"남은 강화키트: {inv.get('강화키트', 0)}개")
        
        await interaction.response.edit_message(content=None, embed=embed, view=self)

    async def bulk_dismantle(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        
        # [중요] 분해 전 리로드
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        
        artifacts = self.user_data.get("artifacts", [])
        characters = self.user_data.get("characters", [])
        
        equipped_ids = set()
        for c in characters:
            eq = c.get("equipped_artifact")
            if eq and eq.get("id"): equipped_ids.add(eq.get("id"))

        new_artifacts = []
        dismantled = 0
        rewards = {}

        # [수정] 분해 시 물고기 제외
        all_fish = set()
        for tier_list in FISH_TIERS.values():
            all_fish.update(tier_list)
        valid_rewards = [i for i in RARE_ITEMS if i not in all_fish]
        if not valid_rewards: valid_rewards = ["사랑나무 가지"]

        for art in artifacts:
            rank = self.get_artifact_rank(art)
            # 장착 안 된 1,2성만
            if rank <= 2 and art.get("id") not in equipped_ids:
                dismantled += 1
                for _ in range(rank):
                    mat = random.choice(valid_rewards)
                    rewards[mat] = rewards.get(mat, 0) + 1
            else:
                new_artifacts.append(art)

        if dismantled == 0:
            return await interaction.response.send_message("❌ 분해할 1~2성 아티팩트가 없습니다.", ephemeral=True)

        self.user_data["artifacts"] = new_artifacts
        inv = self.user_data.setdefault("inventory", {})
        for item, qty in rewards.items():
            inv[item] = inv.get(item, 0) + qty
            
        await self.save_func(self.author.id, self.user_data)
        self.update_view_components()
        
        r_str = ", ".join([f"{k} x{v}" for k, v in rewards.items()])
        await interaction.response.edit_message(
            content=f"🗑️ **{dismantled}개** 분해 완료!\n획득: {r_str}", 
            embed=self.make_base_embed("🔨 분해 모드", "일괄 분해가 완료되었습니다."),
            view=self
        )

    def make_base_embed(self, title, description):
        embed = discord.Embed(title=title, description=description, color=discord.Color.purple())
        if self.mode == "equip":
            equipped = self.char.equipped_artifact
            if equipped and isinstance(equipped, dict):
                name = equipped.get("name", "이름없음")
                lvl = equipped.get("level", 0)
                if lvl > 0: name += f" (+{lvl})"
                desc = equipped.get("description", "설명없음")
            else:
                name = "없음"
                desc = "장착된 아티팩트가 없습니다."
            embed.add_field(name=f"👤 {self.char.name}의 장비", value=f"**{name}**\n{desc}", inline=False)
        return embed

    def make_enhance_preview_embed(self, idx):
        art = self.user_data["artifacts"][idx]
        rank = self.get_artifact_rank(art)
        level = art.get("level", 0)
        
        embed = discord.Embed(title="✨ 강화 준비", description=f"**{art['name']}** (+{level} ➔ +{level+1})", color=discord.Color.blue())
        
        stats = art.get("stats", {})
        stat_txt = []
        for k, v in stats.items():
            if v > 0:
                k_name = {"max_hp":"체력","max_mental":"정신력","attack":"공격","defense":"방어","defense_rate":"방어율"}.get(k, k)
                stat_txt.append(f"{k_name}: {v}")
        embed.add_field(name="📊 현재 스탯", value="\n".join(stat_txt) or "없음", inline=False)
        
        if level < 5:
            cost_data = UPGRADE_COSTS[rank][level]
            req_money = cost_data["money"]
            req_pt = cost_data["pt"]
            req_items = cost_data["items"]
            
            cost_txt = f"💰 {req_money:,}원\n⚡ {req_pt:,}pt\n📦 강화키트 1개"
            if req_items:
                inv = self.user_data.get("inventory", {})
                item_lines = []
                for item, count in req_items.items():
                    have = inv.get(item, 0)
                    mark = "✅" if have >= count else "❌"
                    item_lines.append(f"{mark} {item}: {have}/{count}")
                cost_txt += "\n" + "\n".join(item_lines)
            
            embed.add_field(name="📉 소모 자원", value=cost_txt, inline=False)
        else:
            embed.description = f"**{art['name']}** (최대 레벨 도달)"
            embed.color = discord.Color.red()
            
        return embed