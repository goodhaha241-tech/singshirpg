# gem-link-v4-effects
# rollback-guard-appraisal-gems-v8
# pve-gem-runtime-v8.2
"""Runtime helpers for combat, artifact, and gem effects.

All displayed gem numbers and all runtime calculations use the same final
value helpers in this module.  Stored values remain the unscaled crafting
results so applying this patch never rewrites a player's gems.
"""
from __future__ import annotations

import math
import random


UNIQUE_STAR_PERCENT = (100, 108, 116, 130, 145, 165)
MAIN_STAR_PERCENT = (100, 104, 108, 115, 123, 135)
AUX_STAR_PERCENT = (100, 105, 110, 120, 130, 145)


def _star(value):
    return max(0, min(5, int(value or 0)))


def _scale(value, percent):
    value = max(0, int(value or 0))
    return int(math.floor(value * percent / 100 + 0.5))


def gem_final_effect_value(gem):
    if not isinstance(gem, dict):
        return 0
    return _scale(gem.get("effect_value", 0), UNIQUE_STAR_PERCENT[_star(gem.get("star"))])


def gem_final_main_value(gem):
    if not isinstance(gem, dict):
        return 0
    return _scale(gem.get("main_stat_value", 0), MAIN_STAR_PERCENT[_star(gem.get("star"))])


def gem_final_aux_value(gem):
    if not isinstance(gem, dict):
        return 0
    raw = gem.get("aux_stat_value", gem.get("stat_value", 0))
    return _scale(raw, AUX_STAR_PERCENT[_star(gem.get("star"))])


def equipped_artifacts(source):
    """Return every artifact represented by an artifact, character, or iterable."""
    if not source:
        return []
    if isinstance(source, (list, tuple, set)):
        result = []
        for item in source:
            result.extend(equipped_artifacts(item))
        return result
    if isinstance(source, dict):
        if "equipped_artifact" in source or "equipped_engraved_artifact" in source:
            return [
                artifact
                for artifact in (
                    source.get("equipped_artifact"),
                    source.get("equipped_engraved_artifact"),
                )
                if isinstance(artifact, dict)
            ]
        return [source] if any(key in source for key in ("gems", "special", "stats")) else []
    return [
        artifact
        for artifact in (
            getattr(source, "equipped_artifact", None),
            getattr(source, "equipped_engraved_artifact", None),
        )
        if isinstance(artifact, dict)
    ]


def equipped_gems(source):
    result = []
    for artifact in equipped_artifacts(source):
        result.extend(
            gem for gem in artifact.get("gems", []) if isinstance(gem, dict)
        )
    return result


def gems_named(source, name):
    return [gem for gem in equipped_gems(source) if gem.get("name") == name]


def gems_named_category(source, name, category):
    return [
        gem for gem in gems_named(source, name)
        if gem.get("category") == category
    ]


def gem_named(source, name):
    return next(iter(gems_named(source, name)), None)


def gem_effect_total(source, name):
    return sum(gem_final_effect_value(gem) for gem in gems_named(source, name))


def gem_effect_total_category(source, name, category):
    return sum(
        gem_final_effect_value(gem)
        for gem in gems_named_category(source, name, category)
    )


def gem_max_star(source, name):
    matches = gems_named(source, name)
    return max((_star(gem.get("star")) for gem in matches), default=-1)


def gem_max_star_category(source, name, category):
    matches = gems_named_category(source, name, category)
    return max((_star(gem.get("star")) for gem in matches), default=-1)


def runtime_cooldowns(source):
    """Return a persistent runtime dictionary for players and a safe one for monsters."""
    if source is None:
        return {}
    if isinstance(source, dict):
        runtime = source.get("runtime_cooldowns")
        if not isinstance(runtime, dict):
            runtime = {}
            source["runtime_cooldowns"] = runtime
        return runtime
    runtime = getattr(source, "runtime_cooldowns", None)
    if not isinstance(runtime, dict):
        runtime = {}
        try:
            source.runtime_cooldowns = runtime
        except (AttributeError, TypeError):
            pass
    return runtime


