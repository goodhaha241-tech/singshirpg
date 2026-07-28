# ripple-artifact-v8.7
# battle.py
# pve-gem-runtime-v8.2
# owner-isolated-ui-v8.6.4
# cafe-guild-market-v9.1
import discord
import random
import json
import os
import asyncio
from cards import get_card
from story import update_quest_progress 
import battle_engine
from gem_effects import (
    apply_escalation_to_dice,
    apply_ripple_to_dice,
    battle_end_gem_heal,
    process_gem_turn_start,
    revive_gem_effects,
    runtime_cooldowns,
)

DATA_FILE = "user_data.json"

class BattleView(discord.ui.View):
    # [수정] dungeon_item 매개변수 추가
    def __init__(self, author, player, monsters, user_data, save_func, char_index=0, 
                 victory_callback=None, defeat_callback=None, region_name=None, 
                 is_dungeon_run=False, dungeon_item=None, timeout_callback=None):
        super().__init__(timeout=600 if is_dungeon_run else 180)
        self.author = author
        self.player = player
        self.monsters = monsters
        self.killed_monsters = []
        
        self.user_data = user_data
        self.save_func = save_func
        self.char_index = char_index
        self.victory_callback = victory_callback 
        self.defeat_callback = defeat_callback
        self.region_name = region_name
        self.is_dungeon_run = is_dungeon_run
        self.dungeon_item = dungeon_item # 던전 아이템 정보 저장
        self.timeout_callback = timeout_callback
        self._processing = False
        self._finished = False
        self.message = None
        
        self.turn_count = 1
        self.selected_card = None
        self.is_panic = False
        
        self.revived = False # 일반 부활(불멸의 아티팩트 등)
        self.item_revived = False # 던전 아이템 부활 체크
        
        # [신규] 샤일라 '빛나는' 효과 트리거
        self.shayla_light_trigger = False
        
        self.damage_taken_last_turn = 0
        self.next_turn_accel_stacks = 0
        self.card_page = 0
        
        # 상태이상 초기화
        if not hasattr(self.player, "status_effects"):
            self.player.status_effects = {"bleed": 0, "paralysis": 0, "stun": 0}
        
        # [Fix] 전투 시작 시 런타임 쿨타임 초기화 (던전 연속 전투 시 이전 전투 기록 삭제)
        self.player.runtime_cooldowns = {}
        
        for m in self.monsters:
            if not hasattr(m, "status_effects"):
                m.status_effects = {"bleed": 0, "paralysis": 0, "stun": 0}
            runtime_cooldowns(m)

        # 던전 런 체크: 외부에서 버프를 적용했으므로 중복 적용 방지
        if not self.is_dungeon_run and hasattr(self.player, "apply_battle_start_buffs"):
            self.player.apply_battle_start_buffs()

        # 기간제 버프 적용 로직
        buffs = self.user_data.get("buffs", {})
        for b_name, b_info in buffs.items():
            target = b_info.get("target")
            if target != self.player.name: continue
            stat, val = b_info.get("stat"), b_info.get("value", 0)
            if stat == "attack": self.player.attack += val
            elif stat == "defense": self.player.defense += val
            elif stat == "max_hp":
                self.player.max_hp += val
                self.player.current_hp += val
            elif stat == "max_mental":
                self.player.max_mental += val
                self.player.current_mental += val
            elif stat == "defense_rate":
                self.player.defense_rate += val

        # Standalone battles begin with the fully calculated artifact/gem
        # maximums. Dungeon-run battles preserve resources between rooms.
        if not self.is_dungeon_run:
            self.player.current_hp = self.player.max_hp
            self.player.current_mental = self.player.max_mental
        
        self.update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author.id:
            return True
        await interaction.response.send_message("❌ 본인의 전투만 조작할 수 있습니다.", ephemeral=True)
        return False

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
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("본인의 전투만 조작할 수 있습니다.", ephemeral=True)
        await interaction.response.defer()
        self.card_page -= 1
        self.update_buttons()
        await interaction.edit_original_response(view=self)

    async def next_page_callback(self, interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("본인의 전투만 조작할 수 있습니다.", ephemeral=True)
        await interaction.response.defer()
        self.card_page += 1
        self.update_buttons()
        await interaction.edit_original_response(view=self)

    async def panic_callback(self, interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("본인의 전투만 조작할 수 있습니다.", ephemeral=True)
        await interaction.response.defer()
        self.selected_card = None 
        await self.show_target_selection(interaction)

    def make_skill_callback(self, card_name):
        async def callback(interaction):
            if interaction.user.id != self.author.id:
                return await interaction.response.send_message("본인의 전투만 조작할 수 있습니다.", ephemeral=True)
            if self._processing or self._finished:
                return await interaction.response.send_message("⏳ 이전 전투 행동을 처리 중입니다.", ephemeral=True)
            await interaction.response.defer()
            self.selected_card = get_card(card_name)
            await self.show_target_selection(interaction)
        return callback

    async def show_target_selection(self, interaction):
        active_monsters = [m for m in self.monsters if m.current_hp > 0]
        if not active_monsters: return 
        
        # 광역 카드는 별도의 단일 대상 선택 없이 첫 생존 적을 주 대상으로 삼는다.
        # 주 대상과는 정상적으로 합을 진행하고, 나머지 적에게 광역 피해를 전파한다.
        if (
            self.selected_card
            and getattr(self.selected_card, "is_aoe", False)
        ):
            await self.process_battle_round(interaction, active_monsters[0])
        elif len(active_monsters) == 1:
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
                if i.user.id != self.author.id:
                    return await i.response.send_message("본인의 전투만 조작할 수 있습니다.", ephemeral=True)
                if self._processing or self._finished:
                    return await i.response.send_message("⏳ 이전 전투 행동을 처리 중입니다.", ephemeral=True)
                await i.response.defer()
                target_idx = int(select.values[0])
                await self.process_battle_round(i, self.monsters[target_idx])
                
            select.callback = select_callback
            view = discord.ui.View()
            view.add_item(select)
            await interaction.edit_original_response(content=f"⚔️ **[제 {self.turn_count}턴]** 타겟을 선택하세요.", view=view)

    def _apply_player_aoe(self, primary_target, dice_results):
        """Apply the attack dice of an AOE card to every secondary living monster."""
        if not (
            self.selected_card
            and getattr(self.selected_card, "is_aoe", False)
        ):
            return "", []

        secondary_targets = [
            monster
            for monster in self.monsters
            if monster is not primary_target and monster.current_hp > 0
        ]
        if not secondary_targets:
            return "", []

        attack_dice = [
            dict(dice)
            for dice in dice_results
            if dice.get("type") == "attack" and int(dice.get("value", 0)) > 0
        ]
        if not attack_dice:
            return (
                f"\n📢 **[{self.selected_card.name}]** 광역 범위가 펼쳐졌지만 "
                "적에게 적용할 공격 주사위는 없었습니다.\n",
                [],
            )

        attacker_runtime = getattr(self.player, "runtime_cooldowns", {}) or {}
        outgoing_state = attacker_runtime.get("change_state")
        logs = [f"\n📢 **[{self.selected_card.name}] 광역 공격**"]
        defeated = []

        for monster in secondary_targets:
            total_damage = 0
            effect_logs = []
            target_runtime = getattr(monster, "runtime_cooldowns", {}) or {}
            incoming_state = target_runtime.get("change_state")

            for dice in attack_dice:
                damage = int(dice.get("value", 0))
                defense_rate = max(0, min(100, int(getattr(monster, "defense_rate", 0) or 0)))
                if defense_rate:
                    damage = int(damage * (1 - defense_rate / 100))
                damage = max(0, damage - int(getattr(monster, "defense", 0) or 0) // 3)

                if damage > 0:
                    if outgoing_state == "major":
                        damage = max(1, round(damage * 1.25))
                    elif outgoing_state == "minor":
                        damage = max(0, round(damage * 0.75))
                    if incoming_state == "major":
                        damage = max(1, round(damage * 1.25))
                    elif incoming_state == "minor":
                        damage = max(0, round(damage * 0.75))

                total_damage += damage
                effect_log = battle_engine.apply_dice_effect(
                    dice, self.player, monster, True
                )
                if effect_log:
                    effect_logs.append(effect_log.strip())

            monster.current_hp = max(0, monster.current_hp - total_damage)
            suffix = f" · {' '.join(effect_logs)}" if effect_logs else ""
            logs.append(f"• **{monster.name}**에게 {total_damage} 피해{suffix}")
            if monster.current_hp <= 0:
                defeated.append(monster)

        return "\n".join(logs) + "\n", defeated

    async def process_battle_round(self, interaction, target):
        if self._finished:
            return
        if self._processing:
            if interaction.response.is_done():
                await interaction.followup.send("⏳ 이전 전투 행동을 처리 중입니다.", ephemeral=True)
            else:
                await interaction.response.send_message("⏳ 이전 전투 행동을 처리 중입니다.", ephemeral=True)
            return
        self._processing = True
        log = ""
        rec_log = ""
        
        # 아티팩트 효과 수집 (전투 시작 전 확인)
        effects = []
        art = getattr(self.player, "equipped_artifact", None)
        engrave = getattr(self.player, "equipped_engraved_artifact", None)
        if art and isinstance(art, dict): effects.append(art.get("special"))
        if engrave and isinstance(engrave, dict): effects.append(engrave.get("special"))

        gem_turn_log = process_gem_turn_start(
            self.player,
            target,
            self.turn_count,
            self.selected_card.name if self.selected_card else "",
        )
        if gem_turn_log:
            rec_log += gem_turn_log + "\n"
        if target.current_hp <= 0:
            self.killed_monsters.append(target)
            self.monsters.remove(target)
            if not self.monsters:
                return await self.finish_battle(interaction, rec_log, True)
            self.turn_count += 1
            self.update_buttons()
            self._processing = False
            return await interaction.edit_original_response(
                content=None, embed=self.make_embed(rec_log), view=self
            )

        # 턴 보너스
        applied_accel_stacks = self.next_turn_accel_stacks
        if applied_accel_stacks > 0:
            self.next_turn_accel_stacks = 0
            multiplier = battle_engine.time_accel_multiplier(applied_accel_stacks)
            rec_log += (
                f"⏱️ **[시간가속]** {applied_accel_stacks}스택, "
                f"주사위 위력 ×{multiplier:.2f}!\n"
            )

        # 패닉 회복
        if self.is_panic:
            restore = self.player.max_mental // 2
            self.player.current_mental = min(self.player.max_mental, self.player.current_mental + restore)
            self.is_panic = False
            rec_log += f"### 🧠 정신력 회복!\n**{self.player.name}**이(가) 정신을 차렸습니다! (+{restore})\n"

        is_stunned = False 
        is_player_stunned = self.player.status_effects.get("stun", 0) > 0
        p_res = []

        # 플레이어 행동
        if self.player.current_mental <= 0:
            self.is_panic = True
            is_stunned = True
            p_res = [{"type": "none", "value": 0}]
            log = rec_log + f"### 😱 패닉 상태!\n**{self.player.name}** 행동 불가! (피해 2배)\n"
        elif is_player_stunned:
            is_stunned = True
            p_res = [{"type": "none", "value": 0}]
            log = rec_log + f"### 💫 기절 상태!\n**{self.player.name}** 행동 불가!\n"
        else:
            if self.selected_card:
                # [황금] 각인 효과 로그
                eng = getattr(self.player, "equipped_engraved_artifact", None)
                if eng and isinstance(eng, dict) and eng.get("special") == "youngsan_gold" and self.selected_card.name in ["전부매입", "금융치료"]:
                    rec_log += f"💰 **[{self.player.name}:황금]** 비용 50% 절감!\n"

                p_res = self.selected_card.use_card(
                    self.player.attack, self.player.defense, self.player.current_mental,
                    user_data=self.user_data,
                    damage_taken=self.damage_taken_last_turn,
                    character=self.player
                )

                p_res = battle_engine.apply_stat_scaling(p_res, self.player)
                battle_engine.apply_time_accel_power(p_res, applied_accel_stacks)
            else:
                p_res = [{"type": "none", "value": 0}]
            
            c_name = self.selected_card.name if self.selected_card else "행동 불가"
            log = rec_log + f"### ⚔️ 제 {self.turn_count}턴\n👤 **{self.player.name}** : `{c_name}`\n"

        # 몬스터 행동
        is_monster_stunned = target.status_effects.get("stun", 0) > 0
        if is_monster_stunned:
            m_card = None
            m_res = [{"type": "none", "value": 0}]
        else:
            m_card = target.decide_action()
            m_res = m_card.use_card(target.attack, target.defense)
        m_res = battle_engine.apply_stat_scaling(m_res, target)
        
        # [수정] 배틀 엔진을 통해 아티팩트 효과 처리 (샤일라, 카이안 등)
        art_log, next_trigger = battle_engine.process_turn_start_artifacts(
            self.player, target, p_res, m_res, self.turn_count, self.shayla_light_trigger, 
            self.selected_card.name if self.selected_card else ""
        )
        rec_log += art_log
        self.shayla_light_trigger = next_trigger

        if is_monster_stunned:
            log += f"👾 **{target.name}** : 💫 기절함\n"
        else:
            log += f"👾 **{target.name}** : `{m_card.name}`\n"
        
        # [고조된] 매 턴 모든 유효 주사위에 독립적인 -10~+100 보정.
        if "escalation" in effects and not is_stunned:
            escalation = apply_escalation_to_dice(self.player, p_res)
            if escalation:
                summary = ", ".join(
                    f"{entry['index'] + 1}번 {entry['rolled']:+d}"
                    + (f"(연쇄 +{entry['chained']})" if entry["chained"] else "")
                    for entry in escalation
                )
                log += f"⚡ **[고조]** {summary}\n"

        # [파문] 앞 주사위의 최종값 일부가 뒤 주사위로 연쇄 전이된다.
        if "ripple" in effects and not is_stunned:
            ripple = apply_ripple_to_dice(
                self.player, p_res, self.turn_count
            )
            if ripple:
                amounts = " → ".join(
                    f"+{entry['amount']}" for entry in ripple["transfers"]
                )
                log += f"🌊 **[파문]** 전이 {amounts}"
                if ripple["hp_heal"] or ripple["mental_heal"]:
                    log += (
                        f" · 회복 HP +{ripple['hp_heal']}"
                        f" / 정신 +{ripple['mental_heal']}"
                    )
                log += "\n"

        # 합 및 데미지 계산
        clash_log, dmg_p, dmg_m = battle_engine.process_clash_loop(
            self.player, target, p_res, m_res, effects, [], self.turn_count, is_stunned1=is_stunned
        ) # is_stunned2는 battle_engine 내부에서 m_res가 none일 때 자동 처리됨 (혹은 추가 인자로 넘길 수도 있음)
        
        # [시간가속] 적립된 보너스 적용
        accel_stacks = self.player.runtime_cooldowns.pop("time_accel_next_stacks", 0)
        if accel_stacks > 0:
            self.next_turn_accel_stacks += accel_stacks
        
        # [던전 아이템] 피해 무시 (소모성)
        if self.dungeon_item and self.dungeon_item["type"] == "consumable" and self.dungeon_item.get("effect") == "ignore_dmg":
            if dmg_p > 0 and self.dungeon_item.get("remaining", 0) > 0:
                self.dungeon_item["remaining"] -= 1
                dmg_p = 0
                log += f"\n🛡️ **{self.dungeon_item['name']}** 발동! 피해를 무효화했습니다. (남은 횟수: {self.dungeon_item['remaining']})\n"

        log += clash_log
        self.damage_taken_last_turn = dmg_p

        aoe_log, aoe_defeated = self._apply_player_aoe(target, p_res)
        if aoe_log:
            log += aoe_log
        
        # [던전 아이템] 흡혈 (지속성)
        if self.dungeon_item and self.dungeon_item["type"] == "passive" and self.dungeon_item.get("effect") == "lifesteal":
            if dmg_m > 0:
                heal_val = int(dmg_m * (self.dungeon_item["value"] / 100))
                if heal_val > 0:
                    self.player.current_hp = min(self.player.max_hp, self.player.current_hp + heal_val)
                    log += f" 🧛 **{self.dungeon_item['name']}** 효과로 체력 {heal_val} 회복!"

        # [던전 아이템] 고정 피해 (지속성 - 턴당/공격시)
        if self.dungeon_item and self.dungeon_item["type"] == "passive" and self.dungeon_item.get("effect") == "fixed_dmg":
            fix_dmg = self.dungeon_item["value"]
            target.current_hp -= fix_dmg
            log += f" 🗡️ **{self.dungeon_item['name']}** 추가 피해 {fix_dmg}!"

        defeated_monsters = list(aoe_defeated)
        if target.current_hp <= 0:
            defeated_monsters.append(target)
        for defeated in defeated_monsters:
            if defeated in self.monsters:
                self.killed_monsters.append(defeated)
                self.monsters.remove(defeated)

        # [던전 아이템] 턴 종료 체력 회복 (지속성)
        if self.dungeon_item and self.dungeon_item["type"] == "passive" and self.dungeon_item.get("effect") == "hp_regen":
            regen = self.dungeon_item["value"]
            if self.player.current_hp < self.player.max_hp:
                self.player.current_hp = min(self.player.max_hp, self.player.current_hp + regen)
                log += f"\n🌿 **{self.dungeon_item['name']}** 효과로 체력 {regen} 회복."

        # 플레이어 사망 처리 및 부활 로직
        if self.player.current_hp <= 0:
            # 1. 아티팩트 불멸
            if "immortality" in effects and not self.revived:
                self.revived = True
                self.player.current_hp = self.player.max_hp
                log += "\n\n👼 **[불멸의]** 권능으로 부활했습니다! (HP 완전 회복)"
                revive_log = revive_gem_effects(self.player)
                if revive_log:
                    log += f"\n💎 {revive_log}"
            # 2. [던전 아이템] 부활 (소모성)
            elif self.dungeon_item and self.dungeon_item["type"] == "consumable" and self.dungeon_item.get("effect") == "revive":
                if self.dungeon_item.get("remaining", 0) > 0:
                    self.dungeon_item["remaining"] -= 1
                    self.player.current_hp = self.player.max_hp
                    log += f"\n\n✨ **{self.dungeon_item['name']}** 사용! 기적적으로 되살아났습니다. (남은 횟수: {self.dungeon_item['remaining']})"
                else:
                    # 횟수 소진
                    pass

        # 출혈 상태이상 감소
        pb = self.player.status_effects.get("bleed", 0)
        if pb > 0: self.player.status_effects["bleed"] = max(0, pb - 1)
        
        mb = target.status_effects.get("bleed", 0)
        if mb > 0: target.status_effects["bleed"] = max(0, mb - 1)

        # 전투 종료 판정
        if not self.monsters:
            await self.finish_battle(interaction, log, True)
        elif self.player.current_hp <= 0:
            await self.finish_battle(interaction, log, False)
        else:
            self.turn_count += 1
            self.update_buttons()
            self._processing = False
            await interaction.edit_original_response(content=None, embed=self.make_embed(log), view=self)

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
            if char.status_effects.get("stun", 0) > 0: s.append(f"💫{char.status_effects['stun']}")
            return " ".join(s)

        p = self.player
        embed.add_field(name=f"👤 {p.name} {status_str(p)}", value=f"HP {bar(p.current_hp, p.max_hp, '❤️', '🖤')}\nMG {bar(p.current_mental, p.max_mental, '🔮', '▫️')}", inline=False)
        
        m_list = []
        for m in self.monsters:
            m_list.append(f"👾 {m.name} {status_str(m)}: {bar(m.current_hp, m.max_hp, '🔸', '▫️')}")
        embed.add_field(name="적군", value="\n".join(m_list) or "모두 처치됨", inline=False)
        
        # [던전 아이템 표시]
        if self.dungeon_item:
            di = self.dungeon_item
            info = f"**{di['name']}**"
            if di["type"] == "consumable": info += f" (남은 횟수: {di['remaining']})"
            embed.set_footer(text=f"🎒 던전 아이템: {info}")

        return embed

    async def finish_battle(self, interaction, log, is_win):
        if self._finished:
            return
        self._finished = True
        # 전투 종료 시 아티팩트 수치 제거 (던전 포함 모든 전투 공통)
        if hasattr(self.player, "remove_battle_buffs"):
            self.player.remove_battle_buffs()
        dawn_heal = battle_end_gem_heal(self.player)
        if dawn_heal:
            log += f"\n🌅 **[여명의 젬]** 전투 종료 후 체력 +{dawn_heal}"
        
        buffs = self.user_data.setdefault("buffs", {})
        expired_buffs = []
        
        battle_buff_stats = ["attack", "defense", "max_hp", "max_mental", "defense_rate"]
        for b_name, b_info in list(buffs.items()):
            target = b_info.get("target")
            if (target == self.player.name or target is None) and b_info.get("stat") in battle_buff_stats:
                if "duration" in b_info:
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
            
            # 던전 런이 아닐 때만 지역 통계 저장
            if self.region_name and not self.is_dungeon_run:
                if not isinstance(self.user_data.get("myhome"), dict): self.user_data["myhome"] = {}
                self.user_data["myhome"]["total_subjugations"] = self.user_data["myhome"].get("total_subjugations", 0) + 1
                self.user_data["myhome"]["total_turns"] = self.user_data["myhome"].get("total_turns", 0) + 1
                await update_quest_progress(self.author.id, self.user_data, self.save_func, "kill_region", len(self.killed_monsters), self.region_name)
            try:
                from progression_system_v6 import ensure_progression, weekly_progress
                weekly_progress(self.user_data, "battle_wins", 1)
                progression = ensure_progression(self.user_data)
                if "first_battle" not in progression["achievements"]:
                    progression["achievements"].append("first_battle")
                if self.player.current_hp == 1 and "one_hp_victory" not in progression["secret_achievements"]:
                    progression["secret_achievements"].append("one_hp_victory")
            except ImportError:
                pass

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

        if not self.is_dungeon_run:
            char_data = self.user_data["characters"][self.char_index]
            char_data["current_hp"] = self.player.current_hp
            char_data["current_mental"] = self.player.current_mental
            await self.save_func(self.author.id, self.user_data)
        
        final_embed = self.make_embed(log + res_msg)
        final_embed.color = color
        
        await interaction.edit_original_response(content=None, embed=final_embed, view=None)
        
        if is_win and self.victory_callback:
            await self.victory_callback(interaction, {
                "money": total_money, 
                "pt": total_pt, 
                "items": loot,
                "player_hp": self.player.current_hp,
                "player_mental": self.player.current_mental
            })
        elif not is_win and self.defeat_callback:
            await self.defeat_callback(interaction)

    async def on_timeout(self):
        if self._finished:
            return
        self._finished = True
        for child in self.children:
            child.disabled = True
        if self.is_dungeon_run:
            if hasattr(self.player, "remove_battle_buffs"):
                self.player.remove_battle_buffs()
            if self.timeout_callback:
                try:
                    await self.timeout_callback()
                except Exception as error:
                    print(f"Dungeon battle timeout save failed: {error}")
        try:
            message = getattr(self, "message", None)
            if message:
                text = (
                    "⌛ 전투 입력 시간이 만료되었습니다. 던전은 자동 저장되었습니다.\n"
                    "`던전 → 이어하기`에서 같은 전투를 다시 시작할 수 있습니다."
                    if self.is_dungeon_run else
                    "⌛ 전투 입력 시간이 만료되었습니다."
                )
                await message.edit(content=text, view=None)
        except (discord.NotFound, discord.HTTPException):
            pass
