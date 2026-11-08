import unittest
from fractions import Fraction

from ganesha.math.draft_round_projection import (
    _aggregate_scatter_domain, _convolve, _max_streak_masses,
)


class DraftRoundProjectionTests(unittest.TestCase):
    def test_exact_convolution_conserves_integer_probability_mass(self):
        result = _convolve({0: 3, 10: 1}, {0: 2, 20: 2})
        self.assertEqual(result, {0: 6, 20: 6, 10: 2, 30: 2})
        self.assertEqual(sum(result.values()), 16)

    def test_scatter_class_aggregation_adds_shared_payout_keys(self):
        self.assertEqual(
            _aggregate_scatter_domain({0: {0: 10, 100: 3}, 3: {0: 7, 200: 2}}, range(4)),
            {0: 17, 100: 3, 200: 2},
        )

    def test_ten_spin_streak_distribution_conserves_mass(self):
        result = _max_streak_masses(1, 1, 2, spins=3)
        wins = result["maximum_consecutive_winning_spin_distribution"]
        losses = result["maximum_consecutive_losing_spin_distribution"]
        self.assertEqual(sum(x["probability"]["numerator"] / x["probability"]["denominator"] for x in wins), 1)
        self.assertEqual(sum(x["probability"]["numerator"] / x["probability"]["denominator"] for x in losses), 1)
        p_all_wins = result["probability_at_least_n_consecutive_wins"][-1]["probability"]
        self.assertEqual(Fraction(p_all_wins["numerator"], p_all_wins["denominator"]), Fraction(1, 8))


if __name__ == "__main__":
    unittest.main()
