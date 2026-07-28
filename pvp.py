# ripple-artifact-v8.7
# pvp.py
# pve-gem-runtime-v8.2
# cafe-guild-market-v9.1
import discord
import random
import asyncio
from cards import get_card
from character import Character 
from data_manager import mutate_user_data
import battle_engine
from gem_effects import (
    apply_escalation_to_dice,
    apply_ripple_to_dice,
    battle_end_gem_heal,
    process_gem_turn_start,
    revive_gem_effects,
)

# guild-pvp-stability-v7.2
# pvp-private-command-panel-v8.5
ACTIVE_PVP_USERS = set()

class PVPInviteView(discord.ui.View):
    def __init__(self, author, load_func, save_func):
        super().__init__(timeout=180)
        self.author = author
        self.load_func = load_func
        self.save_func = save_func

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("대련을 연 본인만 상대를 선택할 수 있습니다.", ephemeral=True)
        return False

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="⚔️ 대결할 상대를 선택하세요")
    async def select_user(self, interaction: discord.Interaction, select: discord.ui.UserSelect):
        target = select.values[0]

        if target.id == self.author.id:
            return await interaction.response.send_message("자신과는 싸울 수 없습니다.", ephemeral=True)
        if target.bot:
            return await interaction.response.send_message("봇과는 싸울 수 없습니다.", ephemeral=True)

        # [DB 수정] 두 유저의 데이터를 DB에서 로드
        u1_data = await self.load_func(self.author.id, self.author.display_name)
        u2_data = await self.load_func(target.id, target.display_name)
        
        u1_chars = u1_data.get("characters", [])
        u2_chars = u2_data.get("characters", [])

        if not u1_chars: return await interaction.response.send_message(f"❌ 본인의 캐릭터가 없습니다.", ephemeral=True)
        if not u2_chars: return await interaction.response.send_message(f"❌ 상대방의 캐릭터가 없습니다.", ephemeral=True)
        if self.author.id in ACTIVE_PVP_USERS:
            return await interaction.response.send_message("이미 진행 중인 대련이 있습니다.", ephemeral=True)
        if target.id in ACTIVE_PVP_USERS:
            return await interaction.response.send_message("상대방이 이미 다른 대련을 진행 중입니다.", ephemeral=True)

        ACTIVE_PVP_USERS.update((self.author.id, target.id))
        view = PVPBattleView(self.author, target, u1_data, u2_data, self.save_func, self.load_func)
        
        embed = discord.Embed(
            title="⚔️ 1vs1 결투 신청!", 
            description=f"**{self.author.name}**님이 **{target.name}**님에게 대결을 신청했습니다!\n\n아래 버튼을 눌러 출전할 캐릭터를 선택해주세요.", 
            color=discord.Color.red()
        )
        
        try:
            await interaction.response.edit_message(content=f"✅ **{target.name}**님에게 신청 완료!", view=None, embed=None)
            msg = await interaction.channel.send(content=f"{target.mention}님, 결투 신청이 왔습니다!", embed=embed, view=view)
            view.action_message = msg # [수정] UI 분리를 위해 action_message 사용
        except Exception:
            view.release_users()
            raise


