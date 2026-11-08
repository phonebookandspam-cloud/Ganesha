import unittest
from fractions import Fraction
from ganesha.math.feature_ev import _moments_for_cap, _jackpot_probability

class FeatureDynamicProgrammingTests(unittest.TestCase):
    def test_retrigger_cap_tracks_total_awarded_not_remaining_only(self):
        # Every spin pays 1x and retriggers +1; with a two-spin award cap, total is exactly 2x.
        grouped = {1: [1, 1000, 1000000, 0, 0]}
        expected, second, variance, zero = _moments_for_cap(2, grouped, 1)
        self.assertEqual(expected[(0, 1)], Fraction(2, 1))
        self.assertEqual(second[(0, 1)], Fraction(4, 1))
        self.assertEqual(variance[(0, 1)], Fraction(0, 1))
        self.assertEqual(zero[(0, 1)], Fraction(0, 1))

    def test_jackpot_is_terminal(self):
        grouped = {0: [1, 50_000_000, 50_000_000 ** 2, 0, 1]}
        expected, second, variance, zero = _moments_for_cap(2, grouped, 1)
        self.assertEqual(expected[(0, 2)], Fraction(50000, 1))
        self.assertEqual(second[(0, 2)], Fraction(2_500_000_000, 1))
        self.assertEqual(zero[(0, 2)], Fraction(0, 1))
        self.assertEqual(_jackpot_probability(2, 2, grouped, 1), Fraction(1, 1))

if __name__ == "__main__":
    unittest.main()
