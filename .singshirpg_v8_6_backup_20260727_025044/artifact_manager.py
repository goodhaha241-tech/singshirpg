# artifact_manager.py
# rollback-guard-appraisal-gems-v8
# appraisal-gem-affixes-v8.1
# gem-visibility-tools-v8.3
import discord
import random
import re
import json
import os
from character import (
    Character,
    artifact_effective_stats,
    artifact_primary_stat_key,
)
from items import RARE_ITEMS, GUILD_ITEMS
from artifacts import _make_description, apply_upgrade_bonus
from fishing import FISH_TIERS
from data_manager import get_user_data
from decorators import auto_defer
from gem_manager import gem_detail_text

DATA_FILE = "user_data.json"

# 접두사 키워드
PREFIX_KEYWORDS = [
    "맹렬한", "견고한", "꼼꼼한", "앙심품은", "고조된", "불멸의"
]


def _add_gem_detail_fields(embed, artifact, label):
    if not isinstance(artifact, dict):
        return
    for socket_index, gem in enumerate(artifact.get("gems", [])):
        if not isinstance(gem, dict):
            continue
        embed.add_field(
            name=f"💎 {label} {socket_index + 1}번 · {gem.get('name', '젬')}",
            value=gem_detail_text(gem)[:1024],
            inline=False,
        )

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

# [신규] 각인 아티팩트 강화 비용 (0->1, 1->2, 2->3)
ENGRAVED_UPGRADE_COSTS = {
    0: {"money": 300000, "pt": 10000, "items": {}},
    1: {"money": 350000, "pt": 13000, "items": {}},
    2: {"money": 600000, "pt": 20000, "items": {}}
}

