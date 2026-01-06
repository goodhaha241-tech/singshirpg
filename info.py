# info.py
import discord
from character import Character
from items import ITEM_CATEGORIES

class InventoryPaginationView(discord.ui.View):
    """인벤토리 페이지 넘김을 담당하는 뷰"""
    def __init__(self, author, pages_data):
        super().__init__(timeout=60)
        self.author = author
        self.pages = pages_data 
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = (self.current_page == 0)
        self.next_btn.disabled = (self.current_page == len(self.pages) - 1)
        self.counter_btn.label = f"{self.current_page + 1} / {len(self.pages)}"

    def get_current_embed(self):
        page_data = self.pages[self.current_page]
        embed = discord.Embed(title=f"🎒 {self.author.name}의 가방", color=discord.Color.blue())
        items_text = "\n".join(page_data["items"]) if page_data["items"] else "비어 있음"
        embed.add_field(name=page_data["title"], value=items_text, inline=False)
        return embed

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.primary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

    @discord.ui.button(label="...", style=discord.ButtonStyle.secondary, disabled=True)
    async def counter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_current_embed(), view=self)

async def info_command(ctx, load_data, get_user_data, save_data):
    # [수정] load_data가 None이므로 호출하지 않습니다. (DB 사용으로 변경됨)
    data = None
    # [수정] get_user_data 호출 시 불필요한 data 인자를 제거하고, main.py와 동일하게 display_name을 사용합니다.
    user_stat = await get_user_data(ctx.author.id, ctx.author.display_name)

    embed = discord.Embed(title=f"👤 {ctx.author.name}님의 정보", color=discord.Color.blue())
    embed.add_field(name="💰 보유 자산", value=f"머니: {user_stat.get('money', 0):,}원\n포인트: {user_stat.get('pt', 0):,}pt", inline=False)
    
    # 캐릭터 정보 요약
    chars = user_stat.get("characters", [])
    if chars:
        char_text = ""
        for c in chars:
            char_text += f"• **{c['name']}** (HP: {c['current_hp']}/{c['hp']})\n"
        embed.add_field(name="⚔️ 보유 캐릭터", value=char_text, inline=False)

    view = InfoMainView(ctx.author, user_stat, data, save_data)
    await ctx.send(embed=embed, view=view)

