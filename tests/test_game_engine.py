import unittest
from ganesha.game.engine import (GameEngine, OutcomeStreamExhausted, BonusBuyTermsUnavailable,
                                 InvalidBonusBuyTerms, InvalidMathOutcome, UnapprovedFeatureMechanic)
from ganesha.math.engine import UnspecifiedMathRule

class GameEngineTests(unittest.TestCase):
    def test_math_engine_is_injected_through_a_narrow_versioned_port(self):
        class TestMathPort:
            authority_status = "TEST_FIXTURE_ONLY"
            version = "test-math-v7"
            def evaluate_stops(self, stops, mode):
                return {"mode": mode, "payout_milli": 0, "free_spins_awarded": 0, "scatter_count": 0}
            def award_free_spins(self, scatter_count, retrigger=False):
                return 0
        result = GameEngine(math_port=TestMathPort()).resolve_base_round((0, 0, 0, 0, 0), [])
        self.assertEqual(result["math_authority"], "TEST_FIXTURE_ONLY")
        self.assertEqual(result["math_version"], "test-math-v7")

    def test_magic_and_epic_buy_require_explicit_math_port_terms(self):
        engine = GameEngine()
        with self.assertRaises(BonusBuyTermsUnavailable):
            engine.resolve_bonus_buy_round("MAGIC_BUY", [])
        with self.assertRaises(BonusBuyTermsUnavailable):
            engine.resolve_bonus_buy_round("EPIC_BUY", [])

    def test_bonus_buy_uses_only_explicit_test_port_terms(self):
        class TestBuyMathPort:
            authority_status = "TEST_FIXTURE_ONLY"
            version = "buy-contract-test-v1"
            def evaluate_stops(self, stops, mode):
                return {"mode": mode, "payout_milli": 0, "scatter_count": 0, "jackpot_triggered": False}
            def award_free_spins(self, scatter_count, retrigger=False):
                return 0
            def resolve_bonus_buy_terms(self, mode):
                if mode == "MAGIC_BUY":
                    return {"mode": mode, "initial_free_spins": 2, "purchase_cost_multiplier_milli": 1500, "max_stop_vectors": 2}
                return {"mode": mode, "initial_free_spins": 3, "purchase_cost_multiplier_milli": 4000, "max_stop_vectors": 3}
        engine = GameEngine(math_port=TestBuyMathPort())
        magic = engine.resolve_bonus_buy_round("MAGIC_BUY", [(0, 0, 0, 0, 0)] * 2)
        epic = engine.resolve_bonus_buy_round("EPIC_BUY", [(0, 0, 0, 0, 0)] * 3)
        self.assertEqual(magic["initial_free_spins"], 2)
        self.assertEqual(magic["purchase_cost_multiplier_milli"], 1500)
        self.assertEqual(epic["initial_free_spins"], 3)
        self.assertEqual(epic["purchase_cost_multiplier_milli"], 4000)
        self.assertEqual(magic["math_authority"], "TEST_FIXTURE_ONLY")

    def test_bonus_buy_rejects_invalid_terms_before_consuming_stop_vectors(self):
        class InvalidTermsPort:
            def __init__(self, terms): self.terms = terms
            def evaluate_stops(self, stops, mode): raise AssertionError("must not consume a stop vector")
            def award_free_spins(self, scatter_count, retrigger=False): return 0
            def resolve_bonus_buy_terms(self, mode): return self.terms
        invalid_terms = [
            {"mode": "MAGIC_BUY", "initial_free_spins": True, "purchase_cost_multiplier_milli": 1000, "max_stop_vectors": 2},
            {"mode": "MAGIC_BUY", "initial_free_spins": 0, "purchase_cost_multiplier_milli": 1000, "max_stop_vectors": 2},
            {"mode": "MAGIC_BUY", "initial_free_spins": 2, "purchase_cost_multiplier_milli": 0, "max_stop_vectors": 2},
            {"mode": "EPIC_BUY", "initial_free_spins": 2, "purchase_cost_multiplier_milli": 1000, "max_stop_vectors": 2},
            {"mode": "MAGIC_BUY", "initial_free_spins": 3, "purchase_cost_multiplier_milli": 1000, "max_stop_vectors": 2},
        ]
        for terms in invalid_terms:
            with self.assertRaises(InvalidBonusBuyTerms):
                GameEngine(math_port=InvalidTermsPort(terms)).resolve_bonus_buy_round("MAGIC_BUY", [])

    def test_exhausted_free_spin_outcome_stream_fails_closed(self):
        class ExactThreePort:
            def evaluate_stops(self, stops, mode):
                if mode == "BASE":
                    return {"mode": mode, "payout_milli": 0, "free_spins_awarded": 10, "scatter_count": 3}
                return {"mode": mode, "payout_milli": 0, "scatter_count": 0, "jackpot_triggered": False}
            def award_free_spins(self, scatter_count, retrigger=False): return 0
        with self.assertRaises(OutcomeStreamExhausted):
            GameEngine(math_port=ExactThreePort()).resolve_base_round((0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)])

    def test_round_cap_is_reached_by_the_actual_feature_payout_without_jackpot(self):
        class RoundCapPort:
            def evaluate_stops(self, stops, mode):
                if mode == "BASE":
                    return {"mode": mode, "payout_milli": 100, "free_spins_awarded": 10, "scatter_count": 3}
                return {"mode": mode, "payout_milli": 900, "scatter_count": 0, "jackpot_triggered": False}
            def award_free_spins(self, scatter_count, retrigger=False): return 0
        engine = GameEngine(math_port=RoundCapPort())
        engine.round_cap_milli = 1000
        outcome = engine.resolve_base_round((0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)])
        event = outcome["feature_events"][0]
        self.assertEqual(outcome["total_payout_milli"], 1000)
        self.assertEqual(event["result"]["payout_milli"], 900)
        self.assertEqual(event["payout_awarded_milli"], 900)
        self.assertFalse(event["jackpot_triggered"])
        self.assertTrue(outcome["round_cap_reached"])

    def test_math_port_numeric_fields_reject_bool_float_and_string_coercion(self):
        class MalformedPort:
            def __init__(self, payout): self.payout = payout
            def evaluate_stops(self, stops, mode):
                return {"mode": mode, "payout_milli": self.payout,
                        "free_spins_awarded": 0, "scatter_count": 0}
            def award_free_spins(self, scatter_count, retrigger=False): return 0
        for payout in (True, 1.0, "1"):
            with self.subTest(payout=payout), self.assertRaises(InvalidMathOutcome):
                GameEngine(MalformedPort(payout)).resolve_base_round((0, 0, 0, 0, 0), [])

    def test_math_port_cannot_invent_base_scatter_awards_or_embedded_epic_payload(self):
        class InvalidAwardPort:
            def __init__(self, scatter_count, award): self.scatter_count, self.award = scatter_count, award
            def evaluate_stops(self, stops, mode):
                return {"mode": mode, "payout_milli": 0,
                        "free_spins_awarded": self.award, "scatter_count": self.scatter_count}
            def award_free_spins(self, scatter_count, retrigger=False): return 0
        for scatter_count, award in ((3, 9), (3, True), (4, 0), (4, 10), (5, 0), (5, 10), (15, 0)):
            with self.subTest(scatter_count=scatter_count, award=award):
                with self.assertRaises((InvalidMathOutcome, UnspecifiedMathRule)):
                    GameEngine(InvalidAwardPort(scatter_count, award)).resolve_base_round((0, 0, 0, 0, 0), [])

    def test_user_authorized_four_scatter_awards_twelve_free_spins(self):
        class FourScatterPort:
            def evaluate_stops(self, stops, mode):
                if mode == "BASE":
                    return {"mode": mode, "payout_milli": 0,
                            "free_spins_awarded": 12, "scatter_count": 4}
                return {"mode": mode, "payout_milli": 0,
                        "scatter_count": 0, "jackpot_triggered": False}
            def award_free_spins(self, scatter_count, retrigger=False): return 0

        outcome = GameEngine(FourScatterPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(index,) * 5 for index in range(12)]
        )
        self.assertEqual(outcome["initial_free_spins"], 12)
        self.assertEqual(outcome["free_spins_played"], 12)
        self.assertEqual(outcome["free_spins_awarded_total"], 12)

    def test_jackpot_mechanic_is_rejected_as_stake_stateless_policy_violation(self):
        class JackpotPort:
            def evaluate_stops(self, stops, mode):
                if mode == "BASE":
                    return {"mode": mode, "payout_milli": 0, "free_spins_awarded": 10, "scatter_count": 3}
                return {"mode": mode, "payout_milli": 0, "scatter_count": 0, "jackpot_triggered": True}
            def award_free_spins(self, scatter_count, retrigger=False): return 0
        with self.assertRaises(UnapprovedFeatureMechanic):
            GameEngine(JackpotPort()).resolve_base_round((0, 0, 0, 0, 0), [(0, 0, 0, 0, 0)])

    def test_free_spin_retrigger_is_rejected_even_when_math_port_returns_a_number(self):
        class RetriggerPort:
            def evaluate_stops(self, stops, mode):
                if mode == "BASE":
                    return {"mode": mode, "payout_milli": 0, "free_spins_awarded": 10, "scatter_count": 3}
                return {"mode": mode, "payout_milli": 0, "scatter_count": 0, "jackpot_triggered": False}
            def award_free_spins(self, scatter_count, retrigger=False): return 1 if retrigger else 0
        with self.assertRaises(UnspecifiedMathRule):
            GameEngine(RetriggerPort()).resolve_base_round((0, 0, 0, 0, 0), [(0, 0, 0, 0, 0)])

if __name__ == "__main__":
    unittest.main()
