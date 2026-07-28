import random
import unittest

import battle_engine
import boss_training
from cards import get_card
from recruitment import RECRUIT_REGISTRY


class DummyCombatant:
    def __init__(self, name="테스트", *, hp=1000, attack=100, defense=80):
        self.name = name
        self.max_hp = hp
        self.current_hp = hp
        self.max_mental = 500
        self.current_mental = 500
        self.attack = attack
        self.defense = defense
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
        self.status_immunity = None
        self.status_resistances = {}


class YeongseolDataTests(unittest.TestCase):
    def test_recruit_and_cards_are_registered(self):
        entry = RECRUIT_REGISTRY["Yeongseol"]
        self.assertEqual(entry["name"], "영설")
        self.assertEqual(entry["char_data"]["hp"], 220)
        self.assertEqual(entry["char_data"]["max_mental"], 240)
        self.assertEqual(
            entry["char_data"]["equipped_cards"],
            ["동결건조", "조선:아침", "조선:고요"],
        )
        self.assertEqual(
            [die.effect for die in get_card("동결건조").dice_list],
            ["freeze_3_on_win", None],
        )
        self.assertEqual(
            [die.action_type for die in get_card("조선:고요").dice_list],
            ["defense", "counter", "heal"],
        )

    def test_boss_catalog_has_freeze_and_severe_cold(self):
        self.assertEqual(boss_training.IMMUNITIES["freeze"][1], 300)
        self.assertEqual(boss_training.EFFECT_COSTS["freeze"], 150)
        self.assertEqual(boss_training.SPECIAL_SUPPORTS["영설"][1], 550)
        preset = boss_training.SPECIAL_SKILL_PRESETS["영설"]
        self.assertEqual(preset["name"], "백야의 동결")
        self.assertTrue(preset["is_aoe"])
        self.assertEqual(preset["cooldown"], 4)
        self.assertEqual(preset["purchase_cost"], 450)


class FreezeCombatTests(unittest.TestCase):
    def test_freeze_refreshes_to_longer_duration_and_ticks_once(self):
        source = DummyCombatant("영설")
        target = DummyCombatant("상대")
        self.assertEqual(battle_engine.apply_freeze_status(source, target, 3), 3)
        self.assertEqual(battle_engine.apply_freeze_status(source, target, 2), 0)
        self.assertEqual(target.status_effects["freeze"], 3)
        battle_engine.tick_freeze_end_of_turn(target, 1)
        battle_engine.tick_freeze_end_of_turn(target, 1)
        self.assertEqual(target.status_effects["freeze"], 2)
        battle_engine.tick_freeze_end_of_turn(target, 2)
        self.assertEqual(target.status_effects["freeze"], 1)

    def test_freeze_immunity_and_resistance_use_shared_api(self):
        source = DummyCombatant("영설")
        immune = DummyCombatant("면역")
        immune.status_immunity = "freeze"
        self.assertEqual(battle_engine.apply_freeze_status(source, immune, 5), 0)
        resistant = DummyCombatant("저항")
        resistant.status_resistances = {"freeze": 50}
        battle_engine.apply_freeze_status(source, resistant, 5)
        self.assertEqual(resistant.status_effects["freeze"], 3)

    def test_frozen_stats_floor_once(self):
        target = DummyCombatant(attack=101, defense=81)
        target.status_effects["freeze"] = 2
        self.assertEqual(battle_engine.effective_combat_stat(target, "attack"), 85)
        self.assertEqual(battle_engine.effective_combat_stat(target, "defense"), 68)

    def test_lock_count_distribution_and_aoe_positions(self):
        actor = DummyCombatant()
        actor.status_effects["freeze"] = 5
        rng = random.Random(7728)
        counts = []
        for turn in range(1, 401):
            dice = [
                {"type": "attack", "value": 10},
                {"type": "defense", "value": 10},
                {"type": "attack", "value": 10},
            ]
            battle_engine.apply_freeze_dice_lock(actor, dice, turn, rng)
            counts.append(sum(1 for die in dice if die.get("frozen")))
        self.assertTrue(160 <= counts.count(1) <= 240)
        self.assertTrue(160 <= counts.count(2) <= 240)

        first = [{"type": "attack", "value": 10} for _ in range(3)]
        second = [{"type": "attack", "value": 10} for _ in range(3)]
        battle_engine.apply_freeze_dice_lock(actor, first, 999, random.Random(1))
        battle_engine.apply_freeze_dice_lock(actor, second, 999, random.Random(9))
        first_locked = [i for i, die in enumerate(first) if die.get("frozen")]
        second_locked = [i for i, die in enumerate(second) if die.get("frozen")]
        self.assertEqual(first_locked, second_locked)

        only = [{"type": "none", "value": 0}, {"type": "attack", "value": 10}]
        battle_engine.apply_freeze_dice_lock(actor, only, 1000, random.Random(1))
        self.assertEqual(sum(1 for die in only if die.get("frozen")), 1)


