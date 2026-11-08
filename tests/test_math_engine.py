import unittest
from itertools import product
from unittest.mock import patch
from ganesha.math.config import CONFIG, PAYLINES, REEL_STRIPS, SCATTER, WILD, validate_config
from ganesha.math.engine import (EmbeddedEpicFeatureUnavailable, UnspecifiedMathRule,
                                 board_from_stops, evaluate_board, evaluate_line,
                                 free_spins_awarded)

class MathEngineTests(unittest.TestCase):
    def test_config_shape(self):
        validate_config()
        self.assertEqual(len(REEL_STRIPS), 5)
        self.assertTrue(all(len(reel) == 13 for reel in REEL_STRIPS))
        self.assertEqual(len(PAYLINES), 20)

    def test_config_rejects_boolean_weights_and_payline_rows(self):
        bad_weights = [list(row) for row in __import__("ganesha.math.config", fromlist=["STOP_WEIGHTS"]).STOP_WEIGHTS]
        bad_weights[0][0] = True
        with patch("ganesha.math.config.STOP_WEIGHTS", tuple(tuple(row) for row in bad_weights)):
            with self.assertRaises(ValueError):
                validate_config()
        bad_paylines = [list(row) for row in PAYLINES]
        bad_paylines[0][0] = True
        with patch("ganesha.math.config.PAYLINES", tuple(tuple(row) for row in bad_paylines)):
            with self.assertRaises(ValueError):
                validate_config()

    def test_stop_vector_determinism_and_bounds(self):
        stops = (0, 1, 2, 3, 4)
        self.assertEqual(board_from_stops(stops), board_from_stops(stops))
        with self.assertRaises(ValueError):
            board_from_stops((0, 1, 2, 3, 13))
        with self.assertRaises(ValueError):
            board_from_stops((True, 1, 2, 3, 4))

    def test_wild_substitution(self):
        result = evaluate_line((WILD, "ELEPHANT", "ELEPHANT", "A", "K"))
        self.assertEqual(result["symbol"], "ELEPHANT")
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["payout_milli"], 774)

    def test_scatter_awards(self):
        self.assertEqual(free_spins_awarded(2), 0)
        self.assertEqual(free_spins_awarded(3), 10)
        self.assertEqual(free_spins_awarded(4), 12)
        with self.assertRaises(EmbeddedEpicFeatureUnavailable):
            free_spins_awarded(5)
        for count in (6, 15):
            with self.assertRaises(UnspecifiedMathRule):
                free_spins_awarded(count)
        with self.assertRaises(UnspecifiedMathRule):
            free_spins_awarded(3, retrigger=True)

    def test_free_spins_awarded_rejects_non_boolean_retrigger_flags(self):
        for invalid_retrigger in (0, 1, None, "false"):
            with self.subTest(retrigger=invalid_retrigger):
                with self.assertRaisesRegex(ValueError, "Retrigger flag must be a boolean"):
                    free_spins_awarded(3, retrigger=invalid_retrigger)

    def test_base_board_with_exactly_three_scatter_awards_ten(self):
        board = ((SCATTER, "A", "K"), (SCATTER, "K", "A"), (SCATTER, "A", "K"),
                 ("ELEPHANT", "A", "K"), ("MOUSE", "A", "K"))
        result = evaluate_board(board, "BASE")
        self.assertEqual(result["scatter_count"], 3)
        self.assertEqual(result["free_spins_awarded"], 10)
        self.assertEqual(result["board"], [list(reel) for reel in board])
        self.assertEqual(result["display_board"], [list(reel) for reel in board])

    def test_base_board_with_four_scatter_awards_twelve(self):
        board = ((SCATTER, "A", "K"), (SCATTER, "K", "A"),
                 (SCATTER, "A", "K"), (SCATTER, "ELEPHANT", "A"),
                 ("MOUSE", "A", "K"))
        result = evaluate_board(board, "BASE")
        self.assertEqual(result["scatter_count"], 4)
        self.assertEqual(result["free_spins_awarded"], 12)

    def test_base_board_with_five_scatter_requires_embedded_epic_payload(self):
        board = ((SCATTER, "A", "K"), (SCATTER, "K", "A"),
                 (SCATTER, "A", "K"), (SCATTER, "ELEPHANT", "A"),
                 (SCATTER, "A", "K"))
        with self.assertRaises(EmbeddedEpicFeatureUnavailable):
            evaluate_board(board, "BASE")

    def test_evaluate_board_rejects_unknown_and_non_string_symbols(self):
        valid_board = [list(reel) for reel in board_from_stops((0, 1, 2, 3, 4))]
        unknown_symbol_board = [list(reel) for reel in valid_board]
        unknown_symbol_board[0][0] = "UNREGISTERED_SYMBOL"
        with self.assertRaisesRegex(ValueError, "outside the configured inventory"):
            evaluate_board(unknown_symbol_board)

        non_string_symbol_board = [list(reel) for reel in valid_board]
        non_string_symbol_board[0][0] = 7
        with self.assertRaisesRegex(ValueError, "outside the configured inventory"):
            evaluate_board(non_string_symbol_board)

    def test_free_spin_wild_expansion(self):
        board = ((WILD, "A", "K"), ("A", "K", "A"), ("K", "A", "K"), ("A", "K", "A"), ("K", "A", "K"))
        result = evaluate_board(board, "FREE_SPINS")
        self.assertEqual(result["expanded_wild_reels"], [0])
        self.assertEqual(result["wild_multiplier"], 2)
        self.assertEqual(result["payout_milli"] % 2, 0)
        self.assertEqual(result["display_board"][0], [WILD, WILD, WILD])


    def test_all_wild_free_spin_board_cannot_trigger_a_jackpot(self):
        board = tuple((WILD, WILD, WILD) for _ in range(5))
        result = evaluate_board(board, "FREE_SPINS")
        self.assertFalse(result["jackpot_triggered"])
        self.assertLessEqual(result["payout_milli"], CONFIG.max_win_milli)
        self.assertLess(result["payout_milli"], CONFIG.max_round_win_milli)

    def test_all_stop_vectors_are_finite(self):
        self.assertEqual(sum(1 for _ in product(*(range(len(r)) for r in REEL_STRIPS))), 371293)

    def test_unapproved_buy_costs_and_scatter_award_tuples_are_not_active_config(self):
        self.assertFalse(hasattr(CONFIG, "magic_buy_cost_milli"))
        self.assertFalse(hasattr(CONFIG, "epic_buy_cost_milli"))
        self.assertFalse(hasattr(CONFIG.feature_rules, "base_scatter_awards"))
        self.assertFalse(hasattr(CONFIG.feature_rules, "retrigger_awards"))

    def test_current_draft_spin_caps_cannot_reach_50000x_target(self):
        current_draft_round_bound = CONFIG.max_win_milli * 11
        self.assertEqual(current_draft_round_bound, 11_000_000)
        self.assertLess(current_draft_round_bound, CONFIG.max_round_win_milli)

    def test_full_round_and_monte_carlo_metrics_fail_closed_without_authority(self):
        from ganesha.math.round_ev import exact_full_mode_moments
        from ganesha.math.simulation import run_monte_carlo
        exact = exact_full_mode_moments()
        simulation = run_monte_carlo()
        self.assertEqual(exact["status"], "BLOCKED_UNSPECIFIED_RULES")
        self.assertEqual(simulation["status"], "BLOCKED_UNSPECIFIED_RULES")
        self.assertFalse(exact["canonical_math"])
        self.assertFalse(simulation["sample_run_performed"])
        self.assertEqual(exact["metrics"]["rtp"], "NOT_COMPUTED")
        self.assertEqual(simulation["metrics"]["max_payout_frequency"], "NOT_COMPUTED")
        self.assertNotIn("MAGIC_BUY", exact.get("metrics", {}))

    def test_free_spin_ev_fails_closed_when_retrigger_rules_are_unspecified(self):
        from ganesha.math.feature_ev import exact_free_spins_expected_value
        with self.assertRaises(UnspecifiedMathRule):
            exact_free_spins_expected_value()

    def test_free_spins_wild_expansion_without_scatter_retrigger(self):
        board = ((WILD, "A", "K"), ("A", "K", "A"), ("K", "A", "K"), ("A", "K", "A"), ("K", "A", "K"))
        result = evaluate_board(board, "FREE_SPINS")
        self.assertEqual(result["scatter_count"], 0)
        self.assertEqual(result["free_spins_awarded"], 0)

    def test_free_spins_retrigger_path_is_blocked_without_authority(self):
        from ganesha.math.engine import UnspecifiedMathRule
        stops = (0, 4, 4, 5, 5)
        with self.assertRaises(UnspecifiedMathRule):
            evaluate_board(board_from_stops(stops), "FREE_SPINS")

if __name__ == "__main__":
    unittest.main()