class InfoMainView(discord.ui.View):
    def __init__(self, author, user_data, all_data, save_func):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.all_data = all_data
        self.save_func = save_func

        # 캐릭터 상태 버튼 추가
        status_btn = discord.ui.Button(label="📊 캐릭터 상태", style=discord.ButtonStyle.primary)
        status_btn.callback = self.show_character_status
        self.add_item(status_btn)


    @discord.ui.button(label="🎒 가방 확인", style=discord.ButtonStyle.success)
    async def open_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author: return
        
        inventory = self.user_data.get("inventory", {})
        if not inventory:
            return await interaction.response.send_message("🎒 가방이 비어있습니다.", ephemeral=True)

        categories = {
            "consumable": {"title": "🧪 소비품", "items": []},
            "crafted": {"title": "⚒️ 제작 아이템", "items": []},
            "box": {"title": "📦 상자/열쇠", "items": []},
            "special": {"title": "✨ 특별한 재료", "items": []},
            "material": {"title": "🌿 일반 재료", "items": []}
        }

        for item_name, count in inventory.items():
            if count <= 0: continue
            info = ITEM_CATEGORIES.get(item_name, {"type": "material"})
            itype = info.get("type", "material")

            target = "material"
            if itype == "consumable": target = "consumable"
            elif itype == "crafted": target = "crafted"
            elif itype in ["box", "box_key"]: target = "box"
            elif itype in ["rare_mat", "mythic"]: target = "special"
            
            item_str = f"**{item_name}** x{count}" if target == "special" else f"{item_name} x{count}"
            categories[target]["items"].append(item_str)

        pages_data = []
        for key in ["consumable", "crafted", "box", "special", "material"]:
            if categories[key]["items"]:
                pages_data.append(categories[key])

        if not pages_data:
            await interaction.response.send_message("🎒 가방이 비어있습니다.", ephemeral=True)
        else:
            view = InventoryPaginationView(self.author, pages_data)
            await interaction.response.send_message(embed=view.get_current_embed(), view=view, ephemeral=True)

    async def show_character_status(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        # 캐릭터 상세 정보 뷰로 전환
        view = InfoView(self.author, self.user_data, self.all_data, self.save_func)
        embed = view.create_status_embed()
        await interaction.response.edit_message(embed=embed, view=view)

class InfoView(discord.ui.View):
    """캐릭터 상세 정보 및 상태창 복귀를 위한 뷰"""
    def __init__(self, author, user_data, all_data, save_func, char_index=0):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.all_data = all_data
        self.save_func = save_func
        self.char_index = char_index
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()

        # 캐릭터 페이지네이션 버튼
        char_list = self.user_data.get("characters", [])
        if len(char_list) > 1:
            prev_char_btn = discord.ui.Button(label="◀️ 이전", style=discord.ButtonStyle.secondary, row=0, disabled=(self.char_index == 0))
            prev_char_btn.callback = self.prev_char
            self.add_item(prev_char_btn)

            next_char_btn = discord.ui.Button(label="다음 ▶️", style=discord.ButtonStyle.secondary, row=0, disabled=(self.char_index >= len(char_list) - 1))
            next_char_btn.callback = self.next_char
            self.add_item(next_char_btn)

        # 인벤토리 버튼
        btn_inv = discord.ui.Button(label="🎒 가방", style=discord.ButtonStyle.success, row=1)
        btn_inv.callback = self.open_inventory
        self.add_item(btn_inv)

        # 뒤로가기 버튼
        back_btn = discord.ui.Button(label="⬅️ 정보창으로", style=discord.ButtonStyle.gray, row=1)
        back_btn.callback = self.go_back
        self.add_item(back_btn)

    async def prev_char(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.char_index -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_status_embed(), view=self)

    async def next_char(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        self.char_index += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.create_status_embed(), view=self)

    async def go_back(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        view = InfoMainView(self.author, self.user_data, self.all_data, self.save_func)
        embed = discord.Embed(title=f"👤 {self.author.name}님의 정보", color=discord.Color.blue())
        embed.add_field(name="💰 보유 자산", value=f"머니: {self.user_data.get('money', 0):,}원\n포인트: {self.user_data.get('pt', 0):,}pt", inline=False)
        chars = self.user_data.get("characters", [])
        if chars:
            char_text = "\n".join([f"• **{c['name']}** (HP: {c['current_hp']}/{c['hp']})" for c in chars])
            embed.add_field(name="⚔️ 보유 캐릭터", value=char_text, inline=False)
        await interaction.response.edit_message(embed=embed, view=view)

    async def open_inventory(self, interaction: discord.Interaction):
        if interaction.user != self.author: return
        
        inventory = self.user_data.get("inventory", {})
        if not inventory:
            return await interaction.response.send_message("🎒 가방이 비어있습니다.", ephemeral=True)

        categories = {
            "consumable": {"title": "🧪 소비품", "items": []},
            "crafted": {"title": "⚒️ 제작 아이템", "items": []},
            "box": {"title": "📦 상자/열쇠", "items": []},
            "special": {"title": "✨ 특별한 재료", "items": []},
            "material": {"title": "🌿 일반 재료", "items": []}
        }

        for item_name, count in inventory.items():
            if count <= 0: continue
            info = ITEM_CATEGORIES.get(item_name, {"type": "material"})
            itype = info.get("type", "material")

            target = "material"
            if itype == "consumable": target = "consumable"
            elif itype == "crafted": target = "crafted"
            elif itype in ["box", "box_key"]: target = "box"
            elif itype in ["rare_mat", "mythic"]: target = "special"
            
            item_str = f"**{item_name}** x{count}" if target == "special" else f"{item_name} x{count}"
            categories[target]["items"].append(item_str)

        pages_data = []
        for key in ["consumable", "crafted", "box", "special", "material"]:
            if categories[key]["items"]:
                pages_data.append(categories[key])

        if not pages_data:
            await interaction.response.send_message("🎒 가방이 비어있습니다.", ephemeral=True)
        else:
            view = InventoryPaginationView(self.author, pages_data)
            await interaction.response.send_message(embed=view.get_current_embed(), view=view, ephemeral=True)

    def create_status_embed(self):
        chars = self.user_data.get("characters", [])
        if not chars:
            return discord.Embed(title="캐릭터 없음", description="보유한 캐릭터가 없습니다.", color=discord.Color.red())
        
        if self.char_index >= len(chars): self.char_index = 0
        char_data = chars[self.char_index]
        
        embed = discord.Embed(title=f"📊 {char_data['name']} 상태 정보", color=discord.Color.blue())
        
        # 아티팩트 스탯을 먼저 계산
        art_stats = {"max_hp": 0, "max_mental": 0, "attack": 0, "defense": 0, "defense_rate": 0}
        art = char_data.get("equipped_artifact")
        if art and isinstance(art, dict):
            for key, value in art.get("stats", {}).items():
                if value > 0:
                    art_stats[key] = art_stats.get(key, 0) + value

        # 기본 스탯
        base_hp = char_data.get('hp', 0)
        total_hp = base_hp + art_stats["max_hp"]
        hp_str = f"{char_data.get('current_hp')}/{total_hp} ({base_hp}+{art_stats['max_hp']})" if art_stats["max_hp"] > 0 else f"{char_data.get('current_hp')}/{total_hp}"

        base_mental = char_data.get('max_mental', 90)
        total_mental = base_mental + art_stats["max_mental"]
        mental_str = f"{char_data.get('current_mental')}/{total_mental} ({base_mental}+{art_stats['max_mental']})" if art_stats["max_mental"] > 0 else f"{char_data.get('current_mental')}/{total_mental}"
        
        embed.add_field(name="상태", value=f"❤️ HP: {hp_str}\n🔮 멘탈: {mental_str}", inline=True)
        
        # 능력치
        base_atk = char_data.get('attack', 0)
        total_atk = base_atk + art_stats["attack"]
        atk_str = f"{total_atk} ({base_atk}+{art_stats['attack']})" if art_stats["attack"] > 0 else f"{total_atk}"

        base_dfs = char_data.get('defense', 0)
        total_dfs = base_dfs + art_stats["defense"]
        dfs_str = f"{total_dfs} ({base_dfs}+{art_stats['defense']})" if art_stats["defense"] > 0 else f"{total_dfs}"

        base_dr = char_data.get('defense_rate', 0)
        total_dr = base_dr + art_stats["defense_rate"]
        dr_str = f"{total_dr}% ({base_dr}+{art_stats['defense_rate']})%" if art_stats["defense_rate"] > 0 else f"{total_dr}%"

        ability_value = f"⚔️ 공격력: {atk_str}\n🛡️ 방어력: {dfs_str}\n✨ 피해감소: {dr_str}"
        embed.add_field(name="능력치", value=ability_value, inline=True)
        
        # 장비 정보
        cards = char_data.get("equipped_cards", [])
        card_str = ", ".join(cards) if cards else "없음"
        embed.add_field(name="🎴 장착 카드", value=card_str, inline=False)
        
        art_str = "없음"
        if art:
            art_name = f"{art.get('name')} (+{art.get('level', 0)})"
            art_desc = art.get('description', '설명 없음')
            art_str = f"**{art_name}**\n{art_desc}"
        embed.add_field(name="💍 아티팩트", value=art_str, inline=False)
        
        return embed