"""Tests for the proposed v2 evidence contract; not production integration tests."""
import unittest

from ganesha.wallet.financial_evidence_contract_v2 import (
    BASE_EVENT, FEATURE_EVENT, EVIDENCE_FIELDS, FinancialEvidenceContractError,
    make_v2_event, project_public_v2, validate_spin_evidence, verify_v2_event,
    verify_public_v2_event,
)
from ganesha.math.config import WILD


_FEATURE_BOARD = [["A", "K", "CHAKRA"], ["MOUSE", "A", "K"],
                  [WILD, "A", "MODAK"], ["K", "CHAKRA", "A"],
                  ["A", "MOUSE", "K"]]


class FinancialEvidenceV2Tests(unittest.TestCase):
    def test_base_evidence_validates_and_is_preserved(self):
        payload = {"raw_payout_milli": 100, "wild_multiplier": 1,
                   "expanded_wild_reels": [], "max_win_capped": False,
                   "payout_milli": 100}
        self.assertEqual(set(validate_spin_evidence("BASE", payload)), set(EVIDENCE_FIELDS) | {"payout_milli"})

    def test_feature_evidence_validates_configured_multiplier(self):
        payload = {"raw_payout_milli": 25, "wild_multiplier": 2,
                   "expanded_wild_reels": [2], "max_win_capped": False,
                   "payout_milli": 50, "payout_awarded_milli": 50,
                   "board": _FEATURE_BOARD}
        self.assertEqual(validate_spin_evidence("FEATURE", payload)["payout_milli"], 50)

    def test_over_cap_is_rejected_instead_of_silently_credited(self):
        payload = {"raw_payout_milli": 1_000_001, "wild_multiplier": 1,
                   "expanded_wild_reels": [], "max_win_capped": False,
                   "payout_milli": 1_000_001}
        with self.assertRaises(FinancialEvidenceContractError):
            validate_spin_evidence("BASE", payload)

    def test_exact_cap_and_cap_plus_one_evidence_are_distinct(self):
        at_cap = {"raw_payout_milli": 1_000_000, "wild_multiplier": 1,
                  "expanded_wild_reels": [], "max_win_capped": False,
                  "payout_milli": 1_000_000}
        over_cap = dict(at_cap, raw_payout_milli=1_000_001,
                        max_win_capped=True, payout_milli=1_000_000)
        self.assertEqual(validate_spin_evidence("BASE", at_cap)["payout_milli"], 1_000_000)
        self.assertEqual(validate_spin_evidence("BASE", over_cap)["payout_milli"], 1_000_000)

    def test_malformed_types_and_inconsistent_multiplier_are_rejected(self):
        valid = {"raw_payout_milli": 25, "wild_multiplier": 2,
                 "expanded_wild_reels": [2], "max_win_capped": False,
                 "payout_milli": 50, "board": _FEATURE_BOARD}
        for field, value in (("raw_payout_milli", True), ("raw_payout_milli", 1.0),
                             ("raw_payout_milli", "25"), ("max_win_capped", 0),
                             ("expanded_wild_reels", [2, 2]), ("wild_multiplier", 4)):
            with self.subTest(field=field, value=value):
                with self.assertRaises(FinancialEvidenceContractError):
                    validate_spin_evidence("FEATURE", dict(valid, **{field: value}))

    def test_v2_hash_chain_and_public_projection_preserve_evidence_without_private_fields(self):
        payload = {"raw_payout_milli": 25, "wild_multiplier": 2,
                   "expanded_wild_reels": [2], "max_win_capped": False,
                   "payout_milli": 50, "payout_awarded_milli": 50,
                   "board": _FEATURE_BOARD,
                   "spin_number": 1, "remaining_spins": 9,
                   "round_payout_after_milli": 150, "round_cap_applied": False,
                   "source_ledger_event_hash": "a" * 64,
                   "account_id": "must-not-leak", "rng_commitment": "must-not-leak"}
        event = make_v2_event("round-v2", 1, "round-v2:feature:1", FEATURE_EVENT, payload)
        self.assertTrue(verify_v2_event(event))
        public = project_public_v2(event)
        self.assertTrue(set(EVIDENCE_FIELDS).issubset(public["payload"]))
        self.assertEqual(public["source_event_hash"], "a" * 64)
        self.assertNotIn("account_id", public["payload"])
        self.assertNotIn("rng_commitment", public["payload"])

    def test_base_event_v2_has_a_distinct_event_type_and_exact_evidence(self):
        payload = {"raw_payout_milli": 500, "wild_multiplier": 1,
                   "expanded_wild_reels": [], "max_win_capped": False,
                   "payout_milli": 500, "spin_number": 0,
                   "source_ledger_event_hash": "b" * 64,
                   "outcome_sha256": "c" * 64, "engine_version": "engine-v2",
                   "base_payout_milli": 500, "feature_payout_milli": 0,
                   "total_payout_milli": 500, "payout_minor": 500,
                   "round_cap_milli": 50_000_000, "round_cap_reached": False}
        event = make_v2_event("round-v2-base", 1, "round-v2-base:base", BASE_EVENT, payload)
        self.assertTrue(verify_v2_event(event))
        self.assertEqual(project_public_v2(event)["payload"]["raw_payout_milli"], 500)

    def test_v2_source_and_public_hash_chains_advance_without_rewriting_v1(self):
        first_payload = {"raw_payout_milli": 100, "wild_multiplier": 1,
                         "expanded_wild_reels": [], "max_win_capped": False,
                         "payout_milli": 100, "source_ledger_event_hash": "d" * 64,
                         "outcome_sha256": "e" * 64, "engine_version": "engine-v2",
                         "base_payout_milli": 100, "feature_payout_milli": 50,
                         "total_payout_milli": 150, "payout_minor": 150, "spin_number": 0,
                         "round_cap_milli": 50_000_000, "round_cap_reached": False}
        first = make_v2_event("round-chain", 1, "event-1", BASE_EVENT, first_payload)
        second_payload = {"raw_payout_milli": 25, "wild_multiplier": 2,
                          "expanded_wild_reels": [2], "max_win_capped": False,
                          "payout_milli": 50, "payout_awarded_milli": 50,
                          "board": _FEATURE_BOARD,
                          "source_ledger_event_hash": "f" * 64, "spin_number": 1,
                          "remaining_spins": 9, "round_payout_after_milli": 150,
                          "round_cap_applied": False}
        second = make_v2_event("round-chain", 2, "event-2", FEATURE_EVENT,
                               second_payload, previous_hash=first["event_hash"])
        self.assertTrue(verify_v2_event(second, first["event_hash"], 2))
        public_first = project_public_v2(first)
        public_second = project_public_v2(
            second, previous_public_hash=public_first["event_hash"],
            expected_source_previous_hash=first["event_hash"], expected_sequence=2,
        )
        self.assertEqual(public_second["previous_hash"], public_first["event_hash"])
        self.assertEqual(public_second["source_event_hash"], "f" * 64)
        self.assertTrue(verify_public_v2_event(public_first))
        self.assertTrue(verify_public_v2_event(
            public_second, expected_previous_hash=public_first["event_hash"], expected_sequence=2
        ))

    def test_feature_event_requires_round_awarded_amount(self):
        payload = {"raw_payout_milli": 25, "wild_multiplier": 2,
                   "expanded_wild_reels": [2], "max_win_capped": False,
                   "payout_milli": 50, "board": _FEATURE_BOARD}
        with self.assertRaises(FinancialEvidenceContractError):
            make_v2_event("round-v2-feature", 1, "event-1", FEATURE_EVENT, payload)

    def test_v1_event_is_not_accepted_by_v2_verifier(self):
        with self.assertRaises(FinancialEvidenceContractError):
            verify_v2_event({"schema_version": 1})

    def test_hash_tampering_is_rejected(self):
        payload = {"raw_payout_milli": 100, "wild_multiplier": 1,
                   "expanded_wild_reels": [], "max_win_capped": False,
                   "payout_milli": 100, "source_ledger_event_hash": "1" * 64,
                   "outcome_sha256": "2" * 64, "engine_version": "engine-v2",
                   "base_payout_milli": 100, "feature_payout_milli": 0,
                   "total_payout_milli": 100, "payout_minor": 100,
                   "round_cap_milli": 50_000_000, "round_cap_reached": False}
        event = make_v2_event("round-v2-tamper", 1, "event-1", BASE_EVENT, payload)
        event["payload"]["raw_payout_milli"] = 101
        with self.assertRaises(FinancialEvidenceContractError):
            verify_v2_event(event)

    def test_expanded_reel_must_contain_raw_wild_and_match_display_projection(self):
        payload = {"raw_payout_milli": 25, "wild_multiplier": 2,
                   "expanded_wild_reels": [2], "max_win_capped": False,
                   "payout_milli": 50, "board": [list(reel) for reel in _FEATURE_BOARD]}
        self.assertEqual(validate_spin_evidence("FEATURE", payload)["payout_milli"], 50)
        without_wild = [list(reel) for reel in _FEATURE_BOARD]
        without_wild[2] = ["A", "K", "CHAKRA"]
        with self.assertRaisesRegex(FinancialEvidenceContractError, "no matching raw Ganesha Wild"):
            validate_spin_evidence("FEATURE", dict(payload, board=without_wild))
        bad_display = [list(reel) for reel in _FEATURE_BOARD]
        bad_display[2] = ["A", "A", "A"]
        with self.assertRaisesRegex(FinancialEvidenceContractError, "display board"):
            validate_spin_evidence("FEATURE", dict(payload, display_board=bad_display))


if __name__ == "__main__":
    unittest.main()
