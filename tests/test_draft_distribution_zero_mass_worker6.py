import unittest

from ganesha.math.draft_distribution import summarize_weighted_distribution


class DraftDistributionZeroMassTests(unittest.TestCase):
    def test_zero_mass_outcomes_are_excluded_from_support_and_maximum(self):
        result = summarize_weighted_distribution({0: 4, 1000: 0}, 4)

        self.assertEqual(result["unique_payout_values"], 1)
        self.assertEqual(result["maximum_single_spin_payout_milli"], 0)
        self.assertEqual(result["maximum_single_spin_frequency"], {
            "numerator": 4, "denominator": 4,
        })
        self.assertEqual(result["payout_distribution"], [
            {"payout_milli": 0, "weight_mass": 4},
        ])


if __name__ == "__main__":
    unittest.main()