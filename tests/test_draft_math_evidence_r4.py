import unittest
from fractions import Fraction

from tools.audit_draft_math_evidence_r4 import (
    independent_board_from_stops,
    maximum_path_probability_scopes,
)


class DraftMathEvidenceR4Tests(unittest.TestCase):
    def test_independent_stop_mapping_uses_reel_major_three_row_windows(self):
        strips = (
            ("a0", "a1", "a2", "a3"),
            ("b0", "b1", "b2", "b3"),
            ("c0", "c1", "c2", "c3"),
            ("d0", "d1", "d2", "d3"),
            ("e0", "e1", "e2", "e3"),
        )
        self.assertEqual(
            independent_board_from_stops((3, 2, 1, 0, 3), strips),
            (("a3", "a0", "a1"), ("b2", "b3", "b0"),
             ("c1", "c2", "c3"), ("d0", "d1", "d2"),
             ("e3", "e0", "e1")),
        )

    def test_independent_stop_mapping_rejects_invalid_indices(self):
        strips = tuple(("a", "b", "c") for _ in range(5))
        with self.assertRaises(ValueError):
            independent_board_from_stops((0, 0, 0, 0, 3), strips)
        with self.assertRaises(ValueError):
            independent_board_from_stops((0, 0, 0, 0), strips)

    def test_maximum_path_probabilities_are_reported_under_three_distinct_scopes(self):
        result = maximum_path_probability_scopes(
            total_mass=100,
            base_valid_mass=90,
            exact_three_mass=9,
            max_base_exact_three_mass=3,
            free_valid_mass=80,
            max_free_valid_mass=8,
            free_spins=10,
        )
        conditional_trigger = result["conditional_on_exact_three_trigger_and_each_free_spin_in_0_to_2"]
        conditional_domain = result["conditional_on_base_scatter_0_to_3_and_each_free_spin_in_0_to_2"]
        unconditional = result["unconditional_stop_vector_mass_for_this_known_path"]
        self.assertEqual(Fraction(**conditional_trigger), Fraction(1, 3 * 10**10))
        self.assertEqual(Fraction(**conditional_domain), Fraction(1, 3 * 10**11))
        self.assertEqual(Fraction(**unconditional), Fraction(3 * 8**10, 100**11))

    def test_maximum_path_probability_rejects_inconsistent_mass(self):
        with self.assertRaises(ValueError):
            maximum_path_probability_scopes(
                total_mass=100, base_valid_mass=90, exact_three_mass=95,
                max_base_exact_three_mass=3, free_valid_mass=80,
                max_free_valid_mass=8,
            )


if __name__ == "__main__":
    unittest.main()
