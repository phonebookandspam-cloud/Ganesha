import copy
import unittest

from ganesha.game.engine import GameEngine
from ganesha.game.presentation import (
    PresentationContractError,
    apply_event,
    build_presentation_events,
    initial_state,
    make_event,
    replay_events,
)
from ganesha.math.engine import EmbeddedEpicFeatureUnavailable, UnspecifiedMathRule
from ganesha.math.config import CONFIG, WILD
from ganesha.game.math_port import DraftMathPort


BASE_BOARD = [
    ["A", "SCATTER_LOTUS", "K"],
    ["MOUSE", "A", "SCATTER_LOTUS"],
    ["K", "ELEPHANT", "A"],
    ["SCATTER_LOTUS", "CHAKRA", "MOUSE"],
    ["A", "K", "MODAK"],
]
FEATURE_BOARD = [
    ["A", "K", "CHAKRA"],
    ["MOUSE", "A", "K"],
    [WILD, "A", "MODAK"],
    ["K", "CHAKRA", "A"],
    ["A", "MOUSE", "K"],
]
FEATURE_DISPLAY = [list(reel) for reel in FEATURE_BOARD]
FEATURE_DISPLAY[2] = [WILD, WILD, WILD]
FOUR_SCATTER_BOARD = [["A", "A", "A"] for _ in range(5)]
for _reel, _row in ((0, 0), (1, 1), (2, 2), (4, 1)):
    FOUR_SCATTER_BOARD[_reel][_row] = "SCATTER_LOTUS"


class FixtureMathPort:
    """Explicit test fixture; contains no RNG, probability model or money logic."""
    authority_status = "TEST_FIXTURE_ONLY"
    version = "presentation-fixture-v1"

    def __init__(self, base_board=None):
        self.base_board = copy.deepcopy(base_board or BASE_BOARD)
        self.feature_calls = 0

    def evaluate_stops(self, stops, mode):
        if mode == "BASE":
            count = sum(symbol == "SCATTER_LOTUS" for reel in self.base_board for symbol in reel)
            if count == 3:
                awarded = 10
            elif count == 4:
                awarded = 12
            elif count == 5:
                raise EmbeddedEpicFeatureUnavailable("5 Scatter requires the provider EPICBUY_V37 feature payload")
            elif count < 3:
                awarded = 0
            else:
                raise UnspecifiedMathRule("Fixture refuses unspecified 6+ Scatter behavior")
            return {
                "mode": "BASE", "board": copy.deepcopy(self.base_board),
                "display_board": copy.deepcopy(self.base_board), "raw_payout_milli": 1000,
                "payout_milli": 1000, "wild_multiplier": 1,
                "expanded_wild_reels": [], "max_win_capped": False,
                "free_spins_awarded": awarded, "scatter_count": count,
            }
        if mode == "FREE_SPINS":
            self.feature_calls += 1
            return {
                "mode": "FREE_SPINS", "board": copy.deepcopy(FEATURE_BOARD),
                "display_board": copy.deepcopy(FEATURE_DISPLAY), "payout_milli": 50,
                "raw_payout_milli": 25, "scatter_count": 0, "expanded_wild_reels": [2],
                "wild_multiplier": 2, "line_wins": [], "max_win_capped": False,
                "jackpot_triggered": False,
            }
        raise ValueError("unsupported fixture mode")

    def award_free_spins(self, scatter_count, retrigger=False):
        if retrigger:
            if scatter_count >= 3:
                raise UnspecifiedMathRule("Fixture has no authorized retrigger rule")
            return 0
        if scatter_count == 3:
            return 10
        if scatter_count == 4:
            return 12
        if scatter_count in (0, 1, 2):
            return 0
        if scatter_count == 5:
            raise EmbeddedEpicFeatureUnavailable("5 Scatter requires the provider EPICBUY_V37 feature payload")
        raise UnspecifiedMathRule("Fixture refuses unspecified 6+ Scatter behavior")


class DevelopmentMathPort(FixtureMathPort):
    """Explicit local simulation adapter; not a canonical or financial Math source."""
    authority_status = "DEVELOPMENT_ONLY_NOT_CANONICAL"


