# battle_engine.py
# rollback-guard-appraisal-gems-v8
# pve-gem-runtime-v8.2
import random
from gem_effects import (
    artifact_modifier,
    artifact_trigger_interval,
    consume_balance_bonus,
    consume_chain_bonus,
    consume_guardian_defense_bonus,
    consume_reuse_failure_bonus,
    empty_slot_guard,
    gem_state,
    low_mental_bonus,
    multi_attack_bonus,
    pop_gem_activation_log,
    record_balance_loss,
    record_fierce_aftereffect,
    reflection_damage,
    reflection_incoming_damage,
    reduce_turn_first_damage,
    reduce_guardian_mental_damage,
    reuse_dice_bonus,
    reuse_failure_bonus,
    runtime_cooldowns,
    single_dice_bonus,
    status_amount_after_resistance,
    sturdy_recovery,
    turn_first_dice_bonus,
)

TIME_ACCEL_POWER_PER_STACK = 0.25
KAIAN_TIME_MAX_STACKS = 7
KAIAN_TIME_HP_HEAL_RATIO = 0.10
KAIAN_TIME_MENTAL_HEAL_RATIO = 0.10
KAIAN_TIME_DAMAGE_RATIO = 0.15
FREEZE_STAT_MULTIPLIER = 0.85
SEVERE_COLD_FROST_THRESHOLD = 3
SEVERE_COLD_DURATION = 5
SEVERE_COLD_LIFESTEAL_RATIO = 0.20


def get_emoji(action_type):
    return {"attack": "⚔️", "defense": "🛡️", "counter": "⚡", "heal": "💚", "mental_heal": "🔮", "none": "💨"}.get(action_type, "🎲")


def ensure_status_effects(entity):
    """Legacy combatants lazily receive every shared status key."""
    statuses = getattr(entity, "status_effects", None)
    if not isinstance(statuses, dict):
        statuses = {}
        entity.status_effects = statuses
    for key in ("bleed", "paralysis", "stun", "freeze"):
        statuses.setdefault(key, 0)
    return statuses


def status_summary(entity):
    statuses = ensure_status_effects(entity)
    parts = []
    if statuses["bleed"] > 0:
        parts.append(f"🩸 출혈 {statuses['bleed']}")
    if statuses["paralysis"] > 0:
        parts.append(f"⚡ 마비 {statuses['paralysis']}")
    if statuses["stun"] > 0:
        parts.append(f"💫 기절 {statuses['stun']}")
    if statuses["freeze"] > 0:
        parts.append(
            f"❄️ 빙결 {statuses['freeze']} · 주사위 1~2개 봉쇄 · 공격/방어 -15%"
        )
    frost = int(runtime_cooldowns(entity).get("yeongseol_frost", 0))
    if frost:
        parts.append(f"🌨️ 서리 {frost}/{SEVERE_COLD_FROST_THRESHOLD}")
    return " · ".join(parts)


def effective_combat_stat(entity, key):
    """Return a frozen combat stat with the 15% penalty floored once."""
    value = int(getattr(entity, key, 0) or 0)
    if ensure_status_effects(entity).get("freeze", 0) > 0 and key in {"attack", "defense"}:
        return max(0, int(value * FREEZE_STAT_MULTIPLIER))
    return value


def apply_freeze_status(source, target, turns):
    """Apply freeze using max-duration refresh semantics and shared resistance."""
    statuses = ensure_status_effects(target)
    amount = int(turns)
    if (
        source is not None
        and "status_extend" in set(getattr(source, "general_passives", set()) or set())
    ):
        amount += 1
    amount = status_amount_after_resistance(target, amount, "freeze")
    if amount <= 0:
        return 0
    previous = int(statuses.get("freeze", 0))
    statuses["freeze"] = max(previous, amount)
    return max(0, statuses["freeze"] - previous)


