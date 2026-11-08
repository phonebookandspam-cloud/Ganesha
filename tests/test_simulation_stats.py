import unittest
from ganesha.math.simulation import _metrics

class SimulationStatsTests(unittest.TestCase):
    def test_quantiles_buckets_cvar_and_streaks(self):
        samples = [0, 0, 1000, 2000, 0, 0, 0, 500, 0, 3000]
        result = _metrics(samples, 1)
        self.assertEqual(result["rounds"], 10)
        self.assertEqual(result["hit_frequency"], 0.4)
        self.assertEqual(result["streaks"]["max_consecutive_zero_rounds"], 3)
        self.assertEqual(result["streaks"]["max_consecutive_winning_rounds"], 2)
        self.assertEqual(result["payout_bucket_counts"]["zero"], 6)
        self.assertEqual(result["payout_bucket_counts"]["1_to_5x"], 2)
        self.assertEqual(result["streaks"]["zero_streak_length_histogram_capped_at_10"], {1: 1, 2: 1, 3: 1})

    def test_invalid_payout_samples_are_rejected_before_statistics(self):
        for samples in ([-1, 0, 1], [True, 0], [0.5, 1.5], ["0", "1"]):
            with self.subTest(samples=samples):
                with self.assertRaises(ValueError):
                    _metrics(samples, 1)

    def test_invalid_purchase_cost_is_rejected_before_statistics(self):
        for cost_x in (0, -1, True, float("nan"), float("inf"), "1"):
            with self.subTest(cost_x=cost_x):
                with self.assertRaises(ValueError):
                    _metrics([0, 1000], cost_x)

if __name__ == "__main__":
    unittest.main()
