import unittest
from fractions import Fraction

from ganesha.math.config import SCATTER, WILD
from ganesha.math.draft_distribution import (
    evaluate_spin_payout,
    summarize_weighted_distribution,
)


class DraftSpinDistributionTests(unittest.TestCase):
    def test_exact_weighted_moments_hit_rate_and_tail(self):
        result = summarize_weighted_distribution({0: 3, 1000: 1}, 4)
        self.assertEqual(result["mean_payout_milli"], {"numerator": 250, "denominator": 1})
        self.assertEqual(result["variance_milli_squared"], {"numerator": 187500, "denominator": 1})
        self.assertEqual(result["hit_frequency"], {"numerator": 1, "denominator": 4})
        self.assertEqual(result["loss_frequency"], {"numerator": 3, "denominator": 4})
        self.assertEqual(result["maximum_single_spin_frequency"], {"numerator": 1, "denominator": 4})
        self.assertEqual(result["upper_0_1_percent_cvar_payout_milli"], {"numerator": 1000, "denominator": 1})
        self.assertEqual(result["streak_distribution"]["loss_run_at_least_n"][1],
                         {"n": 2, "numerator": 9, "denominator": 16})
        self.assertEqual(result["streak_distribution"]["win_run_at_least_n"][0],
                         {"n": 1, "numerator": 1, "denominator": 4})

    def test_distribution_requires_exact_integer_mass(self):
        with self.assertRaises(ValueError):
            summarize_weighted_distribution({0: 3, 1000: 1}, 5)
        with self.assertRaises(ValueError):
            summarize_weighted_distribution({0: True, 1000: 1}, 2)

    def test_single_spin_projection_does_not_invent_scatter_awards(self):
        # Four Scatter are deliberately unspecified for the full game. Their
        # presence must not prevent a payout-only projection from being audited.
        board = (
            (SCATTER, SCATTER, SCATTER),
            (SCATTER, WILD, "A"),
            ("A", "K", "MOUSE"),
            ("K", "A", "MOUSE"),
            ("A", "K", "MOUSE"),
        )
        base = evaluate_spin_payout(board, "BASE")
        free_spin = evaluate_spin_payout(board, "FREE_SPINS")
        self.assertIs(type(base), int)
        self.assertIs(type(free_spin), int)
        self.assertGreaterEqual(base, 0)
        self.assertGreaterEqual(free_spin, 0)

    def test_unknown_mode_is_rejected(self):
        board = tuple(("A", "K", "MOUSE") for _ in range(5))
        with self.assertRaises(ValueError):
            evaluate_spin_payout(board, "MAGIC_BUY")


if __name__ == "__main__":
    unittest.main()
