# life-artifact-v5-events
"""Artifact event registry.

This registry separates common artifact hooks from character-exclusive
mechanics. Existing battle behavior remains authoritative while new code can
use these stable keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class EffectContext:
    actor: Any = None
    target: Any = None
    artifact: dict | None = None
    turn: int = 0
    damage: int = 0
    mental_damage: int = 0
    logs: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)


class ArtifactEventRegistry:
    def __init__(self):
        self._handlers: dict[str, list[tuple[int, Callable]]] = {}

    def register(self, event: str, handler: Callable, priority: int = 100):
        self._handlers.setdefault(event, []).append((priority, handler))
        self._handlers[event].sort(key=lambda pair: pair[0])

    def dispatch(self, event: str, context: EffectContext):
        for _, handler in self._handlers.get(event, []):
            handler(context)
        return context


COMMON_ARTIFACT_EFFECTS = {
    "reuse_last_dice": {"event": "on_dice_empty", "label": "꼼꼼한"},
    "fierce_attack": {"event": "on_attack_dice", "label": "맹렬한"},
    "sturdy_defense": {"event": "on_defense_dice", "label": "견고한"},
    "reflection": {"event": "after_damage", "label": "앙심품은"},
    "escalation": {"event": "on_turn_dice", "label": "고조된"},
    "immortality": {"event": "on_death", "label": "불멸의"},
}

CHARACTER_ARTIFACT_EFFECTS = {
    "youngsan_gold", "luude_imprint", "earthreg_faith",
    "sensho_star", "Sensho_star", "kaian_time", "shayla_light",
}

registry = ArtifactEventRegistry()
