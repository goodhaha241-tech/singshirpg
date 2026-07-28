import random
import unittest
from collections import Counter

from artifacts import RANDOM_ARTIFACT_PREFIXES, generate_artifact
from shop import (
    ARTIFACT_GACHA_COST,
    ARTIFACT_TICKET_ITEM,
    consume_artifact_gacha_cost,
    consume_artifact_gacha_costs,
)


class ArtifactGachaCostTests(unittest.TestCase):
    def test_ten_draw_uses_tickets_first_then_points(self):
        data = {
            "pt": 20_000,
            "inventory": {ARTIFACT_TICKET_ITEM: 4},
        }
        paid, payment = consume_artifact_gacha_costs(data, 10)
        self.assertTrue(paid)
        self.assertEqual(payment, {"tickets": 4, "points": 6_000})
        self.assertEqual(data["inventory"][ARTIFACT_TICKET_ITEM], 0)
        self.assertEqual(data["pt"], 14_000)

    def test_ten_draw_cost_is_atomic_when_resources_are_short(self):
        data = {
            "pt": 5 * ARTIFACT_GACHA_COST,
            "inventory": {ARTIFACT_TICKET_ITEM: 4},
        }
        original = {
            "pt": data["pt"],
            "tickets": data["inventory"][ARTIFACT_TICKET_ITEM],
        }
        paid, payment = consume_artifact_gacha_costs(data, 10)
        self.assertFalse(paid)
        self.assertEqual(payment, {"tickets": 0, "points": 0})
        self.assertEqual(data["pt"], original["pt"])
        self.assertEqual(
            data["inventory"][ARTIFACT_TICKET_ITEM],
            original["tickets"],
        )

    def test_single_draw_compatibility_prefers_ticket(self):
        data = {
            "pt": 2_000,
            "inventory": {ARTIFACT_TICKET_ITEM: 1},
        }
        paid, payment = consume_artifact_gacha_cost(data)
        self.assertTrue(paid)
        self.assertEqual(payment, "ticket")
        self.assertEqual(data["pt"], 2_000)
        self.assertEqual(data["inventory"][ARTIFACT_TICKET_ITEM], 0)


class ArtifactPrefixDistributionTests(unittest.TestCase):
    def test_three_star_public_prefixes_are_uniform_and_exclude_imprints(self):
        rng = random.Random(20260728)
        counts = Counter(
            generate_artifact(rank=3, rng=rng)["prefix"]
            for _ in range(7_000)
        )
        self.assertEqual(set(counts), set(RANDOM_ARTIFACT_PREFIXES[3]))
        for count in counts.values():
            self.assertTrue(900 <= count <= 1_100, counts)
        self.assertNotIn("혹한의", counts)
        self.assertNotIn("시간의", counts)

    def test_rank_three_generation_does_not_mutate_base_type_pool(self):
        rng = random.Random(7)
        for _ in range(20):
            generate_artifact(rank=3, rng=rng)
        one_star_names = {
            generate_artifact(rank=1, rng=rng)["name"].split()[-1]
            for _ in range(100)
        }
        self.assertFalse(
            {"티아라", "투구", "보주", "성배", "왕관"} & one_star_names
        )


if __name__ == "__main__":
    unittest.main()
