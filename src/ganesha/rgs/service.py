"""Local RGS orchestration boundary with deterministic round replay."""
import hashlib
import json
import re
import uuid
from pathlib import Path
from ganesha.game.engine import GameEngine
from ganesha.math.config import CONFIG
from ganesha.math.rng import HmacStopGenerator
from ganesha.wallet.ledger import WalletLedger, InvalidRoundState, DuplicateOperation

MAX_SQLITE_INTEGER = (1 << 63) - 1
MAX_BASE_BET_MINOR = (MAX_SQLITE_INTEGER * 1000 - 500) // CONFIG.max_round_win_milli
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _require_identifier(value, field, max_length=128):
    if not isinstance(value, str) or len(value) > max_length or not _IDENTIFIER.fullmatch(value):
        raise ValueError("%s must be a 1-%d character ASCII identifier" % (field, max_length))


def _engine_build_version():
    root = Path(__file__).resolve().parents[3]
    digest = hashlib.sha256()
    for relative in (
        "src/ganesha/game/engine.py", "src/ganesha/game/math_port.py",
        "src/ganesha/game/events.py", "src/ganesha/wallet/ledger.py",
        "src/ganesha/math/engine.py", "src/ganesha/math/config.py", "src/ganesha/math/rng.py",
        "src/ganesha/rgs/service.py",
    ):
        digest.update(relative.encode("utf-8") + b"\0" + (root / relative).read_bytes() + b"\0")
    return "game-engine-sha256:" + digest.hexdigest()


