import unittest

from artifact_overhaul_v5 import (
    ARTIFACT_DUST_ITEM,
    buy_artifact_dust_offer,
)
from boss_training import ensure_boss_training_data
from life_system import (
    TOOL_TOKEN_FRAGMENT_PRICE,
    TOOL_TOKEN_ITEM,
    buy_tool_token_offer,
)


class FragmentShopTests(unittest.TestCase):
    def test_artifact_dust_shop_sells_random_character_fragment(self):
        data = {
            "inventory": {ARTIFACT_DUST_ITEM: 250},
            "life_data": {},
        }
        ok, message = buy_artifact_dust_offer(
            data,
            "support_fragment",
            "2026-07-28",
        )
        self.assertTrue(ok)
        self.assertIn("조각 ×1", message)
        self.assertEqual(data["inventory"][ARTIFACT_DUST_ITEM], 0)
        fragments = ensure_boss_training_data(data)["support_fragments"]
        self.assertEqual(sum(fragments.values()), 1)

    def test_tool_token_shop_uses_fragment_specific_price(self):
        data = {
            "inventory": {TOOL_TOKEN_ITEM: TOOL_TOKEN_FRAGMENT_PRICE},
            "life_data": {},
        }
        ok, message, result = buy_tool_token_offer(
            data,
            "support_fragment",
        )
        self.assertTrue(ok)
        self.assertEqual(result["kind"], "support_fragment")
        self.assertIn("조각 ×1", message)
        self.assertEqual(data["inventory"][TOOL_TOKEN_ITEM], 0)
        fragments = ensure_boss_training_data(data)["support_fragments"]
        self.assertEqual(sum(fragments.values()), 1)

    def test_fragment_purchase_does_not_charge_when_short(self):
        data = {
            "inventory": {TOOL_TOKEN_ITEM: TOOL_TOKEN_FRAGMENT_PRICE - 1},
            "life_data": {},
        }
        ok, _, result = buy_tool_token_offer(data, "support_fragment")
        self.assertFalse(ok)
        self.assertIsNone(result)
        self.assertEqual(
            data["inventory"][TOOL_TOKEN_ITEM],
            TOOL_TOKEN_FRAGMENT_PRICE - 1,
        )


if __name__ == "__main__":
    unittest.main()
