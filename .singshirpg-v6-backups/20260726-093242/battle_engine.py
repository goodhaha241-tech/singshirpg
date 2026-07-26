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

def process_turn_start_artifacts(char, target, my_res, opp_res, turn_count, shayla_trigger, selected_card_name):
    """
    전투 시작 전(합 진행 전) 아티팩트 효과 처리
    """
    log = ""
    effects = []
    
    art = getattr(char, "equipped_artifact", None)
    engrave = getattr(char, "equipped_engraved_artifact", None)
    if art and isinstance(art, dict): effects.append(art.get("special"))
    if engrave and isinstance(engrave, dict): effects.append(engrave.get("special"))

    # 1. [샤일라: 빛나는]
    if shayla_trigger:
        destroy_count = random.randint(1, 3)
        destroyed = 0
        valid_indices = [i for i, d in enumerate(opp_res) if d["type"] != "none"]
        if valid_indices:
            targets = random.sample(valid_indices, min(len(valid_indices), destroy_count))
            for idx in targets:
                opp_res[idx] = {"type": "none", "value": 0}
                destroyed += 1
            log += f"✨ **[{char.name}:빛나는]** 섬광마법으로 주사위 {destroyed}개 파괴!\n"

        if destroyed > 0:
            stack = char.runtime_cooldowns.get("shayla_stack", 0) + destroyed
            if stack >= 10:
                stack = 0
                for d in opp_res:
                    d["type"] = "none"; d["value"] = 0
                log += f"✨ **[{char.name}:빛나는]** 섬광마법 3장:강한 빛 또한 강한 어둠과 같으니, 아무 행동도 할 수 없게 되는 것이다.\n"
            else:
                log += f"(✨파괴 스택: {stack}/10)\n"
            char.runtime_cooldowns["shayla_stack"] = stack

    # 2. [카이안: 시간의]
    if "kaian_time" in effects:
        stack = char.runtime_cooldowns.get("kaian_stack", 0)
        if stack > 0:
            for d in my_res:
                if d["type"] != "none": d["value"] += stack
            log += f"⌛ **[{char.name}:시간]** 가속! (+{stack})\n"

    # 3. [영산: 황금]
    if "youngsan_gold" in effects:
        if char.runtime_cooldowns.get("youngsan_nuke"):
            dmg = int(char.attack * 1.7)
            target.current_hp = max(0, target.current_hp - dmg)
            char.runtime_cooldowns["youngsan_nuke"] = False
            log += f"💰 **[{char.name}:황금]** 자본의 일격! {dmg}의 고정 피해를 입혔습니다!\n"

    # 4. [센쇼: 별똥별]
    if "sensho_star" in effects and selected_card_name == "별의 은총":
        if random.randint(1, 7) == 1:
            char.current_hp = char.max_hp
            dmg = char.current_mental
            target.current_hp = max(0, target.current_hp - dmg)
            log += f"🌠 **[{char.name}:별똥별]** 기적! HP 완전 회복 & 적에게 {dmg} 고정 피해!\n"
            for d in my_res:
                if d["type"] == "defense": d["type"] = "none"; d["value"] = 0
        else:
            for d in my_res:
                if d["type"] == "defense": d["value"] *= 2
            log += f"🌠 **[{char.name}:별똥별]** 가호! 방어 주사위 위력이 2배가 됩니다.\n"

    next_shayla_trigger = False
    if "shayla_light" in effects and selected_card_name == "밀키워킹":
        next_shayla_trigger = True
        
    return log, next_shayla_trigger

