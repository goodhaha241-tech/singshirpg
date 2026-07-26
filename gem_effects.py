# gem-link-v4-effects
# rollback-guard-appraisal-gems-v8
"""Pure helpers for combat and artifact gem effects.

The battle engine can call these helpers at stable event points. They never
modify character-exclusive mechanics such as Kaian's time acceleration.
"""
from __future__ import annotations


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


def gem_named(source, name):
    return next(iter(gems_named(source, name)), None)


def gem_effect_total(source, name):
    return sum(int(gem.get("effect_value", 0) or 0) for gem in gems_named(source, name))


def gem_max_star(source, name):
    matches = gems_named(source, name)
    return max((int(gem.get("star", 0) or 0) for gem in matches), default=-1)


def turn_first_dice_bonus(source):
    return gem_effect_total(source, "선봉의 젬")


def single_dice_bonus(source):
    return gem_effect_total(source, "집중의 젬")


def multi_attack_bonus(source, attack_index):
    if not gems_named(source, "연격의 젬") or attack_index < 2:
        return 0
    return gem_effect_total(source, "연격의 젬") + (2 if attack_index >= 3 else 0)


def low_mental_bonus(source, current, maximum):
    if not gems_named(source, "결의의 젬") or maximum <= 0:
        return 0
    threshold = 0.5 if gem_max_star(source, "결의의 젬") >= 2 else 0.4
    return gem_effect_total(source, "결의의 젬") if current / maximum <= threshold else 0


def reduce_turn_first_damage(source, damage, state):
    if not gems_named(source, "수호의 젬") or damage <= 0 or state.get("guardian_turn_used"):
        return damage
    state["guardian_turn_used"] = True
    pct = min(40, gem_effect_total(source, "수호의 젬"))
    return max(0, round(damage * (100 - pct) / 100))


def cleanse_statuses_once(source, statuses, state):
    if (
        gem_max_star(source, "정화의 젬") < 5
        or state.get("cleanse_used")
        or not statuses
    ):
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
    name = names.get((artifact.get("special"), key))
    if not name:
        return value
    return value + gem_effect_total(artifact, name)
