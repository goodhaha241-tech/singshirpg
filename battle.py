# battle.py
import discord
import random
import json
import os
import asyncio
from cards import get_card
from story import update_quest_progress 
import battle_engine

DATA_FILE = "user_data.json"


class BattleView(discord.ui.View):
    def __init__(self, author, player, monsters, user_data, save_func, char_index=0, victory_callback=None, region_name=None):
        super().__init__(timeout=180)
        self.author = author
        self.player = player
        self.monsters = monsters
        self.killed_monsters = []
        
        self.user_data = user_data
        self.save_func = save_func
        self.char_index = char_index
        self.victory_callback = victory_callback 
        self.region_name = region_name
        
        self.turn_count = 1
        self.selected_card = None
        self.is_panic = False
        
        self.revived = False 
        self.damage_taken_last_turn = 0
        self.next_turn_bonus = 0 
        self.card_page = 0
        
        # 상태이상 초기화
        if not hasattr(self.player, "status_effects"):
            self.player.status_effects = {"bleed": 0, "paralysis": 0}
        
        for m in self.monsters:
            if not hasattr(m, "status_effects"):
                m.status_effects = {"bleed": 0, "paralysis": 0}

        # 전투 시작 시 버프 적용
        if hasattr(self.player, "apply_battle_start_buffs"):
            self.player.apply_battle_start_buffs()

        # [신규] 전투 시작 시 기간제 버프 적용
        buffs = self.user_data.get("buffs", {})
        if "attack" in buffs:
            self.player.attack += buffs["attack"].get("value", 0)
        if "defense" in buffs:
            self.player.defense += buffs["defense"].get("value", 0)
        
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        
        if self.is_panic:
            panic_btn = discord.ui.Button(label="😱 패닉 (행동 불가)", style=discord.ButtonStyle.secondary)
            panic_btn.callback = self.panic_callback
            self.add_item(panic_btn)
            return

        cards = self.player.equipped_cards
        PER_PAGE = 4
        total_pages = (len(cards) - 1) // PER_PAGE + 1
        
        if self.card_page < 0: self.card_page = 0
        if self.card_page >= total_pages: self.card_page = max(0, total_pages - 1)
        
        start = self.card_page * PER_PAGE
        end = start + PER_PAGE
        current_cards = cards[start:end]

        for card_name in current_cards:
            btn = discord.ui.Button(label=card_name, style=discord.ButtonStyle.danger)
            btn.callback = self.make_skill_callback(card_name)
            self.add_item(btn)

        if total_pages > 1:
            if self.card_page > 0:
                prev = discord.ui.Button(label="⬅️", style=discord.ButtonStyle.secondary, row=1)
                prev.callback = self.prev_page_callback
                self.add_item(prev)
            
            ind = discord.ui.Button(label=f"{self.card_page + 1}/{total_pages}", style=discord.ButtonStyle.secondary, disabled=True, row=1)
            self.add_item(ind)

            if self.card_page < total_pages - 1:
                nxt = discord.ui.Button(label="➡️", style=discord.ButtonStyle.secondary, row=1)
                nxt.callback = self.next_page_callback
                self.add_item(nxt)

    async def prev_page_callback(self, interaction):
        if interaction.user != self.author: return
        self.card_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def next_page_callback(self, interaction):
        if interaction.user != self.author: return
        self.card_page += 1
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def panic_callback(self, interaction):
        if interaction.user != self.author: return
        self.selected_card = None 
        await self.show_target_selection(interaction)

    def make_skill_callback(self, card_name):
        async def callback(interaction):
            if interaction.user != self.author: return
            self.selected_card = get_card(card_name)
            await self.show_target_selection(interaction)
        return callback

    async def show_target_selection(self, interaction):
        active_monsters = [m for m in self.monsters if m.current_hp > 0]
        if not active_monsters: return 
        
        if len(active_monsters) == 1:
            await self.process_battle_round(interaction, active_monsters[0])
        else:
            options = []
            for idx, m in enumerate(self.monsters):
                if m.current_hp > 0:
                    options.append(discord.SelectOption(
                        label=f"{m.name}", 
                        description=f"HP: {m.current_hp}/{m.max_hp}", 
                        value=str(idx)
                    ))
            
            select = discord.ui.Select(placeholder="🎯 공격 대상을 선택하세요", options=options)
            
            async def select_callback(i):
                if i.user != self.author: return
                target_idx = int(select.values[0])
                await self.process_battle_round(i, self.monsters[target_idx])
                
            select.callback = select_callback
            view = discord.ui.View()
            view.add_item(select)
            await interaction.response.edit_message(content=f"⚔️ **[제 {self.turn_count}턴]** 타겟을 선택하세요.", view=view)

    # apply_stat_scaling 제거 (battle_engine 사용)

    async def process_battle_round(self, interaction, target):
        log = ""
        rec_log = ""
        
        # 턴 보너스
        applied_bonus = self.next_turn_bonus
        if applied_bonus > 0:
            self.next_turn_bonus = 0
            rec_log += f"⏱️ **[시간가속]** 주사위 위력 +{applied_bonus}!\n"

        # 패닉 회복
        if self.is_panic:
            restore = self.player.max_mental // 2
            self.player.current_mental = min(self.player.max_mental, self.player.current_mental + restore)
            self.is_panic = False
            rec_log += f"### 🧠 정신력 회복!\n**{self.player.name}**이(가) 정신을 차렸습니다! (+{restore})\n"

        is_stunned = False 
        p_res = []

        # 플레이어 행동
        if self.player.current_mental <= 0:
            self.is_panic = True
            is_stunned = True
            p_res = [{"type": "none", "value": 0}]
            log = rec_log + f"### 😱 패닉 상태!\n**{self.player.name}** 행동 불가! (피해 2배)\n"
        else:
            if self.selected_card:
                p_res = self.selected_card.use_card(
                    self.player.attack, self.player.defense, self.player.current_mental,
                    user_data=self.user_data,
                    damage_taken=self.damage_taken_last_turn,
                    character=self.player
                )

                p_res = battle_engine.apply_stat_scaling(p_res, self.player)
                if applied_bonus > 0:
                    for d in p_res: 
                        if d["type"] != "none": d["value"] += applied_bonus
            else:
                p_res = [{"type": "none", "value": 0}]
            
            c_name = self.selected_card.name if self.selected_card else "행동 불가"
            log = rec_log + f"### ⚔️ 제 {self.turn_count}턴\n👤 **{self.player.name}** : `{c_name}`\n"

        # 몬스터 행동
        m_card = target.decide_action()
        m_res = m_card.use_card(target.attack, target.defense)
        m_res = battle_engine.apply_stat_scaling(m_res, target)
        log += f"👾 **{target.name}** : `{m_card.name}`\n"

        # 아티팩트 효과 수집
        effects = []
        art = getattr(self.player, "equipped_artifact", None)
        engrave = getattr(self.player, "equipped_engraved_artifact", None)
        if art and isinstance(art, dict): effects.append(art.get("special"))
        if engrave and isinstance(engrave, dict): effects.append(engrave.get("special"))
        
        # [고조된] 효과
        if "escalation" in effects and not is_stunned and len(p_res) > 0:
            last_used = self.player.runtime_cooldowns.get("escalation", -10)
            if self.turn_count - last_used >= 2:
                bonus = random.randint(1, 30)
                p_res[-1]["value"] += bonus
                self.player.runtime_cooldowns["escalation"] = self.turn_count
                log += f"🔥 **[고조된]** 주사위 폭주! (+{bonus})\n"

        # [수정] battle_engine을 사용한 합 진행
        clash_log, dmg_p, dmg_m = battle_engine.process_clash_loop(
            self.player, target, p_res, m_res, effects, [], self.turn_count, is_stunned1=is_stunned
        )
        
        log += clash_log
        self.damage_taken_last_turn = dmg_p
        
        if target.current_hp <= 0:
            self.killed_monsters.append(target)
            self.monsters.remove(target)

        if self.player.current_hp <= 0 and "immortality" in effects and not self.revived:
            self.revived = True
            self.player.current_hp = self.player.max_hp
            log += "\n\n👼 **[불멸의]** 권능으로 부활했습니다! (HP 완전 회복)"

        pb = self.player.status_effects.get("bleed", 0)
        if pb > 0: self.player.status_effects["bleed"] = max(0, pb - 1)
        
        mb = target.status_effects.get("bleed", 0)
        if mb > 0: target.status_effects["bleed"] = max(0, mb - 1)

        if not self.monsters:
            await self.finish_battle(interaction, log, True)
        elif self.player.current_hp <= 0:
            await self.finish_battle(interaction, log, False)
        else:
            self.turn_count += 1
            self.update_buttons()
            await interaction.response.edit_message(content=None, embed=self.make_embed(log), view=self)

    def get_emoji(self, atype):
        return battle_engine.get_emoji(atype)

    def make_embed(self, log):
        embed = discord.Embed(title=f"🥊 전투 결과 (Turn {self.turn_count-1})", description=log, color=discord.Color.red())
        if self.is_panic: embed.color = discord.Color.purple()
        
        def bar(c, m, e1, e2):
            rate = max(0, min(10, int((c/m)*10))) if m > 0 else 0
            return f"{e1*rate}{e2*(10-rate)} ({c}/{m})"
        
        def status_str(char):
            s = []
            if char.status_effects.get("bleed", 0) > 0: s.append(f"🩸{char.status_effects['bleed']}")
            if char.status_effects.get("paralysis", 0) > 0: s.append(f"⚡{char.status_effects['paralysis']}")
            return " ".join(s)

        p = self.player
        embed.add_field(name=f"👤 {p.name} {status_str(p)}", value=f"HP {bar(p.current_hp, p.max_hp, '❤️', '🖤')}\nMG {bar(p.current_mental, p.max_mental, '🔮', '▫️')}", inline=False)
        
        m_list = []
        for m in self.monsters:
            m_list.append(f"👾 {m.name} {status_str(m)}: {bar(m.current_hp, m.max_hp, '🔸', '▫️')}")
        embed.add_field(name="적군", value="\n".join(m_list) or "모두 처치됨", inline=False)
        return embed

    async def finish_battle(self, interaction, log, is_win):
        if hasattr(self.player, "remove_battle_buffs"):
            self.player.remove_battle_buffs()
        
        buffs = self.user_data.setdefault("buffs", {})
        expired_buffs = []
        
        # [수정] 전투 관련 버프만 차감하도록 변경 (조사 버프 등은 유지)
        battle_buff_stats = ["attack", "defense"]
        for b_name, b_info in list(buffs.items()):
            if b_name in battle_buff_stats and "duration" in b_info:
                b_info["duration"] -= 1
                if b_info["duration"] <= 0:
                    expired_buffs.append(b_name)
        
        for b in expired_buffs:
            del buffs[b]
            log += f"\n📉 **{b}** 버프 효과가 사라졌습니다."

        total_money, total_pt = 0, 0
        loot = {}
        
        if is_win:
            res_msg = "\n\n🏆 **승리!**\n"
            color = discord.Color.gold()
            
            for m in self.killed_monsters:
                money = random.randint(m.money_range[0], m.money_range[1])
                pt = random.randint(m.pt_range[0], m.pt_range[1])
                total_money += money
                total_pt += pt
                
                mob_name = m.name.rstrip(" ABCDEFGHIJKLMNOPQRSTUVWXYZ")
                await update_quest_progress(self.author.id, self.user_data, self.save_func, "kill", 1, mob_name)
                
                if m.reward:
                    cnt = getattr(m, "reward_count", 1)
                    loot[m.reward] = loot.get(m.reward, 0) + cnt
            
            if self.region_name:
                if not isinstance(self.user_data.get("myhome"), dict):
                    self.user_data["myhome"] = {}
                self.user_data["myhome"]["total_subjugations"] = self.user_data["myhome"].get("total_subjugations", 0) + 1
                await update_quest_progress(self.author.id, self.user_data, self.save_func, "kill_region", len(self.killed_monsters), self.region_name)

            self.user_data["money"] += total_money
            self.user_data["pt"] += total_pt
            inv = self.user_data.setdefault("inventory", {})
            for k, v in loot.items():
                inv[k] = inv.get(k, 0) + v
            
            res_msg += f"💰 {total_money}원 | ⚡ {total_pt}pt\n📦 {', '.join([f'{k} x{v}' for k,v in loot.items()])}"
        else:
            res_msg = "\n\n☠️ **패배...** (눈앞이 캄캄해집니다.)"
            color = discord.Color.dark_grey()
            self.player.current_hp = 1

        char_data = self.user_data["characters"][self.char_index]
        char_data["current_hp"] = self.player.current_hp
        char_data["current_mental"] = self.player.current_mental
        
        await self.save_func(self.author.id, self.user_data)
        
        final_embed = self.make_embed(log + res_msg)
        final_embed.color = color
        
        await interaction.response.edit_message(content=None, embed=final_embed, view=None)
        
        if is_win and self.victory_callback:
            await self.victory_callback(interaction, {"money": total_money, "pt": total_pt, "items": loot})