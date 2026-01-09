# use_item.py
import discord
import json
import os
from character import Character
from items import ITEM_CATEGORIES, STAT_UP_ITEMS
from data_manager import get_user_data

DATA_FILE = "user_data.json"


class NameChangeModal(discord.ui.Modal, title="캐릭터 이름 변경"):
    new_name = discord.ui.TextInput(label="새로운 이름", placeholder="변경할 이름 (2~10자)", min_length=2, max_length=10)

    def __init__(self, author, user_data, char_index, save_func):
        super().__init__()
        self.author = author
        self.user_data = user_data
        self.char_index = char_index
        self.save_func = save_func

    async def on_submit(self, interaction: discord.Interaction):
        new_name_val = self.new_name.value.strip()
        self.user_data["characters"][self.char_index]["name"] = new_name_val
        
        inv = self.user_data.get("inventory", {})
        if inv.get("이름 변경권", 0) > 0:
            inv["이름 변경권"] -= 1
            if inv["이름 변경권"] <= 0: del inv["이름 변경권"]
        
        await self.save_func(self.author.id, self.user_data)
        await interaction.response.send_message(f"✅ 이름이 **[{new_name_val}]**(으)로 변경되었습니다!", ephemeral=True)


class ItemUseView(discord.ui.View):
    def __init__(self, author, user_data, save_func, char_index=0):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.char_index = char_index # 전달받은 인덱스 사용
        
        self.char_page = 0
        self.item_page = 0
        self.PER_PAGE = 7
        
        # 전달받은 캐릭터 인덱스에 맞는 페이지 계산
        if self.char_index >= self.PER_PAGE:
            self.char_page = self.char_index // self.PER_PAGE

        self.update_components()

    

    def update_components(self):
        self.clear_items()
        self.add_char_select()
        self.add_item_select()
        self.add_pagination_buttons()
        
        # [편의성] 상태창 복귀 버튼
        self.add_item(discord.ui.Button(label="⬅️ 상태창으로", style=discord.ButtonStyle.secondary, row=4, custom_id="back_info"))

    def add_char_select(self):
        chars = self.user_data.get("characters", [])
        if not chars: return

        total_pages = (len(chars) - 1) // self.PER_PAGE + 1
        if self.char_page < 0: self.char_page = 0
        if self.char_page >= total_pages: self.char_page = max(0, total_pages - 1)

        start = self.char_page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_list = chars[start:end]

        options = []
        for i, c in enumerate(current_list):
            real_idx = start + i
            label = c.get("name", f"캐릭터 {real_idx+1}")
            desc = f"HP: {c.get('current_hp')}/{c.get('hp')}"
            is_default = (real_idx == self.char_index)
            options.append(discord.SelectOption(label=label, description=desc, value=str(real_idx), default=is_default))

        select = discord.ui.Select(placeholder=f"대상 선택 ({self.char_page+1}/{total_pages})", options=options, row=0)
        select.callback = self.on_char_select
        self.add_item(select)

    def add_item_select(self):
        inv = self.user_data.get("inventory", {})
        valid_items = []
        
        for item_name, count in inv.items():
            if count <= 0: continue
            
            desc = ""
            is_usable = False
            
            # 능력치 매핑용 딕셔너리
            stat_map = {
                "hp": "최대 체력", "max_hp": "최대 체력", "max_mental": "최대 정신력",
                "attack": "공격력", "defense": "방어력", "defense_rate": "방어율",
                "success_rate": "조사 성공률"
            }

            if item_name in STAT_UP_ITEMS:
                is_usable = True
                info = STAT_UP_ITEMS[item_name]
                s_name = stat_map.get(info.get("stat"), "능력치")
                val = info.get("value", 0)
                if "duration" in info:
                    desc = f"{s_name} +{val} ({info['duration']}회 지속 버프)"
                else:
                    desc = f"{s_name} +{val} (영구, 최대 {info.get('max_stat', 999)})"
            elif item_name in ITEM_CATEGORIES:
                info = ITEM_CATEGORIES[item_name]
                if info.get("type") == "consumable":
                    is_usable = True
                    if info.get("effect") == "hp": desc = f"체력 {info.get('value')} 회복"
                    elif info.get("effect") == "mental": desc = f"정신력 {info.get('value')} 회복"
                    else: desc = "회복 아이템"
                elif item_name == "이름 변경권":
                    is_usable = True
                    desc = "캐릭터 이름 변경"
                elif item_name == "행운의 부적":
                    is_usable = True
                    desc = "조사 성공률 +5% (1회 조사 지속)"

            if is_usable:
                valid_items.append((item_name, count, desc))

        total_pages = (len(valid_items) - 1) // self.PER_PAGE + 1
        if self.item_page < 0: self.item_page = 0
        if self.item_page >= total_pages: self.item_page = max(0, total_pages - 1)

        if not valid_items:
            select = discord.ui.Select(placeholder="사용 가능한 아이템 없음", options=[discord.SelectOption(label="없음", value="none")], row=1, disabled=True)
            self.add_item(select)
            return

        start = self.item_page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_items = valid_items[start:end]

        options = []
        for name, count, desc in current_items:
            options.append(discord.SelectOption(label=f"{name} ({count}개)", description=desc, value=name))

        select = discord.ui.Select(placeholder=f"아이템 선택 ({self.item_page+1}/{total_pages})", options=options, row=1)
        select.callback = self.on_item_select
        self.add_item(select)

    def add_pagination_buttons(self):
        # 캐릭터 페이지 버튼
        chars = self.user_data.get("characters", [])
        char_pages = (len(chars) - 1) // self.PER_PAGE + 1
        
        if char_pages > 1:
            self.add_item(discord.ui.Button(label="👤 이전", style=discord.ButtonStyle.secondary, row=2, custom_id="prev_char"))
            self.add_item(discord.ui.Button(label="👤 다음", style=discord.ButtonStyle.secondary, row=2, custom_id="next_char"))

        # 아이템 페이지 버튼 추가
        inv = self.user_data.get("inventory", {})
        valid_items = []
        for item_name, count in inv.items():
            if count <= 0: continue
            is_usable = False
            if item_name in STAT_UP_ITEMS or item_name == "이름 변경권":
                is_usable = True
            elif item_name in ITEM_CATEGORIES and ITEM_CATEGORIES[item_name].get("type") == "consumable":
                is_usable = True
            if is_usable:
                valid_items.append(item_name)
        
        item_pages = (len(valid_items) - 1) // self.PER_PAGE + 1
        if item_pages > 1:
            self.add_item(discord.ui.Button(label="📦 이전", style=discord.ButtonStyle.secondary, row=3, custom_id="prev_item"))
            self.add_item(discord.ui.Button(label="📦 다음", style=discord.ButtonStyle.secondary, row=3, custom_id="next_item"))

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.author: return False
        cid = interaction.data.get("custom_id")
        
        if cid == "back_info":
            await interaction.response.defer()
            from info import InfoView
            view = InfoView(self.author, self.user_data, self.save_func, self.char_index)
            await interaction.edit_original_response(content=None, embed=view.create_status_embed(), view=view)
        elif cid == "prev_char":
            await interaction.response.defer()
            self.char_page = max(0, self.char_page - 1)
            self.update_components()
            await interaction.edit_original_response(view=self)
        elif cid == "next_char":
            await interaction.response.defer()
            chars = self.user_data.get("characters", [])
            max_p = (len(chars) - 1) // self.PER_PAGE
            self.char_page = min(max_p, self.char_page + 1)
            self.update_components()
            await interaction.edit_original_response(view=self)
        elif cid == "prev_item":
            await interaction.response.defer()
            self.item_page = max(0, self.item_page - 1)
            self.update_components()
            await interaction.edit_original_response(view=self)
        elif cid == "next_item":
            await interaction.response.defer()
            inv = self.user_data.get("inventory", {})
            valid_items = []
            for item_name, count in inv.items():
                if count <= 0: continue
                is_usable = False
                if item_name in STAT_UP_ITEMS or item_name == "이름 변경권":
                    is_usable = True
                elif item_name in ITEM_CATEGORIES and ITEM_CATEGORIES[item_name].get("type") == "consumable":
                    is_usable = True
                if is_usable:
                    valid_items.append(item_name)
            
            max_p = (len(valid_items) - 1) // self.PER_PAGE
            self.item_page = min(max_p, self.item_page + 1)
            self.update_components()
            await interaction.edit_original_response(view=self)
            
        return True

    async def on_char_select(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.char_index = int(interaction.data['values'][0])
        self.update_components()
        
        char = self.user_data["characters"][self.char_index]
        embed = discord.Embed(title=f"👤 {char['name']} 선택됨", description=f"HP: {char.get('current_hp')}/{char.get('hp')}", color=discord.Color.blue())
        
        # [UX 개선] 상세 스탯 표시
        embed = discord.Embed(title=f"👤 {char['name']} 상태", color=discord.Color.blue())
        embed.add_field(name="❤️ 체력", value=f"{char.get('current_hp')}/{char.get('hp')}", inline=True)
        embed.add_field(name="🧠 정신력", value=f"{char.get('current_mental')}/{char.get('max_mental')}", inline=True)
        embed.add_field(name="⚔️ 공격력", value=f"{char.get('attack')}", inline=True)
        embed.add_field(name="🛡️ 방어력", value=f"{char.get('defense')}", inline=True)
        if char.get('defense_rate', 0) > 0:
            embed.add_field(name="🛡️ 방어율", value=f"{char.get('defense_rate')}%", inline=True)
            
        await interaction.edit_original_response(embed=embed, view=self)

    async def on_item_select(self, interaction: discord.Interaction):
        item_name = interaction.data['values'][0]
        if item_name == "이름 변경권":
            await interaction.response.send_modal(NameChangeModal(self.author, self.user_data, self.char_index, self.save_func))
            return

        await interaction.response.defer()
        self.user_data = await get_user_data(self.author.id, self.author.display_name)
        char_data = self.user_data["characters"][self.char_index]
        inv = self.user_data["inventory"]
        
        if inv.get(item_name, 0) <= 0:
            return await interaction.followup.send("❌ 아이템이 부족합니다.", ephemeral=True)

        msg = ""
        used = False
        embed_fields = [] # (name, value) list for result embed
        
        # 아이템 사용 로직
        if item_name in STAT_UP_ITEMS:
            info = STAT_UP_ITEMS[item_name]

            # [신규] 중복 사용 방지 (한번에 하나만)
            if item_name in self.user_data.get("buffs", {}):
                return await interaction.followup.send(f"❌ 이미 **{item_name}** 효과가 적용 중입니다.", ephemeral=True)

            # [수정] 기간제 버프 아이템과 영구 스탯 상승 아이템 로직 분리
            if "duration" in info:
                buffs = self.user_data.setdefault("buffs", {})
                stat = info["stat"]

                buffs[item_name] = {
                    "stat": stat,
                    "value": info["value"],
                    "duration": info["duration"],
                    "target": char_data["name"]
                }
                
                # [신규] 버프 개수 제한 (최대 2개)
                while len(buffs) > 2:
                    oldest_key = next(iter(buffs))
                    del buffs[oldest_key]

                msg = f"✨ **{item_name}** 사용! (일시적 버프)"
                embed_fields.append(("효과 적용", f"**{stat} +{info['value']}**\n({info['duration']}회 행동 지속)"))
                used = True
            elif "max_stat" in info:
                # [수정] 영구 능력치 강화 아이템은 첫 번째 캐릭터(인덱스 0)만 사용 가능 (단, 방어율 아이템은 제외)
                if self.char_index != 0 and info.get("stat") != "defense_rate":
                    return await interaction.followup.send("⚠️ 이 영구 능력치 강화 아이템은 첫 번째 캐릭터(유저 캐릭터)에게만 사용할 수 있습니다.", ephemeral=True)

                stat = info["stat"]
                val = info["value"]
                limit = info.get("max_stat", 999)
                
                key = "hp" if stat == "max_hp" else "max_mental" if stat == "max_mental" else stat
                if stat == "defense_rate": key = "defense_rate"
                
                curr = char_data.get(key, 0)
                if curr >= limit:
                    return await interaction.followup.send(f"⚠️ {stat} 능력치가 이미 한계({limit})에 도달했습니다!", ephemeral=True)
                    
                char_data[key] = min(limit, curr + val)
                if stat == "max_hp": char_data["current_hp"] += val
                if stat == "max_mental": char_data["current_mental"] += val
                
                msg = f"💪 **{item_name}** 사용! {stat} +{val}"
                stat_names = {"hp": "최대 체력", "max_mental": "최대 정신력", "attack": "공격력", "defense": "방어력", "defense_rate": "방어율"}
                s_name = stat_names.get(key, stat)
                msg = f"💪 **{item_name}** 사용!"
                embed_fields.append((f"{s_name} 상승", f"{curr} ➔ **{char_data[key]}** (한계: {limit})"))
                used = True
            
        elif item_name in ITEM_CATEGORIES and ITEM_CATEGORIES[item_name].get("type") == "consumable":
            info = ITEM_CATEGORIES[item_name]
            eff = info.get("effect")
            val = info.get("value", 0)
            
            if eff == "hp":
                old_v = char_data["current_hp"]
                char_data["current_hp"] = min(char_data["hp"], char_data["current_hp"] + val)
                msg = f"🧪 체력 회복! ({char_data['current_hp']}/{char_data['hp']})"
                msg = f"🧪 **{item_name}** 사용!"
                embed_fields.append(("체력 회복", f"{old_v}/{char_data['hp']} ➔ **{char_data['current_hp']}/{char_data['hp']}**"))
            elif eff == "mental":
                old_v = char_data["current_mental"]
                char_data["current_mental"] = min(char_data["max_mental"], char_data["current_mental"] + val)
                msg = f"💊 정신력 회복! ({char_data['current_mental']}/{char_data['max_mental']})"
                msg = f"💊 **{item_name}** 사용!"
                embed_fields.append(("정신력 회복", f"{old_v}/{char_data['max_mental']} ➔ **{char_data['current_mental']}/{char_data['max_mental']}**"))
            used = True

        if used:
            inv[item_name] -= 1
            if inv[item_name] <= 0: del inv[item_name]
            await self.save_func(self.author.id, self.user_data)
            
            self.update_components()
            embed = discord.Embed(title="✅ 사용 완료", description=msg, color=discord.Color.green())
            for name, value in embed_fields:
                embed.add_field(name=name, value=value, inline=False)
            await interaction.edit_original_response(embed=embed, view=self)