def gem_state(source):
    return runtime_cooldowns(source).setdefault("gem_state", {})


def status_store(source):
    if source is None:
        return {}
    statuses = source.get("status_effects") if isinstance(source, dict) else getattr(source, "status_effects", None)
    if not isinstance(statuses, dict):
        statuses = {}
        if isinstance(source, dict):
            source["status_effects"] = statuses
        else:
            try:
                source.status_effects = statuses
            except (AttributeError, TypeError):
                pass
    return statuses


# ---------------------------------------------------------------------------
# Common combat gems
# ---------------------------------------------------------------------------

def turn_first_dice_bonus(source, valid_index=0):
    value = gem_effect_total(source, "선봉의 젬")
    star = gem_max_star(source, "선봉의 젬")
    if valid_index == 0:
        return value
    if valid_index == 1 and star >= 3:
        return math.ceil(value / 2)
    if valid_index >= 2 and star >= 5:
        return math.ceil(value / 3)
    return 0


def single_dice_bonus(source, dice_type=None):
    value = gem_effect_total(source, "집중의 젬")
    star = gem_max_star(source, "집중의 젬")
    if star >= 5:
        value = math.ceil(value * 1.5)
    elif star >= 3:
        value = math.ceil(value * 1.25)
    return value


def multi_attack_bonus(source, attack_index):
    if not gems_named(source, "연격의 젬") or attack_index < 2:
        return 0
    value = gem_effect_total(source, "연격의 젬")
    star = gem_max_star(source, "연격의 젬")
    if attack_index >= 4 and star >= 5:
        return value * 2
    if attack_index >= 3 and star >= 3:
        return value + math.ceil(value / 2)
    return value


def low_mental_bonus(source, current, maximum):
    if not gems_named(source, "결의의 젬") or maximum <= 0:
        return 0
    star = gem_max_star(source, "결의의 젬")
    threshold = 0.60 if star >= 5 else (0.50 if star >= 3 else 0.40)
    return gem_effect_total(source, "결의의 젬") if current / maximum <= threshold else 0


def consume_balance_bonus(source):
    return max(0, int(gem_state(source).pop("balance_bonus", 0) or 0))


def record_balance_loss(source):
    value = gem_effect_total(source, "균형의 젬")
    if value <= 0:
        return 0
    star = gem_max_star(source, "균형의 젬")
    if star >= 5:
        value *= 2
    elif star >= 3:
        value = math.ceil(value * 1.5)
    state = gem_state(source)
    state["balance_bonus"] = max(int(state.get("balance_bonus", 0) or 0), value)
    return value


def consume_chain_bonus(source):
    return max(0, int(gem_state(source).pop("chain_bonus", 0) or 0))


def record_escalation_chain(source, rolled_bonus):
    pct = min(80, gem_effect_total(source, "연쇄의 젬"))
    if pct <= 0 or rolled_bonus <= 0:
        return 0
    amount = max(1, math.floor(rolled_bonus * pct / 100))
    gem_state(source)["chain_bonus"] = amount
    return amount


def escalation_roll(source, rng=None):
    rng = rng or random
    minimum = min(25, 1 + gem_effect_total(source, "고양의 젬"))
    rolls = 1
    if gems_named(source, "폭주의 젬"):
        star = gem_max_star(source, "폭주의 젬")
        rolls = 3 if star >= 5 else (2 if star >= 3 else 1)
        if star < 3 and rng.randint(1, 100) <= min(75, gem_effect_total(source, "폭주의 젬")):
            rolls += 1
    result = max(rng.randint(minimum, 30) for _ in range(rolls))
    record_escalation_chain(source, result)
    return result


