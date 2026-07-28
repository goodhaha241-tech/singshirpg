import random
import statistics
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch


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
        {
            "name": "센쇼",
            "hp": 180,
            "max_mental": 210,
            "attack": 28,
            "defense": 30,
            "level": 20,
            "equipped_cards": ["기본공격"],
        },
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
        self.assertEqual(boss.grade_for_score(8_999), "S")
        self.assertEqual(boss.grade_for_score(9_000), "SS")
        self.assertEqual(boss.grade_for_score(11_000), "UG")
        self.assertEqual(boss.grade_for_score(13_000), "UF")

    def test_user_boss_grade_rewards_and_self_discount(self):
        self.assertEqual(
            boss.user_boss_grade_reward("UF"),
            {"money": 25_000, "pt": 5_000, "contribution": 500},
        )
        self.assertEqual(
            boss.user_boss_grade_reward("S"),
            {"money": 10_000, "pt": 2_000, "contribution": 200},
        )
        self.assertEqual(
            boss.user_boss_grade_reward("UF", factor=0.7),
            {"money": 17_500, "pt": 3_500, "contribution": 350},
        )

    def test_dungeon_generation_is_deterministic_and_uses_full_budget(self):
        completed = {
            "boss_id": "dungeon-boss",
            "name": "던전 보스",
            "power_score": 10_000,
            "hp": 10_000,
            "mental": 4_000,
            "attack": 80,
            "defense": 70,
            "factors": [
                {"kind": "stat", "stat": "hp", "stars": 3},
                {"kind": "stat", "stat": "attack", "stars": 2},
                {"kind": "growth", "specialty": "attack", "stars": 3},
            ],
            "created_at": "2026-07-28T00:00:00+09:00",
        }
        state = boss.default_dungeon_builder_state(completed)
        state["names"] = ["화염 문지기", "강철 문지기", "서리 문지기"]
        first = boss.build_dungeon_spec(
            completed, boss.dungeon_builder_configs(state)
        )
        second = boss.build_dungeon_spec(
            completed, boss.dungeon_builder_configs(state)
        )
        self.assertEqual(first, second)
        self.assertTrue(first["locked"])
        self.assertEqual(
            sum(monster["share"] for monster in first["monsters"]),
            100,
        )
        self.assertEqual(first["elite"]["target_score"], 8_000)
        self.assertEqual(len(first["monsters"]), 3)
        self.assertTrue(all(len(monster["skills"]) == 3 for monster in first["monsters"]))
        for monster in [*first["monsters"], first["elite"]]:
            generated_score = (
                monster["hp"] // 20
                + monster["mental"] // 20
                + monster["attack"] * 25
                + monster["defense"] * 25
                + monster["skill_score"]
            )
            self.assertEqual(generated_score, monster["target_score"])

    def test_dungeon_factor_rules_and_share_validation(self):
        completed = {
            "boss_id": "factor-dungeon",
            "name": "인자 던전",
            "power_score": 8_000,
            "hp": 8_000,
            "mental": 2_000,
            "attack": 60,
            "defense": 50,
            "factors": [
                {"kind": "stat", "stat": "hp", "stars": 2},
                {"kind": "growth", "specialty": "hp", "stars": 3},
            ],
        }
        factors = boss.eligible_dungeon_factors(completed)
        self.assertGreaterEqual(len(factors), 3)
        self.assertNotIn("growth", {factor["kind"] for factor in factors})
        with self.assertRaises(boss.BossTrainingError):
            boss.validate_dungeon_shares([35, 35, 35])
        with self.assertRaises(boss.BossTrainingError):
            boss.validate_dungeon_shares([15, 45, 40])
        self.assertEqual(boss.validate_dungeon_shares([35, 35, 30]), [35, 35, 30])
        self.assertEqual(boss.USER_BOSS_HOPE_REWARDS["SS"], 2)
        self.assertEqual(boss.USER_BOSS_HOPE_REWARDS["UG"], 3)
        self.assertEqual(boss.USER_BOSS_HOPE_REWARDS["UF"], 4)

    def test_named_status_immunity_and_resistance(self):
        target = {
            "status_immunity": "stun",
            "status_resistances": {"bleed": 50},
            "status_effects": {},
        }
        self.assertEqual(status_amount_after_resistance(target, 3, "stun"), 0)
        self.assertEqual(status_amount_after_resistance(target, 4, "bleed"), 2)

    def test_selected_hint_probability_curve(self):
        support = {"bond": 0, "upgrade": 0}
        self.assertEqual(boss._skill_hint_chance(support), 0.10)
        support.update(bond=40)
        self.assertEqual(boss._skill_hint_chance(support), 0.20)
        support.update(bond=80)
        self.assertEqual(boss._skill_hint_chance(support), 0.30)
        support.update(upgrade=4)
        self.assertEqual(boss._skill_hint_chance(support), 0.38)

    def test_friendship_training_requires_matching_specialty(self):
        class SafeRng:
            def randint(self, low, high):
                return high

            def random(self):
                return 1.0

            def choice(self, values):
                return values[0]

        matching = make_run()
        matching["support_placements"] = {key: [] for key in boss.GROWTH_KEYS}
        matching["support_placements"]["hp"] = [0]
        matching["supports"][0].update(
            specialty="hp", bond=80, level=0, upgrade=0, event_stage=3
        )
        mismatching = deepcopy(matching)
        mismatching["supports"][0]["specialty"] = "attack"

        matching_result = boss.perform_training_action(matching, "hp", SafeRng())
        mismatching_result = boss.perform_training_action(
            mismatching, "hp", SafeRng()
        )
        self.assertGreater(
            matching_result["gains"]["hp"], mismatching_result["gains"]["hp"]
        )
        self.assertEqual(matching_result["friendship_supports"], ["영산"])
        self.assertEqual(mismatching_result["friendship_supports"], [])

    def test_all_supports_grant_base_hints_on_stage_three(self):
        class EventRng:
            def randint(self, low, high):
                return high

            def random(self):
                return 0.0

            def choice(self, values):
                return values[0]

        run = make_run()
        run["support_placements"] = {key: [] for key in boss.GROWTH_KEYS}
        run["support_placements"]["attack"] = [0]
        run["supports"][0].update(
            name="특수능력 없는 캐릭터",
            specialty="attack",
            bond=100,
            event_stage=2,
            owner_id="self",
            equipped_cards=["기본공격"],
        )
        result = boss.perform_training_action(run, "attack", EventRng())
        self.assertEqual(run["supports"][0]["event_stage"], 3)
        self.assertEqual(run["base_skill_hints"]["attack"], 1)
        self.assertEqual(run["base_upgrade_hints"]["attack"], 1)
        self.assertEqual(run["skill_hints"]["기본공격"], 1)
        self.assertFalse(run["inheritance_candidates"])
        self.assertTrue(any("연속 이벤트 완주" in line for line in result["logs"]))

    def test_skill_offers_stay_hidden_and_discount_to_forty_percent(self):
        run = make_run()
        run["phase"] = "build"
        run["turn"] = 70
        run["sp"] = 1_000
        self.assertEqual(boss.available_skill_offers(run), [])

        run["base_upgrade_hints"]["hp"] = 1
        offer = boss.available_skill_offers(run)[0]
        self.assertEqual(offer["base_cost"], 120)
        self.assertEqual(boss._discounted_cost(offer["base_cost"], 1), 108)

        run["base_upgrade_hints"]["hp"] = 4
        purchased = boss.purchase_skill_offer(run, "base:hp:upgrade", 0)
        self.assertEqual(purchased["purchase_cost"], 72)
        self.assertEqual(purchased["hint_discount"], 40)
        self.assertEqual(run["build"]["skills"][0]["name"], "중급회복")
        restored = boss.restore_default_skill(run, 0)
        self.assertTrue(restored["free"])

    def test_training_failure_rate_display_value(self):
        run = make_run()
        run["energy"] = 25
        self.assertEqual(boss.training_failure_rate(run), 25)
        run["injured"] = True
        self.assertEqual(boss.training_failure_rate(run), 40)
        run["energy"] = 0
        self.assertEqual(boss.training_failure_rate(run), 60)

    def test_training_history_keeps_only_three_turns(self):
        run = make_run()
        rng = random.Random(123)
        for _ in range(5):
            boss.perform_training_action(run, "rest", rng)
        self.assertEqual([entry["turn"] for entry in run["history"]], [3, 4, 5])

    def test_tactics_recovers_energy_and_grants_cross_growth(self):
        class SafeRng:
            def randint(self, low, high):
                return high

            def random(self):
                return 1.0

            def choice(self, values):
                return values[0]

        run = make_run()
        run["energy"] = 50
        run["support_placements"] = {key: [] for key in boss.GROWTH_KEYS}
        result = boss.perform_training_action(run, "tactics", SafeRng())
        self.assertEqual(run["energy"], 55)
        self.assertEqual(
            set(result["gains"]),
            {"mental", "attack", "sp"},
        )
        self.assertEqual(boss.TRAINING_ACTIONS["tactics"]["gains"], {
            "attack": 2, "mental": 30, "sp": 35,
        })

    def test_cross_training_values_and_tactics_failure_energy(self):
        self.assertEqual(
            boss.TRAINING_ACTIONS["hp"]["gains"],
            {"hp": 350, "defense": 2, "mental": 30, "sp": 8},
        )
        self.assertEqual(
            boss.TRAINING_ACTIONS["mental"]["gains"],
            {"mental": 220, "attack": 2, "defense": 1, "sp": 8},
        )
        self.assertEqual(
            boss.TRAINING_ACTIONS["defense"]["gains"],
            {"defense": 3, "hp": 180, "mental": 30, "sp": 8},
        )
        self.assertEqual(
            boss.TRAINING_ACTIONS["attack"]["gains"],
            {"attack": 3, "mental": 110, "sp": 12},
        )

        class FailRng:
            def randint(self, low, high):
                return low

            def random(self):
                return 1.0

            def choice(self, values):
                return values[0]

        run = make_run()
        run["energy"] = 0
        before = (run["attack"], run["mental"], run["sp"])
        result = boss.perform_training_action(run, "tactics", FailRng())
        self.assertFalse(result["success"])
        self.assertEqual(run["energy"], 5)
        self.assertEqual((run["attack"], run["mental"], run["sp"]), before)

    def test_deterministic_factors_inheritance_and_passive_discount(self):
        parent_data = {
            "boss_id": "parent-1",
            "name": "부모",
            "grade": "UF",
            "hp": 20_000,
            "mental": 4_000,
            "attack": 120,
            "defense": 80,
            "growth_rates": {
                "hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5
            },
            "inherited_growth_bonus": {"attack": 10},
            "build": {
                "skills": [deepcopy(boss.BASE_SKILL_FAMILIES["attack"]["upgrade"])],
                "passives": ["hp_regen"],
            },
            "hint_catalog": [],
        }
        record = {
            "boss_id": "parent-1",
            "boss_name": "부모",
            "grade": "UF",
            "boss_data": parent_data,
        }
        first, _ = boss.ensure_completed_boss_factors(record)
        second, _ = boss.ensure_completed_boss_factors(record)
        self.assertEqual(first["boss_data"]["factors"], second["boss_data"]["factors"])
        self.assertEqual(
            [factor["kind"] for factor in first["boss_data"]["factors"][:3]],
            ["stat", "stat", "growth"],
        )

        run = make_run()
        run["inheritance_parents"] = [{
            "name": "부모",
            "grade": "UF",
            "factors": [
                {"kind": "stat", "stat": "hp", "stars": 3},
                {"kind": "growth", "specialty": "attack", "stars": 3},
                {"kind": "passive_discount", "passive": "hp_regen", "stars": 3},
            ],
        }]
        run["inheritance_events_done"] = []
        before_hp = run["hp"]
        boss._apply_inheritance_event(run, "start", random.Random(1))
        self.assertEqual(run["hp"], before_hp + 500)
        self.assertEqual(run["inherited_growth_bonus"]["attack"], 10)
        self.assertEqual(run["passive_factor_discounts"]["hp_regen"], 30)
        run["build"]["passives"] = ["hp_regen"]
        self.assertEqual(
            boss._build_sp_cost(run, run["build"]),
            84,
        )
        boss._apply_inheritance_event(run, "mid", random.Random(2))
        boss._apply_inheritance_event(run, "late", random.Random(3))
        after_three = run["hp"]
        boss._apply_inheritance_event(run, "late", random.Random(999))
        self.assertEqual(run["hp"], after_three)
        self.assertEqual(run["hp"], before_hp + 1_500)
        self.assertEqual(run["inheritance_events_done"], ["start", "mid", "late"])

    def test_facility_expansion_scenario_requires_unlock_and_applies_bonuses(self):
        user = make_user()
        with self.assertRaises(boss.BossTrainingError):
            boss.create_training_run(
                user,
                "시설 테스트",
                {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5},
                [0, 1, 2],
                borrowed_support(),
                base_tokens={"hp": 2, "mental": 1, "attack": 1, "defense": 1},
                scenario_id="facility_expansion",
            )
        user = make_user()
        user["life_data"]["boss_training"]["shop_unlocks"][
            "scenario_facility_expansion"
        ] = True
        run = boss.create_training_run(
            user,
            "시설 테스트",
            {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5},
            [0, 1, 2],
            borrowed_support(),
            base_tokens={"hp": 2, "mental": 1, "attack": 1, "defense": 1},
            scenario_id="facility_expansion",
        )
        self.assertEqual(run["scenario_id"], "facility_expansion")
        self.assertEqual(boss.SCENARIOS[run["scenario_id"]]["facility_cap"], 6)
        normal = deepcopy(run)
        normal["scenario_id"] = "normal"
        normal["hp"] = 0
        run["hp"] = 0
        self.assertEqual(boss._apply_growth(normal, "hp", {"hp": 100}, 0)["hp"], 110)
        self.assertEqual(boss._apply_growth(run, "hp", {"hp": 100}, 0)["hp"], 126)
        run.update(hp=100_000, mental=100_000, attack=1_000, defense=1_000)
        run["evaluation_results"] = []
        run["sp"] = 0
        result = boss._simulate_evaluation(run, 70, random.Random(1))
        self.assertTrue(result["win"])
        self.assertEqual(result["sp"], 240)

    def test_all_five_support_specialties_can_appear(self):
        examples = [
            {"hp": 1_000},
            {"max_mental": 1_000},
            {"attack": 100},
            {"defense": 100},
            {"equipped_cards": ["밀키워킹"]},
        ]
        self.assertEqual(
            {boss._support_specialty(character) for character in examples},
            set(boss.GROWTH_KEYS),
        )


class BossTrainingViewSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_dungeon_builder_uses_button_select_ui_and_short_factor_ids(self):
        author = type("Author", (), {"id": 1, "display_name": "테스터"})()
        record = {
            "boss_id": "builder",
            "boss_name": "제작 보스",
            "grade": "UG",
            "power_score": 10_000,
            "boss_data": {
                "boss_id": "builder",
                "name": "제작 보스",
                "power_score": 10_000,
                "hp": 10_000,
                "mental": 3_000,
                "attack": 80,
                "defense": 70,
                "factors": [
                    {"kind": "stat", "stat": "hp", "stars": 3},
                    {"kind": "stat", "stat": "attack", "stars": 2},
                    {"kind": "stat", "stat": "defense", "stars": 1},
                ],
            },
        }
        view = boss.BossDungeonBuilderView(
            author,
            {"guild_id": 1},
            active_run=False,
            record=record,
        )
        await view.setup()
        try:
            self.assertEqual(len(view.children), 7)
            self.assertEqual(
                [getattr(item, "row", None) for item in view.children],
                [0, 1, 2, 3, 4, 4, 4],
            )
            factor_select = view.children[3]
            self.assertTrue(all(len(option.value) == 32 for option in factor_select.options))
            self.assertIn("혼합 엘리트", view.get_embed().fields[-1].name)
        finally:
            view.stop()

    async def test_public_bosses_are_available_as_inheritance_parents(self):
        owned = [{
            "boss_id": "owned",
            "owner_id": "1",
            "boss_name": "내 보스",
            "publish_scope": None,
        }]
        guild_public = [{
            "boss_id": "guild",
            "owner_id": "2",
            "boss_name": "길드 보스",
            "publish_scope": "guild",
        }]
        world_public = [
            {
                "boss_id": "world",
                "owner_id": "3",
                "boss_name": "월드 보스",
                "publish_scope": "world",
            },
            # The guild query can also contain a world boss from this guild;
            # it must still appear only once.
            {
                "boss_id": "guild",
                "owner_id": "2",
                "boss_name": "길드 보스",
                "publish_scope": "guild",
            },
        ]
        with (
            patch(
                "boss_training.list_owned_bosses",
                new=AsyncMock(return_value=owned),
            ),
            patch(
                "boss_training.list_published_bosses",
                new=AsyncMock(side_effect=[guild_public, world_public]),
            ),
        ):
            rows = await boss.list_inheritance_parent_bosses(1, 99)
        self.assertEqual(
            [row["boss_id"] for row in rows],
            ["owned", "guild", "world"],
        )
        self.assertEqual(
            [boss.inheritance_source_label(row) for row in rows],
            ["내 보스", "길드 공개", "월드 공개"],
        )

    async def test_button_skill_wizard_and_build_view_construct(self):
        author = type("Author", (), {"id": 1, "display_name": "테스터"})()
        wizard = boss.BossSkillWizardView(
            author,
            {"guild_id": 1},
            0,
            total_sp=500,
            other_allocated_cost=100,
        )
        self.assertEqual(
            [item.label for item in wizard.children if "주사위" in item.label],
            ["주사위 1개", "주사위 2개", "주사위 3개"],
        )
        wizard.dice = [{"type": "attack", "min": 12, "max": 20}]
        self.assertIn("현재 설계 비용 **75**", wizard.get_embed().fields[-1].value)
        self.assertIn("저장 후 남은 SP **325**", wizard.get_embed().fields[-1].value)
        build = boss.BossBuildView(author, {"guild_id": 1})
        self.assertIn(
            "🎴 스킬 편집",
            [getattr(item, "label", None) for item in build.children],
        )

    async def test_training_uses_separate_main_support_and_log_embeds(self):
        user = make_user()
        boss.create_training_run(
            user,
            "임베드 테스트",
            {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5},
            [0, 1, 2],
            borrowed_support(),
            base_tokens={"hp": 2, "mental": 1, "attack": 1, "defense": 1},
        )
        author = type("Author", (), {"id": 1, "display_name": "테스터"})()
        view = boss.BossTrainingRunView(author, {"guild_id": 1})
        with patch("boss_training.get_user_data", new=AsyncMock(return_value=user)):
            embeds = await view.get_embeds()
        self.assertEqual(len(embeds), 3)
        self.assertNotIn(
            "교차 성장",
            [field.name for field in embeds[0].fields],
        )
        self.assertEqual(embeds[0].fields[-1].name, "현재 컨디션")
        self.assertIn("훈련별 참가 서포트", embeds[1].title)
        self.assertEqual(embeds[1].fields[0].name, "💞 인연 정보")
        self.assertIn("최근 3턴", embeds[2].title)
        self.assertIn(
            "🧬 인자 확인",
            [getattr(item, "label", None) for item in view.children],
        )

    async def test_factor_text_is_visible_in_archive(self):
        author = type("Author", (), {"id": 1, "display_name": "테스터"})()
        record = {
            "boss_id": "factor-boss",
            "boss_name": "인자 보스",
            "grade": "UF",
            "power_score": 13_000,
            "weekly_elo": 1_500,
            "all_time_best_elo": 1_500,
            "is_published": 0,
            "publish_scope": None,
            "boss_data": {
                "hp": 10_000,
                "mental": 3_000,
                "attack": 100,
                "defense": 100,
                "factors": [
                    {"kind": "stat", "stat": "hp", "stars": 3},
                    {"kind": "growth", "specialty": "attack", "stars": 2},
                ],
            },
        }
        view = boss.BossArchiveView(author, {"guild_id": 1})
        view.records = [record]
        view.selected_id = record["boss_id"]
        embed = view.get_embed()
        factor_field = next(field for field in embed.fields if field.name == "🧬 보유 인자")
        self.assertIn("★★★ HP 인자", factor_field.value)
        self.assertIn("★★ 공격 성장률 인자", factor_field.value)


