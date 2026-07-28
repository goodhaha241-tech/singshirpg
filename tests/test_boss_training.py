import random
import statistics
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import boss_training as boss
import life_system
from gem_effects import status_amount_after_resistance


def make_user(*, unlocked=True):
    shop = {}
    if unlocked:
        shop = {"growth_license": True, "base_stat_license": True}
    return {
        "money": 1_000_000,
        "pt": 1_000_000,
        "inventory": {boss.PURE_HOPE_ITEM: 10},
        "characters": [
            {"name": "영산", "hp": 270, "max_mental": 160, "attack": 25, "defense": 40, "level": 20},
            {"name": "어즈렉", "hp": 280, "max_mental": 200, "attack": 20, "defense": 50, "level": 20},
            {"name": "카이안", "hp": 250, "max_mental": 200, "attack": 30, "defense": 30, "level": 20},
        ],
        "life_data": {"boss_training": {"shop_unlocks": shop}},
    }


def borrowed_support(upgrade=0):
    return boss._snapshot_support(
        {"name": "센쇼", "hp": 180, "max_mental": 210, "attack": 28, "defense": 30, "level": 20},
        upgrade,
        "guild-member",
    )


def make_run(seed=1):
    user = make_user()
    return boss.create_training_run(
        user,
        "테스트 보스",
        {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5},
        [0, 1, 2],
        borrowed_support(2),
        base_tokens={"hp": 2, "mental": 1, "attack": 1, "defense": 1},
        rng=random.Random(seed),
    )