def apply_freeze_dice_lock(entity, dice_results, turn_count, rng=None):
    """Lock one or two valid dice once per action; reuse positions for AoE."""
    statuses = ensure_status_effects(entity)
    if statuses.get("freeze", 0) <= 0:
        return ""
    runtime = runtime_cooldowns(entity)
    action_key = (int(turn_count), runtime.get("freeze_action_serial", 0))
    valid = [index for index, die in enumerate(dice_results) if die.get("type") != "none"]
    if not valid:
        return ""
    if runtime.get("freeze_lock_action_key") == action_key:
        locked = [index for index in runtime.get("freeze_lock_indices", []) if index < len(dice_results)]
        first = False
    else:
        roller = rng or random
        count = min(len(valid), roller.randint(1, 2))
        locked = sorted(roller.sample(valid, count))
        runtime["freeze_lock_action_key"] = action_key
        runtime["freeze_lock_indices"] = locked
        first = True
    for index in locked:
        if index < len(dice_results) and dice_results[index].get("type") != "none":
            dice_results[index] = {
                "type": "none", "value": 0, "effect": None, "frozen": True
            }
    if first and locked:
        positions = ", ".join(str(index + 1) for index in locked)
        return f"❄️ **[{entity.name}:빙결]** 주사위 {positions}번 봉쇄!\n"
    return ""


def _has_severe_cold(entity, effects=None):
    effects = set(effects or [])
    if "yeongseol_severe_cold" in effects:
        return True
    for attr in ("equipped_artifact", "equipped_engraved_artifact"):
        artifact = getattr(entity, attr, None)
        if isinstance(artifact, dict) and artifact.get("special") == "yeongseol_severe_cold":
            return True
    return getattr(entity, "inherited_special", None) == "yeongseol_severe_cold"


def process_severe_cold_before_clash(actor, target, dice_results, effects, turn_count):
    """Prepare per-die frost triggers once, without counting AoE targets twice."""
    if not _has_severe_cold(actor, effects):
        return ""
    runtime = runtime_cooldowns(actor)
    action_key = (int(turn_count), runtime.get("freeze_action_serial", 0))
    if runtime.get("severe_cold_action_key") == action_key:
        return ""
    attack_indices = [
        index for index, die in enumerate(dice_results)
        if die.get("type") == "attack"
    ]
    if not attack_indices:
        return ""
    stack = int(runtime.get("yeongseol_frost", 0))
    trigger_indices = []
    for index in attack_indices:
        stack += 1
        if stack >= SEVERE_COLD_FROST_THRESHOLD:
            trigger_indices.append(index)
            stack = 0
    runtime["severe_cold_action_key"] = action_key
    runtime["severe_cold_trigger_indices"] = trigger_indices
    runtime["severe_cold_triggered_targets"] = set()
    runtime["yeongseol_frost"] = stack
    return (
        f"🌨️ **[{actor.name}:혹한]** 서리 +{len(attack_indices)} "
        f"({stack}/{SEVERE_COLD_FROST_THRESHOLD})\n"
    )


def trigger_severe_cold_for_die(actor, target, dice_index, effects, turn_count):
    """Apply a prepared threshold immediately before its triggering clash."""
    if not _has_severe_cold(actor, effects):
        return ""
    runtime = runtime_cooldowns(actor)
    action_key = (int(turn_count), runtime.get("freeze_action_serial", 0))
    if runtime.get("severe_cold_action_key") != action_key:
        return ""
    if int(dice_index) not in runtime.get("severe_cold_trigger_indices", []):
        return ""
    seen = runtime.setdefault("severe_cold_triggered_targets", set())
    key = (id(target), int(dice_index))
    if key in seen:
        return ""
    seen.add(key)
    applied = apply_freeze_status(actor, target, SEVERE_COLD_DURATION)
    return (
        f" ❄️혹한 발동: {target.name} 빙결 "
        f"{ensure_status_effects(target)['freeze']}턴"
        + ("!" if applied else "(면역/기존 지속시간 유지)")
    )


def apply_severe_cold_lifesteal(actor, target, actual_hp_damage, effects=None):
    """Heal from post-mitigation HP damage dealt to a frozen opponent."""
    damage = max(0, int(actual_hp_damage or 0))
    if (
        damage <= 0
        or ensure_status_effects(target).get("freeze", 0) <= 0
        or not _has_severe_cold(actor, effects)
    ):
        return 0
    before = actor.current_hp
    actor.current_hp = min(
        actor.max_hp,
        actor.current_hp + int(damage * SEVERE_COLD_LIFESTEAL_RATIO),
    )
    return actor.current_hp - before


