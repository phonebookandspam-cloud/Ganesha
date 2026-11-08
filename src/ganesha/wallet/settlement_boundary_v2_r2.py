"""Fail-closed Wallet commit adapter for the current BASE GameEngine contract.

Wrap a WalletLedger before passing it to RoundService (or make_handler). The
adapter is a WalletLedger subclass so the existing RoundService type boundary
accepts it, while all non-commit operations delegate to the original ledger.

This adapter enforces the independent spin/round payout guard at the Wallet
outcome-commit boundary and persists a linked v2 evidence sidecar. The v1
round_events stream is not rewritten; the v2 sidecar is a separate versioned
financial-evidence stream whose source hashes bind to the immutable v1 events.
"""
import json
import hashlib
import ipaddress
import re
import sqlite3
from http.server import ThreadingHTTPServer

from ganesha.game.engine_payout_guard_r1 import validate_outcome_for_settlement
from ganesha.wallet.financial_evidence_contract_v2 import (
    BASE_EVENT,
    FEATURE_EVENT,
    ZERO_HASH,
    make_v2_event,
    project_public_v2,
    validate_spin_evidence,
    verify_public_v2_event,
    verify_public_v2_chain,
    verify_v2_event,
)
from ganesha.wallet.ledger import InvalidRoundState, LedgerError, WalletLedger
from ganesha.math.config import CONFIG


MAX_SQLITE_INTEGER = (1 << 63) - 1


class SettlementBoundaryV2Error(LedgerError):
    """Outcome failed the independent financial settlement boundary."""