class BossTrainingCoreTests(unittest.TestCase):
    def test_growth_rates_are_exactly_thirty_percent(self):
        self.assertEqual(
            boss.validate_growth_rates(
                {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5}
            )["hp"],
            10,
        )
        with self.assertRaises(boss.BossTrainingError):
            boss.validate_growth_rates(
                {"hp": 10, "attack": 10, "defense": 10, "mental": 5, "tactics": 5}
            )
        with self.assertRaises(boss.BossTrainingError):
            boss.validate_growth_rates(
                {"hp": 7, "attack": 5, "defense": 5, "mental": 5, "tactics": 8}
            )

    def test_start_cost_is_not_spent_when_setup_is_invalid(self):
        user = make_user()
        before = (user["money"], user["pt"], user["inventory"][boss.PURE_HOPE_ITEM])
        with self.assertRaises(boss.BossTrainingError):
            boss.create_training_run(
                user,
                "테스트 보스",
                {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5},
                [0, 1],
                borrowed_support(),
            )
        self.assertEqual(
            before,
            (user["money"], user["pt"], user["inventory"][boss.PURE_HOPE_ITEM]),
        )

    def test_start_cost_and_base_tokens(self):
        user = make_user()
        run = boss.create_training_run(
            user,
            "테스트 보스",
            {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5},
            [0, 1, 2],
            borrowed_support(),
            base_tokens={"hp": 3, "mental": 1, "attack": 1},
        )
        self.assertEqual(user["money"], 700_000)
        self.assertEqual(user["pt"], 997_000)
        self.assertEqual(user["inventory"][boss.PURE_HOPE_ITEM], 8)
        self.assertEqual(run["hp"], 8_000)
        self.assertEqual(run["mental"], 3_000)
        self.assertEqual(run["attack"], 27)

    def test_support_upgrade_cost_curve_and_overflow_storage(self):
        user = make_user()
        state = boss.ensure_boss_training_data(user)
        state["support_fragments"]["카이안"] = 15
        for expected in range(1, 5):
            self.assertEqual(boss.upgrade_support(user, "카이안"), expected)
        self.assertEqual(state["support_fragments"]["카이안"], 5)
        with self.assertRaises(boss.BossTrainingError):
            boss.upgrade_support(user, "카이안")
        self.assertEqual(state["support_fragments"]["카이안"], 5)

    def test_gacha_has_support_fragment_result(self):
        self.assertEqual(
            (
                life_system.TOOL_GACHA_STONE_WEIGHT,
                life_system.TOOL_GACHA_TOOL_WEIGHT,
                life_system.TOOL_GACHA_SUPPORT_WEIGHT,
            ),
            (60, 35, 5),
        )
        user = make_user()
        with patch("life_system.random.choices", return_value=["support_fragment"]):
            with patch("boss_training.support_character_names", return_value=["카이안"]):
                result = life_system.draw_tool_gacha_result(user)
        self.assertEqual(result["kind"], "support_fragment")
        state = boss.ensure_boss_training_data(user)
        self.assertEqual(state["support_fragments"]["카이안"], 1)

    def test_training_finishes_at_turn_seventy(self):
        run = make_run()
        rng = random.Random(9)
        for _ in range(70):
            if run.get("pending_event_choice"):
                boss.resolve_support_event_choice(run, "sp")
            action = "rest" if run["energy"] < 35 else "hp"
            boss.perform_training_action(run, action, rng)
        self.assertEqual(run["turn"], 70)
        self.assertEqual(run["phase"], "build")
        self.assertEqual(len(run["evaluation_results"]), 5)
        record = boss.finalize_training_run(run)
        self.assertEqual(len(record["build"]["skills"]), 5)

    def test_skill_cost_and_aoe_multiplier(self):
        skill = {
            "name": "광역 출혈",
            "dice": [{"type": "attack", "min": 5, "max": 9}],
            "effects": ["bleed"],
            "cooldown": 2,
            "is_aoe": True,
        }
        self.assertEqual(boss.skill_sp_cost(skill), 110)
        card = boss.BossSkillCard(skill)
        self.assertEqual((card.dice_list[0].d_min, card.dice_list[0].d_max), (3, 6))

    def test_build_budget_rejects_overspend(self):
        run = make_run()
        run["phase"] = "build"
        run["turn"] = 70
        run["sp"] = 10
        run["build"]["skills"] = [{
            "name": "비싼 기술",
            "dice": [{"type": "attack", "min": 18, "max": 30}],
            "effects": ["destroy"],
            "cooldown": 1,
            "is_aoe": False,
        }]
        with self.assertRaises(boss.BossTrainingError):
            boss._require_build_budget(run)

    def test_grade_boundaries_include_ug_and_uf(self):
        self.assertEqual(boss.grade_for_score(7_500), "SS")
        self.assertEqual(boss.grade_for_score(9_000), "UG")
        self.assertEqual(boss.grade_for_score(11_000), "UF")

    def test_named_status_immunity_and_resistance(self):
        target = {
            "status_immunity": "stun",
            "status_resistances": {"bleed": 50},
            "status_effects": {},
        }
        self.assertEqual(status_amount_after_resistance(target, 3, "stun"), 0)
        self.assertEqual(status_amount_after_resistance(target, 4, "bleed"), 2)


class BossBalanceSimulationTests(unittest.TestCase):
    def test_five_hundred_seed_evaluation_distribution(self):
        platinum_wins = 0
        diamond_wins = 0
        scores = []
        for seed in range(500):
            rng = random.Random(seed)
            user = make_user()
            run = boss.create_training_run(
                user,
                "시뮬레이션 보스",
                {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5},
                [0, 1, 2],
                borrowed_support(2),
                base_tokens={"hp": 2, "mental": 1, "attack": 1, "defense": 1},
                rng=rng,
            )
            for _ in range(70):
                if run.get("pending_event_choice"):
                    boss.resolve_support_event_choice(run, "sp")
                if run["energy"] < 35:
                    action = "rest"
                else:
                    placed = [
                        key for key, indices in run["support_placements"].items() if indices
                    ]
                    action = rng.choice(placed or list(boss.GROWTH_KEYS))
                boss.perform_training_action(run, action, rng)
            won = {result["rank"] for result in run["evaluation_results"] if result["win"]}
            platinum_wins += "Platinum" in won
            diamond_wins += "Diamond" in won
            scores.append(boss._run_power_score(run))
        self.assertGreaterEqual(platinum_wins, 400)
        self.assertGreaterEqual(diamond_wins, 25)
        self.assertLessEqual(diamond_wins, 100)
        self.assertGreater(statistics.median(scores), 6_000)


if __name__ == "__main__":
    unittest.main()