def _apply_percent_reduction(damage, percent):
    return max(0, math.floor(max(0, damage) * (100 - max(0, min(90, percent))) / 100))


def reduce_turn_first_damage(source, damage, state=None):
    state = state if isinstance(state, dict) else gem_state(source)
    damage = max(0, int(damage or 0))
    if damage <= 0:
        return damage

    shield = max(0, int(state.get("artifact_shield", 0) or 0))
    if shield:
        absorbed = min(shield, damage)
        damage -= absorbed
        state["artifact_shield"] = shield - absorbed

    revive_guard = max(0, int(state.pop("revive_guard_pct", 0) or 0))
    if revive_guard:
        damage = _apply_percent_reduction(damage, revive_guard)

    endurance = max(0, int(state.pop("endurance_pct", 0) or 0))
    if endurance:
        damage = _apply_percent_reduction(damage, endurance)

    if (
        not gems_named(source, "수호의 젬")
        or damage <= 0
        or state.get("guardian_turn_used")
    ):
        return damage
    state["guardian_turn_used"] = True
    pct = min(60, gem_effect_total(source, "수호의 젬"))
    state["guardian_last_pct"] = pct
    if gem_max_star(source, "수호의 젬") >= 5:
        state["guardian_defense_bonus"] = max(
            int(state.get("guardian_defense_bonus", 0) or 0),
            max(1, math.ceil(pct / 2)),
        )
    return _apply_percent_reduction(damage, pct)


def reduce_guardian_mental_damage(source, mental_damage, state=None):
    state = state if isinstance(state, dict) else gem_state(source)
    if gem_max_star(source, "수호의 젬") < 3:
        return mental_damage
    return _apply_percent_reduction(mental_damage, state.get("guardian_last_pct", 0))


def consume_guardian_defense_bonus(source, dice_type):
    if dice_type != "defense":
        return 0
    return max(0, int(gem_state(source).pop("guardian_defense_bonus", 0) or 0))


def status_amount_after_resistance(source, amount):
    amount = max(0, int(amount or 0))
    if amount <= 0:
        return 0
    value = min(75, gem_effect_total_category(source, "정화의 젬", "combat_common"))
    reduced = math.ceil(amount * (100 - value) / 100)
    if gem_max_star_category(source, "정화의 젬", "combat_common") >= 3:
        reduced = max(0, reduced - 1)
    if gem_state(source).get("status_immunity_turns", 0) > 0:
        return 0
    return reduced


def cleanse_statuses_once(source, statuses=None, state=None):
    statuses = statuses if isinstance(statuses, dict) else status_store(source)
    state = state if isinstance(state, dict) else gem_state(source)
    if (
        gem_max_star_category(source, "정화의 젬", "combat_common") < 5
        or state.get("cleanse_used")
        or not any(int(value or 0) > 0 for value in statuses.values())
    ):
        return False
    for key in list(statuses):
        statuses[key] = 0
    state["cleanse_used"] = True
    return True


def process_gem_turn_start(source, target, turn_count, card_name=""):
    """Apply delayed and per-turn gem effects and return a compact battle log."""
    state = gem_state(source)
    logs = []

    if state.get("guardian_turn") != turn_count:
        state["guardian_turn"] = turn_count
        state["guardian_turn_used"] = False
        state["guardian_last_pct"] = 0

    if cleanse_statuses_once(source, status_store(source), state):
        logs.append("💠 [정화의 젬] 상태이상을 모두 제거")

    immunity = int(state.get("status_immunity_turns", 0) or 0)
    if immunity > 0:
        state["status_immunity_turns"] = immunity - 1

    ember = max(0, int(state.pop("ember_pending", 0) or 0))
    if ember and target is not None and getattr(target, "current_hp", 0) > 0:
        target.current_hp = max(0, target.current_hp - ember)
        logs.append(f"🔥 [잔불의 젬] 후속 피해 {ember}")

    cycle = gem_effect_total(source, "순환의 젬")
    previous = state.get("cycle_card")
    if cycle > 0 and card_name and previous and previous != card_name:
        star = gem_max_star(source, "순환의 젬")
        mental = cycle + (math.ceil(cycle / 2) if star >= 3 else 0)
        old_mental = int(getattr(source, "current_mental", 0) or 0)
        maximum = int(getattr(source, "max_mental", old_mental) or old_mental)
        source.current_mental = min(maximum, old_mental + mental)
        restored = source.current_mental - old_mental
        if restored:
            logs.append(f"🔄 [순환의 젬] 정신력 +{restored}")
        if star >= 5:
            old_hp = int(getattr(source, "current_hp", 0) or 0)
            max_hp = int(getattr(source, "max_hp", old_hp) or old_hp)
            source.current_hp = min(max_hp, old_hp + max(1, math.ceil(cycle / 2)))
    if card_name:
        state["cycle_card"] = card_name
    return "\n".join(logs)