class GamePresentationTests(unittest.TestCase):
    def test_exact_three_scatter_base_outcome_projects_full_free_spin_sequence(self):
        engine = GameEngine(math_port=FixtureMathPort())
        outcome = engine.resolve_base_round((0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-round-1", outcome)
        state = replay_events("fixture-round-1", events)

        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["classification"], "NON_FINANCIAL_PRESENTATION_ONLY")
        self.assertEqual(state["feature_initial_spins"], 10)
        self.assertEqual(state["feature_spins_played"], 10)
        self.assertEqual(state["feature_spins_remaining"], 0)
        self.assertEqual(state["total_payout_milli"], 1500)
        self.assertEqual(state["base_board"], BASE_BOARD)
        self.assertEqual(state["base_display_board"], BASE_BOARD)
        self.assertEqual(sum(event["event_type"] == "FEATURE_REEL_STOPPED" for event in events), 50)
        self.assertEqual(sum(event["event_type"] == "WILD_EXPANSION_APPLIED" for event in events), 10)
        self.assertEqual(sum(event["event_type"] == "MULTIPLIER_APPLIED" for event in events), 10)
        self.assertEqual(sum(event["event_type"] == "FEATURE_SPIN_RESOLVED" for event in events), 10)
        self.assertEqual(events, build_presentation_events("fixture-round-1", outcome))

    def test_four_scatter_awards_twelve_and_projects_all_spins(self):
        outcome = GameEngine(math_port=FixtureMathPort(FOUR_SCATTER_BOARD)).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 12)
        events = build_presentation_events("fixture-four-scatter", outcome)
        state = replay_events("fixture-four-scatter", events)
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["feature_initial_spins"], 12)
        self.assertEqual(state["feature_spins_played"], 12)
        self.assertEqual(state["feature_spins_remaining"], 0)
        self.assertEqual(sum(event["event_type"] == "FEATURE_SPIN_RESOLVED" for event in events), 12)

    def test_five_scatter_requires_provider_embedded_epic_payload_and_six_plus_fails_closed(self):
        for count, expected in ((5, EmbeddedEpicFeatureUnavailable), (6, UnspecifiedMathRule)):
            board = [["A", "A", "A"] for _ in range(5)]
            positions = [(0, 0), (1, 1), (2, 2), (3, 0), (4, 1), (0, 2)]
            for reel_index, row_index in positions[:count]:
                board[reel_index][row_index] = "SCATTER_LOTUS"
            with self.subTest(scatter_count=count):
                with self.assertRaises(expected):
                    GameEngine(math_port=FixtureMathPort(board)).resolve_base_round((0, 0, 0, 0, 0), [])

    def test_builder_rejects_three_plus_scatter_or_retrigger_inside_free_spins(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        outcome["feature_events"][0]["result"]["scatter_count"] = 3
        with self.assertRaises(PresentationContractError):
            build_presentation_events("fixture-fs-scatter", outcome)
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        outcome["feature_events"][0]["retrigger_awarded"] = 1
        with self.assertRaises(PresentationContractError):
            build_presentation_events("fixture-fs-retrigger", outcome)

    def test_builder_accepts_one_or_two_non_triggering_scatter_during_free_spins(self):
        outcome = GameEngine(math_port=DraftMathPort()).resolve_base_round(
            (0, 0, 2, 3, 4), [(0, 0, 4, 0, 5)] * 10)
        events = build_presentation_events(
            "draft-fs-two-scatter", outcome, classification="NON_FINANCIAL_PRESENTATION_ONLY",
        )
        state = replay_events("draft-fs-two-scatter", events, classification="NON_FINANCIAL_PRESENTATION_ONLY")
        self.assertEqual(state["status"], "COMPLETED")

    def test_builder_rejects_four_scatter_even_if_adapter_claims_ten_spins(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        outcome["base_result"]["board"][0][0] = "SCATTER_LOTUS"
        outcome["base_result"]["scatter_count"] = 4
        with self.assertRaises(PresentationContractError):
            build_presentation_events("fixture-four-scatter-forged", outcome)

    def test_replay_rejects_sequence_gap_duplicate_and_tampering(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-round-2", outcome)
        broken = copy.deepcopy(events)
        broken[1]["sequence"] += 1
        with self.assertRaises(PresentationContractError):
            replay_events("fixture-round-2", broken)
        with self.assertRaises(PresentationContractError):
            replay_events("fixture-round-2", events + [events[-1]])
        broken = copy.deepcopy(events)
        broken[1]["payload"]["symbols"][0] = "TAMPERED"
        with self.assertRaises(PresentationContractError):
            replay_events("fixture-round-2", broken)

    def test_board_outcome_must_match_the_five_stopped_reels(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-round-3", outcome)
        board_event = next(event for event in events if event["event_type"] == "BASE_OUTCOME_REVEALED")
        self.assertEqual(board_event["payload"]["board"], BASE_BOARD)
        self.assertEqual(replay_events("fixture-round-3", events)["base_board"], BASE_BOARD)

    def test_reducer_rejects_outcome_board_that_differs_from_reel_stop_events(self):
        state = initial_state("fixture-board-mismatch")
        events = []
        for kind, payload in [("ROUND_PRESENTATION_STARTED", {"mode": "BASE", "classification": "NON_FINANCIAL_PRESENTATION_ONLY"})]:
            event = make_event(state, kind, payload)
            state = apply_event(state, event)
            events.append(event)
        for reel_index, reel in enumerate(BASE_BOARD):
            event = make_event(state, "BASE_REEL_STOPPED", {"reel_index": reel_index, "symbols": list(reel)})
            state = apply_event(state, event)
            events.append(event)
        mismatched = copy.deepcopy(BASE_BOARD)
        mismatched[0][0] = "NOT_THE_STOPPED_SYMBOL"
        invalid = make_event(state, "BASE_OUTCOME_REVEALED", {
            "board": mismatched, "display_board": mismatched,
            "payout_milli": 1000, "free_spins_awarded": 10,
        })
        with self.assertRaises(PresentationContractError):
            apply_event(state, invalid)

    def test_reducer_rejects_buy_mode_until_authoritative_buy_rules_exist(self):
        for mode in ("MAGIC_BUY", "EPIC_BUY"):
            state = initial_state("fixture-buy-mode-" + mode)
            event = make_event(state, "ROUND_PRESENTATION_STARTED", {
                "mode": mode, "classification": "NON_FINANCIAL_PRESENTATION_ONLY",
            })
            with self.subTest(mode=mode), self.assertRaises(PresentationContractError):
                apply_event(state, event)

    def test_feature_cannot_end_with_a_partially_stopped_spin(self):
        state = initial_state("fixture-partial-feature")
        sequence = [
            ("ROUND_PRESENTATION_STARTED", {"mode": "BASE", "classification": "NON_FINANCIAL_PRESENTATION_ONLY"}),
        ]
        sequence.extend(("BASE_REEL_STOPPED", {"reel_index": i, "symbols": list(reel)})
                        for i, reel in enumerate(BASE_BOARD))
        sequence.append(("BASE_OUTCOME_REVEALED", {
            "board": BASE_BOARD, "display_board": BASE_BOARD,
            "raw_payout_milli": 1000, "payout_milli": 1000, "wild_reels": [],
            "multiplier": 1, "max_win_capped": False,
            "free_spins_awarded": 10, "round_cap_reached": False,
        }))
        sequence.append(("FEATURE_STARTED", {"feature": "FREE_SPINS", "initial_spins": 10}))
        sequence.append(("FEATURE_REEL_STOPPED", {
            "spin_number": 1, "reel_index": 0, "symbols": FEATURE_BOARD[0],
        }))
        for kind, payload in sequence:
            event = make_event(state, kind, payload)
            state = apply_event(state, event)
        invalid = make_event(state, "FEATURE_ENDED", {
            "spins_played": 0, "remaining_spins": 10, "payout_milli": 0,
            "termination_reason": "ROUND_CAP", "round_cap_reached": True,
        })
        with self.assertRaises(PresentationContractError):
            apply_event(state, invalid)

    def test_builder_rejects_base_spin_above_max_win_cap(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        outcome["base_result"]["raw_payout_milli"] = CONFIG.max_win_milli + 1
        outcome["base_result"]["payout_milli"] = CONFIG.max_win_milli + 1
        outcome["base_result"]["max_win_capped"] = False
        with self.assertRaises(PresentationContractError):
            build_presentation_events("base-spin-over-cap", outcome)

    def test_unapproved_jackpot_presentation_is_rejected(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        outcome["feature_events"][0]["result"]["jackpot_triggered"] = True
        with self.assertRaises(PresentationContractError):
            build_presentation_events("fixture-unapproved-jackpot", outcome)

    def test_completion_rejects_unbounded_final_payout_projection(self):
        port = FixtureMathPort()
        port.base_board = copy.deepcopy(BASE_BOARD)
        port.base_board[0][1] = "A"
        outcome = GameEngine(math_port=port).resolve_base_round((0, 0, 0, 0, 0), [])
        events = build_presentation_events("fixture-payout-cap", outcome)
        state = replay_events("fixture-payout-cap", events[:-1])
        invalid = make_event(state, "ROUND_PRESENTATION_COMPLETED", {
            "total_payout_milli": 10**15, "feature_spins_played": 0,
            "round_cap_reached": False,
        })
        with self.assertRaises(PresentationContractError):
            apply_event(state, invalid)


    def test_builder_rejects_base_display_board_that_differs_from_raw_board(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        outcome["base_result"]["display_board"][0][0] = "WILD"
        with self.assertRaises(PresentationContractError):
            build_presentation_events("fixture-base-display-forgery", outcome)

    def test_builder_rejects_feature_display_changes_outside_expanded_wild_reels(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        outcome["feature_events"][0]["result"]["display_board"][0][0] = "WILD"
        with self.assertRaises(PresentationContractError):
            build_presentation_events("fixture-feature-display-forgery", outcome)

    def test_reducer_rejects_arbitrary_round_payout_increase(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-payout-arithmetic", outcome)
        index = next(i for i, event in enumerate(events)
                     if event["event_type"] == "FEATURE_SPIN_RESOLVED")
        state = replay_events("fixture-payout-arithmetic", events[:index])
        payload = copy.deepcopy(events[index]["payload"])
        payload["round_payout_after_milli"] += 1
        forged = make_event(state, "FEATURE_SPIN_RESOLVED", payload)
        with self.assertRaises(PresentationContractError):
            apply_event(state, forged)

    def test_reducer_rejects_per_spin_award_that_does_not_reconcile(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-spin-award", outcome)
        index = next(i for i, event in enumerate(events)
                     if event["event_type"] == "FEATURE_SPIN_RESOLVED")
        state = replay_events("fixture-spin-award", events[:index])
        payload = copy.deepcopy(events[index]["payload"])
        payload["payout_awarded_milli"] += 1
        with self.assertRaises(PresentationContractError):
            apply_event(state, make_event(state, "FEATURE_SPIN_RESOLVED", payload))

    def test_reducer_requires_exact_int_and_bool_types(self):
        state = initial_state("fixture-strict-types")
        state = replay_events("fixture-strict-types", [make_event(state, "ROUND_PRESENTATION_STARTED", {
            "mode": "BASE", "classification": "NON_FINANCIAL_PRESENTATION_ONLY",
        })])
        invalid = make_event(state, "BASE_REEL_STOPPED", {"reel_index": True, "symbols": BASE_BOARD[0]})
        with self.assertRaises(PresentationContractError):
            apply_event(state, invalid)
        for i, reel in enumerate(BASE_BOARD):
            state = apply_event(state, make_event(state, "BASE_REEL_STOPPED", {
                "reel_index": i, "symbols": list(reel),
            }))
        with self.assertRaises(PresentationContractError):
            apply_event(state, make_event(state, "BASE_OUTCOME_REVEALED", {
                "board": BASE_BOARD, "display_board": BASE_BOARD,
                "payout_milli": 1000, "free_spins_awarded": 10,
                "round_cap_reached": 1,
            }))

    def test_reducer_requires_base_display_board_to_equal_raw_board(self):
        state = initial_state("fixture-base-display-reducer")
        events = [make_event(state, "ROUND_PRESENTATION_STARTED", {
            "mode": "BASE", "classification": "NON_FINANCIAL_PRESENTATION_ONLY",
        })]
        state = apply_event(state, events[-1])
        for i, reel in enumerate(BASE_BOARD):
            event = make_event(state, "BASE_REEL_STOPPED", {"reel_index": i, "symbols": list(reel)})
            state = apply_event(state, event)
            events.append(event)
        forged_display = copy.deepcopy(BASE_BOARD)
        forged_display[0][0] = "WILD"
        with self.assertRaises(PresentationContractError):
            apply_event(state, make_event(state, "BASE_OUTCOME_REVEALED", {
                "board": BASE_BOARD, "display_board": forged_display,
                "payout_milli": 1000, "free_spins_awarded": 10, "round_cap_reached": False,
            }))

    def test_reducer_requires_expanded_raw_reel_to_contain_wild(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-wild-source", outcome)
        index = next(i for i, event in enumerate(events) if event["event_type"] == "WILD_EXPANSION_APPLIED")
        state = replay_events("fixture-wild-source", events[:index])
        payload = copy.deepcopy(events[index]["payload"])
        payload["reels"] = [1]
        forged_display = copy.deepcopy(FEATURE_BOARD)
        forged_display[1] = ["WILD"] * 3
        payload["display_board"] = forged_display
        with self.assertRaises(PresentationContractError):
            apply_event(state, make_event(state, "WILD_EXPANSION_APPLIED", payload))

    def test_reducer_requires_non_expanded_feature_reels_to_remain_unchanged(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-wild-unchanged", outcome)
        index = next(i for i, event in enumerate(events) if event["event_type"] == "WILD_EXPANSION_APPLIED")
        state = replay_events("fixture-wild-unchanged", events[:index])
        payload = copy.deepcopy(events[index]["payload"])
        payload["display_board"][0][0] = "WILD"
        with self.assertRaises(PresentationContractError):
            apply_event(state, make_event(state, "WILD_EXPANSION_APPLIED", payload))

    def test_reducer_requires_wild_expansion_before_exact_multiplier(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-wild-multiplier-order", outcome)
        expansion_index = next(i for i, event in enumerate(events)
                              if event["event_type"] == "WILD_EXPANSION_APPLIED")
        multiplier_index = next(i for i, event in enumerate(events)
                               if event["event_type"] == "MULTIPLIER_APPLIED")
        multiplier_payload = copy.deepcopy(events[multiplier_index]["payload"])
        before_expansion = replay_events("fixture-wild-multiplier-order", events[:expansion_index])
        with self.assertRaises(PresentationContractError):
            apply_event(before_expansion, make_event(
                before_expansion, "MULTIPLIER_APPLIED", multiplier_payload))

        after_expansion = replay_events("fixture-wild-multiplier-order", events[:multiplier_index])
        wrong_multiplier = copy.deepcopy(multiplier_payload)
        wrong_multiplier["multiplier"] += 1
        with self.assertRaises(PresentationContractError):
            apply_event(after_expansion, make_event(
                after_expansion, "MULTIPLIER_APPLIED", wrong_multiplier))

    def test_reducer_rejects_multiplier_without_wild_expansion(self):
        state = initial_state("fixture-multiplier-without-wild")
        state = apply_event(state, make_event(state, "ROUND_PRESENTATION_STARTED", {
            "mode": "BASE", "classification": "NON_FINANCIAL_PRESENTATION_ONLY",
        }))
        for index, reel in enumerate(BASE_BOARD):
            state = apply_event(state, make_event(state, "BASE_REEL_STOPPED", {
                "reel_index": index, "symbols": list(reel),
            }))
        state = apply_event(state, make_event(state, "BASE_OUTCOME_REVEALED", {
            "board": BASE_BOARD, "display_board": BASE_BOARD,
            "raw_payout_milli": 1000, "payout_milli": 1000, "wild_reels": [],
            "multiplier": 1, "max_win_capped": False,
            "free_spins_awarded": 10, "round_cap_reached": False,
        }))
        state = apply_event(state, make_event(state, "FEATURE_STARTED", {
            "feature": "FREE_SPINS", "initial_spins": 10,
        }))
        for index, reel in enumerate(FEATURE_BOARD):
            state = apply_event(state, make_event(state, "FEATURE_REEL_STOPPED", {
                "spin_number": 1, "reel_index": index, "symbols": list(reel),
            }))
        with self.assertRaises(PresentationContractError):
            apply_event(state, make_event(state, "MULTIPLIER_APPLIED", {
                "spin_number": 1, "multiplier": 2,
            }))

    def test_reducer_rejects_retrigger_total_above_configured_cap(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-retrigger-cap", outcome)
        index = next(i for i, event in enumerate(events) if event["event_type"] == "FEATURE_SPIN_RESOLVED")
        state = replay_events("fixture-retrigger-cap", events[:index])
        payload = copy.deepcopy(events[index]["payload"])
        payload["retrigger_awarded"] = CONFIG.feature_rules.max_total_free_spins + 1
        payload["remaining_spins"] += payload["retrigger_awarded"]
        with self.assertRaises(PresentationContractError):
            apply_event(state, make_event(state, "FEATURE_SPIN_RESOLVED", payload))

    def test_reducer_rejects_unproven_round_cap_termination(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-cap-proof", outcome)
        end_index = next(i for i, event in enumerate(events) if event["event_type"] == "FEATURE_ENDED")
        state = replay_events("fixture-cap-proof", events[:end_index])
        payload = copy.deepcopy(events[end_index]["payload"])
        payload["termination_reason"] = "ROUND_CAP"
        payload["round_cap_reached"] = True
        with self.assertRaises(PresentationContractError):
            apply_event(state, make_event(state, "FEATURE_ENDED", payload))

    def test_reducer_rejects_feature_spin_above_max_win_cap(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("fixture-spin-cap-reducer", outcome)
        index = next(i for i, event in enumerate(events)
                     if event["event_type"] == "FEATURE_SPIN_RESOLVED")
        state = replay_events("fixture-spin-cap-reducer", events[:index])
        payload = copy.deepcopy(events[index]["payload"])
        payload["raw_payout_milli"] = CONFIG.max_win_milli + 1
        payload["payout_milli"] = CONFIG.max_win_milli + 1
        payload["max_win_capped"] = False
        with self.assertRaises(PresentationContractError):
            apply_event(state, make_event(state, "FEATURE_SPIN_RESOLVED", payload))

    def test_builder_rejects_authority_relabeling_and_non_base_base_result(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        forged = copy.deepcopy(outcome)
        forged["math_authority"] = "PROVIDER_APPROVED"
        events = build_presentation_events("fixture-authority-relabel", forged)
        self.assertEqual(replay_events("fixture-authority-relabel", events)["classification"],
                         "NON_FINANCIAL_PRESENTATION_ONLY")
        forged = copy.deepcopy(outcome)
        forged["base_result"]["mode"] = "MAGIC_BUY"
        with self.assertRaises(PresentationContractError):
            build_presentation_events("fixture-base-result-mode", forged)

    def test_development_simulation_is_unconditionally_non_financial(self):
        outcome = GameEngine(math_port=DevelopmentMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("development-simulation", outcome)
        state = replay_events("development-simulation", events)
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["classification"], "NON_FINANCIAL_PRESENTATION_ONLY")

    def test_mutable_development_authority_metadata_never_changes_presentation_classification(self):
        outcome = GameEngine(math_port=DevelopmentMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        self.assertEqual(outcome["math_authority"], "DEVELOPMENT_ONLY_NOT_CANONICAL")
        # Mutating a descriptive claim cannot promote the non-financial projection.
        outcome["math_authority"] = "TEST_FIXTURE_ONLY"
        events = build_presentation_events("development-relabelled-as-fixture", outcome)
        state = replay_events("development-relabelled-as-fixture", events)
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(state["classification"], "NON_FINANCIAL_PRESENTATION_ONLY")
        self.assertTrue(all("math_authority" not in event and "authority_status" not in event
                            for event in events))

    def test_mutable_authority_metadata_cannot_relabel_projection(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        for claimed_authority in ("PROVIDER_APPROVED", "TEST_FIXTURE_ONLY", "DEVELOPMENT_ONLY_NOT_CANONICAL", None):
            forged = copy.deepcopy(outcome)
            forged["math_authority"] = claimed_authority
            events = build_presentation_events("authority-is-never-proof", forged)
            state = replay_events("authority-is-never-proof", events)
            self.assertEqual(state["classification"], "NON_FINANCIAL_PRESENTATION_ONLY")

    def test_classification_cannot_be_overridden_or_coerced(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        for invalid in ("TEST_FIXTURE_ONLY", "NON_FINANCIAL_SIMULATION", 1, True, None, [], {}, ["NON_FINANCIAL_PRESENTATION_ONLY"]):
            with self.subTest(classification=invalid), self.assertRaises(PresentationContractError):
                build_presentation_events("classification-strict", outcome, classification=invalid)
            with self.subTest(initial_state_classification=invalid), self.assertRaises(PresentationContractError):
                initial_state("classification-strict", classification=invalid)

    def test_builder_rejects_non_boolean_jackpot_evidence(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        outcome["feature_events"][0]["result"]["jackpot_triggered"] = 0
        with self.assertRaises(PresentationContractError):
            build_presentation_events("fixture-jackpot-type", outcome)


    def test_builder_rejects_feature_spin_above_max_win_cap(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        result = outcome["feature_events"][0]["result"]
        result["raw_payout_milli"] = CONFIG.max_win_milli + 1
        result["payout_milli"] = CONFIG.max_win_milli + 1
        with self.assertRaises(PresentationContractError):
            build_presentation_events("feature-spin-over-cap", outcome)

    def test_builder_rejects_inconsistent_raw_payout_multiplier_product(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        result = outcome["feature_events"][0]["result"]
        result["payout_milli"] += 1
        with self.assertRaises(PresentationContractError):
            build_presentation_events("feature-payout-product", outcome)

    def test_builder_requires_wild_multiplier_from_exact_expanded_reel_count(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        result = outcome["feature_events"][0]["result"]
        result["wild_multiplier"] = 4
        result["payout_milli"] = 100
        with self.assertRaises(PresentationContractError):
            build_presentation_events("feature-wild-multiplier-count", outcome)

    def test_builder_requires_explicit_expansion_and_multiplier_evidence(self):
        for field in ("expanded_wild_reels", "wild_multiplier"):
            outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
                (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
            del outcome["feature_events"][0]["result"][field]
            with self.subTest(field=field), self.assertRaises(PresentationContractError):
                build_presentation_events("feature-missing-wild-evidence", outcome)

    def test_reducer_requires_exact_string_classification(self):
        state = initial_state("fixture-classification-type")
        for classification in (1, True, None, "TEST_FIXTURE_ONLY", [], {}, ["NON_FINANCIAL_PRESENTATION_ONLY"]):
            event = make_event(state, "ROUND_PRESENTATION_STARTED", {
                "mode": "BASE", "classification": classification,
            })
            with self.subTest(classification=classification), self.assertRaises(PresentationContractError):
                apply_event(state, event)

    def test_builder_rejects_malformed_or_ignored_max_win_capped(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        result = outcome["feature_events"][0]["result"]
        result["max_win_capped"] = 0
        with self.assertRaises(PresentationContractError):
            build_presentation_events("feature-max-win-type", outcome)
        result["raw_payout_milli"] = CONFIG.max_win_milli
        result["wild_multiplier"] = 2
        result["payout_milli"] = CONFIG.max_win_milli
        result["max_win_capped"] = False
        with self.assertRaises(PresentationContractError):
            build_presentation_events("feature-max-win-ignored", outcome)

    def test_reducer_rejects_wrong_wild_multiplier_and_max_win_flag(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("feature-reducer-multiplier", outcome)
        index = next(i for i, event in enumerate(events)
                     if event["event_type"] == "FEATURE_SPIN_RESOLVED")
        for field, value in (("multiplier", 4), ("max_win_capped", 0)):
            state = replay_events("feature-reducer-multiplier", events[:index])
            payload = copy.deepcopy(events[index]["payload"])
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(PresentationContractError):
                apply_event(state, make_event(state, "FEATURE_SPIN_RESOLVED", payload))

    def test_builder_rejects_base_max_win_cap_flag_that_is_ignored(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        base = outcome["base_result"]
        base["raw_payout_milli"] = CONFIG.max_win_milli + 1
        base["payout_milli"] = CONFIG.max_win_milli
        base["max_win_capped"] = False
        with self.assertRaises(PresentationContractError):
            build_presentation_events("base-max-win-ignored", outcome)

    def test_reducer_rejects_base_spin_above_max_win_cap(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        events = build_presentation_events("base-reducer-spin-cap", outcome)
        index = next(i for i, event in enumerate(events)
                     if event["event_type"] == "BASE_OUTCOME_REVEALED")
        state = replay_events("base-reducer-spin-cap", events[:index])
        payload = copy.deepcopy(events[index]["payload"])
        payload["raw_payout_milli"] = CONFIG.max_win_milli + 1
        payload["payout_milli"] = CONFIG.max_win_milli + 1
        payload["max_win_capped"] = False
        with self.assertRaises(PresentationContractError):
            apply_event(state, make_event(state, "BASE_OUTCOME_REVEALED", payload))

    def test_builder_rejects_final_round_cap_flag_not_matching_final_payout(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        outcome["round_cap_reached"] = True
        with self.assertRaises(PresentationContractError):
            build_presentation_events("fixture-forged-round-cap", outcome)

    def test_buy_modes_are_not_inferred_from_base_presentation_contract(self):
        outcome = GameEngine(math_port=FixtureMathPort()).resolve_base_round(
            (0, 0, 0, 0, 0), [(1, 1, 1, 1, 1)] * 10)
        outcome["mode"] = "MAGIC_BUY"
        with self.assertRaises(PresentationContractError):
            build_presentation_events("fixture-buy", outcome)


if __name__ == "__main__":
    unittest.main()