class ArtifactManageView(discord.ui.View):
    def __init__(self, author, user_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        
        self.mode = "equip" # equip, dismantle, enhance
        self.filter_option = "all" 
        
        # 페이지 상태 변수들
        self.filter_page = 0
        self.artifact_page = 0 
        self.char_page = 0 
        self.PER_PAGE = 8 # 관리 목록은 다른 장비 화면과 동일하게 페이지당 8개
        
        self.char_index = 0
        self.selected_artifact_idx = None
        
        self.load_character() 
        self.update_view_components()

    

    def load_character(self):
        char_list = self.user_data.get("characters", [])
        if char_list and 0 <= self.char_index < len(char_list):
            self.char = Character.from_dict(char_list[self.char_index])
            # [Patch] 캐릭터 객체에 각인 아티팩트 정보 수동 주입 (Character 클래스 미지원 대비)
            if "equipped_engraved_artifact" in char_list[self.char_index]:
                self.char.equipped_engraved_artifact = char_list[self.char_index]["equipped_engraved_artifact"]
        else:
            self.char = Character("모험가", 170, 170, 90, 90, 5, 3)

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
    @auto_defer(reload_data=True)
    async def switch_to_equip(self, interaction: discord.Interaction):
        self.mode = "equip"
        self.selected_artifact_idx = None
        self.artifact_page = 0
        self.update_view_components()
        await interaction.edit_original_response(embed=self.make_base_embed("💍 장착 모드", "캐릭터에게 아티팩트를 장착합니다."), view=self)

    @auto_defer(reload_data=True)
    async def switch_to_dismantle(self, interaction: discord.Interaction):
        self.mode = "dismantle"
        self.selected_artifact_idx = None
        self.artifact_page = 0
        self.update_view_components()
        await interaction.edit_original_response(embed=self.make_base_embed("🔨 분해 모드", "아티팩트를 분해하여 재료를 얻습니다."), view=self)

    @auto_defer(reload_data=True)
    async def switch_to_enhance(self, interaction: discord.Interaction):
        self.mode = "enhance"
        self.selected_artifact_idx = None
        self.artifact_page = 0
        self.update_view_components()
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        kit = self.user_data.get("inventory", {}).get("강화키트", 0)
        desc = (f"아티팩트를 강화합니다. (최대 5강)\n"
                f"**[보유 자원]**\n💰 {money:,}원 | ⚡ {pt:,}pt | 📦 강화키트: {kit}개")
        await interaction.edit_original_response(embed=self.make_base_embed("✨ 강화 모드", desc), view=self)

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
        
        # [신규] 정렬 로직: (인덱스, 아티팩트) 튜플 리스트 생성 후 정렬
        # 우선순위: 1. 등급(Rank) 내림차순, 2. 레벨(Level) 내림차순, 3. 이름 오름차순
        indexed_artifacts = [(i, art) for i, art in enumerate(all_artifacts)]
        indexed_artifacts.sort(key=lambda x: (
            -self.get_artifact_rank(x[1]), 
            -x[1].get("level", 0), 
            x[1].get("name", "")
        ))

        filtered_artifacts = []
        
        for idx, art in indexed_artifacts:
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

        # [신규] 강화 모드일 때 각인 아티팩트 선택지 추가 (맨 위에 표시)
        if self.mode == "enhance":
            engraved = self.char.equipped_engraved_artifact
            if engraved and isinstance(engraved, dict):
                lvl = engraved.get("level", 0)
                label = f"🔮 [각인] {engraved['name']} (+{lvl})"
                desc = engraved.get("description", "")[:90]
                opt = discord.SelectOption(label=label, description=desc, value="engraved_art")
                if self.selected_artifact_idx == "engraved_art":
                    opt.default = True
                options.insert(0, opt)

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

    @auto_defer()
    async def prev_art_page(self, interaction: discord.Interaction):
        self.artifact_page -= 1
        self.update_view_components()
        await interaction.edit_original_response(view=self)

    @auto_defer()
    async def next_art_page(self, interaction: discord.Interaction):
        self.artifact_page += 1
        self.update_view_components()
        await interaction.edit_original_response(view=self)

    # --- Callbacks ---
    @auto_defer()
    async def on_char_select(self, interaction: discord.Interaction):
        val = interaction.data['values'][0]
        
        if val == "next_char_page":
            self.char_page += 1
        elif val == "prev_char_page":
            self.char_page -= 1
        else:
            self.char_index = int(val)
            self.load_character()

        self.update_view_components()
        
        # [수정] 캐릭터 변경 시 임베드 정보도 갱신 (이전 캐릭터 정보가 남는 문제 해결)
        embed = self.make_base_embed("💍 장착 모드", "캐릭터에게 아티팩트를 장착합니다.")
        await interaction.edit_original_response(embed=embed, view=self)

    @auto_defer()
    async def on_filter_select(self, interaction: discord.Interaction):
        val = interaction.data['values'][0]
        if val == "next_page": self.filter_page += 1
        elif val == "prev_page": self.filter_page = max(0, self.filter_page - 1)
        else: self.filter_option = val
        
        self.selected_artifact_idx = None
        self.artifact_page = 0
        self.update_view_components()
        await interaction.edit_original_response(view=self)

    # --- ACTION HANDLER ---
    @auto_defer(reload_data=True)
    async def on_artifact_select(self, interaction: discord.Interaction):
        val = interaction.data['values'][0]
        if val == "none": return

        # [신규] 각인 아티팩트 선택 처리
        if self.mode == "enhance" and val == "engraved_art":
            self.selected_artifact_idx = "engraved_art"
            embed = self.make_enhance_preview_embed("engraved_art")
            self.update_view_components()
            await interaction.edit_original_response(embed=embed, view=self)
            return

        # [중요] 행동 전 데이터 리로드 (동시성 문제 및 롤백 방지)

        if self.mode == "equip":
            if val == "unequip":
                # 메인 리스트에서 해당 아티팩트의 장착 정보 해제
                if self.char.equipped_artifact:
                    art_id = self.char.equipped_artifact.get("id")
                    for a in self.user_data.get("artifacts", []):
                        if a.get("id") == art_id:
                            a["equipped_char_index"] = -1
                
                self.char.equipped_artifact = None
                msg = f"✅ **{self.char.name}**: 장착 해제 완료."
            else:
                idx = int(val)
                # 인덱스 유효성 체크
                if idx >= len(self.user_data["artifacts"]):
                    return await interaction.followup.send("❌ 아티팩트 정보가 변경되었습니다. 다시 선택해주세요.", ephemeral=True)
                art = self.user_data["artifacts"][idx]
                
                # 중복 장착 체크
                for i, c in enumerate(self.user_data.get("characters", [])):
                    if i == self.char_index: continue
                    eq = c.get("equipped_artifact")
                    if eq and eq.get("id") == art.get("id"):
                        return await interaction.followup.send(f"❌ 이미 **{c['name']}**에게 장착되어 있습니다.", ephemeral=True)
                
                # 기존에 이 캐릭터가 장착하고 있던 아티팩트가 있다면 리스트에서 인덱스 초기화
                if self.char.equipped_artifact:
                    old_id = self.char.equipped_artifact.get("id")
                    for a in self.user_data.get("artifacts", []):
                        if a.get("id") == old_id:
                            a["equipped_char_index"] = -1

                # 새 아티팩트에 장착 정보 설정 (DB 저장을 위해)
                art["equipped_char_index"] = self.char_index
                
                self.char.equipped_artifact = art
                msg = f"💍 **{self.char.name}**: **{art['name']}** 장착 완료!"
            
            self.user_data["characters"][self.char_index] = self.char.to_dict()
            await self.save_func(self.author.id, self.user_data)
            self.update_view_components()
            await interaction.edit_original_response(content=msg, embed=self.make_base_embed("💍 장착 모드", msg), view=self)

        elif self.mode == "dismantle":
            idx = int(val)
            if idx >= len(self.user_data["artifacts"]):
                return await interaction.followup.send("❌ 아티팩트 정보가 변경되었습니다.", ephemeral=True)
            art = self.user_data["artifacts"][idx]
            
            # 장착 체크
            is_equipped = False
            for c in self.user_data.get("characters", []):
                eq = c.get("equipped_artifact")
                if eq and eq.get("id") == art.get("id"):
                    is_equipped = True
                    break
            if is_equipped:
                return await interaction.followup.send("❌ 장착 중인 아티팩트는 분해할 수 없습니다.", ephemeral=True)

            del self.user_data["artifacts"][idx]
            rank = self.get_artifact_rank(art)
            rewards = []
            inv = self.user_data.setdefault("inventory", {})
            
            # [수정] 분해 시 물고기 제외
            all_fish = set()
            for tier_list in FISH_TIERS.values():
                all_fish.update(tier_list)
            valid_rewards = [i for i in RARE_ITEMS if i not in all_fish and i not in GUILD_ITEMS]
            if not valid_rewards: valid_rewards = ["사랑나무 가지"]

            for _ in range(rank):
                mat = random.choice(valid_rewards)
                inv[mat] = inv.get(mat, 0) + 1
                rewards.append(mat)
            
            await self.save_func(self.author.id, self.user_data)
            self.update_view_components()
            msg = f"🔨 **{art['name']}** 분해 완료! (획득: {', '.join(rewards)})"
            await interaction.edit_original_response(content=msg, embed=self.make_base_embed("🔨 분해 모드", msg), view=self)

        elif self.mode == "enhance":
            idx = int(val)
            if idx >= len(self.user_data["artifacts"]):
                return await interaction.followup.send("❌ 아티팩트 정보가 변경되었습니다.", ephemeral=True)
            
            self.selected_artifact_idx = idx
            embed = self.make_enhance_preview_embed(idx)
            self.update_view_components() 
            await interaction.edit_original_response(embed=embed, view=self)

    @auto_defer()
    async def cancel_enhance_selection(self, interaction: discord.Interaction):
        self.selected_artifact_idx = None
        self.update_view_components()
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)
        kit = self.user_data.get("inventory", {}).get("강화키트", 0)
        desc = (f"아티팩트를 강화합니다. (최대 5강)\n"
                f"**[보유 자원]**\n💰 {money:,}원 | ⚡ {pt:,}pt | 📦 강화키트: {kit}개")
        await interaction.edit_original_response(embed=self.make_base_embed("✨ 강화 모드", desc), view=self)

    @auto_defer(reload_data=True)
    async def confirm_enhance_callback(self, interaction: discord.Interaction):
        if self.selected_artifact_idx is None:
            return await interaction.followup.send("❌ 선택된 아티팩트가 없습니다.", ephemeral=True)
        
        # [신규] 각인 아티팩트 처리
        if self.selected_artifact_idx == "engraved_art":
            art = self.char.equipped_engraved_artifact
            if not art: return await interaction.followup.send("❌ 각인 아티팩트가 없습니다.", ephemeral=True)
            await self.process_enhance(interaction, art, "engraved_art")
            return

        try:
            art = self.user_data["artifacts"][self.selected_artifact_idx]
        except IndexError:
            self.selected_artifact_idx = None
            self.update_view_components()
            return await interaction.edit_original_response(content="❌ 아티팩트 정보를 찾을 수 없습니다.", view=self)

        await self.process_enhance(interaction, art, self.selected_artifact_idx)

    async def process_enhance(self, interaction, art, idx):
        is_engraved = (idx == "engraved_art")
        rank = self.get_artifact_rank(art)
        level = art.get("level", 0)
        
        # [수정] 최대 레벨 체크 (각인: 3강, 일반: 5강)
        max_level = 3 if is_engraved else 5
        if level >= max_level:
            return await interaction.followup.send(f"⚠️ 이미 최대 레벨({max_level}강)입니다.", ephemeral=True)

        inv = self.user_data.setdefault("inventory", {})
        money = self.user_data.get("money", 0)
        pt = self.user_data.get("pt", 0)

        # [수정] 비용 계산 분기
        if is_engraved:
            cost_data = ENGRAVED_UPGRADE_COSTS.get(level, {})
            req_money = cost_data.get("money", 0)
            req_pt = cost_data.get("pt", 0)
            req_items = cost_data.get("items", {})
        else:
            if inv.get("강화키트", 0) < 1:
                return await interaction.response.send_message("❌ **강화키트**가 부족합니다.", ephemeral=True)

            cost_data = UPGRADE_COSTS[rank][level]
            req_money = cost_data["money"]
            req_pt = cost_data["pt"]
            req_items = cost_data["items"]

        if money < req_money:
            return await interaction.followup.send(f"❌ 돈이 부족합니다. ({req_money:,}원 필요)", ephemeral=True)
        if pt < req_pt:
            return await interaction.followup.send(f"❌ 포인트가 부족합니다. ({req_pt:,}pt 필요)", ephemeral=True)
        
        missing_items = []
        for item, count in req_items.items():
            if inv.get(item, 0) < count:
                missing_items.append(f"{item} ({inv.get(item,0)}/{count})")
        
        if missing_items:
            return await interaction.followup.send(f"❌ 재료가 부족합니다: {', '.join(missing_items)}", ephemeral=True)

        if not is_engraved:
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
        
        if is_engraved:
            # 각인 아티팩트는 캐릭터 데이터에 직접 저장
            self.char.equipped_engraved_artifact = art
            self.user_data["characters"][self.char_index] = self.char.to_dict()
        else:
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
        if not is_engraved:
            embed.set_footer(text=f"남은 강화키트: {inv.get('강화키트', 0)}개")
        
        await interaction.edit_original_response(content=None, embed=embed, view=self)

    @auto_defer(reload_data=True)
    async def bulk_dismantle(self, interaction: discord.Interaction):
        
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
        valid_rewards = [i for i in RARE_ITEMS if i not in all_fish and i not in GUILD_ITEMS]
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
            return await interaction.followup.send("❌ 분해할 1~2성 아티팩트가 없습니다.", ephemeral=True)

        self.user_data["artifacts"] = new_artifacts
        inv = self.user_data.setdefault("inventory", {})
        for item, qty in rewards.items():
            inv[item] = inv.get(item, 0) + qty
            
        await self.save_func(self.author.id, self.user_data)
        self.update_view_components()
        
        r_str = ", ".join([f"{k} x{v}" for k, v in rewards.items()])
        await interaction.edit_original_response(
            content=f"🗑️ **{dismantled}개** 분해 완료!\n획득: {r_str}", 
            embed=self.make_base_embed("🔨 분해 모드", "일괄 분해가 완료되었습니다."),
            view=self
        )

    def make_base_embed(self, title, description):
        embed = discord.Embed(title=title, description=description, color=discord.Color.purple())
        if self.mode == "equip":
            equipped = self.char.equipped_artifact
            # 일반 아티팩트
            if equipped and isinstance(equipped, dict):
                name = equipped.get("name", "이름없음")
                lvl = equipped.get("level", 0)
                if lvl > 0: name += f" (+{lvl})"
                desc = equipped.get("description", "설명없음")
                embed.add_field(name="💍 장착 중", value=f"**{name}**\n{desc}", inline=False)
                _add_gem_detail_fields(embed, equipped, "일반")
            else:
                embed.add_field(name="💍 장착 중", value="없음", inline=False)
            
            # [신규] 각인 아티팩트 정보 표시
            engraved = self.char.equipped_engraved_artifact
            if engraved and isinstance(engraved, dict):
                name = engraved.get("name", "이름없음")
                lvl = engraved.get("level", 0)
                if lvl > 0: name += f" (+{lvl})"
                desc = engraved.get("description", "설명없음")
                embed.add_field(name="🔮 각인", value=f"**{name}**\n{desc}", inline=False)
                _add_gem_detail_fields(embed, engraved, "각인")
            else:
                embed.add_field(name="🔮 각인", value="없음", inline=False)
                
            embed.set_footer(text=f"선택된 캐릭터: {self.char.name}")
        return embed

    def make_enhance_preview_embed(self, idx):
        if idx == "engraved_art":
            art = self.char.equipped_engraved_artifact
            rank = 3 # 각인은 기본적으로 3성 취급
            is_engraved = True
        else:
            art = self.user_data["artifacts"][idx]
            rank = self.get_artifact_rank(art)
            is_engraved = False
        level = art.get("level", 0)
        
        embed = discord.Embed(title="✨ 강화 준비", description=f"**{art['name']}** (+{level} ➔ +{level+1})", color=discord.Color.blue())
        
        stats = art.get("stats", {})
        effective_stats = artifact_effective_stats(art)
        primary_stat = artifact_primary_stat_key(art)
        stat_txt = []
        for k, v in stats.items():
            if v > 0:
                k_name = {"max_hp":"체력","max_mental":"정신력","attack":"공격","defense":"방어","defense_rate":"방어율"}.get(k, k)
                actual = effective_stats.get(k, v)
                unit = "%" if k == "defense_rate" else ""
                primary_marker = " (주 능력)" if k == primary_stat else ""
                stat_txt.append(
                    f"{k_name}{primary_marker}: {v}{unit}"
                    + (f" → **{actual}{unit}**" if actual != v else "")
                )
        embed.add_field(name="📊 현재 스탯", value="\n".join(stat_txt) or "없음", inline=False)
        
        desc = art.get("description", "")
        if desc:
            embed.add_field(name="📜 효과 및 설명", value=desc, inline=False)
        _add_gem_detail_fields(embed, art, "선택")

        max_level = 3 if is_engraved else 5
        
        if level < max_level:
            if is_engraved:
                cost_data = ENGRAVED_UPGRADE_COSTS.get(level, {})
                req_money = cost_data.get("money", 0)
                req_pt = cost_data.get("pt", 0)
                req_items = cost_data.get("items", {})
                cost_txt = f"💰 {req_money:,}원\n⚡ {req_pt:,}pt"
            else:
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