def apply_luude_logic(actor, target, current_log):
    """
    루우데 아티팩트(악몽) 효과 처리
    - 50% 확률: 정신력/체력 회복 (기존 유지)
    - 50% 확률: 파괴 스택 적립 및 60% 확률로 (스택*10 + 공격력) 고정 피해 (신규 적용)
    """
    is_mirror = "루우데" in actor.name and "루우데" in target.name

    # 1. 50% 확률로 회복 (기존 로직 유지)
    if random.random() < 0.5:
        heal_val = int(actor.max_mental * 0.1)
        actor.current_mental = min(actor.max_mental, actor.current_mental + heal_val)
        msg = "나 자신을 알라" if is_mirror else "이 잔은 나에게."
        current_log += f" 👁️**[{actor.name}:악몽]** {msg}(+{heal_val})"
        
        h_cnt = actor.runtime_cooldowns.get("luude_heal_cnt", 0) + 1
        if h_cnt >= 3:
            h_cnt = 0
            actor.current_hp = min(actor.max_hp, actor.current_hp + heal_val)
            current_log += f" (❤️체력회복 +{heal_val})"
        actor.runtime_cooldowns["luude_heal_cnt"] = h_cnt

    # 2. 나머지 50% 확률로 공격 (신규 로직 적용)
    else:
        # 파괴 스택 증가
        stack = actor.runtime_cooldowns.get("luude_destroy_stack", 0) + 1
        
        # 60% 확률로 스택 폭발 (고정 피해)
        if random.randint(1, 100) <= 60:
            fixed_dmg = (stack * 10) + actor.attack
            target.current_hp = max(0, target.current_hp - fixed_dmg)
            
            msg = "너 자신을 알라." if is_mirror else "이 잔은 그대에게."
            current_log += f" 👁️**[{actor.name}:악몽]** {msg} 악몽은 그렇게 흩어지니. {fixed_dmg} 개의 꿈이 방금 부서졌다. (스택 {stack}개 소모)"
            
            # 스택 초기화
            actor.runtime_cooldowns["luude_destroy_stack"] = 0
        else:
            # 발동 실패 시 스택만 유지
            actor.runtime_cooldowns["luude_destroy_stack"] = stack
            current_log += f" 👁️(파괴스택: {stack})"
            
    return current_log

def apply_dice_effect(dice, attacker, defender, is_win, is_self=False):
    """주사위 효과 적용 헬퍼 함수 (마비, 출혈, 기절 등 파싱)"""
    eff = dice.get("effect", "")
    if not eff: return ""
    
    target = attacker if is_self else defender
    log = ""
    
    # 조건 체크 (on_win, self)
    condition_met = True
    if "on_win" in eff and not is_win: condition_met = False
    if "self" in eff and not is_self: condition_met = False 
    if not condition_met: return ""

    parts = eff.split("_")
    
    # 확률 체크 (prob_X)
    prob = 100
    if "prob" in parts:
        try:
            prob_idx = parts.index("prob")
            prob = int(parts[prob_idx + 1])
        except: pass
    
    if random.randint(1, 100) > prob: return ""

    # 값 추출 (paralysis_X, bleed_X)
    val = 0
    if len(parts) > 1 and parts[1].isdigit():
        val = int(parts[1])

    # 효과 적용
    if "paralysis" in parts and "dmg" not in parts and "atk" not in parts:
        target.status_effects["paralysis"] = target.status_effects.get("paralysis", 0) + val
        log += f" ⚡마비({val})"
    
    elif "bleed" in parts and "synergy" not in parts:
        target.status_effects["bleed"] = target.status_effects.get("bleed", 0) + val
        log += f" 🩸출혈({val})"
        
    elif "stun" in parts:
        target.status_effects["stun"] = target.status_effects.get("stun", 0) + val
        log += f" 💫기절({val})"

    return log