class SevereColdTests(unittest.TestCase):
    def test_frost_counts_remaining_attack_dice_and_freezes_all_targets(self):
        actor = DummyCombatant("영설")
        actor.equipped_engraved_artifact = {
            "special": "yeongseol_severe_cold"
        }
        actor.runtime_cooldowns["yeongseol_frost"] = 2
        target1 = DummyCombatant("대상1")
        target2 = DummyCombatant("대상2")
        dice = [
            {"type": "attack", "value": 20},
            {"type": "attack", "value": 20},
            {"type": "none", "value": 0},
        ]
        log1 = battle_engine.process_severe_cold_before_clash(
            actor, target1, dice, ["yeongseol_severe_cold"], 1
        )
        log2 = battle_engine.process_severe_cold_before_clash(
            actor, target2, dice, ["yeongseol_severe_cold"], 1
        )
        trigger1 = battle_engine.trigger_severe_cold_for_die(
            actor, target1, 0, ["yeongseol_severe_cold"], 1
        )
        trigger2 = battle_engine.trigger_severe_cold_for_die(
            actor, target2, 0, ["yeongseol_severe_cold"], 1
        )
        self.assertEqual(actor.runtime_cooldowns["yeongseol_frost"], 1)
        self.assertEqual(target1.status_effects["freeze"], 5)
        self.assertEqual(target2.status_effects["freeze"], 5)
        self.assertIn("서리 +2", log1)
        self.assertEqual(log2, "")
        self.assertIn("혹한 발동", trigger1)
        self.assertIn("혹한 발동", trigger2)

    def test_triggering_attack_can_lifesteal_immediately(self):
        actor = DummyCombatant("영설")
        actor.current_hp = 500
        actor.equipped_engraved_artifact = {
            "special": "yeongseol_severe_cold"
        }
        actor.runtime_cooldowns["yeongseol_frost"] = 2
        target = DummyCombatant("대상")
        dice = [{"type": "attack", "value": 50}]
        battle_engine.process_severe_cold_before_clash(
            actor, target, dice, ["yeongseol_severe_cold"], 3
        )
        battle_engine.trigger_severe_cold_for_die(
            actor, target, 0, ["yeongseol_severe_cold"], 3
        )
        healed = battle_engine.apply_severe_cold_lifesteal(
            actor, target, 100, ["yeongseol_severe_cold"]
        )
        self.assertEqual(target.status_effects["freeze"], 5)
        self.assertEqual(healed, 20)
        self.assertEqual(actor.current_hp, 520)


class YeongseolSupportTests(unittest.TestCase):
    def test_support_specialty_and_sp_multiplier(self):
        support = {
            "name": "영설",
            "hp": 220,
            "attack": 34,
            "defense": 30,
            "max_mental": 240,
            "equipped_cards": ["동결건조"],
        }
        self.assertEqual(boss_training._support_specialty(support), "attack")
        base = {
            "mood": 3,
            "facility_levels": {"attack": 1},
            "growth_rates": {"attack": 0},
            "inherited_growth_bonus": {},
            "injured": False,
            "scenario_id": "normal",
            "sp": 0,
            "attack": 0,
        }
        one = dict(base)
        one["facility_levels"] = dict(base["facility_levels"])
        one["growth_rates"] = dict(base["growth_rates"])
        one["inherited_growth_bonus"] = {}
        boss_training._apply_growth(
            one, "attack", {"attack": 3, "sp": 12}, 0.0, 0.25
        )
        self.assertEqual(one["sp"], 15)
        two = dict(base)
        two["facility_levels"] = dict(base["facility_levels"])
        two["growth_rates"] = dict(base["growth_rates"])
        two["inherited_growth_bonus"] = {}
        boss_training._apply_growth(
            two, "attack", {"attack": 3, "sp": 12}, 0.0, 0.50
        )
        self.assertEqual(two["sp"], 18)
        self.assertEqual(one["attack"], two["attack"])

    def test_support_personality_is_documented(self):
        self.assertIn(
            "SP 획득량 +25%",
            boss_training.support_personality_text("영설"),
        )

    def test_stage_three_unlocks_all_three_card_hints_and_preset(self):
        run = {
            "turn": 20,
            "base_skill_hints": {},
            "base_upgrade_hints": {},
            "skill_hints": {},
            "special_preset_hints": {},
            "hint_history": [],
        }
        support = {
            "name": "영설",
            "specialty": "attack",
            "equipped_cards": ["동결건조", "조선:아침", "조선:고요"],
        }
        logs = boss_training._grant_stage_three_hints(
            run, support, random.Random(1)
        )
        self.assertEqual(
            set(run["skill_hints"]),
            {"동결건조", "조선:아침", "조선:고요"},
        )
        self.assertEqual(run["special_preset_hints"]["영설"], 1)
        self.assertTrue(any("백야" not in line and "강력 프리셋" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
