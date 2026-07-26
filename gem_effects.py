# gem-link-v4-effects
"""Pure helpers for combat and artifact gem effects.

The battle engine can call these helpers at stable event points. They never
modify character-exclusive mechanics such as Kaian's time acceleration.
"""
from __future__ import annotations


def equipped_gems(artifact):
    if not artifact:
        return []
    return [g for g in artifact.get("gems", []) if isinstance(g, dict)]


def gem_named(artifact, name):
    return next((g for g in equipped_gems(artifact) if g.get("name") == name), None)


def turn_first_dice_bonus(artifact):
    gem = gem_named(artifact, "선봉의 젬")
    return int(gem.get("effect_value", 0)) if gem else 0


def single_dice_bonus(artifact):
    gem = gem_named(artifact, "집중의 젬")
    return int(gem.get("effect_value", 0)) if gem else 0


def multi_attack_bonus(artifact, attack_index):
    gem = gem_named(artifact, "연격의 젬")
    if not gem or attack_index < 2:
        return 0
    return int(gem.get("effect_value", 0)) + (2 if attack_index >= 3 else 0)


def low_mental_bonus(artifact, current, maximum):
    gem = gem_named(artifact, "결의의 젬")
    if not gem or maximum <= 0:
        return 0
    threshold = 0.5 if int(gem.get("star", 0)) >= 2 else 0.4
    return int(gem.get("effect_value", 0)) if current / maximum <= threshold else 0


def reduce_turn_first_damage(artifact, damage, state):
    gem = gem_named(artifact, "수호의 젬")
    if not gem or damage <= 0 or state.get("guardian_turn_used"):
        return damage
    state["guardian_turn_used"] = True
    pct = min(40, int(gem.get("effect_value", 0)))
    return max(0, round(damage * (100 - pct) / 100))


def cleanse_statuses_once(artifact, statuses, state):
    gem = gem_named(artifact, "정화의 젬")
    if not gem or int(gem.get("star", 0)) < 5 or state.get("cleanse_used") or not statuses:
        return False
    statuses.clear()
    state["cleanse_used"] = True
    return True


def artifact_modifier(artifact, key, value):
    """Apply dedicated-gem numeric modifiers only to artifact-origin effects."""
    names = {
        ("fierce_attack", "damage"): "격화의 젬",
        ("sturdy_defense", "heal"): "맥박의 젬",
        ("reflection", "reflect"): "가시의 젬",
        ("escalation", "roll_min"): "고양의 젬",
    }
    gem = gem_named(artifact, names.get((artifact.get("special"), key)))
    if not gem:
        return value
    return value + int(gem.get("effect_value", 0))