class BossBalanceSimulationTests(unittest.TestCase):
    @staticmethod
    def _simulate_scores(*, scenario=False, strong_parents=False):
        parent_records = []
        if strong_parents:
            for index in range(2):
                parent_records.append({
                    "boss_id": f"uf-parent-{index}",
                    "boss_name": f"UF 부모 {index + 1}",
                    "grade": "UF",
                    "boss_data": {
                        "boss_id": f"uf-parent-{index}",
                        "name": f"UF 부모 {index + 1}",
                        "grade": "UF",
                        "hp": 20_000,
                        "mental": 5_000,
                        "attack": 100,
                        "defense": 100,
                        "growth_rates": {
                            "hp": 10, "attack": 5, "defense": 5,
                            "mental": 5, "tactics": 5,
                        },
                        "inherited_growth_bonus": {},
                        "hint_catalog": [],
                        "build": {"skills": [], "passives": []},
                        "factors": [
                            {"kind": "stat", "stat": "hp", "stars": 3},
                            {"kind": "stat", "stat": "attack", "stars": 3},
                            {"kind": "growth", "specialty": "attack", "stars": 3},
                        ],
                        "factors_version": boss.FACTOR_VERSION,
                    },
                })
        scores = []
        for seed in range(500):
            rng = random.Random(seed)
            user = make_user()
            user["life_data"]["boss_training"]["shop_unlocks"][
                "scenario_facility_expansion"
            ] = True
            run = boss.create_training_run(
                user,
                "확장 시뮬레이션",
                {"hp": 10, "attack": 5, "defense": 5, "mental": 5, "tactics": 5},
                [0, 1, 2],
                borrowed_support(2),
                base_tokens={"hp": 2, "mental": 1, "attack": 1, "defense": 1},
                parent_records=parent_records,
                scenario_id="facility_expansion" if scenario else "normal",
                rng=rng,
            )
            for _ in range(70):
                if run.get("pending_event_choice"):
                    boss.resolve_support_event_choice(run, "sp")
                action = (
                    "rest"
                    if run["energy"] < 35
                    else rng.choice(
                        [
                            key for key, indices in run["support_placements"].items()
                            if indices
                        ]
                        or list(boss.GROWTH_KEYS)
                    )
                )
                boss.perform_training_action(run, action, rng)
            # 최종 빌드에서 획득 SP를 실제로 배정할 수 있다는 전제로 평가한다.
            run["spent_sp"] = run["sp"]
            scores.append(boss._run_power_score(run))
        return scores

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

    def test_five_hundred_seed_scenario_and_high_star_inheritance(self):
        normal = self._simulate_scores()
        scenario = self._simulate_scores(scenario=True)
        inherited = self._simulate_scores(scenario=True, strong_parents=True)
        self.assertGreater(statistics.median(scenario), statistics.median(normal))
        self.assertGreater(statistics.median(inherited), statistics.median(scenario))
        self.assertGreater(sum(score >= 11_000 for score in inherited), 100)
        self.assertGreater(sum(score >= 13_000 for score in inherited), 0)


if __name__ == "__main__":
    unittest.main()