class RoundService:
    def __init__(self, ledger, game_engine=None, stop_generator=None,
                 allow_unapproved_math_for_tests=False, allow_test_vectors_for_tests=False):
        if not isinstance(ledger, WalletLedger):
            raise TypeError("A WalletLedger implementation is required")
        self.ledger = ledger
        self.game_engine = game_engine or GameEngine()
        self.stop_generator = stop_generator
        if type(allow_unapproved_math_for_tests) is not bool:
            raise TypeError("allow_unapproved_math_for_tests must be a boolean")
        if type(allow_test_vectors_for_tests) is not bool:
            raise TypeError("allow_test_vectors_for_tests must be a boolean")
        self.allow_unapproved_math_for_tests = allow_unapproved_math_for_tests
        self.allow_test_vectors_for_tests = allow_test_vectors_for_tests
        self.engine_version = _engine_build_version()

    def _mode_terms(self, mode, base_bet_minor):
        if mode == "BASE":
            return base_bet_minor, CONFIG.feature_rules.max_total_free_spins, None
        if mode in ("MAGIC_BUY", "EPIC_BUY"):
            terms = self.game_engine.get_bonus_buy_terms(mode)
            multiplier = terms["purchase_cost_multiplier_milli"]
            charge_minor = (base_bet_minor * multiplier + 500) // 1000
            return charge_minor, terms["max_stop_vectors"], terms
        raise ValueError("Unsupported round mode")

    def play_round(self, account_id, round_id, operation_id, base_bet_minor, mode, internal_stop_vectors=None):
        """Stops are generated server-side. Explicit vectors are permitted only for tests/audit."""
        _require_identifier(account_id, "account_id")
        _require_identifier(round_id, "round_id")
        _require_identifier(operation_id, "operation_id", max_length=110)
        if type(base_bet_minor) is not int or base_bet_minor <= 0 or base_bet_minor > MAX_BASE_BET_MINOR:
            raise ValueError("base_bet_minor is outside the supported integer range")
        if not isinstance(mode, str):
            raise ValueError("mode must be a string")
        if internal_stop_vectors is not None and not self.allow_test_vectors_for_tests:
            raise RuntimeError("Client-supplied stop vectors are restricted to explicit test-only service instances")
        if internal_stop_vectors is None and not self.allow_unapproved_math_for_tests:
            # A free-form `authority_status` attribute is not a trust decision.
            # This repository has no verified canonical-Math approval trust store,
            # so every server-generated financial round remains disabled until
            # that trust chain is implemented and independently reviewed.
            raise RuntimeError("Server-generated financial rounds are disabled until a canonical Math approval trust record is configured")
        charge_minor, max_vectors, bonus_buy_terms = self._mode_terms(mode, base_bet_minor)
        payout_cap_minor = (base_bet_minor * CONFIG.max_round_win_milli + 500) // 1000
        if internal_stop_vectors is not None:
            canonical = json.dumps([list(v) for v in internal_stop_vectors], separators=(",", ":"))
            commitment = "TEST:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        else:
            if not isinstance(self.stop_generator, HmacStopGenerator):
                raise RuntimeError("Production path requires server-side HmacStopGenerator; client stops are forbidden")
            commitment = self.stop_generator.commitment(round_id)

        try:
            generator_version = "test-vector" if internal_stop_vectors is not None else self.stop_generator.version
            reserved = self.ledger.reserve_bet(operation_id, round_id, account_id, charge_minor, commitment,
                                               max_payout_minor=payout_cap_minor, round_mode=mode,
                                               base_bet_minor=base_bet_minor, generator_version=generator_version,
                                               engine_version=self.engine_version)
        except DuplicateOperation:
            try:
                prior_round = self.ledger.round_snapshot(round_id)
            except InvalidRoundState:
                raise
            if prior_round["round"]["account_id"] != account_id:
                raise InvalidRoundState("Round belongs to a different account")
            raise
        snapshot = self.ledger.round_snapshot(round_id)
        if snapshot["round"]["account_id"] != account_id:
            raise InvalidRoundState("Round belongs to a different account")
        if snapshot["round"]["rng_commitment"] != commitment:
            raise InvalidRoundState("Round retry does not match the original RNG commitment")
        if snapshot["round"]["max_payout_minor"] != payout_cap_minor:
            raise InvalidRoundState("Round retry does not match the original payout cap")
        if snapshot["round"]["status"] == "SETTLED":
            return {"reservation": reserved, "outcome": snapshot["outcome"], "settlement": snapshot["operations"]["CREDIT"],
                    "events": snapshot["events"], "state": self.ledger.round_state(round_id)}
        if snapshot["round"]["status"] == "REFUNDED":
            raise InvalidRoundState("Round was already refunded")
        owner_id = "worker-" + uuid.uuid4().hex
        try:
            fencing_token = self.ledger.claim_recovery_lease(round_id, owner_id)
        except InvalidRoundState:
            # A concurrent identical request may have completed between the snapshot and lease claim.
            latest = self.ledger.round_snapshot(round_id)
            if latest["round"]["status"] == "SETTLED":
                return {"reservation": reserved, "outcome": latest["outcome"],
                        "settlement": latest["operations"]["CREDIT"], "events": latest["events"],
                        "state": self.ledger.round_state(round_id)}
            if latest["round"]["status"] == "REFUNDED":
                raise InvalidRoundState("Round was refunded by a concurrent request")
            raise
        try:
            snapshot = self.ledger.round_snapshot(round_id)
            if snapshot["round"]["status"] == "OUTCOME_COMMITTED":
                self.ledger.record_win_presented(round_id, fencing_token=fencing_token)
                self.ledger.renew_recovery_lease(round_id, owner_id, fencing_token)
                settled = self.ledger.settle_round(operation_id + ":settle", round_id, fencing_token=fencing_token)
                return {"reservation": reserved, "outcome": snapshot["outcome"], "settlement": settled,
                        "events": self.ledger.round_events(round_id), "state": self.ledger.round_state(round_id)}
            if snapshot["round"]["status"] != "BET_RESERVED":
                raise InvalidRoundState("Unexpected round state under recovery lease")
            try:
                if internal_stop_vectors is None:
                    if not isinstance(self.stop_generator, HmacStopGenerator):
                        raise RuntimeError("Recovery requires the original server-side HMAC generator")
                    stops = self.stop_generator.stop_vectors(round_id, max_vectors)
                else:
                    stops = list(internal_stop_vectors)
                if mode == "BASE":
                    if not stops:
                        raise ValueError("Base round requires one base stop vector")
                    outcome = self.game_engine.resolve_base_round(stops[0], stops[1:])
                else:
                    outcome = self.game_engine.resolve_bonus_buy_round(mode, stops, terms=bonus_buy_terms)
                outcome["engine_version"] = self.engine_version
                if outcome.get("initial_free_spins", 0):
                    has_feature_trace = any(event["event_type"] == "FEATURE_STARTED" for event in snapshot["events"])
                    if not has_feature_trace:
                        self.ledger.record_feature_progress(round_id, int(outcome["initial_free_spins"]),
                                                             list(outcome["feature_events"]),
                                                             bool(outcome["round_cap_reached"]),
                                                             fencing_token=fencing_token,
                                                             base_payout_milli=(outcome["base_result"]["payout_milli"]
                                                                                if mode == "BASE" else 0),
                                                             round_cap_milli=self.game_engine.round_cap_milli)
            except Exception:
                self.ledger.refund_reserved_round(operation_id + ":refund", round_id, fencing_token=fencing_token)
                raise

            payout_minor = (base_bet_minor * int(outcome["total_payout_milli"]) + 500) // 1000
            self.ledger.renew_recovery_lease(round_id, owner_id, fencing_token)
            self.ledger.commit_outcome(round_id, outcome, payout_minor, fencing_token=fencing_token)
            self.ledger.record_win_presented(round_id, fencing_token=fencing_token)
            self.ledger.renew_recovery_lease(round_id, owner_id, fencing_token)
            settled = self.ledger.settle_round(operation_id + ":settle", round_id, fencing_token=fencing_token)
            return {"reservation": reserved, "outcome": outcome, "settlement": settled,
                    "events": self.ledger.round_events(round_id), "state": self.ledger.round_state(round_id)}
        finally:
            self.ledger.release_recovery_lease(round_id, owner_id, fencing_token)

    def recover_round(self, round_id, account_id=None):
        """Resume a durable local round after process loss; test-vector rounds are not replayable."""
        snapshot = self.ledger.round_snapshot(round_id)
        row = snapshot["round"]
        if account_id is not None and row["account_id"] != account_id:
            raise InvalidRoundState("Round belongs to a different account")
        if row["status"] == "SETTLED":
            return {"round_id": round_id, "status": "SETTLED", "outcome": snapshot["outcome"],
                    "settlement": snapshot["operations"]["CREDIT"], "events": snapshot["events"],
                    "state": self.ledger.round_state(round_id)}
        if row["status"] == "REFUNDED":
            return {"round_id": round_id, "status": "REFUNDED"}
        debit = next((item for item in snapshot["operation_records"] if item["action"] == "DEBIT"), None)
        if debit is None:
            raise InvalidRoundState("Pending round has no durable debit operation")
        operation_id = debit["operation_id"]
        if row["status"] == "OUTCOME_COMMITTED":
            owner_id = "recovery-" + uuid.uuid4().hex
            token = self.ledger.claim_recovery_lease(round_id, owner_id)
            try:
                self.ledger.record_win_presented(round_id, fencing_token=token)
                self.ledger.renew_recovery_lease(round_id, owner_id, token)
                settled = self.ledger.settle_round(operation_id + ":settle", round_id, fencing_token=token)
                return {"round_id": round_id, "status": "SETTLED", "outcome": snapshot["outcome"], "settlement": settled,
                        "events": self.ledger.round_events(round_id), "state": self.ledger.round_state(round_id)}
            finally:
                self.ledger.release_recovery_lease(round_id, owner_id, token)
        if str(row["rng_commitment"]).startswith("TEST:"):
            return self._refund_pending_round(round_id, operation_id, "TEST_VECTOR_INPUT_NOT_PERSISTED")
        if row["engine_version"] != self.engine_version:
            return self._refund_pending_round(round_id, operation_id, "ENGINE_BUILD_VERSION_MISMATCH")
        if not isinstance(self.stop_generator, HmacStopGenerator):
            return self._refund_pending_round(round_id, operation_id, "RNG_SECRET_UNAVAILABLE")
        if (row["generator_version"] != self.stop_generator.version
                or self.stop_generator.commitment(round_id) != row["rng_commitment"]):
            return self._refund_pending_round(round_id, operation_id, "RNG_VERSION_OR_COMMITMENT_MISMATCH")
        return self.play_round(row["account_id"], round_id, operation_id, int(row["base_bet_minor"]), row["mode"])

    def _refund_pending_round(self, round_id, operation_id, reason):
        owner_id = "refund-pending-" + uuid.uuid4().hex
        token = self.ledger.claim_recovery_lease(round_id, owner_id)
        try:
            refunded = self.ledger.refund_reserved_round(operation_id + ":refund", round_id, fencing_token=token)
            return {"round_id": round_id, "status": "REFUNDED", "refund": refunded, "reason": reason,
                    "events": self.ledger.round_events(round_id), "state": self.ledger.round_state(round_id)}
        finally:
            self.ledger.release_recovery_lease(round_id, owner_id, token)

    def recover_pending_rounds(self):
        """Attempt each durable pending round once; failures are returned per round, not hidden."""
        results = []
        for round_id in self.ledger.pending_round_ids():
            try:
                results.append({"round_id": round_id, "ok": True, "result": self.recover_round(round_id)})
            except Exception as exc:
                results.append({"round_id": round_id, "ok": False, "error": type(exc).__name__, "detail": str(exc)})
        return results