# ---------------------------------------------------------------------------
# Dedicated artifact gems
# ---------------------------------------------------------------------------

def dedicated_value(source, name):
    return gem_effect_total(source, name)


def artifact_modifier(artifact, key, value):
    """Apply dedicated-gem numeric modifiers only to artifact-origin effects."""
    if not isinstance(artifact, dict):
        return value
    names = {
        ("fierce_attack", "damage"): "격화의 젬",
        ("sturdy_defense", "heal"): "맥박의 젬",
        ("reflection", "reflect"): "가시의 젬",
        ("escalation", "roll_min"): "고양의 젬",
    }
    name = names.get((artifact.get("special"), key))
    if not name:
        return value
    result = value + gem_effect_total(artifact, name)
    if (
        artifact.get("special") == "fierce_attack"
        and key == "damage"
        and gem_max_star(artifact, "도화선의 젬") >= 5
    ):
        result += gem_effect_total(artifact, "도화선의 젬")
    return result


def artifact_trigger_interval(artifact, special, default=2):
    if not isinstance(artifact, dict) or artifact.get("special") != special:
        return default
    name = {"fierce_attack": "도화선의 젬"}.get(special)
    if name and gem_max_star(artifact, name) >= 3:
        return 1
    return default


def reuse_dice_bonus(artifact):
    return dedicated_value(artifact, "복기의 젬")


def reuse_failure_bonus(artifact, state):
    value = dedicated_value(artifact, "교정의 젬")
    if value <= 0:
        return 0
    star = gem_max_star(artifact, "교정의 젬")
    cap = 3 if star >= 5 else (2 if star >= 3 else 1)
    stacks = min(cap, int(state.get("reuse_failure_stacks", 0) or 0) + 1)
    state["reuse_failure_stacks"] = stacks
    return stacks * value


def consume_reuse_failure_bonus(artifact, state):
    stacks = max(0, int(state.pop("reuse_failure_stacks", 0) or 0))
    return stacks * dedicated_value(artifact, "교정의 젬")


def empty_slot_guard(artifact):
    value = dedicated_value(artifact, "여백의 젬")
    star = gem_max_star(artifact, "여백의 젬")
    if star >= 5:
        return value * 2
    if star >= 3:
        return value + math.ceil(value / 2)
    return value


def record_fierce_aftereffect(artifact, fierce_value, source_state):
    pct = min(80, dedicated_value(artifact, "잔불의 젬"))
    if pct <= 0:
        return 0
    ember = max(1, math.floor(fierce_value * pct / 100))
    source_state["ember_pending"] = int(source_state.get("ember_pending", 0) or 0) + ember
    return ember


