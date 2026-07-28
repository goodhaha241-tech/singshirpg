import unittest

import cafe_tycoon_v92 as cafe


class CafeTycoonSeasonTests(unittest.TestCase):
    def test_single_player_mode_is_supported(self):
        self.assertEqual(cafe.MIN_PLAYERS, 1)
        self.assertEqual(cafe._season_vote_needed(1), 1)

    def test_non_participants_do_not_block_cycle(self):
        members = [
            {"participating": 1, "ready": 1},
            {"participating": 0, "ready": 0},
            {"participating": 0, "ready": 0},
        ]
        self.assertTrue(cafe._participating_members_ready(members))
        members[0]["ready"] = 0
        self.assertFalse(cafe._participating_members_ready(members))
        self.assertFalse(cafe._participating_members_ready([]))

    def test_strict_majority_vote_boundaries(self):
        self.assertEqual(cafe._season_vote_needed(2), 2)
        self.assertEqual(cafe._season_vote_needed(3), 2)
        self.assertEqual(cafe._season_vote_needed(4), 3)

    def test_shop_is_stable_and_has_eight_appearances_four_effects(self):
        owned = {"appearances": [], "effects": []}
        first = cafe._season_shop(91, 3, owned)
        second = cafe._season_shop(91, 3, owned)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 12)
        self.assertEqual(len(set(first)), 12)
        self.assertEqual(sum(key in cafe.DECOR_APPEARANCES for key in first), 8)
        self.assertEqual(sum(key in cafe.DECOR_EFFECTS for key in first), 4)

    def test_reputation_milestones_are_one_time_and_queue_vip(self):
        state = cafe._default_state()
        self.assertEqual(cafe._apply_reputation_progress(state, 24, 25), 20)
        self.assertEqual(state["vip_queue"], 1)
        self.assertEqual(cafe._apply_reputation_progress(state, 25, 25), 0)
        self.assertEqual(state["vip_queue"], 1)
        self.assertEqual(cafe._apply_reputation_progress(state, 25, 76), 70)
        self.assertEqual(state["vip_queue"], 3)
        self.assertEqual(state["milestones_claimed"], [25, 50, 75])

    def test_three_matching_appearances_give_small_satisfaction_bonus(self):
        state = cafe._default_state()
        state["orders"] = [{
            "id": 1,
            "kind": "drink",
            "quantity": 1,
            "preferred_theme": "cozy",
            "vip": False,
        }]
        state["products"]["아메리카노"] = 1
        slots = list(cafe.DECOR_SLOTS)[:3]
        for slot in slots:
            key = f"cozy_{slot}"
            state["decor_loadout"][slot]["appearance"] = key
        ok, cash, score, reputation, tokens, _ = cafe._serve_order(
            state, 1, recipe_allocations={"아메리카노": 1}
        )
        self.assertTrue(ok)
        self.assertEqual(cash, 8_800)
        self.assertEqual(score, 11)
        self.assertEqual(reputation, 2)
        self.assertEqual(tokens, 5)

    def test_six_matching_appearances_and_vip_rewards(self):
        state = cafe._default_state()
        state["orders"] = [{
            "id": 2,
            "kind": "drink",
            "quantity": 3,
            "preferred_theme": "cozy",
            "vip": True,
        }]
        state["products"]["아메리카노"] = 3
        for slot in cafe.DECOR_SLOTS:
            state["decor_loadout"][slot]["appearance"] = f"cozy_{slot}"
        ok, cash, score, reputation, tokens, _ = cafe._serve_order(
            state, 2, recipe_allocations={"아메리카노": 3}
        )
        self.assertTrue(ok)
        self.assertEqual(cash, 28_800)
        self.assertEqual(score, 36)
        self.assertEqual(reputation, 3)
        self.assertEqual(tokens, 23)

    def test_order_board_effect_increases_order_and_action_caps(self):
        state = cafe._default_state()
        state["machines"]["lounge"] = 3
        state["decor_loadout"]["sign"]["effect"] = "sign_order_board"
        self.assertEqual(cafe._action_cap(state), 6)
        cafe._fill_orders(state, 5)
        self.assertEqual(len(state["orders"]), 5)

    def test_cost_and_manual_effect_values(self):
        state = cafe._default_state()
        state["decor_loadout"]["counter"]["effect"] = "counter_stock"
        state["decor_loadout"]["wall"]["effect"] = "wall_research_cost"
        state["decor_loadout"]["lighting"]["effect"] = "lighting_upgrade"
        self.assertEqual(cafe._stock_bundle(state)["원두"], 7)
        self.assertEqual(cafe._stock_bundle(state)["우유"], 4)
        self.assertEqual(cafe._research_price(state, 1), 21_250)
        self.assertEqual(cafe._upgrade_price(state, 1), 72_000)

        state["decor_loadout"]["lighting"]["effect"] = "lighting_manual_score"
        self.assertEqual(
            cafe._manual_score(state, cafe.RECIPE_CATALOG["아메리카노"]),
            6,
        )

    def test_automatic_display_and_service_effects(self):
        state = cafe._default_state()
        state["orders"] = [{
            "id": 11,
            "kind": "drink",
            "quantity": 1,
            "preferred_theme": "modern",
            "vip": False,
        }]
        state["products"]["아메리카노"] = 1
        state["decor_collection"]["effects"].append("display_service")
        state["decor_loadout"]["display_case"]["effect"] = "display_service"
        _, _, reputation, tokens, notes = cafe._resolve_automatic_turn(state)
        self.assertEqual(reputation, 1)
        self.assertEqual(tokens, 4)
        self.assertTrue(any("자동 서빙" in note for note in notes))

        dessert_state = cafe._default_state()
        dessert_state["machines"]["display"] = 0
        dessert_state["decor_collection"]["effects"].append("display_dessert")
        dessert_state["decor_loadout"]["display_case"]["effect"] = "display_dessert"
        before = dessert_state["products"]["간단한 다과"]
        cafe._resolve_automatic_turn(dessert_state)
        self.assertEqual(
            dessert_state["products"]["간단한 다과"],
            before + 1,
        )

    def test_legacy_state_gets_new_fields_without_losing_recipes(self):
        state = {
            "ingredients": {},
            "machines": {},
            "products": {},
            "unlocked_recipes": ["아메리카노"],
            "orders": [{"id": 7, "kind": "drink", "quantity": 1}],
        }
        normalized = cafe._normalize_state(state)
        self.assertEqual(normalized["state_version"], cafe.CAFE_STATE_VERSION)
        self.assertIn("아메리카노", normalized["unlocked_recipes"])
        self.assertIn("preferred_theme", normalized["orders"][0])
        self.assertFalse(normalized["orders"][0]["vip"])
        self.assertIn("decor_collection", normalized)

    def test_next_season_keeps_collection_and_recipes_but_resets_run(self):
        state = cafe._default_state()
        state["unlocked_recipes"].append("바닐라라떼")
        state["products"]["바닐라라떼"] = 9
        state["machines"]["coffee"] = 4
        state["decor_collection"]["appearances"].append("cozy_sign")
        state["decor_loadout"]["sign"]["appearance"] = "cozy_sign"
        next_state = cafe._next_season_state(state, 77, 2)
        self.assertIn("바닐라라떼", next_state["unlocked_recipes"])
        self.assertEqual(next_state["products"]["바닐라라떼"], 0)
        self.assertEqual(next_state["machines"]["coffee"], 1)
        self.assertIn("cozy_sign", next_state["decor_collection"]["appearances"])
        self.assertEqual(
            next_state["decor_loadout"]["sign"]["appearance"], "cozy_sign"
        )
        self.assertEqual(len(next_state["season_shop"]), 12)


class CafeTycoonViewSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_interior_shop_and_history_views_construct(self):
        state = cafe._default_state()
        state["decor_collection"]["appearances"].append("cozy_sign")
        state["decor_collection"]["effects"].append("sign_order_board")
        state["season_shop"] = cafe._season_shop(
            1, 1, state["decor_collection"]
        )
        session = {
            "id": 1,
            "host_id": 10,
            "host_name": "방장",
            "status": "running",
            "turn_no": 1,
            "season_no": 1,
            "score": 0,
            "cafe_cash": 30_000,
            "reputation": 0,
            "decor_tokens": 100,
            "state": state,
        }
        members = [{
            "user_id": 10,
            "user_name": "방장",
            "actions_left": 2,
            "ready": 0,
            "participating": 0,
            "end_vote": 0,
        }]
        author = type("Author", (), {"id": 10, "display_name": "방장"})()

        main = cafe.CafeTycoonSessionView(1)
        main.rebuild(session, members)
        self.assertEqual(len(main.children), 7)

        interior = cafe.CafeTycoonInteriorView(author, 1)
        interior.session = session
        interior.members = members
        interior.rebuild()
        self.assertEqual(len(interior.children), 5)

        shop = cafe.CafeTycoonDecorShopView(author, 1)
        shop.session = session
        shop.members = members
        shop.rebuild()
        self.assertEqual(len(shop.children), 4)

        history = cafe.CafeTycoonSeasonHistoryView(author, 1)
        history.session = session
        history.members = members
        history.rewards = []
        history.rebuild()
        self.assertEqual(len(history.children), 2)


if __name__ == "__main__":
    unittest.main()
