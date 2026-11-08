"""Strict public v2 event and cumulative settlement-chain verification."""
import hashlib
import unittest

from ganesha.wallet.financial_evidence_contract_v2 import (
    BASE_EVENT, FEATURE_EVENT, make_v2_event, project_public_v2,
    verify_public_v2_chain, verify_public_v2_event,
)
from ganesha.math.config import WILD


BOARD = [["A", "K", "CHAKRA"], ["MOUSE", "A", "K"],
         [WILD, "A", "MODAK"], ["K", "CHAKRA", "A"], ["A", "MOUSE", "K"]]


def valid_chain():
    source_base = "a" * 64
    source_feature = "b" * 64
    base = make_v2_event("public-round", 1, "public-round:v2:outcome", BASE_EVENT, {
        "raw_payout_milli": 100, "wild_multiplier": 1, "expanded_wild_reels": [],
        "max_win_capped": False, "payout_milli": 100, "spin_number": 0,
        "board": BOARD, "display_board": BOARD, "source_ledger_event_hash": source_base,
        "outcome_sha256": "c" * 64, "engine_version": "engine-test-v1",
        "base_payout_milli": 100, "feature_payout_milli": 50,
        "total_payout_milli": 150, "payout_minor": 150,
        "round_cap_milli": 1_000, "round_cap_reached": False,
    })
    feature = make_v2_event("public-round", 2, "public-round:v2:feature:1", FEATURE_EVENT, {
        "raw_payout_milli": 25, "wild_multiplier": 2, "expanded_wild_reels": [2],
        "max_win_capped": False, "payout_milli": 50, "spin_number": 1,
        "payout_awarded_milli": 50, "remaining_spins": 9,
        "round_payout_after_milli": 150, "round_cap_applied": False,
        "board": BOARD, "display_board": [[WILD, WILD, WILD] if i == 2 else [*r] for i, r in enumerate(BOARD)],
        "source_ledger_event_hash": source_feature,
    }, previous_hash=base["event_hash"])
    public_base = project_public_v2(base)
    public_feature = project_public_v2(
        feature, previous_public_hash=public_base["event_hash"],
        expected_source_previous_hash=base["event_hash"], expected_sequence=2,
    )
    return [public_base, public_feature]


class FinancialEvidencePublicProjectionV2R1Tests(unittest.TestCase):
    def test_valid_base_feature_public_chain_reconciles(self):
        self.assertTrue(verify_public_v2_chain(valid_chain()))

    def test_public_base_rejects_missing_round_aggregate_fields_even_with_valid_hash(self):
        event = valid_chain()[0]
        del event["payload"]["feature_payout_milli"]
        event["event_hash"] = hashlib.sha256(
            __import__("json").dumps({k: v for k, v in event.items() if k != "event_hash"},
                                      sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "missing round settlement fields"):
            verify_public_v2_event(event)

    def test_public_feature_rejects_missing_lifecycle_fields_even_with_valid_hash(self):
        chain = valid_chain()
        event = chain[1]
        del event["payload"]["round_cap_applied"]
        event["event_hash"] = hashlib.sha256(
            __import__("json").dumps({k: v for k, v in event.items() if k != "event_hash"},
                                      sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "missing lifecycle/cap fields"):
            verify_public_v2_event(event, expected_previous_hash=chain[0]["event_hash"], expected_sequence=2)

    def test_public_feature_award_tampering_is_rejected_after_rehash(self):
        chain = valid_chain()
        chain[1]["payload"]["payout_awarded_milli"] = 49
        chain[1]["event_hash"] = hashlib.sha256(
            __import__("json").dumps({k: v for k, v in chain[1].items() if k != "event_hash"},
                                      sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "cumulative payout"):
            verify_public_v2_chain(chain)

    def test_cross_round_public_event_is_rejected(self):
        chain = valid_chain()
        chain[1]["round_id"] = "other-round"
        with self.assertRaisesRegex(ValueError, "cross-round"):
            verify_public_v2_chain(chain)


if __name__ == "__main__":
    unittest.main()
