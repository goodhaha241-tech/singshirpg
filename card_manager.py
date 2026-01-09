# card_manager.py
import discord
from cards import get_card
from character import Character
from decorators import auto_defer

class CardManageView(discord.ui.View):
    def __init__(self, author, user_data, save_func, char_index=0):
        super().__init__(timeout=60)
        self.author = author
        self.user_data = user_data
        self.save_func = save_func
        self.char_index = char_index
        
        char_list = self.user_data.get("characters", [])
        if char_list and len(char_list) > char_index:
            self.char = Character.from_dict(char_list[char_index])
        else:
            # 안전장치
            from character import DEFAULT_PLAYER_DATA
            self.char = Character.from_dict(DEFAULT_PLAYER_DATA.copy())
        
        self.my_cards = self.user_data.get("cards", ["기본공격", "기본방어", "기본반격"])
        self.page = 0 
        self.PER_PAGE = 7
        self.update_select_menu()

    def update_select_menu(self):
        self.clear_items()
        
        # [수정] 데이터 갱신 시 카드 목록도 동기화
        self.my_cards = self.user_data.get("cards", ["기본공격", "기본방어", "기본반격"])
        
        valid_cards = [c for c in self.my_cards if get_card(c)]
        total_pages = (len(valid_cards) - 1) // self.PER_PAGE + 1
        if total_pages < 1: total_pages = 1
        
        if self.page < 0: self.page = 0
        if self.page >= total_pages: self.page = total_pages - 1
        
        start = self.page * self.PER_PAGE
        end = start + self.PER_PAGE
        current_page_cards = valid_cards[start:end]
        
        options = []
        for card_name in current_page_cards:
            card_obj = get_card(card_name)
            is_equipped = card_name in self.char.equipped_cards
            
            label = f"{card_name} {'(장착중)' if is_equipped else ''}"
            desc = card_obj.description[:95] if card_obj.description else "설명 없음"
            
            options.append(discord.SelectOption(
                label=label, value=card_name, description=desc, 
                emoji="✅" if is_equipped else "🃏"
            ))

        if not options:
            options.append(discord.SelectOption(label="카드 없음", value="none"))

        placeholder = f"카드 선택 ({self.page + 1}/{total_pages})"
        select = discord.ui.Select(placeholder=placeholder, options=options, row=0)
        select.callback = self.select_callback
        self.add_item(select)
        
        if total_pages > 1:
            prev_btn = discord.ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)
            
            next_btn = discord.ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=1, disabled=(self.page == total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

        # [편의성] 상태창 복귀 버튼
        self.add_item(discord.ui.Button(label="⬅️ 상태창으로", style=discord.ButtonStyle.success, row=2, custom_id="back_info"))

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.author: return False
        
        # [신규] 상태창 복귀 처리
        if interaction.data.get("custom_id") == "back_info":
            await interaction.response.defer()
            from info import InfoView
            # [수정] InfoView 생성자 인자 오류 수정 (all_data는 더 이상 사용되지 않음)
            view = InfoView(self.author, self.user_data, self.save_func, self.char_index)
            await interaction.edit_original_response(content=None, embed=view.create_status_embed(), view=view)
            return False # 상호작용 처리 완료
            
        return True # 다른 콜백 실행 허용

    @auto_defer(reload_data=True)
    async def prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        self.update_select_menu()
        await interaction.edit_original_response(view=self)

    @auto_defer(reload_data=True)
    async def next_page(self, interaction: discord.Interaction):
        self.page += 1
        self.update_select_menu()
        await interaction.edit_original_response(view=self)

    @auto_defer(reload_data=True)
    async def select_callback(self, interaction: discord.Interaction):
        # [수정] 최신 데이터로 캐릭터 및 카드 정보 갱신
        char_list = self.user_data.get("characters", [])
        if char_list and len(char_list) > self.char_index:
            self.char = Character.from_dict(char_list[self.char_index])
        self.my_cards = self.user_data.get("cards", [])

        card_name = interaction.data['values'][0]
        if card_name == "none": return

        msg = ""
        if card_name in self.char.equipped_cards:
            self.char.equipped_cards.remove(card_name)
            msg = f"✅ **{card_name}** 해제 완료."
        else:
            if len(self.char.equipped_cards) >= self.char.card_slots:
                return await interaction.followup.send(f"❌ 슬롯 부족! (최대 {self.char.card_slots}장)", ephemeral=True)
            self.char.equipped_cards.append(card_name)
            msg = f"⚔️ **{card_name}** 장착 완료."

        if "characters" in self.user_data:
            self.user_data["characters"][self.char_index] = self.char.to_dict()
        
        await self.save_func(self.author.id, self.user_data)
        
        self.update_select_menu()
        await interaction.edit_original_response(content=msg, embed=self.create_embed(), view=self)

    def create_embed(self):
        embed = discord.Embed(title=f"🃏 {self.char.name}의 카드 설정", color=discord.Color.blue())
        
        if self.char.equipped_cards:
            equipped_list = []
            for c in self.char.equipped_cards:
                obj = get_card(c)
                desc = obj.description if obj else "정보 없음"
                equipped_list.append(f"• **{c}**: {desc}")
            embed.add_field(name="현재 장착 중", value="\n".join(equipped_list), inline=False)
        else:
            embed.description = "장착된 카드가 없습니다."
            
        embed.set_footer(text=f"장착 슬롯: {len(self.char.equipped_cards)} / {self.char.card_slots}")
        return embed