def sturdy_recovery(artifact, source, base_heal):
    heal = artifact_modifier(artifact, "heal", base_heal)
    old_hp = int(getattr(source, "current_hp", 0) or 0)
    max_hp = int(getattr(source, "max_hp", old_hp) or old_hp)
    actual = min(max_hp - old_hp, heal)
    source.current_hp = old_hp + max(0, actual)
    overflow = max(0, heal - max(0, actual))
    state = gem_state(source)
    consecration = min(100, dedicated_value(artifact, "축성의 젬"))
    shield = math.floor(overflow * consecration / 100) if overflow else 0
    if gem_max_star(artifact, "축성의 젬") >= 5 and heal > 0:
        shield += max(1, math.ceil(heal * 0.10))
    if shield:
        state["artifact_shield"] = int(state.get("artifact_shield", 0) or 0) + shield
    endurance = min(50, dedicated_value(artifact, "인내의 젬"))
    if endurance:
        if gem_max_star(artifact, "인내의 젬") >= 3:
            endurance += 5
        if gem_max_star(artifact, "인내의 젬") >= 5:
            state["status_immunity_turns"] = max(
                int(state.get("status_immunity_turns", 0) or 0), 2
            )
        state["endurance_pct"] = min(60, endurance)
    return max(0, actual), shield


def reflection_incoming_damage(artifact, source, damage):
    value = min(40, dedicated_value(artifact, "응보의 젬"))
    if value <= 0:
        return damage
    star = gem_max_star(artifact, "응보의 젬")
    if star >= 3:
        value += 5
    state = gem_state(source)
    if star >= 5:
        state["balance_bonus"] = max(
            int(state.get("balance_bonus", 0) or 0),
            dedicated_value(artifact, "응보의 젬"),
        )
    return _apply_percent_reduction(damage, min(50, value))


def reflection_damage(artifact, source, base_damage):
    state = gem_state(source)
    grudge = max(0, int(state.pop("grudge_bonus", 0) or 0))
    result = artifact_modifier(artifact, "reflect", base_damage) + grudge
    value = dedicated_value(artifact, "원한의 젬")
    if value:
        star = gem_max_star(artifact, "원한의 젬")
        multiplier = 3 if star >= 5 else (2 if star >= 3 else 1)
        state["grudge_bonus"] = value * multiplier
    return result


def revive_gem_effects(source):
    state = gem_state(source)
    logs = []
    return_value = gem_effect_total(source, "회귀의 젬")
    if return_value:
        state["revive_guard_pct"] = min(60, return_value)
        state["balance_bonus"] = max(
            int(state.get("balance_bonus", 0) or 0),
            max(1, math.ceil(return_value / 2)),
        )
        logs.append(f"회귀: 다음 피해 {min(60, return_value)}% 감소")

    dedicated_cleanse = [
        gem for gem in gems_named(source, "정화의 젬")
        if gem.get("category") == "dedicated"
    ]
    if dedicated_cleanse:
        star = max(_star(gem.get("star")) for gem in dedicated_cleanse)
        value = sum(gem_final_effect_value(gem) for gem in dedicated_cleanse)
        statuses = status_store(source)
        if star >= 3:
            for key in list(statuses):
                statuses[key] = 0
            logs.append("정화: 상태이상 전부 제거")
        else:
            for key, amount in list(statuses.items()):
                statuses[key] = max(0, math.floor(int(amount or 0) * (100 - min(90, value)) / 100))
        if star >= 5:
            state["status_immunity_turns"] = max(
                int(state.get("status_immunity_turns", 0) or 0), 2
            )
    return " · ".join(logs)


def battle_end_gem_heal(source):
    value = gem_effect_total(source, "여명의 젬")
    if value <= 0:
        return 0
    star = gem_max_star(source, "여명의 젬")
    if star >= 5:
        value *= 2
    elif star >= 3:
        value += math.ceil(value / 2)
    old = int(getattr(source, "current_hp", 0) or 0)
    maximum = int(getattr(source, "max_hp", old) or old)
    source.current_hp = min(maximum, old + value)
    return source.current_hp - old


