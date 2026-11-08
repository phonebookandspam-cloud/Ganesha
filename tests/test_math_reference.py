import unittest
from itertools import product

from ganesha.math.config import (CONFIG, PAYLINES, PAYOUT_SCALE_DENOMINATOR,
                                 PAYOUT_SCALE_NUMERATOR, PAYTABLE_MILLI,
                                 REEL_STRIPS, SCATTER, STOP_WEIGHTS, WILD)
from ganesha.math.engine import UnspecifiedMathRule, board_from_stops, evaluate_board
from ganesha.math.reference import (UnspecifiedReferenceRule, evaluate_board as reference_board,
                                    evaluate_line)


class IndependentMathReferenceTests(unittest.TestCase):
    def _reference(self, board, mode):
        expanded = ([i for i, reel in enumerate(board) if WILD in reel]
                    if mode == "FREE_SPINS" else [])
        multiplier = 1
        if expanded:
            multiplier = min(
                CONFIG.feature_rules.free_spin_wild_reel_multiplier ** len(expanded)
                * (2 if len(expanded) == 5 else 1),
                CONFIG.feature_rules.max_wild_reel_multiplier,
            )
        return reference_board(
            board, paylines=PAYLINES, paytable_milli=PAYTABLE_MILLI,
            wild_symbol=WILD, scatter_symbol=SCATTER, mode=mode,
            wild_expansion_reels=expanded, wild_multiplier=multiplier,
            scale_numerator=PAYOUT_SCALE_NUMERATOR,
            scale_denominator=PAYOUT_SCALE_DENOMINATOR,
            payout_cap_milli=CONFIG.max_win_milli,
        )

    def test_independent_reference_matches_fixed_base_and_feature_vectors(self):
        vectors = ((0, 0, 0, 0, 0), (1, 2, 3, 4, 5), (6, 7, 8, 9, 10),
                   (12, 11, 10, 9, 8), (3, 2, 1, 0, 12))
        for stops in vectors:
            board = board_from_stops(stops)
            for mode in ("BASE", "FREE_SPINS"):
                try:
                    expected = evaluate_board(board, mode)
                except UnspecifiedMathRule:
                    with self.assertRaises(UnspecifiedReferenceRule):
                        self._reference(board, mode)
                else:
                    self.assertEqual(self._reference(board, mode), expected,
                                     (stops, mode))

    def test_reference_uses_twelve_spins_for_four_scatter_and_fails_closed_for_five(self):
        four = ((SCATTER, "A", "K"), (SCATTER, "K", "A"),
                (SCATTER, "A", "K"), (SCATTER, "ELEPHANT", "A"),
                ("MOUSE", "A", "K"))
        self.assertEqual(self._reference(four, "BASE")["free_spins_awarded"], 12)
        five = ((SCATTER, "A", "K"), (SCATTER, "K", "A"),
                (SCATTER, "A", "K"), (SCATTER, "ELEPHANT", "A"),
                (SCATTER, "A", "K"))
        with self.assertRaises(UnspecifiedReferenceRule):
            self._reference(five, "BASE")

    def test_independent_reference_rejects_invalid_and_ambiguous_inputs(self):
        board = tuple(tuple("A" for _ in range(3)) for _ in range(5))
        with self.assertRaises(ValueError):
            reference_board(board, paylines=(), paytable_milli=PAYTABLE_MILLI,
                            wild_symbol=WILD, scatter_symbol=SCATTER, mode="BASE")
        with self.assertRaises(ValueError):
            reference_board(board, paylines=PAYLINES, paytable_milli=PAYTABLE_MILLI,
                            wild_symbol=WILD, scatter_symbol=SCATTER, mode="BASE",
                            payout_cap_milli=True)

    def test_reference_line_rejects_incomplete_and_malformed_paytable_entries(self):
        line = ("A", "A", "A", "A", "A")
        malformed_paytables = (
            {"A": {3: 100, 4: 200}},
            {"A": {3: 100, 4: 200, 5: 300, 6: 400}},
            {"A": {3: 100, 4: 200, 5: True}},
            {"A": {3: 100, 4: 200, 5: -1}},
            {"A": {3: 100, 4: 200, 5: 300.0}},
        )
        for paytable in malformed_paytables:
            with self.subTest(paytable=paytable):
                with self.assertRaises(ValueError):
                    evaluate_line(line, paytable, wild_symbol="WILD")

    def test_reference_requires_explicit_expanded_wild_to_exist_on_raw_reel(self):
        board = tuple(tuple("A" for _ in range(3)) for _ in range(5))
        with self.assertRaisesRegex(ValueError, "must contain the Wild"):
            reference_board(board, paylines=PAYLINES, paytable_milli=PAYTABLE_MILLI,
                            wild_symbol=WILD, scatter_symbol=SCATTER, mode="FREE_SPINS",
                            wild_expansion_reels=[0])


if __name__ == "__main__":
    unittest.main()