def process_clash_loop(char1, char2, res1, res2, effs1, effs2, turn_count, is_stunned1=False, is_stunned2=False):
    """
    합(Clash) 처리 및 결과 반환
    """
    log = ""
    damage_taken1 = 0
    damage_taken2 = 0

    # 어즈렉 각인용 변수
    total_def1, total_def2 = 0, 0
    first_type1, first_type2 = None, None

    # 이펙트 안전 로딩
    if not effs1 and char1:
        effs1 = []
        art = getattr(char1, "equipped_artifact", None)
        if isinstance(art, dict): effs1.append(art.get("special"))
        eng = getattr(char1, "equipped_engraved_artifact", None)
        if isinstance(eng, dict): effs1.append(eng.get("special"))

    if not effs2 and char2:
        effs2 = []
        art = getattr(char2, "equipped_artifact", None)
        if isinstance(art, dict): effs2.append(art.get("special"))
        eng = getattr(char2, "equipped_engraved_artifact", None)
        if isinstance(eng, dict): effs2.append(eng.get("special"))
    
    max_len = max(len(res1), len(res2))
    
    for i in range(max_len):
        d1 = res1[i] if i < len(res1) else {"type": "none", "value": 0}
        d2 = res2[i] if i < len(res2) else {"type": "none", "value": 0}
        
        # 1. 마비 효과 적용 (값 감소)
        p1_para = char1.status_effects.get("paralysis", 0)
        p2_para = char2.status_effects.get("paralysis", 0)

        if d1["type"] != "none" and p1_para > 0: d1["value"] = max(0, d1["value"] - p1_para * 2)
        if d2["type"] != "none" and p2_para > 0: d2["value"] = max(0, d2["value"] - p2_para * 2)

        # 2. 마비 비례 공격력 증가 (atk_boost_para_X)
        if d1.get("effect") and "atk_boost_para" in d1["effect"] and p2_para > 0:
            try: d1["value"] += int(d1["effect"].split("_")[-1]) * p2_para
            except: pass
        if d2.get("effect") and "atk_boost_para" in d2["effect"] and p1_para > 0:
            try: d2["value"] += int(d2["effect"].split("_")[-1]) * p1_para
            except: pass

        # 3. 잠금 (Lock)
        if d1.get("effect") == "lock_others":
            destroyed = 0
            for j in range(i+1, len(res2)):
                if res2[j]["type"] != "none":
                    res2[j] = {"type": "none", "value": 0}
                    destroyed += 1
            if destroyed > 0:
                log += f"🔒 **{char1.name}**의 잠금! 적 주사위 {destroyed}개 파괴!\n"
                if "luude_imprint" in effs1: 
                    for _ in range(destroyed): log = apply_luude_logic(char1, char2, log)
                    log += "\n"

        if d2.get("effect") == "lock_others":
            destroyed = 0
            for j in range(i+1, len(res1)):
                if res1[j]["type"] != "none":
                    res1[j] = {"type": "none", "value": 0}
                    destroyed += 1
            if destroyed > 0:
                log += f"🔒 **{char2.name}**의 잠금! 적 주사위 {destroyed}개 파괴!\n"
                if "luude_imprint" in effs2:
                    for _ in range(destroyed): log = apply_luude_logic(char2, char1, log)
                    log += "\n"

        # 4. 출혈 시너지
        if d1.get("effect") == "bleed_synergy": d1["value"] += char2.status_effects.get("bleed", 0)
        if d2.get("effect") == "bleed_synergy": d2["value"] += char1.status_effects.get("bleed", 0)

        t1, v1 = d1["type"], d1["value"]
        t2, v2 = d2["type"], d2["value"]
        
        if i == 0: first_type1, first_type2 = t1, t2
        if t1 == "defense": total_def1 += v1
        if t2 == "defense": total_def2 += v2

        clash_log = f"\n**[{i+1}합]** "

        # [꼼꼼한] 재사용
        if "reuse_last_dice" in effs1 and not is_stunned1 and t1 == "none" and t2 != "none" and i > 0:
            ld = res1[i-1]; t1, v1 = ld["type"], ld["value"]
            clash_log += f"✨ **{char1.name}[꼼꼼한]** 재사용! "
        if "reuse_last_dice" in effs2 and not is_stunned2 and t2 == "none" and t1 != "none" and i > 0:
            ld = res2[i-1]; t2, v2 = ld["type"], ld["value"]
            clash_log += f"✨ **{char2.name}[꼼꼼한]** 재사용! "

        # [맹렬한] / [견고한] 아티팩트
        if "fierce_attack" in effs1 and t1 == "attack":
            last = char1.runtime_cooldowns.get("fierce_attack", -10)
            if turn_count - last >= 2:
                v1 += char1.attack; char1.runtime_cooldowns["fierce_attack"] = turn_count
                clash_log += f"🔥 **{char1.name}[맹렬한]** "
        if "fierce_attack" in effs2 and t2 == "attack":
            last = char2.runtime_cooldowns.get("fierce_attack", -10)
            if turn_count - last >= 2:
                v2 += char2.attack; char2.runtime_cooldowns["fierce_attack"] = turn_count
                clash_log += f"🔥 **{char2.name}[맹렬한]** "

        if "sturdy_defense" in effs1 and t1 == "defense":
            last = char1.runtime_cooldowns.get("sturdy_defense", -10)
            if turn_count - last >= 2:
                heal = (v1 * 2) // 3; char1.current_hp = min(char1.max_hp, char1.current_hp + heal)
                char1.runtime_cooldowns["sturdy_defense"] = turn_count
                clash_log += f"🛡️ **{char1.name}[견고한]**(+{heal}) "
        if "sturdy_defense" in effs2 and t2 == "defense":
            last = char2.runtime_cooldowns.get("sturdy_defense", -10)
            if turn_count - last >= 2:
                heal = (v2 * 2) // 3; char2.current_hp = min(char2.max_hp, char2.current_hp + heal)
                char2.runtime_cooldowns["sturdy_defense"] = turn_count
                clash_log += f"🛡️ **{char2.name}[견고한]**(+{heal}) "

        clash_log += f"{get_emoji(t1)}{v1} vs {get_emoji(t2)}{v2}"
        
        dmg1, dmg2 = 0, 0 
        mental_dmg1, mental_dmg2 = 0, 0
        win1, win2 = False, False

        # --- 승패 판정 ---
        if t1 == "attack":
            if t2 == "attack": dmg2 = v1
            elif t2 == "defense": dmg2 = max(0, v1 - v2)
            elif t2 == "counter": 
                if v1 >= v2: dmg2 = v1; win1 = True
            elif t2 in ["heal", "mental_heal", "none"]: dmg2 = v1; win1 = True
        elif t1 == "counter":
            if t2 == "attack" and v1 > v2: dmg2 = v1; win1 = True
        
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

        val_win1 = v1 > v2
        val_win2 = v2 > v1

        # --- [최적화] 효과 적용 (apply_dice_effect 사용) ---
        clash_log += apply_dice_effect(d1, char1, char2, val_win1)
        clash_log += apply_dice_effect(d2, char2, char1, val_win2)
        
        if "self" in (d1.get("effect") or ""): clash_log += apply_dice_effect(d1, char1, char2, val_win1, is_self=True)
        if "self" in (d2.get("effect") or ""): clash_log += apply_dice_effect(d2, char2, char1, val_win2, is_self=True)

        # [마비 비례 고정 피해] (dmg_by_para_X)
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

        # [자해] (self_dmg_X_Y)
        if d1.get("effect") and "self_dmg_" in d1["effect"]:
            try:
                dmg = 0
                if "by_para" in d1["effect"] and p1_para > 0:
                    dmg = p1_para * int(d1["effect"].split("_")[-1])
                elif "by_para" not in d1["effect"]:
                    parts = d1["effect"].split("_")
                    dmg = random.randint(int(parts[2]), int(parts[3]))
                if dmg > 0:
                    char1.current_hp = max(0, char1.current_hp - dmg); clash_log += f" 🩸자해(-{dmg})"
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
                    char2.current_hp = max(0, char2.current_hp - dmg); clash_log += f" 🩸자해(-{dmg})"
            except: pass

        # 정신력 피해 계산
        if dmg1 > 0 and t2 != "mental_heal": mental_dmg1 = dmg1 // 2
        if dmg2 > 0 and t1 != "mental_heal": mental_dmg2 = dmg2 // 2

        # 방어율 및 방어력 비례 경감
        if dmg1 > 0:
            if getattr(char1, "defense_rate", 0) > 0: dmg1 = int(dmg1 * (1 - char1.defense_rate / 100))
            dmg1 = max(0, dmg1 - int(char1.defense / 3))
        if dmg2 > 0:
            if getattr(char2, "defense_rate", 0) > 0: dmg2 = int(dmg2 * (1 - char2.defense_rate / 100))
            dmg2 = max(0, dmg2 - int(char2.defense / 3))

        # 패닉 2배
        if is_stunned1 and dmg1 > 0: dmg1 *= 2; mental_dmg1 *= 2; clash_log += " (⚠️패닉 2배)"
        if is_stunned2 and dmg2 > 0: dmg2 *= 2; mental_dmg2 *= 2; clash_log += " (⚠️패닉 2배)"

        # 출혈 추가 피해
        bleed1 = char1.status_effects.get("bleed", 0)
        if bleed1 > 0 and dmg2 > 0:
            b_dmg1 = int(dmg2 * 0.5 * bleed1)
            if b_dmg1 > 0: char1.current_hp = max(0, char1.current_hp - b_dmg1); clash_log += f" 🩸출혈(-{b_dmg1})"; damage_taken1 += b_dmg1

        bleed2 = char2.status_effects.get("bleed", 0)
        if bleed2 > 0 and dmg1 > 0:
            b_dmg2 = int(dmg1 * 0.5 * bleed2)
            if b_dmg2 > 0: char2.current_hp = max(0, char2.current_hp - b_dmg2); clash_log += f" 🩸출혈(-{b_dmg2})"; damage_taken2 += b_dmg2

        # 반사 / 흡혈
        if "reflection" in effs1 and dmg1 > 0:
            refl = (dmg1 * 3) // 4
            if refl > 0: char2.current_hp = max(0, char2.current_hp - refl); clash_log += f" 💢반사(-{refl})"
        if "reflection" in effs2 and dmg2 > 0:
            refl = (dmg2 * 3) // 4
            if refl > 0: char1.current_hp = max(0, char1.current_hp - refl); clash_log += f" 💢반사(-{refl})"

        if val_win1 and d1.get("effect") == "absorb_hp":
            char1.current_hp = min(char1.max_hp, char1.current_hp + dmg2); clash_log += " 🧛흡혈"
        if val_win2 and d2.get("effect") == "absorb_hp":
            char2.current_hp = min(char2.max_hp, char2.current_hp + dmg1); clash_log += " 🧛흡혈"

        # [시간가속] (합 승리 시)
        if d1.get("effect") == "time_accel" and val_win1:
            last = char1.runtime_cooldowns.get("time_accel_last_turn", -1)
            if last < turn_count:
                if "kaian_time" in effs1:
                    stack = char1.runtime_cooldowns.get("kaian_stack", 0) + 6
                    char1.runtime_cooldowns["kaian_stack"] = stack
                    clash_log += f" ⌛(🔺{stack})"
                    if stack >= 42: # 시간붕괴
                        char1.runtime_cooldowns["kaian_stack"] = 0
                        dmg_val = char1.attack * 2
                        char2.current_hp = max(0, char2.current_hp - dmg_val)
                        clash_log += f"\n⌛ **[시간붕괴]** 시간술식 3장: 시간은 비명을 지를 수 없으니, 시간을 대신해 비명을 지르라. (-{dmg_val})"
                else:
                    char1.runtime_cooldowns["time_accel_bonus"] = char1.runtime_cooldowns.get("time_accel_bonus", 0) + 6
                    clash_log += " ⌛가속(+6)"
                char1.runtime_cooldowns["time_accel_last_turn"] = turn_count

        if d2.get("effect") == "time_accel" and val_win2:
            last = char2.runtime_cooldowns.get("time_accel_last_turn", -1)
            if last < turn_count:
                if "kaian_time" in effs2:
                    stack = char2.runtime_cooldowns.get("kaian_stack", 0) + 6
                    char2.runtime_cooldowns["kaian_stack"] = stack
                    clash_log += f" ⌛(🔺{stack})"
                    if stack >= 42: # 시간붕괴
                        char2.runtime_cooldowns["kaian_stack"] = 0
                        dmg_val = char2.attack * 2
                        char1.current_hp = max(0, char1.current_hp - dmg_val)
                        clash_log += f"\n⌛ **[시간붕괴]** 시간술식 3장: 시간은 비명을 지를 수 없으니, 시간을 대신해 비명을 지르라. (-{dmg_val})"
                else:
                    char2.runtime_cooldowns["time_accel_bonus"] = char2.runtime_cooldowns.get("time_accel_bonus", 0) + 6
                    clash_log += " ⌛가속(+6)"
                char2.runtime_cooldowns["time_accel_last_turn"] = turn_count

        # 파괴 (루우데 각인 연동)
        if val_win1 and d1.get("effect") == "destroy_next_on_hit" and i + 1 < len(res2):
            res2[i+1] = {"type": "none", "value": 0}; clash_log += " 💥파괴!"
            if "luude_imprint" in effs1: clash_log = apply_luude_logic(char1, char2, clash_log)
        
        if val_win2 and d2.get("effect") == "destroy_next_on_hit" and i + 1 < len(res1):
            res1[i+1] = {"type": "none", "value": 0}; clash_log += " 💥파괴!"
            if "luude_imprint" in effs2: clash_log = apply_luude_logic(char2, char1, clash_log)

        # 최종 피해 적용
        char1.current_hp = max(0, char1.current_hp - dmg1)
        char2.current_hp = max(0, char2.current_hp - dmg2)
        char1.current_mental = max(0, char1.current_mental - mental_dmg1)
        char2.current_mental = max(0, char2.current_mental - mental_dmg2)
        
        # 회복 처리 (방어 시 정신력 회복 포함)
        if t1 == "heal": char1.current_hp = min(char1.max_hp, char1.current_hp + v1); clash_log += f" 💚+{v1}"
        if t1 == "mental_heal": char1.current_mental = min(char1.max_mental, char1.current_mental + v1); clash_log += f" 🔮+{v1}"
        if t1 == "defense" and t2 == "attack":
            m_heal = min(v1, v2) // 2
            if m_heal > 0: char1.current_mental = min(char1.max_mental, char1.current_mental + m_heal); clash_log += f" 🛡️🔮+{m_heal}"

        if t2 == "heal": char2.current_hp = min(char2.max_hp, char2.current_hp + v2); clash_log += f" 💚+{v2}"
        if t2 == "mental_heal": char2.current_mental = min(char2.max_mental, char2.current_mental + v2); clash_log += f" 🔮+{v2}"
        if t2 == "defense" and t1 == "attack":
            m_heal = min(v2, v1) // 2
            if m_heal > 0: char2.current_mental = min(char2.max_mental, char2.current_mental + m_heal); clash_log += f" 🛡️🔮+{m_heal}"

        if dmg2 > 0: clash_log += f" 💥{char2.name} HP-{dmg2}"; damage_taken2 += dmg2
        if dmg1 > 0: clash_log += f" 🩸{char1.name} HP-{dmg1}"; damage_taken1 += dmg1
        
        log += clash_log
        
        # 상태이상 턴 감소
        if t1 in ["defense", "heal", "mental_heal"] and char1.status_effects.get("paralysis", 0) > 0: char1.status_effects["paralysis"] -= 1
        if t2 in ["defense", "heal", "mental_heal"] and char2.status_effects.get("paralysis", 0) > 0: char2.status_effects["paralysis"] -= 1
        if char1.status_effects.get("stun", 0) > 0: char1.status_effects["stun"] -= 1
        if char2.status_effects.get("stun", 0) > 0: char2.status_effects["stun"] -= 1

        if char1.current_hp <= 0 or char2.current_hp <= 0: break

    # [어즈렉 각인: 믿음어린]
    if "earthreg_faith" in effs1 and first_type1 == "defense":
        heal = int(total_def1 * 0.25)
        if heal > 0:
            char1.current_hp = min(char1.max_hp, char1.current_hp + heal)
            log += f"\n🛡️ **[{char1.name}:믿음]** 믿는 자에게 빛이 있나니(+{heal})"
    
    if "earthreg_faith" in effs2 and first_type2 == "defense":
        heal = int(total_def2 * 0.25)
        if heal > 0:
            char2.current_hp = min(char2.max_hp, char2.current_hp + heal)
            log += f"\n🛡️ **[{char2.name}:믿음]** 믿는 자에게 빛이 있나니(+{heal})"

    return log, damage_taken1, damage_taken2