class PVPCommandView(discord.ui.View):
    """A private, player-owned command panel for one PvP turn."""

    PER_PAGE = 4

    def __init__(self, battle_view, player_num):
        super().__init__(timeout=180)
        self.battle_view = battle_view
        self.player_num = int(player_num)
        self.user = battle_view.expected_user(self.player_num)
        self.turn = int(battle_view.turn_count)
        self.page = 0
        self.rebuild()

    @property
    def character(self):
        return self.battle_view.p1_char if self.player_num == 1 else self.battle_view.p2_char

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user.id:
            return True
        await interaction.response.send_message("본인의 커맨드 창만 조작할 수 있습니다.", ephemeral=True)
        return False

    def rebuild(self):
        self.clear_items()
        character = self.character
        if character.current_mental <= 0:
            panic = discord.ui.Button(
                label="패닉 · 정신력 회복",
                style=discord.ButtonStyle.secondary,
                row=0,
            )

            async def panic_callback(interaction):
                if self.turn != self.battle_view.turn_count:
                    return await interaction.response.send_message(
                        "이 커맨드 창은 이전 턴의 것입니다.",
                        ephemeral=True,
                    )
                await self.battle_view.receive_action(interaction, self.player_num, None)

            panic.callback = panic_callback
            self.add_item(panic)
            return

        cards = list(getattr(character, "equipped_cards", []) or [])
        if not cards:
            unavailable = discord.ui.Button(
                label="행동 불가 · 정신력 회복",
                style=discord.ButtonStyle.secondary,
                row=0,
            )

            async def unavailable_callback(interaction):
                await self.battle_view.receive_action(interaction, self.player_num, None)

            unavailable.callback = unavailable_callback
            self.add_item(unavailable)
            return

        total_pages = max(1, (len(cards) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        start = self.page * self.PER_PAGE
        for card_name in cards[start:start + self.PER_PAGE]:
            button = discord.ui.Button(label=card_name[:80], style=discord.ButtonStyle.primary, row=0)

            async def choose(interaction, selected=card_name):
                if self.turn != self.battle_view.turn_count:
                    return await interaction.response.send_message(
                        "이 커맨드 창은 이전 턴의 것입니다.",
                        ephemeral=True,
                    )
                card = get_card(selected)
                if card is None:
                    return await interaction.response.send_message("카드 정보를 찾지 못했습니다.", ephemeral=True)
                await self.battle_view.receive_action(interaction, self.player_num, card)

            button.callback = choose
            self.add_item(button)

        if total_pages > 1:
            previous = discord.ui.Button(
                label="이전",
                style=discord.ButtonStyle.secondary,
                row=1,
                disabled=self.page <= 0,
            )
            counter = discord.ui.Button(
                label=f"{self.page + 1}/{total_pages}",
                style=discord.ButtonStyle.secondary,
                row=1,
                disabled=True,
            )
            following = discord.ui.Button(
                label="다음",
                style=discord.ButtonStyle.secondary,
                row=1,
                disabled=self.page >= total_pages - 1,
            )

            async def move(interaction, delta):
                self.page = max(0, min(self.page + delta, total_pages - 1))
                self.rebuild()
                await interaction.response.edit_message(embed=self.get_embed(), view=self)

            async def move_previous(interaction):
                await move(interaction, -1)

            async def move_next(interaction):
                await move(interaction, 1)

            previous.callback = move_previous
            following.callback = move_next
            self.add_item(previous)
            self.add_item(counter)
            self.add_item(following)

    def get_embed(self):
        character = self.character
        cards = list(getattr(character, "equipped_cards", []) or [])
        start = self.page * self.PER_PAGE
        lines = []
        for card_name in cards[start:start + self.PER_PAGE]:
            card = get_card(card_name)
            lines.append(f"**{card_name}**\n{card.description if card else '효과 정보 없음'}")
        if character.current_mental <= 0:
            detail = "정신력이 바닥나 패닉 행동만 선택할 수 있습니다."
        elif not cards:
            detail = "장착한 기술이 없어 정신력 회복 행동만 선택할 수 있습니다."
        else:
            detail = "\n\n".join(lines)
        return discord.Embed(
            title=f"🕹️ {character.name} 전용 커맨드 · {self.turn}턴",
            description=detail,
            color=discord.Color.blue() if self.player_num == 1 else discord.Color.red(),
        )


class PVPBattleView(discord.ui.View):
    def __init__(self, p1_user, p2_user, p1_data, p2_data, save_func, load_func):
        super().__init__(timeout=600)
        self.p1_user = p1_user
        self.p2_user = p2_user
        self.save_func = save_func
        self.load_func = load_func 
        self.p1_data = p1_data
        self.p2_data = p2_data
        
        self.p1_char = None
        self.p2_char = None
        self.p1_char_idx = -1
        self.p2_char_idx = -1
        
        self.turn_count = 1
        self.p1_card = "waiting" 
        self.p2_card = "waiting"
        
        self.p1_revived = False
        self.p2_revived = False
        self.p1_next_accel_stacks = 0
        self.p2_next_accel_stacks = 0
        self.p1_damage_last = 0
        self.p2_damage_last = 0
        
        # [신규] 샤일라 아티팩트 트리거
        self.p1_shayla_trigger = False
        self.p2_shayla_trigger = False
        
        self.processing_turn = False
        self.last_turn_summary = None
        self.started = False
        self.finished = False
        self.state_lock = asyncio.Lock()
        
        # [수정] UI 분리를 위한 메시지 객체
        self.status_message = None # 상단 상태창
        self.action_message = None # 하단 기술 선택창
        self.command_messages = {}
        
        # [신규] 기술 선택 UI 상태 관리
        self.selection_mode = None # None, 'p1', 'p2'
        self.card_page = 0
        
        self.update_setup_buttons()

    def release_users(self):
        ACTIVE_PVP_USERS.discard(self.p1_user.id)
        ACTIVE_PVP_USERS.discard(self.p2_user.id)

    def expected_user(self, player_num):
        return self.p1_user if player_num == 1 else self.p2_user

    def update_setup_buttons(self):
        self.clear_items()
        is_ready1 = (self.p1_char is not None)
        is_ready2 = (self.p2_char is not None)

        lbl1 = "🔵 P1 준비" if not is_ready1 else "🔵 P1 완료"
        style1 = discord.ButtonStyle.secondary if not is_ready1 else discord.ButtonStyle.primary
        b1 = discord.ui.Button(label=lbl1, style=style1, row=0, disabled=is_ready1)
        b1.callback = self.p1_char_select_open
        self.add_item(b1)
        
        lbl2 = "🔴 P2 준비" if not is_ready2 else "🔴 P2 완료"
        style2 = discord.ButtonStyle.secondary if not is_ready2 else discord.ButtonStyle.danger
        b2 = discord.ui.Button(label=lbl2, style=style2, row=0, disabled=is_ready2)
        b2.callback = self.p2_char_select_open
        self.add_item(b2)

        cancel = discord.ui.Button(label="대련 취소·거절", style=discord.ButtonStyle.danger, row=1)
        cancel.callback = self.cancel_match
        self.add_item(cancel)

    async def cancel_match(self, interaction: discord.Interaction):
        if interaction.user.id not in {self.p1_user.id, self.p2_user.id}:
            return await interaction.response.send_message("대련 참가자만 취소할 수 있습니다.", ephemeral=True)
        async with self.state_lock:
            if self.started or self.finished:
                return await interaction.response.send_message("이미 시작되었거나 종료된 대련입니다.", ephemeral=True)
            self.finished = True
        self.release_users()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"🚫 **{interaction.user.display_name}**님이 대련을 취소했습니다.",
            embed=None,
            view=self,
        )
        self.stop()

    async def p1_char_select_open(self, interaction: discord.Interaction):
        if interaction.user != self.p1_user: return await interaction.response.send_message("본인이 아닙니다.", ephemeral=True)
        
        self.p1_data = await self.load_func(self.p1_user.id, self.p1_user.display_name)
        
        view = PVPCharSelectView(self, self.p1_user, self.p1_data, 1)
        await interaction.response.send_message("출전할 캐릭터를 선택하세요.", view=view, ephemeral=True)

    async def p2_char_select_open(self, interaction: discord.Interaction):
        if interaction.user != self.p2_user: return await interaction.response.send_message("본인이 아닙니다.", ephemeral=True)
        
        self.p2_data = await self.load_func(self.p2_user.id, self.p2_user.display_name)
        
        view = PVPCharSelectView(self, self.p2_user, self.p2_data, 2)
        await interaction.response.send_message("출전할 캐릭터를 선택하세요.", view=view, ephemeral=True)

    async def set_character(self, interaction, player_num, idx):
        expected = self.expected_user(player_num)
        if interaction.user.id != expected.id:
            return await interaction.response.send_message("본인의 캐릭터만 선택할 수 있습니다.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        user_data = self.p1_data if player_num == 1 else self.p2_data
        characters = user_data.get("characters", [])
        if not 0 <= idx < len(characters):
            return await interaction.followup.send("선택한 캐릭터를 찾지 못했습니다.", ephemeral=True)
        char_data = characters[idx]
        char_obj = Character.from_dict(char_data)
        if int(getattr(char_obj, "current_hp", 0) or 0) <= 0:
            return await interaction.followup.send("전투 불능인 캐릭터는 출전할 수 없습니다.", ephemeral=True)
        
        if "equipped_engraved_artifact" in char_data:
            char_obj.equipped_engraved_artifact = char_data["equipped_engraved_artifact"]
        
        if hasattr(char_obj, "apply_battle_start_buffs"):
            char_obj.apply_battle_start_buffs()
            char_obj.current_hp = char_obj.max_hp
            char_obj.current_mental = char_obj.max_mental
            
        char_obj.runtime_cooldowns = {}
        if not hasattr(char_obj, "status_effects"): char_obj.status_effects = {"bleed": 0, "paralysis": 0}

        async with self.state_lock:
            if self.started or self.finished:
                return await interaction.followup.send("이미 시작되었거나 종료된 대련입니다.", ephemeral=True)
            if player_num == 1:
                if self.p1_char is not None:
                    return await interaction.followup.send("이미 출전 캐릭터를 선택했습니다.", ephemeral=True)
                self.p1_char = char_obj
                self.p1_char_idx = idx
            else:
                if self.p2_char is not None:
                    return await interaction.followup.send("이미 출전 캐릭터를 선택했습니다.", ephemeral=True)
                self.p2_char = char_obj
                self.p2_char_idx = idx

        await self.check_start(interaction)
        await interaction.followup.send(f"✅ **{char_obj.name}** 출전 준비 완료!", ephemeral=True)

    async def check_start(self, interaction):
        # [수정] 전투 시작 시, 상단/하단 메시지 분리하여 생성/수정
        if self.p1_char and self.p2_char:
            async with self.state_lock:
                if self.started or self.finished:
                    return
                self.started = True
            status_embed = self.make_status_embed("⚔️ **1vs1 대전 시작!**\n기술을 선택하세요.")
            action_embed = discord.Embed(
                title="🕹️ 기술 선택",
                description="각 참가자는 **내 커맨드 열기**에서 자신의 기술을 선택합니다.",
                color=discord.Color.greyple(),
            )

            # 준비 단계의 버튼을 메시지에 다시 붙이기 전에 전투용 버튼으로 교체한다.
            # discord.py는 edit() 시점의 View 상태를 전송하므로, 순서가 뒤집히면
            # 화면에는 계속 '준비 완료' 버튼만 남는다.
            self.selection_mode = None
            self.card_page = 0
            self.update_main_buttons()

            # 기존 메시지가 있으면 수정, 없으면 새로 전송
            if self.action_message:
                # 캐릭터 선택 단계에서 사용하던 메시지를 action_message로 재활용
                self.status_message = await interaction.channel.send(embed=status_embed)
                await self.action_message.edit(content=None, embed=action_embed, view=self)
            else:
                # /pvp 명령어로 바로 시작된 경우 (이 분기는 현재 사용되지 않음)
                self.status_message = await interaction.channel.send(embed=status_embed)
                self.action_message = await interaction.channel.send(embed=action_embed, view=self)
        else:
            # 아직 준비 중인 경우
            self.update_setup_buttons()
            if self.action_message: 
                await self.action_message.edit(view=self)
            else: 
                self.action_message = await interaction.channel.send(content="준비 완료!", view=self)

    def update_main_buttons(self):
        # 공개 화면에는 상대 기술 버튼을 노출하지 않고 개인 커맨드 입구만 둔다.
        self.clear_items()
        command = discord.ui.Button(
            label="🎴 내 커맨드 열기",
            style=discord.ButtonStyle.primary,
            row=0,
            disabled=self.finished,
        )
        command.callback = self.open_command_panel
        self.add_item(command)

        p1_ready = discord.ui.Button(
            label="🔵 P1 선택 완료" if self.p1_card != "waiting" else "🔵 P1 선택 중",
            style=discord.ButtonStyle.success if self.p1_card != "waiting" else discord.ButtonStyle.secondary,
            row=1,
            disabled=True,
        )
        p2_ready = discord.ui.Button(
            label="🔴 P2 선택 완료" if self.p2_card != "waiting" else "🔴 P2 선택 중",
            style=discord.ButtonStyle.success if self.p2_card != "waiting" else discord.ButtonStyle.secondary,
            row=1,
            disabled=True,
        )
        self.add_item(p1_ready)
        self.add_item(p2_ready)

    async def open_command_panel(self, interaction: discord.Interaction):
        if self.finished:
            return await interaction.response.send_message("이미 종료된 대련입니다.", ephemeral=True)
        if interaction.user.id == self.p1_user.id:
            player_num = 1
        elif interaction.user.id == self.p2_user.id:
            player_num = 2
        else:
            return await interaction.response.send_message("대련 참가자만 커맨드를 선택할 수 있습니다.", ephemeral=True)

        current = self.p1_card if player_num == 1 else self.p2_card
        if current != "waiting":
            return await interaction.response.send_message("이미 이번 턴의 행동을 선택했습니다.", ephemeral=True)

        view = PVPCommandView(self, player_num)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)
        try:
            self.command_messages[player_num] = await interaction.original_response()
        except (discord.NotFound, discord.HTTPException):
            pass

    async def refresh_command_panels(self):
        for player_num, message in list(self.command_messages.items()):
            try:
                if self.finished:
                    await message.edit(
                        embed=discord.Embed(
                            title="⚔️ 대련 종료",
                            description="대련이 종료되어 커맨드 입력을 마쳤습니다.",
                            color=discord.Color.dark_grey(),
                        ),
                        view=None,
                    )
                    continue
                view = PVPCommandView(self, player_num)
                await message.edit(embed=view.get_embed(), view=view)
            except (discord.NotFound, discord.HTTPException):
                self.command_messages.pop(player_num, None)

    # [신규] 카드 버튼 추가 헬퍼
    def add_card_buttons(self, player_char, player_num):
        if player_char.current_mental <= 0:
            b = discord.ui.Button(label="패닉", style=discord.ButtonStyle.secondary)
            b.callback = self.make_panic_callback(player_num)
            self.add_item(b)
            return

        cards = list(getattr(player_char, "equipped_cards", []) or [])
        if not cards:
            b = discord.ui.Button(label="행동 불가 · 정신력 회복", style=discord.ButtonStyle.secondary)
            b.callback = self.make_panic_callback(player_num)
            self.add_item(b)
            return
        PER_PAGE = 4
        total_pages = (len(cards) - 1) // PER_PAGE + 1
        
        start = self.card_page * PER_PAGE
        current_page_cards = cards[start:start + PER_PAGE]

        for card_name in current_page_cards:
            btn = discord.ui.Button(label=card_name, style=discord.ButtonStyle.primary)
            btn.callback = self.make_card_callback(card_name, player_num)
            self.add_item(btn)

        if total_pages > 1:
            row = 1
            if self.card_page > 0:
                prev_btn = discord.ui.Button(label="<", style=discord.ButtonStyle.secondary, row=row)
                prev_btn.callback = self.prev_card_page
                self.add_item(prev_btn)
            
            if self.card_page < total_pages - 1:
                next_btn = discord.ui.Button(label=">", style=discord.ButtonStyle.secondary, row=row)
                next_btn.callback = self.next_card_page
                self.add_item(next_btn)

    # [신규] 카드 페이지네이션 및 콜백 생성
    async def prev_card_page(self, interaction: discord.Interaction):
        if self.selection_mode not in {"p1", "p2"}:
            return await interaction.response.send_message("현재 기술을 선택하는 중이 아닙니다.", ephemeral=True)
        player_num = 1 if self.selection_mode == "p1" else 2
        if interaction.user.id != self.expected_user(player_num).id:
            return await interaction.response.send_message("상대방의 기술 목록은 조작할 수 없습니다.", ephemeral=True)
        self.card_page = max(0, self.card_page - 1)
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)

    async def next_card_page(self, interaction: discord.Interaction):
        if self.selection_mode not in {"p1", "p2"}:
            return await interaction.response.send_message("현재 기술을 선택하는 중이 아닙니다.", ephemeral=True)
        player_num = 1 if self.selection_mode == "p1" else 2
        if interaction.user.id != self.expected_user(player_num).id:
            return await interaction.response.send_message("상대방의 기술 목록은 조작할 수 없습니다.", ephemeral=True)
        self.card_page += 1
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)

    def make_card_callback(self, card_name, player_num):
        expected_turn = self.turn_count
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.expected_user(player_num).id:
                return await interaction.response.send_message("상대방의 행동은 선택할 수 없습니다.", ephemeral=True)
            if expected_turn != self.turn_count:
                return await interaction.response.send_message("이 버튼은 이전 턴의 것입니다. 현재 기술을 다시 선택해주세요.", ephemeral=True)
            if self.selection_mode != f"p{player_num}":
                return await interaction.response.send_message("이미 닫힌 기술 선택 화면입니다.", ephemeral=True)
            card = get_card(card_name)
            if card is None:
                return await interaction.response.send_message("카드 정보를 찾지 못했습니다.", ephemeral=True)
            await self.receive_action(interaction, player_num, card)
        return callback

    def make_panic_callback(self, player_num):
        expected_turn = self.turn_count
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.expected_user(player_num).id:
                return await interaction.response.send_message("상대방의 행동은 선택할 수 없습니다.", ephemeral=True)
            if expected_turn != self.turn_count:
                return await interaction.response.send_message("이 버튼은 이전 턴의 것입니다.", ephemeral=True)
            await self.receive_action(interaction, player_num, None)
        return callback
        
    async def back_to_main_selection(self, interaction: discord.Interaction):
        if self.selection_mode not in {"p1", "p2"}:
            return await interaction.response.send_message("이미 기술 선택 화면을 닫았습니다.", ephemeral=True)
        player_num = 1 if self.selection_mode == "p1" else 2
        if interaction.user.id != self.expected_user(player_num).id:
            return await interaction.response.send_message("상대방의 화면은 조작할 수 없습니다.", ephemeral=True)
        self.selection_mode = None
        self.card_page = 0
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)

    # [수정] 기술 선택창을 여는 방식 변경
    async def p1_select_open(self, interaction):
        if interaction.user.id != self.p1_user.id:
            return await interaction.response.send_message("P1만 선택할 수 있습니다.", ephemeral=True)
        self.selection_mode = 'p1'
        self.card_page = 0
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)

    async def p2_select_open(self, interaction):
        if interaction.user.id != self.p2_user.id:
            return await interaction.response.send_message("P2만 선택할 수 있습니다.", ephemeral=True)
        self.selection_mode = 'p2'
        self.card_page = 0
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)
    
    # [수정] ephemeral view 대신 메인 뷰에서 액션 수신
    async def receive_action(self, interaction, player_num, card):
        if interaction.user.id != self.expected_user(player_num).id:
            return await interaction.response.send_message("상대방의 행동은 선택할 수 없습니다.", ephemeral=True)

        should_resolve = False
        async with self.state_lock:
            if self.finished:
                return await interaction.response.send_message("이미 종료된 대련입니다.", ephemeral=True)
            if self.processing_turn:
                return await interaction.response.send_message("⚠️ 현재 턴을 처리 중입니다. 잠시만 기다려주세요.", ephemeral=True)
            current = self.p1_card if player_num == 1 else self.p2_card
            if current != "waiting":
                return await interaction.response.send_message("이미 이번 턴의 행동을 선택했습니다.", ephemeral=True)
            if player_num == 1:
                self.p1_card = card
            else:
                self.p2_card = card
            self.selection_mode = None
            self.card_page = 0
            should_resolve = self.p1_card != "waiting" and self.p2_card != "waiting"
            if should_resolve:
                self.processing_turn = True

        self.update_main_buttons()
        selected_name = card.name if card is not None else "패닉 · 정신력 회복"
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"✅ {self.turn_count}턴 커맨드 확정",
                description=f"**{selected_name}**을 선택했습니다.\n상대의 선택을 기다립니다.",
                color=discord.Color.green(),
            ),
            view=None,
        )
        if self.action_message:
            await self.action_message.edit(
                embed=discord.Embed(
                    title=f"🕹️ 기술 선택 (턴 {self.turn_count})",
                    description="각 참가자는 **내 커맨드 열기**에서 자신의 기술을 선택합니다.",
                    color=discord.Color.greyple(),
                ),
                view=self,
            )

        if should_resolve:
            try:
                await self.resolve_turn(interaction)
            except Exception:
                async with self.state_lock:
                    self.p1_card = "waiting"
                    self.p2_card = "waiting"
                self.update_main_buttons()
                if self.action_message:
                    await self.action_message.edit(
                        embed=discord.Embed(
                            title=f"🕹️ 기술 선택 (턴 {self.turn_count})",
                            description="오류로 선택이 초기화되었습니다. 각자의 커맨드 창에서 다시 선택해주세요.",
                            color=discord.Color.orange(),
                        ),
                        view=self,
                    )
                await self.refresh_command_panels()
                await interaction.followup.send("턴 처리 중 오류가 발생해 행동 선택을 초기화했습니다.", ephemeral=True)
                raise
            finally:
                self.processing_turn = False

    async def _save_latest_character(self, user, character_index, character):
        character_data = character.to_dict()

        def merge(latest):
            characters = latest.setdefault("characters", [])
            if not 0 <= character_index < len(characters):
                raise IndexError(f"대련 캐릭터 슬롯을 찾지 못했습니다: {character_index}")
            characters[character_index] = character_data

        return await mutate_user_data(
            user.id,
            merge,
            user.display_name,
        )

    async def resolve_turn(self, interaction):
        log = f"### ⚔️ 제 {self.turn_count}턴 결과\n"
        
        accel_stacks1 = self.p1_next_accel_stacks; self.p1_next_accel_stacks = 0
        accel_stacks2 = self.p2_next_accel_stacks; self.p2_next_accel_stacks = 0
        if accel_stacks1 > 0:
            multiplier = battle_engine.time_accel_multiplier(accel_stacks1)
            log += f"✨ P1 시간가속 {accel_stacks1}스택(×{multiplier:.2f})\n"
        if accel_stacks2 > 0:
            multiplier = battle_engine.time_accel_multiplier(accel_stacks2)
            log += f"✨ P2 시간가속 {accel_stacks2}스택(×{multiplier:.2f})\n"

        gem_log1 = process_gem_turn_start(
            self.p1_char,
            self.p2_char,
            self.turn_count,
            self.p1_card.name if self.p1_card not in (None, "waiting") else "",
        )
        gem_log2 = process_gem_turn_start(
            self.p2_char,
            self.p1_char,
            self.turn_count,
            self.p2_card.name if self.p2_card not in (None, "waiting") else "",
        )
        if gem_log1:
            log += f"🔵 {gem_log1}\n"
        if gem_log2:
            log += f"🔴 {gem_log2}\n"
        if self.p1_char.current_hp <= 0:
            self.p1_card = None
        if self.p2_char.current_hp <= 0:
            self.p2_card = None

        p1_res = []
        if self.p1_card is None: 
            self.p1_char.current_mental += self.p1_char.max_mental//2
            log += f"😵 **{self.p1_char.name}** 패닉 회복!\n"
        else:
            # [황금] 각인 효과 로그
            eng = getattr(self.p1_char, "equipped_engraved_artifact", None)
            if eng and isinstance(eng, dict) and eng.get("special") == "youngsan_gold" and self.p1_card.name in ["전부매입", "금융치료"]:
                log += f"💰 **[{self.p1_char.name}:황금]** 비용 50% 절감!\n"

            p1_res = self.p1_card.use_card(
                self.p1_char.attack, self.p1_char.defense, self.p1_char.current_mental,
                damage_taken=self.p1_damage_last, character=self.p1_char, user_data=self.p1_data
            )
            p1_res = battle_engine.apply_stat_scaling(p1_res, self.p1_char)
            battle_engine.apply_time_accel_power(p1_res, accel_stacks1)

        p2_res = []
        if self.p2_card is None:
            self.p2_char.current_mental += self.p2_char.max_mental//2
            log += f"😵 **{self.p2_char.name}** 패닉 회복!\n"
        else:
            # [황금] 각인 효과 로그
            eng = getattr(self.p2_char, "equipped_engraved_artifact", None)
            if eng and isinstance(eng, dict) and eng.get("special") == "youngsan_gold" and self.p2_card.name in ["전부매입", "금융치료"]:
                log += f"💰 **[{self.p2_char.name}:황금]** 비용 50% 절감!\n"

            p2_res = self.p2_card.use_card(
                self.p2_char.attack, self.p2_char.defense, self.p2_char.current_mental,
                damage_taken=self.p2_damage_last, character=self.p2_char, user_data=self.p2_data
            )
            p2_res = battle_engine.apply_stat_scaling(p2_res, self.p2_char)
            battle_engine.apply_time_accel_power(p2_res, accel_stacks2)

        c1_name = self.p1_card.name if self.p1_card else "행동 불가"
        c2_name = self.p2_card.name if self.p2_card else "행동 불가"
        self.last_turn_summary = f"이전 턴: 🔵{c1_name} vs 🔴{c2_name}"
        log += f"🔵 **{self.p1_char.name}** (`{c1_name}`) vs 🔴 **{self.p2_char.name}** (`{c2_name}`)\n"
        
        def get_effects(char):
            effs = []
            art = getattr(char, "equipped_artifact", None)
            eng = getattr(char, "equipped_engraved_artifact", None)
            if art: effs.append(art.get("special"))
            if eng: effs.append(eng.get("special"))
            return effs

        effs1 = get_effects(self.p1_char)
        effs2 = get_effects(self.p2_char)

        # [수정] 배틀 엔진을 통해 아티팩트 효과 처리 (샤일라, 카이안 등)
        # P1 Artifacts
        p1_card_name = self.p1_card.name if self.p1_card else ""
        log1, next_trig1 = battle_engine.process_turn_start_artifacts(
            self.p1_char, self.p2_char, p1_res, p2_res, self.turn_count, self.p1_shayla_trigger, p1_card_name
        )
        log += log1
        self.p1_shayla_trigger = next_trig1

        # P2 Artifacts
        p2_card_name = self.p2_card.name if self.p2_card else ""
        log2, next_trig2 = battle_engine.process_turn_start_artifacts(
            self.p2_char, self.p1_char, p2_res, p1_res, self.turn_count, self.p2_shayla_trigger, p2_card_name
        )
        log += log2
        self.p2_shayla_trigger = next_trig2

        for char, results, effects, marker in (
            (self.p1_char, p1_res, effs1, "🔵"),
            (self.p2_char, p2_res, effs2, "🔴"),
        ):
            if "escalation" in effects:
                escalation = apply_escalation_to_dice(char, results)
                if escalation:
                    summary = ", ".join(
                        f"{entry['index'] + 1}번 {entry['rolled']:+d}"
                        + (f"(연쇄 +{entry['chained']})" if entry["chained"] else "")
                        for entry in escalation
                    )
                    log += f"{marker} ⚡ **{char.name}[고조]** {summary}\n"
            if "ripple" in effects:
                ripple = apply_ripple_to_dice(char, results, self.turn_count)
                if ripple:
                    amounts = " → ".join(
                        f"+{entry['amount']}" for entry in ripple["transfers"]
                    )
                    log += f"{marker} 🌊 **{char.name}[파문]** {amounts}"
                    if ripple["hp_heal"] or ripple["mental_heal"]:
                        log += (
                            f" · HP +{ripple['hp_heal']}"
                            f" / 정신 +{ripple['mental_heal']}"
                        )
                    log += "\n"

        # [수정] battle_engine을 사용한 합 진행
        clash_log, dmg1, dmg2 = battle_engine.process_clash_loop(
            self.p1_char, self.p2_char, p1_res, p2_res, effs1, effs2, self.turn_count,
            is_stunned1=(self.p1_card is None), is_stunned2=(self.p2_card is None)
        )
        
        # [시간가속] 적립된 보너스 적용
        b1 = self.p1_char.runtime_cooldowns.pop("time_accel_next_stacks", 0)
        if b1 > 0:
            self.p1_next_accel_stacks += b1
            
        b2 = self.p2_char.runtime_cooldowns.pop("time_accel_next_stacks", 0)
        if b2 > 0:
            self.p2_next_accel_stacks += b2
        
        log += clash_log
        self.p1_damage_last = dmg1
        self.p2_damage_last = dmg2

        if self.p1_char.status_effects.get("bleed", 0) > 0: self.p1_char.status_effects["bleed"] = max(0, self.p1_char.status_effects["bleed"] - 1)
        if self.p2_char.status_effects.get("bleed", 0) > 0: self.p2_char.status_effects["bleed"] = max(0, self.p2_char.status_effects["bleed"] - 1)

        if self.p1_char.current_hp <= 0 and "immortality" in effs1 and not self.p1_revived:
            self.p1_revived = True
            self.p1_char.current_hp = self.p1_char.max_hp
            revive_log = revive_gem_effects(self.p1_char)
            log += "\n👼 P1 부활!" + (f" ({revive_log})" if revive_log else "")
        if self.p2_char.current_hp <= 0 and "immortality" in effs2 and not self.p2_revived:
            self.p2_revived = True
            self.p2_char.current_hp = self.p2_char.max_hp
            revive_log = revive_gem_effects(self.p2_char)
            log += "\n👼 P2 부활!" + (f" ({revive_log})" if revive_log else "")

        if self.p1_char.current_hp <= 0 or self.p2_char.current_hp <= 0:
            if self.p1_char.current_hp <= 0 and self.p2_char.current_hp <= 0:
                res_msg = "\n🤝 무승부!"
            elif self.p1_char.current_hp <= 0:
                res_msg = f"\n🏆 **{self.p2_char.name}** 승리!"
            else:
                res_msg = f"\n🏆 **{self.p1_char.name}** 승리!"
            
            if hasattr(self.p1_char, "remove_battle_buffs"): self.p1_char.remove_battle_buffs()
            if hasattr(self.p2_char, "remove_battle_buffs"): self.p2_char.remove_battle_buffs()
            dawn1 = battle_end_gem_heal(self.p1_char)
            dawn2 = battle_end_gem_heal(self.p2_char)
            if dawn1:
                log += f"\n🌅 P1 여명의 젬: 체력 +{dawn1}"
            if dawn2:
                log += f"\n🌅 P2 여명의 젬: 체력 +{dawn2}"
            
            self.p1_data = await self._save_latest_character(
                self.p1_user,
                self.p1_char_idx,
                self.p1_char,
            )
            self.p2_data = await self._save_latest_character(
                self.p2_user,
                self.p2_char_idx,
                self.p2_char,
            )

            # [수정] 전투 종료 시 메시지 업데이트
            final_status_embed = self.make_status_embed(log + res_msg)
            final_status_embed.color = discord.Color.gold()
            
            if self.status_message:
                try: await self.status_message.edit(embed=final_status_embed)
                except: self.status_message = await interaction.channel.send(embed=final_status_embed)
            
            for child in self.children: child.disabled = True
            
            # 하단 액션창도 정리
            if self.action_message:
                await self.action_message.edit(content="**⚔️ 전투 종료 ⚔️**", embed=None, view=self)
            
            self.finished = True
            await self.refresh_command_panels()
            self.release_users()
            self.stop()
        else:
            self.turn_count += 1
            self.p1_card = "waiting"
            self.p2_card = "waiting"
            
            # [수정] 분리된 UI 업데이트
            await self.update_battle_messages(interaction, log)

    # [신규] 전투 중 상태창/액션창 동시 업데이트
    async def update_battle_messages(self, interaction, turn_log):
        # 1. 상단 상태창 업데이트
        status_embed = self.make_status_embed(turn_log)
        if self.status_message:
            try:
                await self.status_message.edit(embed=status_embed)
            except discord.errors.NotFound:
                self.status_message = await interaction.channel.send(embed=status_embed)
        else:
            self.status_message = await interaction.channel.send(embed=status_embed)

        # 2. 하단 액션창 업데이트
        self.update_main_buttons()
        action_embed = discord.Embed(
            title=f"🕹️ 기술 선택 (턴 {self.turn_count})",
            description="각 참가자는 **내 커맨드 열기**에서 자신의 기술을 선택합니다.",
            color=discord.Color.greyple(),
        )
        
        if self.action_message:
            try:
                await self.action_message.edit(embed=action_embed, view=self)
            except discord.errors.NotFound:
                self.action_message = await interaction.channel.send(embed=action_embed, view=self)
        else:
             self.action_message = await interaction.channel.send(embed=action_embed, view=self)
        await self.refresh_command_panels()

    def get_emoji(self, action_type):
        return battle_engine.get_emoji(action_type)

    def make_status_embed(self, log):
        safe_log = str(log or "")
        if len(safe_log) > 3900:
            safe_log = "…(앞부분 생략)\n" + safe_log[-3880:]
        embed = discord.Embed(title=f"🥊 1vs1 대전 (제 {self.turn_count}턴)", description=safe_log, color=discord.Color.blue())
        def bar(c, m, e1, e2):
            rate = max(0, min(10, int((c/m)*10))) if m > 0 else 0
            return f"{e1 * rate}{e2 * (10-rate)} ({c}/{m})"
        
        def st_str(char):
            s = []
            if char.status_effects.get('bleed',0) > 0: s.append(f"🩸{char.status_effects['bleed']}")
            if char.status_effects.get('paralysis',0) > 0: s.append(f"⚡{char.status_effects['paralysis']}")
            return " ".join(s)

        embed.add_field(name=f"🔵 {self.p1_char.name} {st_str(self.p1_char)}", value=f"HP {bar(self.p1_char.current_hp, self.p1_char.max_hp, '🟦', '⬜')}\nMG {bar(self.p1_char.current_mental, self.p1_char.max_mental, '🔮', '▫️')}", inline=True)
        embed.add_field(name="VS", value="⚡", inline=True)
        embed.add_field(name=f"🔴 {self.p2_char.name} {st_str(self.p2_char)}", value=f"HP {bar(self.p2_char.current_hp, self.p2_char.max_hp, '🟥', '⬜')}\nMG {bar(self.p2_char.current_mental, self.p2_char.max_mental, '🔮', '▫️')}", inline=True)
        
        # 이전 턴 요약 항상 표시
        if self.last_turn_summary:
            embed.set_footer(text=self.last_turn_summary)
        return embed

    async def on_timeout(self):
        if self.finished:
            return
        self.finished = True
        self.release_users()
        for child in self.children:
            child.disabled = True
        if self.action_message:
            try:
                await self.action_message.edit(content="⏱️ 대련이 장시간 입력 없이 종료되었습니다.", embed=None, view=self)
            except (discord.NotFound, discord.HTTPException):
                pass
        await self.refresh_command_panels()

# --- [공용] 캐릭터 선택 뷰 ---
class PVPCharSelectView(discord.ui.View):
    def __init__(self, battle_view, user, user_data, player_num):
        super().__init__(timeout=120)
        self.battle_view, self.user, self.user_data, self.player_num = battle_view, user, user_data, player_num
        self.add_select()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user.id:
            return True
        await interaction.response.send_message("본인의 캐릭터만 선택할 수 있습니다.", ephemeral=True)
        return False
    def add_select(self):

        char_list = self.user_data.get("characters", [])
        options = [discord.SelectOption(label=c.get("name"), description=f"HP:{c.get('hp')}", value=str(i)) for i, c in enumerate(char_list)]
        if not options: options.append(discord.SelectOption(label="없음", value="none"))
        self.select = discord.ui.Select(placeholder=f"캐릭터 1명 선택", options=options)
        self.select.callback = self.callback; self.add_item(self.select)
    async def callback(self, i):
        if self.select.values[0] == "none": return await i.response.send_message("X", ephemeral=True)
        await self.battle_view.set_character(i, self.player_num, int(self.select.values[0]))
