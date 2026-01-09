# pvp.py
import discord
import random
from cards import get_card
from character import Character 
import battle_engine


class PVPInviteView(discord.ui.View):
    def __init__(self, author, load_func, save_func):
        super().__init__(timeout=60)
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
        view.message = msg

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
        
        self.message = None      
        self.log_message = None  
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
        if self.p1_char and self.p2_char:
            self.update_main_buttons()
            start_embed = discord.Embed(title="📜 전투 개시", description="전투 준비 완료!", color=discord.Color.light_grey())
            if not self.log_message:
                self.log_message = await interaction.channel.send(embed=start_embed)
            
            embed = self.make_embed(f"⚔️ **1vs1 대전 시작!**\n기술을 선택하세요.")
            if self.message: await self.message.edit(embed=embed, view=self)
            else: self.message = await interaction.channel.send(embed=embed, view=self)
        else:
            self.update_setup_buttons()
            if self.message: await self.message.edit(view=self)
            else: await interaction.channel.send(content="준비 완료!", view=self)

    def update_main_buttons(self):
        self.clear_items()
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

    async def p1_select_open(self, interaction):
        if interaction.user != self.p1_user: return
        view = PVPSelectView(self.p1_char, self, 1) 
        await interaction.response.send_message("기술 선택", view=view, ephemeral=True)

    async def p2_select_open(self, interaction):
        if interaction.user != self.p2_user: return
        view = PVPSelectView(self.p2_char, self, 2)
        await interaction.response.send_message("기술 선택", view=view, ephemeral=True)
    
    async def receive_action(self, interaction, player_num, card):
        if player_num == 1: self.p1_card = card
        else: self.p2_card = card
        await interaction.response.edit_message(content="✅ 선택 완료!", view=None)
        
        if self.p1_card != "waiting" and self.p2_card != "waiting":
            await self.resolve_turn(interaction)
        else:
            self.update_main_buttons()
            embed = self.make_embed("상대방 기다리는 중...")
            if self.message: await self.message.edit(embed=embed, view=self)

    # apply_stat_scaling 제거 (battle_engine 사용)

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

        log += f"🔵 **{self.p1_char.name}** vs 🔴 **{self.p2_char.name}**\n"
        
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

            embed = self.make_embed(log + res_msg)
            embed.color = discord.Color.gold()
            
            if self.log_message:
                try: await self.log_message.edit(embed=embed)
                except: self.log_message = await interaction.channel.send(embed=embed)
            
            for child in self.children: child.disabled = True
            await self.message.edit(view=self)
            self.stop()
        else:
            self.turn_count += 1
            self.p1_card = "waiting"
            self.p2_card = "waiting"
            self.update_main_buttons()
            
            res_embed = self.make_embed(log)
            if self.log_message:
                try: await self.log_message.edit(embed=res_embed)
                except: self.log_message = await interaction.channel.send(embed=res_embed)
                
            next_embed = self.make_embed("다음 행동을 선택하세요.")
            if self.message:
                try: await self.message.edit(embed=next_embed, view=self)
                except: self.message = await interaction.channel.send(embed=next_embed, view=self)

    def get_emoji(self, action_type):
        return battle_engine.get_emoji(action_type)

    def make_embed(self, log):
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
        return embed

# --- [공용] 선택 뷰들 ---
class PVPCharSelectView(discord.ui.View):
    def __init__(self, battle_view, user, user_data, player_num):
        super().__init__(timeout=60)
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

class PVPSelectView(discord.ui.View):
    def __init__(self, player_obj, battle_view, player_num, char_idx_in_team=0):
        super().__init__(timeout=60)
        self.player_obj, self.battle_view, self.player_num, self.char_idx_in_team = player_obj, battle_view, player_num, char_idx_in_team
        self.page = 0; self.update_buttons()
    def update_buttons(self):
        self.clear_items()
        if self.player_obj.current_mental <= 0:
            b = discord.ui.Button(label="패닉", style=discord.ButtonStyle.secondary); b.callback = self.panic_callback; self.add_item(b); return
        cards = self.player_obj.equipped_cards; PER = 4; total = (len(cards)-1)//PER + 1
        start = self.page * PER; cur = cards[start:start+PER]
        for c in cur:
            b = discord.ui.Button(label=c, style=discord.ButtonStyle.primary); b.callback = self.make_callback(c); self.add_item(b)
        if total > 1:
            if self.page > 0: b=discord.ui.Button(label="<", style=discord.ButtonStyle.secondary); b.callback=self.prev_cb; self.add_item(b)
            if self.page < total-1: b=discord.ui.Button(label=">", style=discord.ButtonStyle.secondary); b.callback=self.next_cb; self.add_item(b)
    def make_callback(self, c_name):
        async def cb(i):
            sc = get_card(c_name)
            await self.battle_view.receive_action(i, self.player_num, sc)
        return cb
    async def prev_cb(self, i): self.page=max(0,self.page-1); self.update_buttons(); await i.response.edit_message(view=self)
    async def next_cb(self, i): self.page+=1; self.update_buttons(); await i.response.edit_message(view=self)
    async def panic_callback(self, i):
        await self.battle_view.receive_action(i, self.player_num, None)