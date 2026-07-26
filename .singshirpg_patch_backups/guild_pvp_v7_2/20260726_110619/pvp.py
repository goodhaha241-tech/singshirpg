# pvp.py
import discord
import random
from cards import get_card
from character import Character 
import battle_engine


class PVPInviteView(discord.ui.View):
    def __init__(self, author, load_func, save_func):
        super().__init__(timeout=None)
        self.author = author
        self.load_func = load_func
        self.save_func = save_func

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

        view = PVPBattleView(self.author, target, u1_data, u2_data, self.save_func, self.load_func)
        
        embed = discord.Embed(
            title="⚔️ 1vs1 결투 신청!", 
            description=f"**{self.author.name}**님이 **{target.name}**님에게 대결을 신청했습니다!\n\n아래 버튼을 눌러 출전할 캐릭터를 선택해주세요.", 
            color=discord.Color.red()
        )
        
        await interaction.response.edit_message(content=f"✅ **{target.name}**님에게 신청 완료!", view=None, embed=None)
        msg = await interaction.channel.send(content=f"{target.mention}님, 결투 신청이 왔습니다!", embed=embed, view=view)
        view.action_message = msg # [수정] UI 분리를 위해 action_message 사용

class PVPBattleView(discord.ui.View):
    def __init__(self, p1_user, p2_user, p1_data, p2_data, save_func, load_func):
        super().__init__(timeout=None)
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
        self.p1_next_bonus = 0
        self.p2_next_bonus = 0
        self.p1_damage_last = 0
        self.p2_damage_last = 0
        
        # [신규] 샤일라 아티팩트 트리거
        self.p1_shayla_trigger = False
        self.p2_shayla_trigger = False
        
        self.processing_turn = False
        self.last_turn_summary = None
        
        # [수정] UI 분리를 위한 메시지 객체
        self.status_message = None # 상단 상태창
        self.action_message = None # 하단 기술 선택창
        
        # [신규] 기술 선택 UI 상태 관리
        self.selection_mode = None # None, 'p1', 'p2'
        self.card_page = 0
        
        self.update_setup_buttons()

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
        user_data = self.p1_data if player_num == 1 else self.p2_data
        char_data = user_data["characters"][idx]
        char_obj = Character.from_dict(char_data)
        
        if "equipped_engraved_artifact" in char_data:
            char_obj.equipped_engraved_artifact = char_data["equipped_engraved_artifact"]
        
        if hasattr(char_obj, "apply_battle_start_buffs"):
            char_obj.apply_battle_start_buffs()
            
        char_obj.runtime_cooldowns = {}
        if not hasattr(char_obj, "status_effects"): char_obj.status_effects = {"bleed": 0, "paralysis": 0}

        if player_num == 1:
            self.p1_char = char_obj
            self.p1_char_idx = idx
        else:
            self.p2_char = char_obj
            self.p2_char_idx = idx

        await self.check_start(interaction)

    async def check_start(self, interaction):
        # [수정] 전투 시작 시, 상단/하단 메시지 분리하여 생성/수정
        if self.p1_char and self.p2_char:
            status_embed = self.make_status_embed("⚔️ **1vs1 대전 시작!**\n기술을 선택하세요.")
            action_embed = discord.Embed(title="🕹️ 기술 선택", description="아래 버튼을 눌러 기술을 선택하세요.", color=discord.Color.greyple())

            # 기존 메시지가 있으면 수정, 없으면 새로 전송
            if self.action_message:
                # 캐릭터 선택 단계에서 사용하던 메시지를 action_message로 재활용
                self.status_message = await interaction.channel.send(embed=status_embed)
                await self.action_message.edit(content=None, embed=action_embed, view=self)
            else:
                # /pvp 명령어로 바로 시작된 경우 (이 분기는 현재 사용되지 않음)
                self.status_message = await interaction.channel.send(embed=status_embed)
                self.action_message = await interaction.channel.send(embed=action_embed, view=self)
            
            self.update_main_buttons()
        else:
            # 아직 준비 중인 경우
            self.update_setup_buttons()
            if self.action_message: 
                await self.action_message.edit(view=self)
            else: 
                self.action_message = await interaction.channel.send(content="준비 완료!", view=self)

    def update_main_buttons(self):
        # [수정] 기술 선택 UI 통합
        self.clear_items()
        
        # 1. P1 기술 선택 모드
        if self.selection_mode == 'p1':
            self.add_card_buttons(self.p1_char, 1)
            back_btn = discord.ui.Button(label="⬅️ 뒤로", style=discord.ButtonStyle.gray, row=2)
            back_btn.callback = self.back_to_main_selection
            self.add_item(back_btn)
            return

        # 2. P2 기술 선택 모드
        if self.selection_mode == 'p2':
            self.add_card_buttons(self.p2_char, 2)
            back_btn = discord.ui.Button(label="⬅️ 뒤로", style=discord.ButtonStyle.gray, row=2)
            back_btn.callback = self.back_to_main_selection
            self.add_item(back_btn)
            return

        # 3. 기본 선택 모드
        label1 = "✅ 준비 완료" if self.p1_card != "waiting" else f"🔵 {self.p1_char.name} 선택"
        style1 = discord.ButtonStyle.success if self.p1_card != "waiting" else discord.ButtonStyle.primary
        b1 = discord.ui.Button(label=label1, style=style1, disabled=(self.p1_card != "waiting"), row=0)
        b1.callback = self.p1_select_open
        self.add_item(b1)
        
        label2 = "✅ 준비 완료" if self.p2_card != "waiting" else f"🔴 {self.p2_char.name} 선택"
        style2 = discord.ButtonStyle.success if self.p2_card != "waiting" else discord.ButtonStyle.danger
        b2 = discord.ui.Button(label=label2, style=style2, disabled=(self.p2_card != "waiting"), row=0)
        b2.callback = self.p2_select_open
        self.add_item(b2)

    # [신규] 카드 버튼 추가 헬퍼
    def add_card_buttons(self, player_char, player_num):
        if player_char.current_mental <= 0:
            b = discord.ui.Button(label="패닉", style=discord.ButtonStyle.secondary)
            b.callback = self.make_panic_callback(player_num)
            self.add_item(b)
            return

        cards = player_char.equipped_cards
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
        self.card_page = max(0, self.card_page - 1)
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)

    async def next_card_page(self, interaction: discord.Interaction):
        self.card_page += 1
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)

    def make_card_callback(self, card_name, player_num):
        async def callback(interaction: discord.Interaction):
            card = get_card(card_name)
            await self.receive_action(interaction, player_num, card)
        return callback

    def make_panic_callback(self, player_num):
        async def callback(interaction: discord.Interaction):
            await self.receive_action(interaction, player_num, None)
        return callback
        
    async def back_to_main_selection(self, interaction: discord.Interaction):
        self.selection_mode = None
        self.card_page = 0
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)

    # [수정] 기술 선택창을 여는 방식 변경
    async def p1_select_open(self, interaction):
        if interaction.user != self.p1_user: return
        self.selection_mode = 'p1'
        self.card_page = 0
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)

    async def p2_select_open(self, interaction):
        if interaction.user != self.p2_user: return
        self.selection_mode = 'p2'
        self.card_page = 0
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)
    
    # [수정] ephemeral view 대신 메인 뷰에서 액션 수신
    async def receive_action(self, interaction, player_num, card):
        if self.processing_turn:
            return await interaction.response.send_message("⚠️ 현재 턴을 처리 중입니다. 잠시만 기다려주세요.", ephemeral=True)

        if player_num == 1: self.p1_card = card
        else: self.p2_card = card
        
        # 기술 선택 모드에서 메인 선택 모드로 복귀
        self.selection_mode = None
        self.card_page = 0
        
        # 뷰를 먼저 업데이트해서 "준비 완료" 상태를 보여줌
        self.update_main_buttons()
        await interaction.response.edit_message(view=self)
        
        # 양쪽 모두 선택 완료 시 턴 진행
        if self.p1_card != "waiting" and self.p2_card != "waiting":
            self.processing_turn = True
            try:
                await self.resolve_turn(interaction)
            finally:
                self.processing_turn = False

    async def resolve_turn(self, interaction):
        log = f"### ⚔️ 제 {self.turn_count}턴 결과\n"
        
        bonus1 = self.p1_next_bonus; self.p1_next_bonus = 0
        bonus2 = self.p2_next_bonus; self.p2_next_bonus = 0
        if bonus1 > 0: log += f"✨ P1 시간가속(+{bonus1})\n"
        if bonus2 > 0: log += f"✨ P2 시간가속(+{bonus2})\n"

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
            if bonus1 > 0:
                for d in p1_res: 
                    if d["type"] != "none": d["value"] += bonus1

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
            if bonus2 > 0:
                for d in p2_res:
                    if d["type"] != "none": d["value"] += bonus2

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

        if "escalation" in effs1 and p1_res:
            last = self.p1_char.runtime_cooldowns.get("escalation", -10)
            if self.turn_count - last >= 2:
                p1_res[-1]["value"] += random.randint(1, 30)
                self.p1_char.runtime_cooldowns["escalation"] = self.turn_count
        if "escalation" in effs2 and p2_res:
            last = self.p2_char.runtime_cooldowns.get("escalation", -10)
            if self.turn_count - last >= 2:
                p2_res[-1]["value"] += random.randint(1, 30)
                self.p2_char.runtime_cooldowns["escalation"] = self.turn_count

        # [수정] battle_engine을 사용한 합 진행
        clash_log, dmg1, dmg2 = battle_engine.process_clash_loop(
            self.p1_char, self.p2_char, p1_res, p2_res, effs1, effs2, self.turn_count,
            is_stunned1=(self.p1_card is None), is_stunned2=(self.p2_card is None)
        )
        
        # [시간가속] 적립된 보너스 적용
        b1 = self.p1_char.runtime_cooldowns.get("time_accel_bonus", 0)
        if b1 > 0:
            self.p1_next_bonus += b1
            self.p1_char.runtime_cooldowns["time_accel_bonus"] = 0
            
        b2 = self.p2_char.runtime_cooldowns.get("time_accel_bonus", 0)
        if b2 > 0:
            self.p2_next_bonus += b2
            self.p2_char.runtime_cooldowns["time_accel_bonus"] = 0
        
        log += clash_log
        self.p1_damage_last = dmg1
        self.p2_damage_last = dmg2

        if self.p1_char.status_effects.get("bleed", 0) > 0: self.p1_char.status_effects["bleed"] = max(0, self.p1_char.status_effects["bleed"] - 1)
        if self.p2_char.status_effects.get("bleed", 0) > 0: self.p2_char.status_effects["bleed"] = max(0, self.p2_char.status_effects["bleed"] - 1)

        if self.p1_char.current_hp <= 0 and "immortality" in effs1 and not self.p1_revived:
            self.p1_revived = True; self.p1_char.current_hp = self.p1_char.max_hp; log += "\n👼 P1 부활!"
        if self.p2_char.current_hp <= 0 and "immortality" in effs2 and not self.p2_revived:
            self.p2_revived = True; self.p2_char.current_hp = self.p2_char.max_hp; log += "\n👼 P2 부활!"

        if self.p1_char.current_hp <= 0 or self.p2_char.current_hp <= 0:
            res_msg = "\n🏆 전투 종료!"
            if self.p1_char.current_hp <= 0: res_msg = f"\n🏆 **{self.p2_char.name}** 승리!"
            if self.p2_char.current_hp <= 0: res_msg = f"\n🏆 **{self.p1_char.name}** 승리!"
            
            if hasattr(self.p1_char, "remove_battle_buffs"): self.p1_char.remove_battle_buffs()
            if hasattr(self.p2_char, "remove_battle_buffs"): self.p2_char.remove_battle_buffs()
            
            self.p1_data["characters"][self.p1_char_idx] = self.p1_char.to_dict()
            self.p2_data["characters"][self.p2_char_idx] = self.p2_char.to_dict()

            await self.save_func(self.p1_user.id, self.p1_data)
            await self.save_func(self.p2_user.id, self.p2_data)

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
        action_embed = discord.Embed(title=f"🕹️ 기술 선택 (턴 {self.turn_count})", description="아래 버튼을 눌러 기술을 선택하세요.", color=discord.Color.greyple())
        
        if self.action_message:
            try:
                await self.action_message.edit(embed=action_embed, view=self)
            except discord.errors.NotFound:
                self.action_message = await interaction.channel.send(embed=action_embed, view=self)
        else:
             self.action_message = await interaction.channel.send(embed=action_embed, view=self)

    def get_emoji(self, action_type):
        return battle_engine.get_emoji(action_type)

    def make_status_embed(self, log):
        embed = discord.Embed(title=f"🥊 1vs1 대전 (제 {self.turn_count}턴)", description=log, color=discord.Color.blue())
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

# --- [공용] 캐릭터 선택 뷰 ---
class PVPCharSelectView(discord.ui.View):
    def __init__(self, battle_view, user, user_data, player_num):
        super().__init__(timeout=None)
        self.battle_view, self.user, self.user_data, self.player_num = battle_view, user, user_data, player_num
        self.add_select()
    def add_select(self):

        char_list = self.user_data.get("characters", [])
        options = [discord.SelectOption(label=c.get("name"), description=f"HP:{c.get('hp')}", value=str(i)) for i, c in enumerate(char_list)]
        if not options: options.append(discord.SelectOption(label="없음", value="none"))
        self.select = discord.ui.Select(placeholder=f"캐릭터 1명 선택", options=options)
        self.select.callback = self.callback; self.add_item(self.select)
    async def callback(self, i):
        if self.select.values[0] == "none": return await i.response.send_message("X", ephemeral=True)
        await self.battle_view.set_character(i, self.player_num, int(self.select.values[0]))