import copy
import unittest

from ganesha.game.events import (
    EventContractError,
    apply_simulation_event,
    initial_simulation_state,
    make_simulation_event,
    replay_simulation_events,
)


BOARD = [
    ["A", "SCATTER_LOTUS", "K"], ["MOUSE", "A", "SCATTER_LOTUS"],
    ["K", "ELEPHANT", "A"], ["SCATTER_LOTUS", "CHAKRA", "MOUSE"],
    ["A", "K", "MODAK"],
]


def board_with_scatter_count(count):
    board = copy.deepcopy(BOARD)
    cells = [(reel, row) for reel in range(5) for row in range(3)]
    for reel, row in cells:
        board[reel][row] = "A"
    for reel, row in cells[:count]:
        board[reel][row] = "SCATTER_LOTUS"
    return board


def simulation_stream(scatter_count=3, initial_spins=10, played=None,
                      base_payout=100, feature_payout=50, total_payout=150,
                      round_cap_reached=False):
    state = initial_simulation_state("runtime-event-test")
    events = []
    board = board_with_scatter_count(scatter_count)
    played = initial_spins if played is None else played

    def emit(event_type, payload):
        nonlocal state
        event = make_simulation_event(
            state, "runtime-event-test:simulation:%d" % (state["event_count"] + 1),
            event_type, payload,
        )
        events.append(event)
        state = apply_simulation_event(state, event)

    emit("SIMULATION_STARTED", {"mode": "BASE", "math_version": "test-math-v1"})
    emit("SIMULATION_OUTCOME_COMMITTED", {
        "base_board": board, "base_display_board": board,
        "scatter_count": scatter_count, "initial_free_spins": initial_spins,
        "free_spins_played": played, "base_payout_milli": base_payout,
        "feature_payout_milli": feature_payout, "total_payout_milli": total_payout,
        "round_cap_reached": round_cap_reached, "math_version": "test-math-v1",
    })
    emit("SIMULATION_COMPLETED", {"terminal_status": "COMPLETED"})
    return events, state


class SimulationEventContractTests(unittest.TestCase):
    def test_exact_three_scatter_simulation_replays_completed_outcome(self):
        events, state = simulation_stream()
        rebuilt = replay_simulation_events("runtime-event-test", events)
        self.assertEqual(rebuilt, state)
        self.assertEqual(state["classification"], "NON_FINANCIAL_SIMULATION")
        self.assertFalse(state["financial_effects"])
        self.assertEqual(state["initial_free_spins"], 10)
        self.assertEqual(state["free_spins_played"], 10)
        self.assertEqual(state["total_payout_milli"], 150)

    def test_four_scatter_simulation_accepts_twelve_free_spins(self):
        events, state = simulation_stream(
            scatter_count=4, initial_spins=12, played=12,
        )
        rebuilt = replay_simulation_events("runtime-event-test", events)
        self.assertEqual(rebuilt, state)
        self.assertEqual(state["initial_free_spins"], 12)
        self.assertEqual(state["free_spins_played"], 12)

    def test_five_and_six_plus_scatter_awards_fail_closed(self):
        for count in (5, 6):
            state = initial_simulation_state("runtime-event-test")
            first = make_simulation_event(state, "start", "SIMULATION_STARTED",
                                          {"mode": "BASE", "math_version": "test-math-v1"})
            state = apply_simulation_event(state, first)
            invalid = make_simulation_event(state, "outcome", "SIMULATION_OUTCOME_COMMITTED", {
                "base_board": board_with_scatter_count(count),
                "base_display_board": board_with_scatter_count(count),
                "scatter_count": count, "initial_free_spins": 0, "free_spins_played": 0,
                "base_payout_milli": 0, "feature_payout_milli": 0,
                "total_payout_milli": 0, "round_cap_reached": False,
                "math_version": "test-math-v1",
            })
            with self.subTest(scatter_count=count), self.assertRaises(EventContractError):
                apply_simulation_event(state, invalid)

    def test_wrong_exact_three_award_is_rejected(self):
        events, _ = simulation_stream()
        forged = copy.deepcopy(events)
        forged[1]["payload"]["initial_free_spins"] = 12
        forged[1]["event_hash"] = "0" * 64
        with self.assertRaises(EventContractError):
            replay_simulation_events("runtime-event-test", forged)

    def test_sequence_duplicate_and_tampered_hash_are_rejected(self):
        events, _ = simulation_stream()
        with self.assertRaisesRegex(EventContractError, "duplicate"):
            replay_simulation_events("runtime-event-test", [events[0], events[0]])
        with self.assertRaisesRegex(EventContractError, "sequence"):
            replay_simulation_events("runtime-event-test", [events[0], dict(events[2])])
        tampered = copy.deepcopy(events)
        tampered[1]["payload"]["total_payout_milli"] = 999
        with self.assertRaisesRegex(EventContractError, "hash"):
            replay_simulation_events("runtime-event-test", tampered)

    def test_simulation_events_are_not_accepted_as_financial_round_events(self):
        events, _ = simulation_stream()
        from ganesha.game.events import apply_event, initial_state
        with self.assertRaises(EventContractError):
            apply_event(initial_state("runtime-event-test"), events[0])

    def test_short_free_spin_sequence_without_round_cap_is_rejected(self):
        with self.assertRaisesRegex(EventContractError, "before exhaustion"):
            simulation_stream(played=9)

    def test_forged_round_cap_flag_without_cap_payout_is_rejected(self):
        with self.assertRaisesRegex(EventContractError, "round-cap flag"):
            simulation_stream(round_cap_reached=True)

    def test_valid_round_cap_can_terminate_free_spins_early(self):
        from ganesha.math.config import CONFIG
        feature_payout = CONFIG.max_round_win_milli - 100
        events, state = simulation_stream(
            played=3, base_payout=100, feature_payout=feature_payout,
            total_payout=CONFIG.max_round_win_milli, round_cap_reached=True,
        )
        rebuilt = replay_simulation_events("runtime-event-test", events)
        self.assertEqual(rebuilt, state)
        self.assertEqual(state["free_spins_played"], 3)
        self.assertTrue(state["round_cap_reached"])

    def test_zero_feature_outcome_is_valid_without_scatter(self):
        events, state = simulation_stream(
            scatter_count=0, initial_spins=0, played=0,
            base_payout=100, feature_payout=0, total_payout=100,
        )
        self.assertEqual(replay_simulation_events("runtime-event-test", events), state)
        self.assertEqual(state["free_spins_played"], 0)

    def test_simulation_scatter_count_must_match_board(self):
        state = initial_simulation_state("runtime-event-test")
        started = make_simulation_event(state, "start", "SIMULATION_STARTED",
                                        {"mode": "BASE", "math_version": "test-math-v1"})
        state = apply_simulation_event(state, started)
        invalid = make_simulation_event(state, "outcome", "SIMULATION_OUTCOME_COMMITTED", {
            "base_board": board_with_scatter_count(0),
            "base_display_board": board_with_scatter_count(0),
            "scatter_count": 3, "initial_free_spins": 10, "free_spins_played": 10,
            "base_payout_milli": 100, "feature_payout_milli": 50,
            "total_payout_milli": 150, "round_cap_reached": False,
            "math_version": "test-math-v1",
        })
        with self.assertRaisesRegex(EventContractError, "differs from the committed"):
            apply_simulation_event(state, invalid)


if __name__ == "__main__":
    unittest.main()
