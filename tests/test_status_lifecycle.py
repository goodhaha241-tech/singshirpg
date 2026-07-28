import unittest

import battle_engine
from gem_effects import apply_ripple_to_dice


class DummyCombatant:
    def __init__(self, name="테스트"):
        self.name = name
        self.max_hp = 1_000
        self.current_hp = 1_000
        self.max_mental = 500
        self.current_mental = 500
        self.attack = 0
        self.defense = 0
        self.defense_rate = 0
        self.status_effects = {
            "bleed": 0,
            "paralysis": 0,
            "stun": 0,
            "freeze": 0,
        }
        self.runtime_cooldowns = {}
        self.general_passives = set()
        self.equipped_artifact = None
        self.equipped_engraved_artifact = None


class StatusLifecycleTests(unittest.TestCase):
    def test_bleed_consumes_on_damage_or_non_attack_die_but_only_once(self):
        actor = DummyCombatant()
        actor.status_effects["bleed"] = 4

        battle_engine.consume_die_statuses(
            actor, "attack", took_bleed_damage=False
        )
        self.assertEqual(actor.status_effects["bleed"], 4)

        battle_engine.consume_die_statuses(
            actor, "attack", took_bleed_damage=True
        )
        self.assertEqual(actor.status_effects["bleed"], 3)

        battle_engine.consume_die_statuses(
            actor, "counter", took_bleed_damage=True
        )
        self.assertEqual(actor.status_effects["bleed"], 2)

    def test_bleed_damage_consumption_is_wired_into_clash(self):
        bleeding = DummyCombatant("출혈 대상")
        attacker = DummyCombatant("공격자")
        bleeding.status_effects["bleed"] = 3

        battle_engine.process_clash_loop(
            bleeding,
            attacker,
            [{"type": "attack", "value": 5}],
            [{"type": "attack", "value": 10}],
            [],
            [],
            1,
        )

        self.assertEqual(bleeding.status_effects["bleed"], 2)
        self.assertLess(bleeding.current_hp, 990)

    def test_paralysis_consumes_on_every_non_attack_type(self):
        actor = DummyCombatant()
        actor.status_effects["paralysis"] = 4

        battle_engine.consume_die_statuses(actor, "attack")
        self.assertEqual(actor.status_effects["paralysis"], 4)
        for die_type, expected in (
            ("defense", 3),
            ("counter", 2),
            ("heal", 1),
            ("mental_heal", 0),
        ):
            battle_engine.consume_die_statuses(actor, die_type)
            self.assertEqual(actor.status_effects["paralysis"], expected)

    def test_paralysis_reduces_each_valid_die_by_two_per_stack(self):
        actor = DummyCombatant("마비 대상")
        target = DummyCombatant("상대")
        actor.status_effects["paralysis"] = 2
        dice = [{"type": "attack", "value": 10}]

        battle_engine.process_clash_loop(
            actor,
            target,
            dice,
            [{"type": "none", "value": 0}],
            [],
            [],
            1,
        )

        self.assertEqual(dice[0]["resolved_value"], 6)
        self.assertEqual(actor.status_effects["paralysis"], 2)

    def test_stun_ticks_once_only_after_skipped_action(self):
        actor = DummyCombatant()
        actor.status_effects["stun"] = 2

        self.assertEqual(
            battle_engine.tick_stun_after_skipped_action(actor, 7), 1
        )
        self.assertEqual(
            battle_engine.tick_stun_after_skipped_action(actor, 7), 0
        )
        self.assertEqual(actor.status_effects["stun"], 1)
        self.assertEqual(
            battle_engine.tick_stun_after_skipped_action(actor, 8), 1
        )
        self.assertEqual(actor.status_effects["stun"], 0)

    def test_stunned_actor_skips_action_and_takes_double_damage(self):
        actor = DummyCombatant("기절 대상")
        target = DummyCombatant("상대")
        actor.status_effects["stun"] = 2

        battle_engine.process_clash_loop(
            actor,
            target,
            [{"type": "none", "value": 0}],
            [{"type": "attack", "value": 10}],
            [],
            [],
            3,
            is_stunned1=True,
        )

        self.assertEqual(actor.current_hp, 980)
        self.assertEqual(actor.status_effects["stun"], 1)


class EncounterRuntimeTests(unittest.TestCase):
    def test_floor_reset_clears_artifact_timestamps_and_keeps_run_buffs(self):
        actor = DummyCombatant()
        actor.equipped_engraved_artifact = {"special": "ripple"}
        actor.runtime_cooldowns = {
            "guild_attack_bonus": 3,
            "fierce_attack": 8,
            "gem_state": {"ripple_last_turn": 8},
        }

        battle_engine.reset_encounter_runtime(
            actor, preserve_keys=("guild_attack_bonus",)
        )

        self.assertEqual(actor.runtime_cooldowns, {"guild_attack_bonus": 3})
        result = apply_ripple_to_dice(
            actor,
            [
                {"type": "attack", "value": 12},
                {"type": "attack", "value": 12},
            ],
            1,
        )
        self.assertIsNotNone(result)

    def test_special_owner_can_be_the_engraved_artifact(self):
        actor = DummyCombatant()
        actor.equipped_artifact = {"special": "unrelated"}
        engraved = {"special": "fierce_attack", "enhancement": 3}
        actor.equipped_engraved_artifact = engraved
        self.assertIs(
            battle_engine.artifact_for_special(actor, "fierce_attack"),
            engraved,
        )


if __name__ == "__main__":
    unittest.main()