GEM_STAR_UNLOCKS = {
    "복기의 젬": ("재사용 주사위 보정 강화", "재사용 주사위 보정 대폭 강화"),
    "교정의 젬": ("교정 보너스 최대 2회 누적", "교정 보너스 최대 3회 누적"),
    "여백의 젬": ("빈 구간 방어 보정 150%", "빈 구간 방어 보정 200%"),
    "격화의 젬": ("맹렬 추가 위력 성급 증폭", "맹렬 추가 위력 최대 증폭"),
    "도화선의 젬": ("맹렬 발동 간격 1턴", "맹렬 발동 후 잔불 연계 강화"),
    "잔불의 젬": ("잔불 전환율 성급 증폭", "잔불 전환율 최대 증폭"),
    "맥박의 젬": ("회복량 성급 증폭", "회복량 최대 증폭"),
    "축성의 젬": ("초과 회복 보호막 효율 강화", "초과 회복이 없어도 회복량 10% 보호막"),
    "인내의 젬": ("피해 경감 +5%p", "견고 발동 후 상태이상 1턴 면역"),
    "가시의 젬": ("반사량 성급 증폭", "반사량 최대 증폭"),
    "원한의 젬": ("다음 반사 누적량 2배", "다음 반사 누적량 3배"),
    "응보의 젬": ("피해 경감 +5%p", "반사 후 다음 주사위 보너스"),
    "고양의 젬": ("고조 최솟값 성급 증폭", "고조 최솟값 최대 증폭"),
    "폭주의 젬": ("고조 보너스를 2회 굴려 높은 값 선택", "3회 굴려 높은 값 선택"),
    "연쇄의 젬": ("전달 비율 성급 증폭", "전달 비율 최대 증폭"),
    "회귀의 젬": ("부활 후 보호 효과 강화", "부활 후 보호 효과 최대 강화"),
    "여명의 젬": ("전투 종료 회복량 150%", "전투 종료 회복량 200%"),
    "선봉의 젬": ("두 번째 유효 주사위에도 50% 적용", "세 번째 이후에도 33% 적용"),
    "균형의 젬": ("다음 주사위 보너스 150%", "다음 주사위 보너스 200%"),
    "수호의 젬": ("첫 실피해의 정신 피해도 함께 감소", "발동 후 다음 방어 주사위 강화"),
    "집중의 젬": ("단일 주사위 보너스 125%", "단일 주사위 보너스 150%"),
    "연격의 젬": ("세 번째 이후 공격 보너스 150%", "네 번째 이후 공격 보너스 200%"),
    "결의의 젬": ("발동 기준 정신력 50%", "발동 기준 정신력 60%"),
    "순환의 젬": ("교대 사용 정신 회복량 150%", "교대 사용 시 체력도 추가 회복"),
    "풍요의 젬": ("품질 70 이상 수확량 +1", "품질 85 이상 수확량 추가 +1"),
    "경작의 젬": ("최종 품질 추가 +5", "최종 품질 추가 +10"),
    "관개의 젬": ("과습 건강 감소 방지", "물주기 시 건강 +2"),
    "청류의 젬": ("자연 수질 감소 완화·질병 1회 방지", "고수질 출하 품질 +6"),
    "양식의 젬": ("첫 먹이 수질 감소 없음", "출하 수량 +1 확률 25%"),
    "장인의 젬": ("세공 성공률 추가 +3%p", "세공 성공률 추가 +7%p"),
    "조리의 젬": ("훌륭함 가중치 추가 +5", "걸작 가중치 추가 +3"),
}


def gem_star_unlock_lines(gem):
    if not isinstance(gem, dict):
        return []
    name = gem.get("name")
    star = _star(gem.get("star"))
    unlocks = GEM_STAR_UNLOCKS.get(name)
    if not unlocks:
        return []
    result = []
    if star >= 3:
        result.append(f"3성: {unlocks[0]}")
    if star >= 5:
        result.append(f"5성: {unlocks[1]}")
    return result