def tick_freeze_end_of_turn(entity, turn_count):
    """Decrease freeze exactly once for a resolved combat turn."""
    statuses = ensure_status_effects(entity)
    runtime = runtime_cooldowns(entity)
    if runtime.get("freeze_tick_turn") == int(turn_count):
        return 0
    runtime["freeze_tick_turn"] = int(turn_count)
    before = int(statuses.get("freeze", 0))
    if before > 0:
        statuses["freeze"] = before - 1
        return 1
    return 0


def time_accel_multiplier(stacks):
    """시간가속 스택에 따른 주사위 위력 배율을 반환합니다."""
    return 1.0 + (max(0, int(stacks)) * TIME_ACCEL_POWER_PER_STACK)


def apply_time_accel_power(dice_results, stacks):
    """모든 유효 주사위에 시간가속 배율을 적용합니다."""
    stacks = max(0, int(stacks))
    if stacks <= 0:
        return dice_results

    multiplier = time_accel_multiplier(stacks)
    for dice in dice_results:
        if dice.get("type") == "none":
            continue
        value = max(0, dice.get("value", 0))
        dice["value"] = int((value * multiplier) + 0.5)
    return dice_results


def gain_time_acceleration(actor, target, effects, turn_count):
    """합 승리 시 시간가속을 적립하고, 각인 만충 효과를 처리합니다."""
    runtime = runtime_cooldowns(actor)
    last_turn = runtime.get("time_accel_last_turn", -1)
    if last_turn >= turn_count:
        return ""
    runtime["time_accel_last_turn"] = turn_count

    if "kaian_time" not in effects:
        runtime["time_accel_next_stacks"] = 1
        return " ⌛가속(다음 턴 ×1.25)"

    stack = min(KAIAN_TIME_MAX_STACKS, runtime.get("kaian_stack", 0) + 1)
    if stack < KAIAN_TIME_MAX_STACKS:
        runtime["kaian_stack"] = stack
        multiplier = time_accel_multiplier(stack)
        return f" ⌛가속({stack}/{KAIAN_TIME_MAX_STACKS}, ×{multiplier:.2f})"

    runtime["kaian_stack"] = 0

    hp_before = actor.current_hp
    mental_before = actor.current_mental
    hp_heal = max(1, int(actor.max_hp * KAIAN_TIME_HP_HEAL_RATIO))
    mental_heal = max(1, int(actor.max_mental * KAIAN_TIME_MENTAL_HEAL_RATIO))
    actor.current_hp = min(actor.max_hp, actor.current_hp + hp_heal)
    actor.current_mental = min(actor.max_mental, actor.current_mental + mental_heal)
    hp_restored = actor.current_hp - hp_before
    mental_restored = actor.current_mental - mental_before

    damage = max(1, int(target.max_hp * KAIAN_TIME_DAMAGE_RATIO))
    target.current_hp = max(0, target.current_hp - damage)
    return (
        f"\n⌛ **[시간붕괴]** 시간가속이 가득 찼습니다! "
        f"HP +{hp_restored}, 정신력 +{mental_restored}, "
        f"**{target.name}**에게 최대 체력 비례 피해 {damage}!"
    )


