# battle_engine.py
import random

def get_emoji(action_type):
    return {"attack": "⚔️", "defense": "🛡️", "counter": "⚡", "heal": "💚", "mental_heal": "🔮", "none": "💨"}.get(action_type, "🎲")

def apply_stat_scaling(dice_results, char):
    """캐릭터 스탯에 따라 주사위 값을 보정합니다."""
    for dice in dice_results:
        d_type = dice.get("type")
        val = dice.get("value", 0)
        bonus = 0
        
        if d_type == "attack":
            bonus = int(char.attack * 0.5)
        elif d_type == "defense":
            if val > 1: 
                bonus = int(char.defense * 0.5)
        elif d_type == "counter":
            bonus = int((char.attack * 0.25) + (char.defense * 0.25))
        elif d_type in ["heal", "mental_heal"]:
            bonus = int(char.defense * 0.2)

        dice["value"] = val + bonus
    return dice_results

def process_clash_loop(char1, char2, res1, res2, effs1, effs2, turn_count, is_stunned1=False, is_stunned2=False):
    """
    두 캐릭터(char1, char2)의 주사위 결과(res1, res2)를 비교하여 합을 진행합니다.
    반환값: (전투 로그 문자열, char1이 받은 피해, char2가 받은 피해)
    """
    log = ""
    damage_taken1 = 0
    damage_taken2 = 0

    # [수정] 이펙트 리스트가 비어있을 경우 캐릭터 객체에서 직접 추출 시도 (BattleView 누락 대비)
    if not effs1 and char1:
        effs1 = []
        art = getattr(char1, "equipped_artifact", None)
        if isinstance(art, dict) and art.get("special"): 
            effs1.append(art.get("special"))
        eng = getattr(char1, "equipped_engraved_artifact", None)
        if isinstance(eng, dict) and eng.get("special"): 
            effs1.append(eng.get("special"))

    if not effs2 and char2:
        effs2 = []
        art = getattr(char2, "equipped_artifact", None)
        if isinstance(art, dict) and art.get("special"): 
            effs2.append(art.get("special"))
        eng = getattr(char2, "equipped_engraved_artifact", None)
        if isinstance(eng, dict) and eng.get("special"): 
            effs2.append(eng.get("special"))
    
    max_len = max(len(res1), len(res2))
    
    for i in range(max_len):
        d1 = res1[i] if i < len(res1) else {"type": "none", "value": 0}
        d2 = res2[i] if i < len(res2) else {"type": "none", "value": 0}
        
        # --- [마비 효과 적용] ---
        p1_para = char1.status_effects.get("paralysis", 0)
        p2_para = char2.status_effects.get("paralysis", 0)

        if d1["type"] != "none" and p1_para > 0:
            d1["value"] = max(0, d1["value"] - p1_para * 2)
        if d2["type"] != "none" and p2_para > 0:
            d2["value"] = max(0, d2["value"] - p2_para * 2)

        # [마비 관련 특수 효과: 공격력 증가]
        if d1.get("effect") and "atk_boost_para" in d1["effect"] and p2_para > 0:
            try: d1["value"] += int(d1["effect"].split("_")[-1]) * p2_para
            except: pass
        if d2.get("effect") and "atk_boost_para" in d2["effect"] and p1_para > 0:
            try: d2["value"] += int(d2["effect"].split("_")[-1]) * p1_para
            except: pass

        # [잠금]
        if d1.get("effect") == "lock_others":
            for j in range(i+1, len(res2)): res2[j] = {"type": "none", "value": 0}
            log += f"🔒 **{char1.name}**의 잠금! 적의 후속 행동 봉인!\n"
        if d2.get("effect") == "lock_others":
            for j in range(i+1, len(res1)): res1[j] = {"type": "none", "value": 0}
            log += f"🔒 **{char2.name}**의 잠금! 적의 후속 행동 봉인!\n"

        # [출혈 시너지]
        if d1.get("effect") == "bleed_synergy": d1["value"] += char2.status_effects.get("bleed", 0)
        if d2.get("effect") == "bleed_synergy": d2["value"] += char1.status_effects.get("bleed", 0)

        t1, v1 = d1["type"], d1["value"]
        t2, v2 = d2["type"], d2["value"]
        
        clash_log = f"\n**[{i+1}합]** "
        
        # [아티팩트 효과]
        if "reuse_last_dice" in effs1 and not is_stunned1 and t1 == "none" and t2 != "none" and i > 0:
            ld = res1[i-1]; t1, v1 = ld["type"], ld["value"]
            clash_log += f"✨ **{char1.name}[꼼꼼한]** 재사용! "
        
        if "reuse_last_dice" in effs2 and not is_stunned2 and t2 == "none" and t1 != "none" and i > 0:
            ld = res2[i-1]; t2, v2 = ld["type"], ld["value"]
            clash_log += f"✨ **{char2.name}[꼼꼼한]** 재사용! "

        if "fierce_attack" in effs1 and t1 == "attack":
            last = char1.runtime_cooldowns.get("fierce_attack", -10)
            if turn_count - last >= 2:
                v1 += char1.attack
                char1.runtime_cooldowns["fierce_attack"] = turn_count
                clash_log += f"🔥 **{char1.name}[맹렬한]** "

        if "fierce_attack" in effs2 and t2 == "attack":
            last = char2.runtime_cooldowns.get("fierce_attack", -10)
            if turn_count - last >= 2:
                v2 += char2.attack
                char2.runtime_cooldowns["fierce_attack"] = turn_count
                clash_log += f"🔥 **{char2.name}[맹렬한]** "

        if "sturdy_defense" in effs1 and t1 == "defense":
            last = char1.runtime_cooldowns.get("sturdy_defense", -10)
            if turn_count - last >= 2:
                heal = (v1 * 2) // 3
                char1.current_hp = min(char1.max_hp, char1.current_hp + heal)
                char1.runtime_cooldowns["sturdy_defense"] = turn_count
                clash_log += f"🛡️ **{char1.name}[견고한]**(+{heal}) "

        if "sturdy_defense" in effs2 and t2 == "defense":
            last = char2.runtime_cooldowns.get("sturdy_defense", -10)
            if turn_count - last >= 2:
                heal = (v2 * 2) // 3
                char2.current_hp = min(char2.max_hp, char2.current_hp + heal)
                char2.runtime_cooldowns["sturdy_defense"] = turn_count
                clash_log += f"🛡️ **{char2.name}[견고한]**(+{heal}) "

        clash_log += f"{get_emoji(t1)}{v1} vs {get_emoji(t2)}{v2}"
        
        dmg1, dmg2 = 0, 0 # char1이 받는 피해, char2가 받는 피해
        mental_dmg1, mental_dmg2 = 0, 0
        win1, win2 = False, False

        # === 승패 판정 ===
        # char1 공격
        if t1 == "attack":
            if t2 == "attack": dmg2 = v1
            elif t2 == "defense": dmg2 = max(0, v1 - v2)
            elif t2 == "counter": 
                if v1 >= v2: dmg2 = v1; win1 = True
            elif t2 in ["heal", "mental_heal", "none"]: dmg2 = v1; win1 = True
        elif t1 == "counter":
            if t2 == "attack" and v1 > v2: dmg2 = v1; win1 = True
        
        # char2 공격
        if t2 == "attack":
            if t1 == "attack": dmg1 = v2
            elif t1 == "defense": dmg1 = max(0, v2 - v1)
            elif t1 == "counter":
                if v2 >= v1: dmg1 = v2; win2 = True
            elif t1 in ["heal", "mental_heal", "none"]: dmg1 = v2; win2 = True
        elif t2 == "counter":
            if t1 == "attack" and v2 > v1: dmg1 = v2; win2 = True

        if t1 == "attack" and t2 == "attack":
            if v1 > v2: win1 = True
            elif v2 > v1: win2 = True

        # === 효과 적용 함수 ===
        def apply_effect(dice, target, is_win, is_self=False):
            eff = dice.get("effect", "")
            if not eff: return ""
            t = char1 if is_self else target # is_self=True면 char1(자신)에게 적용, 아니면 target에게 적용
            if dice is d2: # d2(char2)의 주사위인 경우 타겟 반전
                 t = char2 if is_self else char1

            # 1. 일반 마비/출혈
            if "paralysis_" in eff and "prob" not in eff and "boost" not in eff and "dmg" not in eff:
                try:
                    val = int(eff.split("_")[1])
                    condition = "on_win" in eff and is_win or "self" in eff and is_self or "on_win" not in eff and "self" not in eff
                    if condition: t.status_effects["paralysis"] = t.status_effects.get("paralysis", 0) + val
                except: pass
            
            if "bleed_" in eff and "synergy" not in eff:
                try:
                    val = int(eff.split("_")[1])
                    condition = "on_win" in eff and is_win or "self" in eff and is_self or "on_win" not in eff and "self" not in eff
                    if condition: t.status_effects["bleed"] = t.status_effects.get("bleed", 0) + val
                except: pass

            # 2. 확률적 마비
            if "paralysis_" in eff and "prob_" in eff:
                try:
                    parts = eff.split("_")
                    val = int(parts[1]) 
                    prob = int(parts[3])
                    condition = "on_win" in eff and is_win or "on_win" not in eff
                    if condition and random.randint(1, 100) <= prob:
                        t.status_effects["paralysis"] = t.status_effects.get("paralysis", 0) + val
                        return f" ⚡마비({val})"
                except: pass
            return ""

        log_add1 = apply_effect(d1, char2, win1)
        if log_add1: clash_log += log_add1
        
        log_add2 = apply_effect(d2, char1, win2)
        if log_add2: clash_log += log_add2
        
        if "self" in (d1.get("effect") or ""): apply_effect(d1, char1, win1, is_self=True)
        if "self" in (d2.get("effect") or ""): apply_effect(d2, char2, win2, is_self=True)

        # [마비 비례 고정 피해]
        if d1.get("effect") and "dmg_by_para_" in d1["effect"]:
             try:
                 mult = int(d1["effect"].split("_")[-1])
                 if p2_para > 0:
                     fixed = p2_para * mult
                     char2.current_hp = max(0, char2.current_hp - fixed)
                     clash_log += f" ⚡마비피해(-{fixed})"
             except: pass
        if d2.get("effect") and "dmg_by_para_" in d2["effect"]:
             try:
                 mult = int(d2["effect"].split("_")[-1])
                 if p1_para > 0:
                     fixed = p1_para * mult
                     char1.current_hp = max(0, char1.current_hp - fixed)
                     clash_log += f" ⚡마비피해(-{fixed})"
             except: pass

        # [자해]
        if d1.get("effect") and "self_dmg_" in d1["effect"]:
            try:
                dmg = 0
                if "by_para" in d1["effect"] and p1_para > 0:
                    dmg = p1_para * int(d1["effect"].split("_")[-1])
                elif "by_para" not in d1["effect"]:
                    parts = d1["effect"].split("_")
                    dmg = random.randint(int(parts[2]), int(parts[3]))
                
                if dmg > 0:
                    char1.current_hp = max(0, char1.current_hp - dmg)
                    clash_log += f" 🩸자해(-{dmg})"
            except: pass

        if d2.get("effect") and "self_dmg_" in d2["effect"]:
            try:
                dmg = 0
                if "by_para" in d2["effect"] and p2_para > 0:
                    dmg = p2_para * int(d2["effect"].split("_")[-1])
                elif "by_para" not in d2["effect"]:
                    parts = d2["effect"].split("_")
                    dmg = random.randint(int(parts[2]), int(parts[3]))
                
                if dmg > 0:
                    char2.current_hp = max(0, char2.current_hp - dmg)
                    clash_log += f" 🩸자해(-{dmg})"
            except: pass

        # 정신력 피해 계산
        if dmg1 > 0 and t2 != "mental_heal": mental_dmg1 = dmg1 // 2
        if dmg2 > 0 and t1 != "mental_heal": mental_dmg2 = dmg2 // 2

        # 방어율 적용
        if dmg1 > 0 and getattr(char1, "defense_rate", 0) > 0:
            dmg1 = int(dmg1 * (1 - char1.defense_rate / 100))
        if dmg2 > 0 and getattr(char2, "defense_rate", 0) > 0:
            dmg2 = int(dmg2 * (1 - char2.defense_rate / 100))

        # 패닉 시 피해 2배
        if is_stunned1 and dmg1 > 0: dmg1 *= 2; mental_dmg1 *= 2; clash_log += " (⚠️패닉 2배)"
        if is_stunned2 and dmg2 > 0: dmg2 *= 2; mental_dmg2 *= 2; clash_log += " (⚠️패닉 2배)"

        # [출혈: 행동 시 준 피해의 반절 * 스택]
        bleed1 = char1.status_effects.get("bleed", 0)
        if bleed1 > 0 and dmg2 > 0:
            b_dmg1 = int(dmg2 * 0.5 * bleed1)
            if b_dmg1 > 0:
                char1.current_hp = max(0, char1.current_hp - b_dmg1)
                clash_log += f" 🩸출혈(-{b_dmg1})"
                damage_taken1 += b_dmg1

        bleed2 = char2.status_effects.get("bleed", 0)
        if bleed2 > 0 and dmg1 > 0:
            b_dmg2 = int(dmg1 * 0.5 * bleed2)
            if b_dmg2 > 0:
                char2.current_hp = max(0, char2.current_hp - b_dmg2)
                clash_log += f" 🩸출혈(-{b_dmg2})"
                damage_taken2 += b_dmg2

        # 반사
        if "reflection" in effs1 and dmg1 > 0:
            refl = (dmg1 * 3) // 4
            if refl > 0: char2.current_hp = max(0, char2.current_hp - refl); clash_log += f" 💢반사(-{refl})"
        if "reflection" in effs2 and dmg2 > 0:
            refl = (dmg2 * 3) // 4
            if refl > 0: char1.current_hp = max(0, char1.current_hp - refl); clash_log += f" 💢반사(-{refl})"

        # 흡혈 (이미 구현된 로직 사용)
        if dmg2 > 0 and d1.get("effect") == "absorb_hp":
            char1.current_hp = min(char1.max_hp, char1.current_hp + dmg2); clash_log += " 🧛흡혈"
        if dmg1 > 0 and d2.get("effect") == "absorb_hp":
            char2.current_hp = min(char2.max_hp, char2.current_hp + dmg1); clash_log += " 🧛흡혈"

        # 파괴
        if dmg2 > 0 and d1.get("effect") == "destroy_next_on_hit" and i + 1 < len(res2):
            res2[i+1] = {"type": "none", "value": 0}; clash_log += " 💥파괴!"
        if dmg1 > 0 and d2.get("effect") == "destroy_next_on_hit" and i + 1 < len(res1):
            res1[i+1] = {"type": "none", "value": 0}; clash_log += " 💥파괴!"

        # 최종 적용
        char1.current_hp = max(0, char1.current_hp - dmg1)
        char2.current_hp = max(0, char2.current_hp - dmg2)
        char1.current_mental = max(0, char1.current_mental - mental_dmg1)
        char2.current_mental = max(0, char2.current_mental - mental_dmg2)
        
        # 회복
        if t1 == "heal": char1.current_hp = min(char1.max_hp, char1.current_hp + v1); clash_log += f" 💚+{v1}"
        if t1 == "mental_heal": char1.current_mental = min(char1.max_mental, char1.current_mental + v1); clash_log += f" 🔮+{v1}"
        if t2 == "heal": char2.current_hp = min(char2.max_hp, char2.current_hp + v2); clash_log += f" 💚+{v2}"
        if t2 == "mental_heal": char2.current_mental = min(char2.max_mental, char2.current_mental + v2); clash_log += f" 🔮+{v2}"

        if dmg2 > 0: clash_log += f" 💥{char2.name} HP-{dmg2}"
        if dmg1 > 0: 
            clash_log += f" 🩸{char1.name} HP-{dmg1}"
            damage_taken1 += dmg1
        if dmg2 > 0: damage_taken2 += dmg2
        
        log += clash_log
        
        # 마비 스택 감소 (방어/회복 행동 시)
        if t1 in ["defense", "heal", "mental_heal"] and char1.status_effects.get("paralysis", 0) > 0:
            char1.status_effects["paralysis"] -= 1
        if t2 in ["defense", "heal", "mental_heal"] and char2.status_effects.get("paralysis", 0) > 0:
            char2.status_effects["paralysis"] -= 1
            
        if char2.current_hp <= 0:
            log += f"\n💀 **{char2.name}** 처치!"
            break
        if char1.current_hp <= 0:
            break

    return log, damage_taken1, damage_taken2