class GuardedWalletLedger(WalletLedger):
    """WalletLedger-compatible decorator enforcing payout evidence on commit."""

    def __init__(self, delegate, *, spin_cap_milli=None, round_cap_milli=None):
        if not isinstance(delegate, WalletLedger):
            raise TypeError("delegate must be a WalletLedger")
        spin_cap = CONFIG.max_win_milli if spin_cap_milli is None else spin_cap_milli
        round_cap = CONFIG.max_round_win_milli if round_cap_milli is None else round_cap_milli
        if type(spin_cap) is not int or spin_cap <= 0:
            raise ValueError("spin_cap_milli must be a positive exact integer")
        if type(round_cap) is not int or round_cap <= 0:
            raise ValueError("round_cap_milli must be a positive exact integer")
        if spin_cap > CONFIG.max_win_milli:
            raise ValueError("spin_cap_milli cannot exceed the canonical configured limit")
        if round_cap > CONFIG.max_round_win_milli:
            raise ValueError("round_cap_milli cannot exceed the canonical configured limit")
        self._spin_cap_milli = spin_cap
        self._round_cap_milli = round_cap
        self._delegate = delegate
        with self._delegate._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS round_financial_evidence_v2 (
                round_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                event_json TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                source_ledger_event_hash TEXT NOT NULL,
                PRIMARY KEY(round_id, sequence)
            )""")
            # Existing evidence rows are append-only at the SQLite boundary.
            # Recovery may append a missing suffix, but ordinary SQL UPDATE,
            # DELETE, or conflict-driven REPLACE must not rewrite a committed
            # prefix. This is local database hardening, not protection against
            # an actor who can alter the SQLite schema or database file.
            db.executescript("""
            CREATE TRIGGER IF NOT EXISTS round_financial_evidence_v2_no_update
            BEFORE UPDATE ON round_financial_evidence_v2
            BEGIN
              SELECT RAISE(ABORT, 'round financial evidence v2 is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS round_financial_evidence_v2_no_delete
            BEFORE DELETE ON round_financial_evidence_v2
            BEGIN
              SELECT RAISE(ABORT, 'round financial evidence v2 is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS round_financial_evidence_v2_no_replace
            BEFORE INSERT ON round_financial_evidence_v2
            WHEN EXISTS (
              SELECT 1 FROM round_financial_evidence_v2
              WHERE (round_id=NEW.round_id AND sequence=NEW.sequence)
                 OR event_id=NEW.event_id
            )
            BEGIN
              SELECT RAISE(ABORT, 'round financial evidence v2 duplicate identity is immutable');
            END;
            """)

    def __setattr__(self, name, value):
        if name in ("_spin_cap_milli", "_round_cap_milli") and name in self.__dict__:
            raise AttributeError("guarded payout caps are immutable after construction")
        super().__setattr__(name, value)

    @property
    def spin_cap_milli(self):
        return self._spin_cap_milli

    @property
    def round_cap_milli(self):
        return self._round_cap_milli

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def _validate_spin_evidence(self, outcome):
        """Apply v2 evidence arithmetic to BASE and each FREE_SPINS result.

        GameEngine intentionally retains the MathPort mode ``FREE_SPINS``;
        the v2 evidence contract's semantic mode is ``FEATURE``. The mode is
        supplied to the validator, not rewritten in the persisted outcome.
        """
        if not isinstance(outcome, dict) or outcome.get("mode") != "BASE":
            raise SettlementBoundaryV2Error("only BASE outcomes are enabled at this boundary")
        base = outcome.get("base_result")
        if not isinstance(base, dict):
            raise SettlementBoundaryV2Error("BASE result is malformed")
        validate_spin_evidence("BASE", base, self.spin_cap_milli)
        if (base["raw_payout_milli"] > MAX_SQLITE_INTEGER
                or base["raw_payout_milli"] * base["wild_multiplier"] > MAX_SQLITE_INTEGER
                or base["payout_milli"] > MAX_SQLITE_INTEGER):
            raise SettlementBoundaryV2Error("BASE payout evidence exceeds the supported integer range")
        events = outcome.get("feature_events")
        if not isinstance(events, list):
            raise SettlementBoundaryV2Error("feature_events must be a list")
        for item in events:
            if not isinstance(item, dict) or not isinstance(item.get("result"), dict):
                raise SettlementBoundaryV2Error("FEATURE event result is malformed")
            if item["result"].get("mode") != "FREE_SPINS":
                raise SettlementBoundaryV2Error("Math FEATURE result must retain FREE_SPINS mode")
            validate_spin_evidence("FEATURE", item["result"], self.spin_cap_milli)
            result = item["result"]
            if (result["raw_payout_milli"] > MAX_SQLITE_INTEGER
                    or result["raw_payout_milli"] * result["wild_multiplier"] > MAX_SQLITE_INTEGER
                    or result["payout_milli"] > MAX_SQLITE_INTEGER):
                raise SettlementBoundaryV2Error("FEATURE payout evidence exceeds the supported integer range")
        return outcome

    @staticmethod
    def _build_v2_events(round_id, outcome, ledger_events, round_row, round_cap_milli):
        by_id = {event["event_id"]: event for event in ledger_events}
        base_source = by_id.get(round_id + ":outcome")
        if not base_source or base_source.get("event_type") != "OUTCOME_COMMITTED":
            raise SettlementBoundaryV2Error("v1 OUTCOME_COMMITTED source event is missing")
        base = outcome["base_result"]
        outcome_json = json.dumps(outcome, sort_keys=True, separators=(",", ":"))
        outcome_digest = hashlib.sha256(outcome_json.encode("utf-8")).hexdigest()
        total_milli = outcome["total_payout_milli"]
        base_bet_minor = round_row.get("base_bet_minor")
        payout_minor = round_row.get("payout_minor")
        if type(base_bet_minor) is not int or base_bet_minor <= 0 or type(payout_minor) is not int or payout_minor < 0:
            raise SettlementBoundaryV2Error("reserved round bet or committed payout is invalid")
        expected_minor = (base_bet_minor * total_milli + 500) // 1000
        source_payload = base_source.get("payload")
        if (not isinstance(source_payload, dict)
                or source_payload.get("outcome_sha256") != outcome_digest
                or source_payload.get("payout_minor") != payout_minor
                or source_payload.get("engine_version") != round_row.get("engine_version")
                or payout_minor != expected_minor):
            raise SettlementBoundaryV2Error("v1 OUTCOME_COMMITTED digest, engine version or Wallet payout does not match the persisted outcome")
        base_payload = {key: base[key] for key in (
            "raw_payout_milli", "wild_multiplier", "expanded_wild_reels", "max_win_capped", "payout_milli"
        )}
        feature_payout = total_milli - base["payout_milli"]
        base_payload.update({
            "spin_number": 0,
            "board": base.get("board"),
            "display_board": base.get("display_board", base.get("board")),
            "source_ledger_event_hash": base_source["event_hash"],
            "outcome_sha256": outcome_digest,
            "engine_version": round_row["engine_version"],
            "base_payout_milli": base["payout_milli"],
            "feature_payout_milli": feature_payout,
            "total_payout_milli": total_milli,
            "payout_minor": payout_minor,
            "round_cap_milli": round_cap_milli,
            "round_cap_reached": outcome["round_cap_reached"],
        })
        events = [make_v2_event(
            round_id, 1, round_id + ":v2:outcome", BASE_EVENT, base_payload, ZERO_HASH
        )]
        previous = events[-1]["event_hash"]
        initial = outcome["initial_free_spins"]
        for index, item in enumerate(outcome["feature_events"], start=1):
            source_id = round_id + ":feature-spin-%d" % index
            source = by_id.get(source_id)
            if not source or source.get("event_type") != "FEATURE_SPIN_RESOLVED":
                raise SettlementBoundaryV2Error("v1 FEATURE_SPIN_RESOLVED source event is missing")
            result = item["result"]
            source_payload = source.get("payload")
            expected_remaining = initial - index
            if (not isinstance(source_payload, dict)
                    or source_payload.get("spin_number") != index
                    or source_payload.get("stops") != list(item["stops"])
                    or source_payload.get("payout_milli") != item["payout_awarded_milli"]
                    or source_payload.get("remaining_spins") != expected_remaining
                    or source_payload.get("round_payout_after_milli") != item["round_payout_after_milli"]
                    or source_payload.get("round_cap_applied") != item["round_cap_applied"]
                    or source_payload.get("board") != result.get("board")
                    or source_payload.get("display_board") != result.get("display_board", result.get("board"))):
                raise SettlementBoundaryV2Error("v1 FEATURE_SPIN_RESOLVED payload does not match the committed Math outcome")
            payload = {key: result[key] for key in (
                "raw_payout_milli", "wild_multiplier", "expanded_wild_reels", "max_win_capped", "payout_milli"
            )}
            payload.update({
                "spin_number": index,
                "stops": list(item["stops"]),
                "payout_awarded_milli": item["payout_awarded_milli"],
                "remaining_spins": expected_remaining,
                "round_payout_after_milli": item["round_payout_after_milli"],
                "round_cap_applied": item["round_cap_applied"],
                "board": result.get("board"),
                "display_board": result.get("display_board", result.get("board")),
                "source_ledger_event_hash": source["event_hash"],
            })
            event = make_v2_event(
                round_id, index + 1, round_id + ":v2:feature:%d" % index,
                FEATURE_EVENT, payload, previous,
            )
            events.append(event)
            previous = event["event_hash"]
        return events

    def _ensure_v2_evidence(self, round_id):
        snapshot = self._delegate.round_snapshot(round_id)
        if snapshot["round"]["status"] not in ("OUTCOME_COMMITTED", "SETTLED") or not snapshot["outcome"]:
            raise SettlementBoundaryV2Error("v2 evidence requires a durably committed Wallet outcome")
        outcome = snapshot["outcome"]
        if (snapshot["round"].get("mode") != "BASE"
                or outcome.get("engine_version") != snapshot["round"].get("engine_version")):
            raise SettlementBoundaryV2Error("persisted outcome identity differs from its reserved round")
        self._delegate.round_state(round_id)  # replay and verify the immutable v1 source hash chain
        self._validate_spin_evidence(outcome)
        validate_outcome_for_settlement(
            outcome, spin_cap_milli=self.spin_cap_milli, round_cap_milli=self.round_cap_milli
        )
        desired = self._build_v2_events(
            round_id, outcome, snapshot["events"], snapshot["round"], self.round_cap_milli
        )
        with self._delegate._connect() as db:
            self._delegate._begin_immediate(db)
            rows = db.execute(
                "SELECT event_json,event_id,event_type,schema_version,sequence,event_hash,source_ledger_event_hash "
                "FROM round_financial_evidence_v2 WHERE round_id=? ORDER BY sequence",
                (round_id,),
            ).fetchall()
            if len(rows) > len(desired):
                db.rollback()
                raise SettlementBoundaryV2Error("v2 evidence stream contains unexpected trailing events")
            for index, row in enumerate(rows):
                expected = desired[index]
                try:
                    event = json.loads(row["event_json"])
                except (TypeError, ValueError) as exc:
                    db.rollback()
                    raise SettlementBoundaryV2Error("persisted v2 evidence JSON is malformed") from exc
                source_hash = expected["payload"].get("source_ledger_event_hash")
                if (event != expected
                        or row["event_id"] != expected["event_id"]
                        or row["event_type"] != expected["event_type"]
                        or row["schema_version"] != expected["schema_version"]
                        or row["sequence"] != expected["sequence"]
                        or row["event_hash"] != expected["event_hash"]
                        or row["source_ledger_event_hash"] != source_hash):
                    db.rollback()
                    raise SettlementBoundaryV2Error("persisted v2 evidence conflicts with committed outcome")
            for event in desired[len(rows):]:
                source_hash = event["payload"].get("source_ledger_event_hash")
                if not isinstance(source_hash, str) or len(source_hash) != 64:
                    db.rollback()
                    raise SettlementBoundaryV2Error("v2 event is not linked to a v1 source event hash")
                encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                db.execute(
                    "INSERT INTO round_financial_evidence_v2 "
                    "(round_id,sequence,event_id,event_type,schema_version,event_json,event_hash,source_ledger_event_hash) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (round_id, event["sequence"], event["event_id"], event["event_type"],
                     event["schema_version"], encoded, event["event_hash"], source_hash),
                )
            db.commit()
        return self.financial_evidence_v2(round_id)

    def financial_evidence_v2(self, round_id):
        snapshot = self._delegate.round_snapshot(round_id)
        if snapshot["round"]["status"] not in ("OUTCOME_COMMITTED", "SETTLED") or not snapshot["outcome"]:
            raise SettlementBoundaryV2Error("v2 evidence requires a durably committed Wallet outcome")
        self._delegate.round_state(round_id)  # verify the immutable v1 event hash chain and reducer
        expected = self._build_v2_events(
            round_id, snapshot["outcome"], snapshot["events"], snapshot["round"], self.round_cap_milli
        )
        with self._delegate._connect() as db:
            rows = db.execute(
                "SELECT event_json,event_id,event_type,schema_version,sequence,event_hash,source_ledger_event_hash "
                "FROM round_financial_evidence_v2 WHERE round_id=? ORDER BY sequence", (round_id,)
            ).fetchall()
        if len(rows) != len(expected):
            raise SettlementBoundaryV2Error("v2 evidence stream is incomplete or has unexpected trailing events")
        result = []
        previous = ZERO_HASH
        for index, row in enumerate(rows, start=1):
            event = json.loads(row["event_json"])
            verify_v2_event(event, previous, index)
            source_hash = event["payload"].get("source_ledger_event_hash")
            expected_source_id = (round_id + ":outcome" if event["event_type"] == BASE_EVENT
                                  else round_id + ":feature-spin-%d" % (event["sequence"] - 1))
            source = next((item for item in snapshot["events"] if item["event_id"] == expected_source_id), None)
            if (event != expected[index - 1]
                    or row["event_id"] != event["event_id"]
                    or row["event_type"] != event["event_type"]
                    or row["schema_version"] != event["schema_version"]
                    or row["sequence"] != event["sequence"]
                    or row["event_hash"] != event["event_hash"]
                    or source is None
                    or source_hash != source["event_hash"]
                    or row["source_ledger_event_hash"] != source_hash):
                raise SettlementBoundaryV2Error("v2 evidence does not exactly reconcile to its outcome and immutable v1 source event")
            result.append(event)
            previous = event["event_hash"]
        return result

    def public_financial_evidence_v2(self, round_id):
        source_events = self.financial_evidence_v2(round_id)
        projected = []
        previous_public = ZERO_HASH
        previous_source = ZERO_HASH
        for index, event in enumerate(source_events, start=1):
            item = project_public_v2(
                event, previous_public_hash=previous_public,
                expected_source_previous_hash=previous_source,
                expected_sequence=index,
            )
            verify_public_v2_event(item, expected_previous_hash=previous_public, expected_sequence=index)
            projected.append(item)
            previous_public = item["event_hash"]
            previous_source = event["event_hash"]
        verify_public_v2_chain(projected)
        return projected

    def _reject_reserved_outcome(self, round_id, snapshot, fencing_token, message):
        """Refund a rejected, still-reserved debit rather than strand player funds."""
        if snapshot["round"]["status"] == "BET_RESERVED":
            debit = next((item for item in snapshot["operation_records"]
                          if item.get("action") == "DEBIT"), None)
            if debit is not None:
                self._delegate.refund_reserved_round(
                    debit["operation_id"] + ":refund", round_id, fencing_token=fencing_token
                )
        raise SettlementBoundaryV2Error(message)

    def commit_outcome(self, round_id, outcome, payout_minor, fencing_token):
        snapshot = self._delegate.round_snapshot(round_id)
        row = snapshot["round"]
        if row.get("mode") != "BASE":
            self._reject_reserved_outcome(
                round_id, snapshot, fencing_token,
                "MAGIC_BUY and EPIC_BUY remain disabled at this boundary",
            )
        if type(payout_minor) is not int or not 0 <= payout_minor <= MAX_SQLITE_INTEGER:
            self._reject_reserved_outcome(
                round_id, snapshot, fencing_token,
                "payout_minor must be a supported exact non-negative integer",
            )
        if not isinstance(outcome, dict) or outcome.get("engine_version") != row.get("engine_version"):
            self._reject_reserved_outcome(
                round_id, snapshot, fencing_token,
                "outcome engine version does not match the reserved round",
            )
        try:
            self._validate_spin_evidence(outcome)
            checked = validate_outcome_for_settlement(
                outcome, spin_cap_milli=self.spin_cap_milli, round_cap_milli=self.round_cap_milli
            )
        except SettlementBoundaryV2Error as exc:
            self._reject_reserved_outcome(round_id, snapshot, fencing_token, str(exc))
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            self._reject_reserved_outcome(
                round_id, snapshot, fencing_token,
                "payout evidence failed independent validation: %s" % exc,
            )
        if checked["total_payout_milli"] > MAX_SQLITE_INTEGER:
            self._reject_reserved_outcome(
                round_id, snapshot, fencing_token,
                "total milli payout exceeds the supported integer range",
            )

        base_bet_minor = row.get("base_bet_minor")
        if type(base_bet_minor) is not int or base_bet_minor <= 0:
            self._reject_reserved_outcome(round_id, snapshot, fencing_token, "reserved base bet is invalid")
        expected_minor = (base_bet_minor * checked["total_payout_milli"] + 500) // 1000
        if expected_minor > MAX_SQLITE_INTEGER or payout_minor != expected_minor:
            self._reject_reserved_outcome(
                round_id, snapshot, fencing_token,
                "Wallet minor-unit payout does not reconcile to guarded milli payout",
            )
        if expected_minor > row.get("max_payout_minor", -1):
            self._reject_reserved_outcome(
                round_id, snapshot, fencing_token,
                "guarded payout exceeds the reserved Wallet round cap",
            )
        committed = self._delegate.commit_outcome(round_id, outcome, payout_minor, fencing_token)
        self._ensure_v2_evidence(round_id)
        return committed

    def record_win_presented(self, round_id, fencing_token):
        self._ensure_v2_evidence(round_id)
        return self._delegate.record_win_presented(round_id, fencing_token)

    def settle_round(self, operation_id, round_id, fencing_token):
        self._ensure_v2_evidence(round_id)
        return self._delegate.settle_round(operation_id, round_id, fencing_token)


def create_guarded_server(host, port, ledger, stop_generator, sessions, nonce_registry,
                          frontend_root=None, game_engine=None,
                          allow_unapproved_math_for_tests=False):
    """Create a loopback-only RGS server with guarded engine, Wallet and v2 evidence.

    This low-level factory is intentionally not a production approval entrypoint:
    production callers must use ``standard_startup_v1.create_guarded_rgs_server``
    so canonical-Math approval is checked. The explicit test override is local
    development-only. A raw or missing GameEngine is never accepted here.
    """
    from ganesha.rgs.http_api import make_handler
    from ganesha.rgs.standard_startup_v1 import GuardedGameEngine

    if not isinstance(host, str) or not host:
        raise ValueError("guarded reference server requires an explicit loopback host")
    try:
        loopback = host.lower() == "localhost" or ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ValueError("guarded reference server may bind only to a loopback address")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("port must be an exact integer in [0, 65535]")
    if type(game_engine) is not GuardedGameEngine:
        raise TypeError("guarded RGS server requires GuardedGameEngine from the standard startup boundary")
    if type(allow_unapproved_math_for_tests) is not bool:
        raise TypeError("allow_unapproved_math_for_tests must be an exact boolean")
    game_engine._assert_startup_capability(test_mode=allow_unapproved_math_for_tests)

    guarded = GuardedWalletLedger(
        ledger,
        spin_cap_milli=getattr(game_engine, "spin_cap_milli", None),
        round_cap_milli=getattr(game_engine, "round_cap_milli", None),
    )
    base_handler = make_handler(
        ledger=guarded,
        stop_generator=stop_generator,
        sessions=sessions,
        nonce_registry=nonce_registry,
        frontend_root=frontend_root,
        enable_round_api=True,
        game_engine=game_engine,
        allow_unapproved_math_for_tests=allow_unapproved_math_for_tests,
    )

    class GuardedRGSHandler(base_handler):
        def do_GET(self):
            match = re.fullmatch(
                r"/api/v2/rounds/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/financial-evidence",
                self.path.split("?", 1)[0],
            )
            if not match:
                return super().do_GET()
            account_id = self._authenticate("GET", None)
            if not account_id:
                return self._json(401, {"error": "REQUEST_AUTHENTICATION_FAILED"})
            round_id = match.group(1)
            try:
                snapshot = guarded.round_snapshot(round_id)
                if snapshot["round"]["account_id"] != account_id:
                    return self._json(404, {"error": "NOT_FOUND"})
                events = guarded.public_financial_evidence_v2(round_id)
            except InvalidRoundState:
                return self._json(404, {"error": "NOT_FOUND_OR_INVALID_ROUND"})
            except (SettlementBoundaryV2Error, ValueError, TypeError):
                return self._json(409, {"error": "FINANCIAL_EVIDENCE_NOT_VERIFIABLE"})
            return self._json(200, {
                "contract": "ganesha.wallet.financial-evidence",
                "schema_version": 2,
                "round_id": round_id,
                "events": events,
            })

    server = ThreadingHTTPServer((host, port), GuardedRGSHandler)
    server.guarded_ledger = guarded
    return server