def apply_stat_scaling(dice_results, char):
    """캐릭터 스탯에 따라 주사위 값을 보정합니다."""
    for dice in dice_results:
        d_type = dice.get("type")
        val = dice.get("value", 0)
        bonus = 0
        
        if d_type == "attack":
            bonus = int(effective_combat_stat(char, "attack") * 0.5)
        elif d_type == "defense":
            if val > 1: 
                bonus = int(effective_combat_stat(char, "defense") * 0.5)
        elif d_type == "counter":
            bonus = int(
                (effective_combat_stat(char, "attack") * 0.25)
                + (effective_combat_stat(char, "defense") * 0.25)
            )
        elif d_type in ["heal", "mental_heal"]:
            bonus = int(effective_combat_stat(char, "defense") * 0.2)

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
            apply_time_accel_power(my_res, stack)
            multiplier = time_accel_multiplier(stack)
            log += (
                f"⌛ **[{char.name}:시간]** 가속 "
                f"{stack}/{KAIAN_TIME_MAX_STACKS}! (주사위 ×{multiplier:.2f})\n"
            )

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

    # Freeze is resolved after artifact destruction and before the first clash.
    log += apply_freeze_dice_lock(char, my_res, turn_count)
    log += apply_freeze_dice_lock(target, opp_res, turn_count)
        
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
            current_log += f" 👁️**[{actor.name}:악몽]** {msg} 모두의 잔이 찼고, 나는 {fixed_dmg} 개의 가능성을 돌려주니.(스택 {stack}개 소모)"
            
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

    if is_self and eff in {"self_major", "self_minor"}:
        runtime = runtime_cooldowns(attacker)
        state = "major" if eff == "self_major" else "minor"
        runtime["change_state"] = state
        label = "메이저" if state == "major" else "마이너"
        detail = "주는·받는 피해 +25%" if state == "major" else "주는·받는 피해 -25%"
        return f" 🎼{label}({detail})"

    # 값 추출 (paralysis_X, bleed_X)
    val = 0
    if len(parts) > 1 and parts[1].isdigit():
        val = int(parts[1])
    status_key = next(
        (key for key in ("paralysis", "bleed", "stun", "freeze") if key in parts),
        None,
    )
    if (
        status_key
        and "status_extend" in set(getattr(attacker, "general_passives", set()) or set())
    ):
        val += 1
    val = status_amount_after_resistance(target, val, status_key)

    # 효과 적용
    if "paralysis" in parts and "dmg" not in parts and "atk" not in parts:
        if val > 0:
            target.status_effects["paralysis"] = target.status_effects.get("paralysis", 0) + val
            log += f" ⚡마비({val})"
    
    elif "bleed" in parts and "synergy" not in parts:
        if val > 0:
            target.status_effects["bleed"] = target.status_effects.get("bleed", 0) + val
            log += f" 🩸출혈({val})"
        
    elif "stun" in parts:
        if val > 0:
            target.status_effects["stun"] = target.status_effects.get("stun", 0) + val
            log += f" 💫기절({val})"
    elif "freeze" in parts:
        if val > 0:
            previous = ensure_status_effects(target).get("freeze", 0)
            target.status_effects["freeze"] = max(previous, val)
            log += f" ❄️빙결({target.status_effects['freeze']}턴)"

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
    art1 = getattr(char1, "equipped_artifact", None)
    art2 = getattr(char2, "equipped_artifact", None)
    art1 = art1 if isinstance(art1, dict) else {}
    art2 = art2 if isinstance(art2, dict) else {}
    valid1 = [d for d in res1 if d.get("type") != "none"]
    valid2 = [d for d in res2 if d.get("type") != "none"]
    attack_index1 = attack_index2 = 0
    valid_index1 = valid_index2 = 0
    runtime1 = runtime_cooldowns(char1)
    runtime2 = runtime_cooldowns(char2)
    state1 = gem_state(char1)
    state2 = gem_state(char2)

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

    ensure_status_effects(char1)
    ensure_status_effects(char2)
    log += process_severe_cold_before_clash(char1, char2, res1, effs1, turn_count)
    log += process_severe_cold_before_clash(char2, char1, res2, effs2, turn_count)
    
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
        if t1 == "attack":
            v1 += int(runtime1.get("guild_attack_bonus", 0))
        elif t1 in {"defense", "counter"}:
            v1 += int(runtime1.get("guild_defense_bonus", 0))
        if t2 == "attack":
            v2 += int(runtime2.get("guild_attack_bonus", 0))
        elif t2 in {"defense", "counter"}:
            v2 += int(runtime2.get("guild_defense_bonus", 0))
        if t1 != "none":
            v1 += consume_balance_bonus(char1) + consume_chain_bonus(char1)
            v1 += consume_guardian_defense_bonus(char1, t1)
        if t2 != "none":
            v2 += consume_balance_bonus(char2) + consume_chain_bonus(char2)
            v2 += consume_guardian_defense_bonus(char2, t2)
        if t1 == "attack":
            attack_index1 += 1
        if t2 == "attack":
            attack_index2 += 1
        if t1 != "none":
            v1 += turn_first_dice_bonus(char1, valid_index1)
            if len(valid1) == 1:
                v1 += single_dice_bonus(char1, t1)
            v1 += multi_attack_bonus(char1, attack_index1)
            v1 += low_mental_bonus(char1, char1.current_mental, char1.max_mental)
            valid_index1 += 1
        if t2 != "none":
            v2 += turn_first_dice_bonus(char2, valid_index2)
            if len(valid2) == 1:
                v2 += single_dice_bonus(char2, t2)
            v2 += multi_attack_bonus(char2, attack_index2)
            v2 += low_mental_bonus(char2, char2.current_mental, char2.max_mental)
            valid_index2 += 1

        clash_log = f"\n**[{i+1}합]** "
        clash_log += trigger_severe_cold_for_die(
            char1, char2, i, effs1, turn_count
        )
        clash_log += trigger_severe_cold_for_die(
            char2, char1, i, effs2, turn_count
        )

        # [꼼꼼한] 재사용
        if "reuse_last_dice" in effs1 and not is_stunned1 and t1 == "none" and t2 != "none" and i > 0:
            ld = res1[i-1]
            if ld.get("type") != "none":
                t1, v1 = ld["type"], ld["value"]
                bonus = reuse_dice_bonus(art1) + consume_reuse_failure_bonus(art1, state1)
                v1 += bonus
                clash_log += f"✨ **{char1.name}[꼼꼼한]** 재사용(+{bonus})! "
            else:
                reuse_failure_bonus(art1, state1)
        if "reuse_last_dice" in effs2 and not is_stunned2 and t2 == "none" and t1 != "none" and i > 0:
            ld = res2[i-1]
            if ld.get("type") != "none":
                t2, v2 = ld["type"], ld["value"]
                bonus = reuse_dice_bonus(art2) + consume_reuse_failure_bonus(art2, state2)
                v2 += bonus
                clash_log += f"✨ **{char2.name}[꼼꼼한]** 재사용(+{bonus})! "
            else:
                reuse_failure_bonus(art2, state2)
        if "reuse_last_dice" in effs1 and t1 == "none" and t2 != "none":
            guard = empty_slot_guard(art1)
            if guard > 0:
                t1, v1 = "defense", guard
                clash_log += f"🛡️ **{char1.name}[여백]** "
        if "reuse_last_dice" in effs2 and t2 == "none" and t1 != "none":
            guard = empty_slot_guard(art2)
            if guard > 0:
                t2, v2 = "defense", guard
                clash_log += f"🛡️ **{char2.name}[여백]** "

        if i == 0:
            first_type1, first_type2 = t1, t2
        if t1 == "defense":
            total_def1 += v1
        if t2 == "defense":
            total_def2 += v2

        # [맹렬한] / [견고한] 아티팩트
        if "fierce_attack" in effs1 and t1 == "attack":
            last = runtime1.get("fierce_attack", -10)
            if turn_count - last >= artifact_trigger_interval(art1, "fierce_attack", 2):
                fierce = artifact_modifier(
                    art1, "damage", effective_combat_stat(char1, "attack")
                )
                v1 += fierce
                runtime1["fierce_attack"] = turn_count
                record_fierce_aftereffect(art1, fierce, state1)
                clash_log += f"🔥 **{char1.name}[맹렬한]** "
        if "fierce_attack" in effs2 and t2 == "attack":
            last = runtime2.get("fierce_attack", -10)
            if turn_count - last >= artifact_trigger_interval(art2, "fierce_attack", 2):
                fierce = artifact_modifier(
                    art2, "damage", effective_combat_stat(char2, "attack")
                )
                v2 += fierce
                runtime2["fierce_attack"] = turn_count
                record_fierce_aftereffect(art2, fierce, state2)
                clash_log += f"🔥 **{char2.name}[맹렬한]** "

        if "sturdy_defense" in effs1 and t1 == "defense":
            last = runtime1.get("sturdy_defense", -10)
            if turn_count - last >= 2:
                heal, shield = sturdy_recovery(art1, char1, (v1 * 2) // 3)
                runtime1["sturdy_defense"] = turn_count
                clash_log += f"🛡️ **{char1.name}[견고한]**(+{heal}"
                clash_log += f", 보호막 {shield}" if shield else ""
                clash_log += ") "
        if "sturdy_defense" in effs2 and t2 == "defense":
            last = runtime2.get("sturdy_defense", -10)
            if turn_count - last >= 2:
                heal, shield = sturdy_recovery(art2, char2, (v2 * 2) // 3)
                runtime2["sturdy_defense"] = turn_count
                clash_log += f"🛡️ **{char2.name}[견고한]**(+{heal}"
                clash_log += f", 보호막 {shield}" if shield else ""
                clash_log += ") "

        # Keep the final displayed dice values available to callers such as
        # guild training without changing the normal combat dice payload.
        if i < len(res1):
            res1[i]["resolved_type"] = t1
            res1[i]["resolved_value"] = max(0, int(v1))
        if i < len(res2):
            res2[i]["resolved_type"] = t2
            res2[i]["resolved_value"] = max(0, int(v2))

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
        if t1 != "none" and t2 != "none":
            if val_win2:
                record_balance_loss(char1)
            elif val_win1:
                record_balance_loss(char2)

        # --- [최적화] 효과 적용 (apply_dice_effect 사용) ---
        clash_log += apply_dice_effect(d1, char1, char2, val_win1)
        clash_log += apply_dice_effect(d2, char2, char1, val_win2)
        for extra_effect in d1.get("extra_effects", []):
            clash_log += apply_dice_effect(
                {"effect": extra_effect}, char1, char2, val_win1
            )
        for extra_effect in d2.get("extra_effects", []):
            clash_log += apply_dice_effect(
                {"effect": extra_effect}, char2, char1, val_win2
            )
        
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
            dmg1 = max(0, dmg1 - int(effective_combat_stat(char1, "defense") / 3))
        if dmg2 > 0:
            if getattr(char2, "defense_rate", 0) > 0: dmg2 = int(dmg2 * (1 - char2.defense_rate / 100))
            dmg2 = max(0, dmg2 - int(effective_combat_stat(char2, "defense") / 3))

        # 메이저/마이너는 일반 합 피해에만 적용한다. 서로 배타적이며
        # 다른 체인지 카드를 사용하거나 전투가 끝날 때까지 유지된다.
        if dmg1 > 0:
            outgoing = runtime2.get("change_state")
            incoming = runtime1.get("change_state")
            if outgoing == "major": dmg1 = max(1, round(dmg1 * 1.25))
            elif outgoing == "minor": dmg1 = max(0, round(dmg1 * 0.75))
            if incoming == "major": dmg1 = max(1, round(dmg1 * 1.25))
            elif incoming == "minor": dmg1 = max(0, round(dmg1 * 0.75))
        if dmg2 > 0:
            outgoing = runtime1.get("change_state")
            incoming = runtime2.get("change_state")
            if outgoing == "major": dmg2 = max(1, round(dmg2 * 1.25))
            elif outgoing == "minor": dmg2 = max(0, round(dmg2 * 0.75))
            if incoming == "major": dmg2 = max(1, round(dmg2 * 1.25))
            elif incoming == "minor": dmg2 = max(0, round(dmg2 * 0.75))

        if "reflection" in effs1 and dmg1 > 0:
            dmg1 = reflection_incoming_damage(art1, char1, dmg1)
        if "reflection" in effs2 and dmg2 > 0:
            dmg2 = reflection_incoming_damage(art2, char2, dmg2)

        # 패닉 2배
        if is_stunned1 and dmg1 > 0: dmg1 *= 2; mental_dmg1 *= 2; clash_log += " (⚠️패닉 2배)"
        if is_stunned2 and dmg2 > 0: dmg2 *= 2; mental_dmg2 *= 2; clash_log += " (⚠️패닉 2배)"

        if state1.get("guardian_turn") != turn_count:
            state1["guardian_turn"] = turn_count
            state1["guardian_turn_used"] = False
        if state2.get("guardian_turn") != turn_count:
            state2["guardian_turn"] = turn_count
            state2["guardian_turn_used"] = False
        if hasattr(char1, "modify_incoming_damage"):
            dmg1 = char1.modify_incoming_damage(dmg1)
        if hasattr(char2, "modify_incoming_damage"):
            dmg2 = char2.modify_incoming_damage(dmg2)
        dmg1 = reduce_turn_first_damage(char1, dmg1, state1)
        dmg2 = reduce_turn_first_damage(char2, dmg2, state2)
        mental_dmg1 = reduce_guardian_mental_damage(char1, mental_dmg1, state1)
        mental_dmg2 = reduce_guardian_mental_damage(char2, mental_dmg2, state2)

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
            refl = reflection_damage(art1, char1, (dmg1 * 3) // 4)
            if refl > 0: char2.current_hp = max(0, char2.current_hp - refl); clash_log += f" 💢반사(-{refl})"
        if "reflection" in effs2 and dmg2 > 0:
            refl = reflection_damage(art2, char2, (dmg2 * 3) // 4)
            if refl > 0: char1.current_hp = max(0, char1.current_hp - refl); clash_log += f" 💢반사(-{refl})"

        absorb1 = next(
            (effect for effect in [d1.get("effect"), *d1.get("extra_effects", [])]
             if (effect or "").startswith("absorb_hp")),
            None,
        )
        absorb2 = next(
            (effect for effect in [d2.get("effect"), *d2.get("extra_effects", [])]
             if (effect or "").startswith("absorb_hp")),
            None,
        )
        if val_win1 and absorb1:
            ratio = 0.25 if absorb1 == "absorb_hp_25" else 1.0
            healed = max(0, int(dmg2 * ratio))
            char1.current_hp = min(char1.max_hp, char1.current_hp + healed)
            clash_log += f" 🧛흡혈(+{healed})"
        if val_win2 and absorb2:
            ratio = 0.25 if absorb2 == "absorb_hp_25" else 1.0
            healed = max(0, int(dmg1 * ratio))
            char2.current_hp = min(char2.max_hp, char2.current_hp + healed)
            clash_log += f" 🧛흡혈(+{healed})"

        # [시간가속] (합 승리 시)
        if d1.get("effect") == "time_accel" and val_win1:
            clash_log += gain_time_acceleration(char1, char2, effs1, turn_count)

        if d2.get("effect") == "time_accel" and val_win2:
            clash_log += gain_time_acceleration(char2, char1, effs2, turn_count)

        # 파괴 (루우데 각인 연동)
        if (
            val_win1
            and "destroy_next_on_hit" in [d1.get("effect"), *d1.get("extra_effects", [])]
            and i + 1 < len(res2)
        ):
            res2[i+1] = {"type": "none", "value": 0}; clash_log += " 💥파괴!"
            if "luude_imprint" in effs1: clash_log = apply_luude_logic(char1, char2, clash_log)
        
        if (
            val_win2
            and "destroy_next_on_hit" in [d2.get("effect"), *d2.get("extra_effects", [])]
            and i + 1 < len(res1)
        ):
            res1[i+1] = {"type": "none", "value": 0}; clash_log += " 💥파괴!"
            if "luude_imprint" in effs2: clash_log = apply_luude_logic(char2, char1, clash_log)

        # 최종 피해 적용
        actual_dmg1 = min(max(0, int(char1.current_hp)), max(0, int(dmg1)))
        actual_dmg2 = min(max(0, int(char2.current_hp)), max(0, int(dmg2)))
        char1.current_hp = max(0, char1.current_hp - dmg1)
        char2.current_hp = max(0, char2.current_hp - dmg2)
        char1.current_mental = max(0, char1.current_mental - mental_dmg1)
        char2.current_mental = max(0, char2.current_mental - mental_dmg2)

        # 혹한의 흡혈은 방어·피해감소를 모두 거친 실제 HP 피해만 사용한다.
        if dmg2 > 0:
            healed = apply_severe_cold_lifesteal(
                char1, char2, actual_dmg2, effs1
            )
            if healed > 0:
                clash_log += f" 🌨️혹한 흡혈(+{healed})"
        if dmg1 > 0:
            healed = apply_severe_cold_lifesteal(
                char2, char1, actual_dmg1, effs2
            )
            if healed > 0:
                clash_log += f" 🌨️혹한 흡혈(+{healed})"
        
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

    gem_log1 = pop_gem_activation_log(char1)
    gem_log2 = pop_gem_activation_log(char2)
    if gem_log1:
        log += f"\n💎 **{char1.name} 젬 발동** — {gem_log1}"
    if gem_log2:
        log += f"\n💎 **{char2.name} 젬 발동** — {gem_log2}"

    return log, damage_taken1, damage_taken2
