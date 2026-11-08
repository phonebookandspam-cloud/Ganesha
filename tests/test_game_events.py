import unittest

from ganesha.game.events import EventContractError, apply_event, initial_state, make_event, replay_events


class RoundEventContractTests(unittest.TestCase):
    def _event(self, state, seq, event_type, payload):
        event = make_event(state, "event-%d" % seq, event_type, payload)
        return event, apply_event(state, event)

    def _reserved_state(self):
        state = initial_state("round-contract")
        for seq, kind, payload in (
            (1, "ROUND_OPENED", {"mode": "BASE"}),
            (2, "BET_RESERVED", {"account_id": "player-1", "currency": "USD", "debit_minor": 100, "operation_id": "debit-1"}),
            (3, "RNG_COMMITTED", {"commitment": "a" * 64, "generator_version": "test-v1"}),
        ):
            _, state = self._event(state, seq, kind, payload)
        return state

    def test_ordered_round_lifecycle_replays_deterministically(self):
        state = initial_state("round-contract")
        events = []
        for seq, kind, payload in (
            (1, "ROUND_OPENED", {"mode": "BASE"}),
            (2, "BET_RESERVED", {"account_id": "player-1", "currency": "USD", "debit_minor": 100, "operation_id": "debit-1"}),
            (3, "RNG_COMMITTED", {"commitment": "a" * 64, "generator_version": "test-v1"}),
            (4, "OUTCOME_COMMITTED", {"outcome_sha256": "b" * 64, "payout_minor": 250, "engine_version": "engine-v1"}),
            (5, "WIN_PRESENTED", {"payout_minor": 250}),
            (6, "SETTLED", {"operation_id": "credit-1", "credit_minor": 250, "currency": "USD"}),
            (7, "END_ROUND", {"terminal_status": "SETTLED"}),
        ):
            event, state = self._event(state, seq, kind, payload)
            events.append(event)
        replayed = replay_events("round-contract", events)
        self.assertEqual(replayed, state)
        self.assertEqual(replayed["status"], "ENDED")
        self.assertEqual(replayed["payout_minor"], 250)

    def test_server_outcome_event_accepts_only_well_formed_reel_boards(self):
        state = self._reserved_state()
        board = [["A", "K", "MOUSE"] for _ in range(5)]
        event = make_event(state, "outcome-board", "OUTCOME_COMMITTED",
                           {"outcome_sha256": "c" * 64, "payout_minor": 0, "engine_version": "engine-v1",
                            "base_board": board, "base_display_board": board})
        self.assertEqual(apply_event(state, event)["status"], "OUTCOME_COMMITTED")
        malformed = [list(reel) for reel in board]
        malformed.pop()
        invalid = make_event(state, "outcome-bad-board", "OUTCOME_COMMITTED",
                             {"outcome_sha256": "c" * 64, "payout_minor": 0, "engine_version": "engine-v1",
                              "base_board": malformed})
        with self.assertRaises(EventContractError):
            apply_event(state, invalid)

    def test_invalid_transition_and_missing_rng_are_rejected(self):
        state = initial_state("round-invalid")
        event = make_event(state, "outcome-first", "OUTCOME_COMMITTED",
                           {"outcome_sha256": "b" * 64, "payout_minor": 0, "engine_version": "x"})
        with self.assertRaises(EventContractError):
            apply_event(state, event)

    def test_sequence_gap_duplicate_event_id_and_tampered_hash_are_rejected(self):
        state = self._reserved_state()
        event = make_event(state, "event-5", "OUTCOME_COMMITTED",
                           {"outcome_sha256": "b" * 64, "payout_minor": 0, "engine_version": "x"})
        with self.assertRaises(EventContractError):
            apply_event(state, dict(event, sequence=5))
        with self.assertRaises(EventContractError):
            apply_event(state, dict(event, event_hash="0" * 64))
        with self.assertRaises(EventContractError):
            replay_events("round-contract", [event, event])

    def test_unknown_future_schema_version_fails_closed(self):
        state = initial_state("round-v2")
        event = make_event(state, "event-v2", "ROUND_OPENED", {"mode": "BASE"})
        event["schema_version"] = 2
        with self.assertRaises(EventContractError):
            apply_event(state, event)

    def test_event_envelope_rejects_unversioned_extension_fields(self):
        state = initial_state("round-envelope")
        event = make_event(state, "open", "ROUND_OPENED", {"mode": "BASE"})
        event["provider_hint"] = "untrusted"
        with self.assertRaises(EventContractError):
            apply_event(state, event)

    def test_committed_milli_payout_must_reconcile_to_feature_trace(self):
        state = self._reserved_state()
        _, state = self._event(state, 4, "FEATURE_STARTED", {"feature": "FREE_SPINS", "initial_spins": 1})
        _, state = self._event(state, 5, "FEATURE_SPIN_RESOLVED",
                               {"spin_number": 1, "stops": [0, 1, 2, 3, 4], "payout_milli": 35,
                                "retrigger_awarded": 0, "remaining_spins": 0})
        _, state = self._event(state, 6, "FEATURE_ENDED",
                               {"spins_played": 1, "payout_milli": 35, "termination_reason": "EXHAUSTED"})
        mismatched_feature = make_event(state, "bad-feature-total", "OUTCOME_COMMITTED",
                                        {"outcome_sha256": "d" * 64, "payout_minor": 4,
                                         "engine_version": "engine-v1", "base_payout_milli": 5,
                                         "feature_payout_milli": 34, "total_payout_milli": 39})
        with self.assertRaises(EventContractError):
            apply_event(state, mismatched_feature)
        mismatched_total = make_event(state, "bad-round-total", "OUTCOME_COMMITTED",
                                      {"outcome_sha256": "e" * 64, "payout_minor": 4,
                                       "engine_version": "engine-v1", "base_payout_milli": 5,
                                       "feature_payout_milli": 35, "total_payout_milli": 39})
        with self.assertRaises(EventContractError):
            apply_event(state, mismatched_total)
        valid = make_event(state, "valid-total", "OUTCOME_COMMITTED",
                           {"outcome_sha256": "f" * 64, "payout_minor": 4,
                            "engine_version": "engine-v1", "base_payout_milli": 5,
                            "feature_payout_milli": 35, "total_payout_milli": 40})
        committed = apply_event(state, valid)
        self.assertEqual(committed["total_payout_milli"], 40)

    def test_replay_rejects_non_object_entries_and_invalid_event_identifiers(self):
        with self.assertRaises(EventContractError):
            replay_events("round-malformed", [None])
        with self.assertRaises(EventContractError):
            replay_events("round-malformed", [{"event_id": ""}])
        state = initial_state("round-malformed")
        with self.assertRaises(EventContractError):
            make_event(state, "valid-id", "X" * 65, {})

    def test_refund_and_settlement_are_mutually_exclusive(self):
        state = self._reserved_state()
        event = make_event(state, "refund", "REFUNDED",
                           {"operation_id": "refund-1", "refund_minor": 100, "currency": "USD"})
        state = apply_event(state, event)
        end = make_event(state, "end", "END_ROUND", {"terminal_status": "REFUNDED"})
        state = apply_event(state, end)
        self.assertEqual(state["status"], "ENDED")
        with self.assertRaises(EventContractError):
            apply_event(state, make_event(state, "late-settle", "SETTLED",
                                          {"operation_id": "credit-1", "credit_minor": 0, "currency": "USD"}))

    def test_free_spins_feature_sequence_checks_remaining_count(self):
        state = self._reserved_state()
        _, state = self._event(state, 4, "FEATURE_STARTED", {"feature": "FREE_SPINS", "initial_spins": 2})
        event = make_event(state, "bad-spin", "FEATURE_SPIN_RESOLVED",
                           {"spin_number": 1, "stops": [0, 1, 2, 3, 4], "payout_milli": 0,
                            "retrigger_awarded": 1, "remaining_spins": 0})
        with self.assertRaises(EventContractError):
            apply_event(state, event)

    def test_free_spins_retrigger_fails_closed_even_when_remaining_count_reconciles(self):
        state = self._reserved_state()
        _, state = self._event(state, 4, "FEATURE_STARTED", {"feature": "FREE_SPINS", "initial_spins": 2})
        event = make_event(state, "forged-retrigger", "FEATURE_SPIN_RESOLVED",
                           {"spin_number": 1, "stops": [0, 1, 2, 3, 4], "payout_milli": 0,
                            "retrigger_awarded": 1, "remaining_spins": 2})
        with self.assertRaisesRegex(EventContractError, "retrigger is unspecified"):
            apply_event(state, event)

    def test_financial_round_cap_cannot_end_free_spins_without_verifiable_cap_evidence(self):
        state = self._reserved_state()
        _, state = self._event(state, 4, "FEATURE_STARTED", {"feature": "FREE_SPINS", "initial_spins": 2})
        _, state = self._event(state, 5, "FEATURE_SPIN_RESOLVED",
                               {"spin_number": 1, "stops": [0, 1, 2, 3, 4], "payout_milli": 0,
                                "retrigger_awarded": 0, "remaining_spins": 1})
        event = make_event(state, "unverified-cap-end", "FEATURE_ENDED",
                           {"spins_played": 1, "payout_milli": 0, "termination_reason": "ROUND_CAP"})
        with self.assertRaisesRegex(EventContractError, "ROUND_CAP termination requires verifiable"):
            apply_event(state, event)

    def test_financial_round_cap_requires_exact_base_plus_feature_reconciliation(self):
        state = self._reserved_state()
        _, state = self._event(state, 4, "FEATURE_STARTED", {
            "feature": "FREE_SPINS", "initial_spins": 2,
            "base_payout_milli": 100, "round_cap_milli": 1000,
        })
        _, state = self._event(state, 5, "FEATURE_SPIN_RESOLVED", {
            "spin_number": 1, "stops": [0, 1, 2, 3, 4], "payout_milli": 900,
            "retrigger_awarded": 0, "remaining_spins": 1,
            "round_payout_after_milli": 1000, "round_cap_applied": False,
        })
        _, state = self._event(state, 6, "FEATURE_ENDED", {
            "spins_played": 1, "payout_milli": 900, "termination_reason": "ROUND_CAP",
        })
        committed = make_event(state, "cap-outcome", "OUTCOME_COMMITTED", {
            "outcome_sha256": "a" * 64, "payout_minor": 100,
            "engine_version": "engine-v1", "base_payout_milli": 100,
            "feature_payout_milli": 900, "total_payout_milli": 1000,
        })
        self.assertTrue(apply_event(state, committed)["round_cap_reached"])

    def test_financial_round_cap_rejects_forged_round_payout_after_spin(self):
        state = self._reserved_state()
        _, state = self._event(state, 4, "FEATURE_STARTED", {
            "feature": "FREE_SPINS", "initial_spins": 2,
            "base_payout_milli": 100, "round_cap_milli": 1000,
        })
        event = make_event(state, "forged-cap-spin", "FEATURE_SPIN_RESOLVED", {
            "spin_number": 1, "stops": [0, 1, 2, 3, 4], "payout_milli": 900,
            "retrigger_awarded": 0, "remaining_spins": 1,
            "round_payout_after_milli": 999, "round_cap_applied": False,
        })
        with self.assertRaisesRegex(EventContractError, "round payout does not reconcile"):
            apply_event(state, event)

    def test_financial_feature_cannot_continue_after_round_cap_is_reached(self):
        state = self._reserved_state()
        _, state = self._event(state, 4, "FEATURE_STARTED", {
            "feature": "FREE_SPINS", "initial_spins": 2,
            "base_payout_milli": 100, "round_cap_milli": 1000,
        })
        _, state = self._event(state, 5, "FEATURE_SPIN_RESOLVED", {
            "spin_number": 1, "stops": [0, 1, 2, 3, 4], "payout_milli": 900,
            "retrigger_awarded": 0, "remaining_spins": 1,
            "round_payout_after_milli": 1000, "round_cap_applied": False,
        })
        event = make_event(state, "spin-after-cap", "FEATURE_SPIN_RESOLVED", {
            "spin_number": 2, "stops": [0, 1, 2, 3, 4], "payout_milli": 0,
            "retrigger_awarded": 0, "remaining_spins": 0,
            "round_payout_after_milli": 1000, "round_cap_applied": False,
        })
        with self.assertRaisesRegex(EventContractError, "cannot continue after the round cap"):
            apply_event(state, event)


if __name__ == "__main__":
    unittest.main()
