"""SQLite reference ledger with atomic integer accounting and idempotent operations.

This is a local reference implementation, not a production wallet/provider adapter.
"""
import hashlib
import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Dict, Optional
from ganesha.game.events import EventContractError, apply_event, initial_state, make_event, replay_events

class LedgerError(Exception):
    pass

class InsufficientFunds(LedgerError):
    pass

class DuplicateOperation(LedgerError):
    pass

class InvalidRoundState(LedgerError):
    pass

class RoundLeaseBusy(LedgerError):
    pass

class StaleFencingToken(LedgerError):
    pass

MAX_SQLITE_INTEGER = (1 << 63) - 1
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class _ClosingSQLiteConnection(sqlite3.Connection):
    """Preserve sqlite transaction context semantics and close on context exit."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _require_identifier(value, field):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("%s must be a 1-128 character ASCII identifier" % field)


class WalletLedger:
    def __init__(self, database_path):
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._write_lock_retry_count = 0
        self._retry_counter_lock = threading.Lock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path, timeout=0.25, isolation_level=None, factory=_ClosingSQLiteConnection
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=250")
        connection.execute("PRAGMA foreign_keys=ON")
        # journal_mode is persistent database state; setting it on every short-lived
        # connection creates avoidable schema-lock contention under concurrent writers.
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @property
    def write_lock_retry_count(self):
        with self._retry_counter_lock:
            return self._write_lock_retry_count

    def _begin_immediate(self, db, timeout_seconds=30.0):
        """Acquire SQLite's single-writer slot with bounded, fair retry backoff.

        Retrying is safe here because BEGIN IMMEDIATE fails before the transaction
        begins and no ledger mutation has been applied on that connection.
        """
        deadline = time.monotonic() + timeout_seconds
        attempt = 0
        while True:
            try:
                db.execute("BEGIN IMMEDIATE")
                return
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "locked" not in message and "busy" not in message:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise
                with self._retry_counter_lock:
                    self._write_lock_retry_count += 1
                base_delay = min(0.005 * (2 ** min(attempt, 5)), 0.1)
                jitter = 0.75 + ((time.monotonic_ns() % 500) / 1000.0)
                time.sleep(min(base_delay * jitter, remaining))
                attempt += 1

    def _initialize(self):
        # Establish WAL once before opening the normal per-operation connections.
        # WAL mode persists in the database file; do not reconfigure it on every connect.
        with closing(sqlite3.connect(self.database_path, timeout=15, isolation_level=None)) as setup:
            mode = setup.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise LedgerError("SQLite WAL mode could not be enabled")
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
              account_id TEXT PRIMARY KEY, currency TEXT NOT NULL,
              balance_minor INTEGER NOT NULL CHECK(balance_minor >= 0),
              opening_balance_minor INTEGER
            );
            CREATE TABLE IF NOT EXISTS rounds (
              round_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id),
              currency TEXT NOT NULL, bet_minor INTEGER NOT NULL CHECK(bet_minor > 0),
              max_payout_minor INTEGER NOT NULL CHECK(max_payout_minor >= 0),
              mode TEXT NOT NULL DEFAULT 'BASE', base_bet_minor INTEGER NOT NULL DEFAULT 0,
              generator_version TEXT NOT NULL DEFAULT 'legacy-local', engine_version TEXT NOT NULL DEFAULT 'legacy-local',
              fencing_token INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL CHECK(status IN ('BET_RESERVED','OUTCOME_COMMITTED','SETTLED','REFUNDED')),
              outcome_json TEXT, payout_minor INTEGER NOT NULL DEFAULT 0 CHECK(payout_minor >= 0),
              settlement_operation_id TEXT UNIQUE, rng_commitment TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operations (
              operation_id TEXT PRIMARY KEY, round_id TEXT NOT NULL,
              action TEXT NOT NULL, amount_minor INTEGER NOT NULL,
              response_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS journal (
              entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
              operation_id TEXT NOT NULL UNIQUE REFERENCES operations(operation_id),
              round_id TEXT NOT NULL, account_id TEXT NOT NULL,
              currency TEXT NOT NULL, delta_minor INTEGER NOT NULL,
              entry_type TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS round_events (
              round_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE,
              event_type TEXT NOT NULL, schema_version INTEGER NOT NULL, event_json TEXT NOT NULL,
              event_hash TEXT NOT NULL, PRIMARY KEY(round_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS recovery_leases (
              round_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
              fencing_token INTEGER NOT NULL, expires_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_rounds_account ON rounds(account_id);
            CREATE INDEX IF NOT EXISTS idx_journal_round ON journal(round_id);
            """)
            account_columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)").fetchall()}
            if "opening_balance_minor" not in account_columns:
                db.execute("ALTER TABLE accounts ADD COLUMN opening_balance_minor INTEGER")
                # A legacy balance row alone cannot prove its original opening value.
                # Keep the new column NULL until an operator supplies verified source
                # evidence; do not infer a historical baseline from an incomplete ledger.
            columns = {row[1] for row in db.execute("PRAGMA table_info(rounds)").fetchall()}
            if "max_payout_minor" not in columns:
                db.execute(
                    "ALTER TABLE rounds ADD COLUMN max_payout_minor INTEGER NOT NULL DEFAULT %d CHECK(max_payout_minor >= 0)"
                    % MAX_SQLITE_INTEGER
                )
            migrations = {
                "mode": "TEXT NOT NULL DEFAULT 'BASE'",
                "base_bet_minor": "INTEGER NOT NULL DEFAULT 0",
                "generator_version": "TEXT NOT NULL DEFAULT 'legacy-local'",
                "engine_version": "TEXT NOT NULL DEFAULT 'legacy-local'",
                "fencing_token": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, declaration in migrations.items():
                if name not in columns:
                    db.execute("ALTER TABLE rounds ADD COLUMN %s %s" % (name, declaration))

    def _append_round_event_tx(self, db, round_id, event_id, event_type, payload):
        existing = db.execute("SELECT event_json FROM round_events WHERE event_id=?", (event_id,)).fetchone()
        if existing:
            event = json.loads(existing["event_json"])
            if event["round_id"] != round_id or event["event_type"] != event_type or event["payload"] != payload:
                raise DuplicateOperation("event_id reused with different round event")
            return replay_events(round_id, [json.loads(row[0]) for row in db.execute(
                "SELECT event_json FROM round_events WHERE round_id=? ORDER BY sequence", (round_id,)
            ).fetchall()])
        rows = db.execute("SELECT event_json FROM round_events WHERE round_id=? ORDER BY sequence", (round_id,)).fetchall()
        state = replay_events(round_id, [json.loads(row[0]) for row in rows])
        event = make_event(state, event_id, event_type, payload)
        next_state = apply_event(state, event)
        encoded = json.dumps(event, sort_keys=True, separators=(",", ":"))
        db.execute("INSERT INTO round_events(round_id,sequence,event_id,event_type,schema_version,event_json,event_hash) VALUES(?,?,?,?,?,?,?)",
                   (round_id, event["sequence"], event_id, event_type, event["schema_version"], encoded, event["event_hash"]))
        return next_state

    def round_events(self, round_id):
        _require_identifier(round_id, "round_id")
        with self._connect() as db:
            rows = db.execute("SELECT event_json FROM round_events WHERE round_id=? ORDER BY sequence", (round_id,)).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def round_state(self, round_id):
        return replay_events(round_id, self.round_events(round_id))

    def claim_recovery_lease(self, round_id, owner_id, lease_seconds=30):
        _require_identifier(round_id, "round_id")
        _require_identifier(owner_id, "owner_id")
        if type(lease_seconds) not in (int, float) or lease_seconds <= 0 or lease_seconds > 300:
            raise ValueError("lease_seconds must be >0 and <=300")
        now = time.time()
        with self._connect() as db:
            self._begin_immediate(db)
            row = db.execute("SELECT status,fencing_token FROM rounds WHERE round_id=?", (round_id,)).fetchone()
            if not row:
                db.rollback()
                raise InvalidRoundState("Unknown round")
            if row["status"] in ("SETTLED", "REFUNDED"):
                db.rollback()
                raise InvalidRoundState("Terminal round does not need a recovery lease")
            lease = db.execute("SELECT * FROM recovery_leases WHERE round_id=?", (round_id,)).fetchone()
            if lease and lease["expires_at"] > now:
                db.rollback()
                raise RoundLeaseBusy("Round is leased by another active worker")
            token = int(row["fencing_token"]) + 1
            db.execute("UPDATE rounds SET fencing_token=? WHERE round_id=?", (token, round_id))
            db.execute("INSERT INTO recovery_leases(round_id,owner_id,fencing_token,expires_at) VALUES(?,?,?,?) "
                       "ON CONFLICT(round_id) DO UPDATE SET owner_id=excluded.owner_id,fencing_token=excluded.fencing_token,expires_at=excluded.expires_at",
                       (round_id, owner_id, token, now + float(lease_seconds)))
            db.commit()
            return token

    def _assert_fencing_token_tx(self, db, round_id, fencing_token):
        if type(fencing_token) is not int or fencing_token <= 0:
            raise StaleFencingToken("A valid fencing token is required for every round mutation")
        lease = db.execute("SELECT fencing_token,expires_at FROM recovery_leases WHERE round_id=?", (round_id,)).fetchone()
        row = db.execute("SELECT fencing_token FROM rounds WHERE round_id=?", (round_id,)).fetchone()
        if (not lease or not row or int(lease["fencing_token"]) != fencing_token
                or int(row["fencing_token"]) != fencing_token or float(lease["expires_at"]) <= time.time()):
            raise StaleFencingToken("Fencing token is stale, expired or not owned by this round")

    def release_recovery_lease(self, round_id, owner_id, fencing_token):
        with self._connect() as db:
            self._begin_immediate(db)
            db.execute("UPDATE recovery_leases SET expires_at=0 WHERE round_id=? AND owner_id=? AND fencing_token=?",
                       (round_id, owner_id, fencing_token))
            db.commit()

    def renew_recovery_lease(self, round_id, owner_id, fencing_token, lease_seconds=30):
        if type(lease_seconds) not in (int, float) or lease_seconds <= 0 or lease_seconds > 300:
            raise ValueError("lease_seconds must be >0 and <=300")
        with self._connect() as db:
            self._begin_immediate(db)
            lease = db.execute("SELECT fencing_token,expires_at FROM recovery_leases WHERE round_id=? AND owner_id=?",
                               (round_id, owner_id)).fetchone()
            round_row = db.execute("SELECT fencing_token FROM rounds WHERE round_id=?", (round_id,)).fetchone()
            if (not lease or not round_row or int(lease["fencing_token"]) != fencing_token
                    or int(round_row["fencing_token"]) != fencing_token or float(lease["expires_at"]) <= time.time()):
                db.rollback()
                raise StaleFencingToken("Cannot renew an expired or superseded fencing lease")
            db.execute("UPDATE recovery_leases SET expires_at=? WHERE round_id=? AND owner_id=? AND fencing_token=?",
                       (time.time() + float(lease_seconds), round_id, owner_id, fencing_token))
            db.commit()

    def create_account(self, account_id, currency, opening_balance_minor):
        _require_identifier(account_id, "account_id")
        if not isinstance(currency, str) or not currency or len(currency) > 12 or type(opening_balance_minor) is not int or opening_balance_minor < 0 or opening_balance_minor > MAX_SQLITE_INTEGER:
            raise ValueError("Invalid account parameters")
        with self._connect() as db:
            self._begin_immediate(db)
            row = db.execute("SELECT currency,balance_minor,opening_balance_minor FROM accounts WHERE account_id=?", (account_id,)).fetchone()
            if row:
                if (row["currency"] != currency or row["balance_minor"] != opening_balance_minor
                        or row["opening_balance_minor"] != opening_balance_minor):
                    db.rollback()
                    raise DuplicateOperation("Account already exists with different opening state")
            else:
                db.execute("INSERT INTO accounts(account_id,currency,balance_minor,opening_balance_minor) VALUES(?,?,?,?)",
                           (account_id, currency, opening_balance_minor, opening_balance_minor))
            db.commit()

    def balance(self, account_id):
        with self._connect() as db:
            row = db.execute("SELECT balance_minor,currency FROM accounts WHERE account_id=?", (account_id,)).fetchone()
            if not row:
                raise LedgerError("Unknown account")
            return {"balance_minor": row["balance_minor"], "currency": row["currency"]}

    def _existing_operation(self, db, operation_id, round_id, action, amount_minor):
        row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if not row:
            return None
        if row["round_id"] != round_id or row["action"] != action or row["amount_minor"] != amount_minor:
            raise DuplicateOperation("operation_id reused with different request")
        return json.loads(row["response_json"])

    def reserve_bet(self, operation_id, round_id, account_id, bet_minor,
                    rng_commitment="TEST:UNCOMMITTED", max_payout_minor=MAX_SQLITE_INTEGER,
                    round_mode="BASE", base_bet_minor=None, generator_version="test-only",
                    engine_version="legacy-local"):
        _require_identifier(operation_id, "operation_id")
        _require_identifier(round_id, "round_id")
        _require_identifier(account_id, "account_id")
        if (type(bet_minor) is not int or bet_minor <= 0 or bet_minor > MAX_SQLITE_INTEGER
                or type(max_payout_minor) is not int or max_payout_minor < 0 or max_payout_minor > MAX_SQLITE_INTEGER):
            raise ValueError("Invalid bet or payout-cap request")
        if round_mode not in ("BASE", "MAGIC_BUY", "EPIC_BUY"):
            raise ValueError("Invalid round mode")
        if base_bet_minor is None:
            base_bet_minor = bet_minor
        if type(base_bet_minor) is not int or base_bet_minor <= 0 or base_bet_minor > MAX_SQLITE_INTEGER:
            raise ValueError("Invalid base bet")
        if not isinstance(generator_version, str) or not generator_version or len(generator_version) > 128:
            raise ValueError("Invalid generator version")
        if not isinstance(engine_version, str) or not engine_version or len(engine_version) > 128:
            raise ValueError("Invalid engine version")
        with self._connect() as db:
            self._begin_immediate(db)
            existing = self._existing_operation(db, operation_id, round_id, "DEBIT", bet_minor)
            if existing is not None:
                existing_round = db.execute("SELECT account_id,rng_commitment,max_payout_minor,mode,base_bet_minor,generator_version,engine_version FROM rounds WHERE round_id=?", (round_id,)).fetchone()
                if (not existing_round or existing_round["account_id"] != account_id
                        or existing_round["rng_commitment"] != rng_commitment
                        or existing_round["max_payout_minor"] != max_payout_minor
                        or existing_round["mode"] != round_mode
                        or existing_round["base_bet_minor"] != base_bet_minor
                        or existing_round["generator_version"] != generator_version
                        or existing_round["engine_version"] != engine_version):
                    db.rollback()
                    raise DuplicateOperation("Retry does not match the original account, RNG commitment or payout cap")
                db.commit()
                return existing
            if db.execute("SELECT 1 FROM rounds WHERE round_id=?", (round_id,)).fetchone():
                db.rollback()
                raise DuplicateOperation("round_id already exists")
            account = db.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
            if not account:
                db.rollback()
                raise LedgerError("Unknown account")
            if account["balance_minor"] < bet_minor:
                db.rollback()
                raise InsufficientFunds("Insufficient funds")
            new_balance = account["balance_minor"] - bet_minor
            db.execute("UPDATE accounts SET balance_minor=? WHERE account_id=?", (new_balance, account_id))
            db.execute("INSERT INTO rounds(round_id,account_id,currency,bet_minor,max_payout_minor,mode,base_bet_minor,generator_version,engine_version,status,rng_commitment) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (round_id, account_id, account["currency"], bet_minor, max_payout_minor, round_mode, base_bet_minor, generator_version, engine_version, "BET_RESERVED", rng_commitment))
            response = {"round_id": round_id, "status": "BET_RESERVED", "balance_minor": new_balance, "currency": account["currency"]}
            db.execute("INSERT INTO operations VALUES(?,?,?,?,?)", (operation_id, round_id, "DEBIT", bet_minor, json.dumps(response, sort_keys=True)))
            db.execute("INSERT INTO journal(operation_id,round_id,account_id,currency,delta_minor,entry_type) VALUES(?,?,?,?,?,?)",
                       (operation_id, round_id, account_id, account["currency"], -bet_minor, "BET_DEBIT"))
            self._append_round_event_tx(db, round_id, round_id + ":opened", "ROUND_OPENED", {"mode": round_mode})
            self._append_round_event_tx(db, round_id, round_id + ":bet-reserved", "BET_RESERVED",
                                        {"account_id": account_id, "currency": account["currency"],
                                         "debit_minor": bet_minor, "operation_id": operation_id})
            self._append_round_event_tx(db, round_id, round_id + ":rng-committed", "RNG_COMMITTED",
                                        {"commitment": rng_commitment, "generator_version": generator_version})
            db.commit()
            return response

    def commit_outcome(self, round_id, outcome, payout_minor, fencing_token):
        _require_identifier(round_id, "round_id")
        if type(payout_minor) is not int or payout_minor < 0 or payout_minor > MAX_SQLITE_INTEGER:
            raise ValueError("payout_minor must be a supported non-negative integer")
        if not isinstance(outcome, dict):
            raise ValueError("outcome must be an object")
        outcome_json = json.dumps(outcome, sort_keys=True, separators=(",", ":"))
        with self._connect() as db:
            self._begin_immediate(db)
            row = db.execute("SELECT * FROM rounds WHERE round_id=?", (round_id,)).fetchone()
            if not row:
                db.rollback()
                raise InvalidRoundState("Unknown round")
            if row["status"] == "OUTCOME_COMMITTED":
                # An idempotent replay is still a mutation-boundary request: it
                # must carry the currently valid lease, not merely know an old
                # operation's contents.
                self._assert_fencing_token_tx(db, round_id, fencing_token)
                if row["outcome_json"] == outcome_json and row["payout_minor"] == payout_minor:
                    db.commit()
                    return {"round_id": round_id, "status": row["status"], "payout_minor": payout_minor}
                db.rollback()
                raise DuplicateOperation("Round already has a different committed outcome")
            if row["status"] != "BET_RESERVED":
                db.rollback()
                raise InvalidRoundState("Outcome can only be committed after bet reservation")
            # A service-generated outcome must carry the integer milli-bet total
            # that the ledger independently converts into currency minor units.
            # The versioned RoundService build identifier marks service outcomes.
            # Older direct-ledger fixtures (including their historical test
            # engine labels) remain outside this stricter service contract.
            if str(row["engine_version"]).startswith("game-engine-sha256:"):
                total_payout_milli = outcome.get("total_payout_milli")
                if (outcome.get("mode") != row["mode"]
                        or type(total_payout_milli) is not int or total_payout_milli < 0):
                    db.rollback()
                    raise LedgerError("Service outcome mode or total_payout_milli is missing or invalid")
                expected_payout_minor = (int(row["base_bet_minor"]) * total_payout_milli + 500) // 1000
                if payout_minor != expected_payout_minor:
                    db.rollback()
                    raise LedgerError("Currency payout does not match the committed milli-bet outcome")
            if payout_minor > row["max_payout_minor"]:
                db.rollback()
                raise LedgerError("Outcome exceeds the payout cap reserved for this round")
            self._assert_fencing_token_tx(db, round_id, fencing_token)
            db.execute("UPDATE rounds SET status='OUTCOME_COMMITTED',outcome_json=?,payout_minor=? WHERE round_id=?",
                       (outcome_json, payout_minor, round_id))
            self._append_round_event_tx(db, round_id, round_id + ":outcome", "OUTCOME_COMMITTED",
                                        dict({"outcome_sha256": hashlib.sha256(outcome_json.encode("utf-8")).hexdigest(),
                                              "payout_minor": payout_minor,
                                              "engine_version": str(outcome.get("engine_version", row["engine_version"]))},
                                             **({"base_payout_milli": int(outcome.get("base_result", {}).get("payout_milli", 0)),
                                                 "feature_payout_milli": sum(int(item.get("payout_awarded_milli",
                                                                                         item.get("result", {}).get("payout_milli", 0)))
                                                                              for item in outcome.get("feature_events", [])),
                                                 "total_payout_milli": int(outcome["total_payout_milli"])}
                                                if (type(outcome.get("total_payout_milli")) is int
                                                    and ((isinstance(outcome.get("base_result"), dict)
                                                          and type(outcome["base_result"].get("payout_milli")) is int)
                                                         or outcome.get("mode") in ("MAGIC_BUY", "EPIC_BUY"))) else {}),
                                             **({"base_board": outcome["base_result"]["board"],
                                                 "base_display_board": outcome["base_result"].get("display_board", outcome["base_result"]["board"])}
                                                if isinstance(outcome.get("base_result"), dict)
                                                and "board" in outcome["base_result"] else {})))
            db.commit()
            return {"round_id": round_id, "status": "OUTCOME_COMMITTED", "payout_minor": payout_minor}

    def record_feature_progress(self, round_id, initial_spins, feature_events, round_cap_reached=False, *,
                                fencing_token, base_payout_milli=None, round_cap_milli=None):
        """Persist the draft engine's feature trace as ordered, replayable lifecycle events."""
        _require_identifier(round_id, "round_id")
        if type(initial_spins) is not int or initial_spins <= 0 or not isinstance(feature_events, list):
            raise ValueError("Invalid feature progress")
        if (base_payout_milli is None) != (round_cap_milli is None):
            raise ValueError("Base payout and round cap evidence must be supplied together")
        if base_payout_milli is not None and (type(base_payout_milli) is not int or base_payout_milli < 0
                                              or type(round_cap_milli) is not int or round_cap_milli <= 0
                                              or base_payout_milli > round_cap_milli):
            raise ValueError("Invalid base payout or round cap evidence")
        with self._connect() as db:
            self._begin_immediate(db)
            row = db.execute("SELECT status FROM rounds WHERE round_id=?", (round_id,)).fetchone()
            if not row or row["status"] != "BET_RESERVED":
                db.rollback()
                raise InvalidRoundState("Feature progress requires a reserved round")
            self._assert_fencing_token_tx(db, round_id, fencing_token)
            start_payload = {"feature": "FREE_SPINS", "initial_spins": initial_spins}
            if base_payout_milli is not None:
                start_payload.update({"base_payout_milli": base_payout_milli, "round_cap_milli": round_cap_milli})
            self._append_round_event_tx(db, round_id, round_id + ":feature-start", "FEATURE_STARTED", start_payload)
            state = replay_events(round_id, [json.loads(item[0]) for item in db.execute(
                "SELECT event_json FROM round_events WHERE round_id=? ORDER BY sequence", (round_id,)
            ).fetchall()])
            for item in feature_events:
                result = item.get("result", {})
                payout = item.get("payout_awarded_milli", result.get("payout_milli", 0))
                retrigger = item.get("retrigger_awarded", 0)
                remaining = state["feature_spins_remaining"] - 1 + retrigger
                spin_payload = {"spin_number": item["spin_number"], "stops": list(item["stops"]),
                                "payout_milli": int(payout), "retrigger_awarded": int(retrigger),
                                "remaining_spins": remaining,
                                **({"board": result["board"],
                                    "display_board": result.get("display_board", result["board"])}
                                   if isinstance(result, dict) and "board" in result else {})}
                if base_payout_milli is not None:
                    after = item.get("round_payout_after_milli")
                    cap_applied = item.get("round_cap_applied")
                    if type(after) is not int or type(cap_applied) is not bool:
                        raise ValueError("Engine feature event lacks round-cap reconciliation evidence")
                    spin_payload.update({"round_payout_after_milli": after, "round_cap_applied": cap_applied})
                self._append_round_event_tx(db, round_id, round_id + ":feature-spin-%d" % item["spin_number"],
                                            "FEATURE_SPIN_RESOLVED", spin_payload)
                state = replay_events(round_id, [json.loads(entry[0]) for entry in db.execute(
                    "SELECT event_json FROM round_events WHERE round_id=? ORDER BY sequence", (round_id,)
                ).fetchall()])
            reason = "ROUND_CAP" if round_cap_reached else "EXHAUSTED"
            self._append_round_event_tx(db, round_id, round_id + ":feature-end", "FEATURE_ENDED",
                                        {"spins_played": state["feature_spins_played"],
                                         "payout_milli": state["feature_payout_milli"],
                                         "termination_reason": reason})
            db.commit()
            return replay_events(round_id, [json.loads(entry[0]) for entry in db.execute(
                "SELECT event_json FROM round_events WHERE round_id=? ORDER BY sequence", (round_id,)
            ).fetchall()])

    def settle_round(self, operation_id, round_id, fencing_token):
        _require_identifier(operation_id, "operation_id")
        _require_identifier(round_id, "round_id")
        with self._connect() as db:
            self._begin_immediate(db)
            row = db.execute("SELECT * FROM rounds WHERE round_id=?", (round_id,)).fetchone()
            if not row:
                db.rollback()
                raise InvalidRoundState("Unknown round")
            existing = self._existing_operation(db, operation_id, round_id, "CREDIT", row["payout_minor"])
            if existing is not None:
                self._assert_fencing_token_tx(db, round_id, fencing_token)
                db.commit()
                return existing
            if row["status"] != "OUTCOME_COMMITTED":
                db.rollback()
                raise InvalidRoundState("Round is not awaiting settlement")
            self._assert_fencing_token_tx(db, round_id, fencing_token)
            if row["payout_minor"] > row["max_payout_minor"]:
                db.rollback()
                raise LedgerError("Committed payout exceeds the payout cap reserved for this round")
            account = db.execute("SELECT * FROM accounts WHERE account_id=?", (row["account_id"],)).fetchone()
            if row["payout_minor"] > MAX_SQLITE_INTEGER - account["balance_minor"]:
                db.rollback()
                raise LedgerError("Settlement would exceed the supported integer balance range")
            new_balance = account["balance_minor"] + row["payout_minor"]
            db.execute("UPDATE accounts SET balance_minor=? WHERE account_id=?", (new_balance, row["account_id"]))
            response = {"round_id": round_id, "status": "SETTLED", "payout_minor": row["payout_minor"],
                        "balance_minor": new_balance, "currency": row["currency"]}
            db.execute("INSERT INTO operations VALUES(?,?,?,?,?)", (operation_id, round_id, "CREDIT", row["payout_minor"], json.dumps(response, sort_keys=True)))
            db.execute("INSERT INTO journal(operation_id,round_id,account_id,currency,delta_minor,entry_type) VALUES(?,?,?,?,?,?)",
                       (operation_id, round_id, row["account_id"], row["currency"], row["payout_minor"], "PAYOUT_CREDIT"))
            db.execute("UPDATE rounds SET status='SETTLED',settlement_operation_id=? WHERE round_id=?", (operation_id, round_id))
            self._append_round_event_tx(db, round_id, round_id + ":settled", "SETTLED",
                                        {"operation_id": operation_id, "credit_minor": row["payout_minor"], "currency": row["currency"]})
            self._append_round_event_tx(db, round_id, round_id + ":ended", "END_ROUND", {"terminal_status": "SETTLED"})
            db.commit()
            return response

    def refund_reserved_round(self, operation_id, round_id, fencing_token):
        _require_identifier(operation_id, "operation_id")
        _require_identifier(round_id, "round_id")
        with self._connect() as db:
            self._begin_immediate(db)
            row = db.execute("SELECT * FROM rounds WHERE round_id=?", (round_id,)).fetchone()
            if not row:
                db.rollback()
                raise InvalidRoundState("Unknown round")
            existing = self._existing_operation(db, operation_id, round_id, "REFUND", row["bet_minor"])
            if existing is not None:
                self._assert_fencing_token_tx(db, round_id, fencing_token)
                db.commit()
                return existing
            if row["status"] != "BET_RESERVED":
                db.rollback()
                raise InvalidRoundState("Only a reserved round without committed outcome can be refunded")
            self._assert_fencing_token_tx(db, round_id, fencing_token)
            account = db.execute("SELECT * FROM accounts WHERE account_id=?", (row["account_id"],)).fetchone()
            if row["bet_minor"] > MAX_SQLITE_INTEGER - account["balance_minor"]:
                db.rollback()
                raise LedgerError("Refund would exceed the supported integer balance range")
            new_balance = account["balance_minor"] + row["bet_minor"]
            db.execute("UPDATE accounts SET balance_minor=? WHERE account_id=?", (new_balance, row["account_id"]))
            response = {"round_id": round_id, "status": "REFUNDED", "refund_minor": row["bet_minor"],
                        "balance_minor": new_balance, "currency": row["currency"]}
            db.execute("INSERT INTO operations VALUES(?,?,?,?,?)", (operation_id, round_id, "REFUND", row["bet_minor"], json.dumps(response, sort_keys=True)))
            db.execute("INSERT INTO journal(operation_id,round_id,account_id,currency,delta_minor,entry_type) VALUES(?,?,?,?,?,?)",
                       (operation_id, round_id, row["account_id"], row["currency"], row["bet_minor"], "BET_REFUND"))
            db.execute("UPDATE rounds SET status='REFUNDED' WHERE round_id=?", (round_id,))
            self._append_round_event_tx(db, round_id, round_id + ":refunded", "REFUNDED",
                                        {"operation_id": operation_id, "refund_minor": row["bet_minor"], "currency": row["currency"]})
            self._append_round_event_tx(db, round_id, round_id + ":ended", "END_ROUND", {"terminal_status": "REFUNDED"})
            db.commit()
            return response

    def round_snapshot(self, round_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM rounds WHERE round_id=?", (round_id,)).fetchone()
            if not row:
                raise InvalidRoundState("Unknown round")
            operations = db.execute("SELECT * FROM operations WHERE round_id=? ORDER BY rowid", (round_id,)).fetchall()
            return {
                "round": dict(row),
                "outcome": json.loads(row["outcome_json"]) if row["outcome_json"] else None,
                "operations": {item["action"]: json.loads(item["response_json"]) for item in operations},
                "events": [json.loads(item["event_json"]) for item in db.execute(
                    "SELECT event_json FROM round_events WHERE round_id=? ORDER BY sequence", (round_id,)
                ).fetchall()],
                "operation_records": [dict(item) for item in operations],
            }

    def pending_round_ids(self):
        with self._connect() as db:
            rows = db.execute("SELECT round_id FROM rounds WHERE status IN ('BET_RESERVED','OUTCOME_COMMITTED') ORDER BY rowid").fetchall()
        return [row["round_id"] for row in rows]

    def record_win_presented(self, round_id, fencing_token):
        """Record the server's win-presentation event; it is not proof of rendered pixels."""
        _require_identifier(round_id, "round_id")
        with self._connect() as db:
            self._begin_immediate(db)
            row = db.execute("SELECT status,payout_minor FROM rounds WHERE round_id=?", (round_id,)).fetchone()
            if not row or row["status"] != "OUTCOME_COMMITTED":
                db.rollback()
                raise InvalidRoundState("Win presentation event requires committed outcome")
            self._assert_fencing_token_tx(db, round_id, fencing_token)
            state = replay_events(round_id, [json.loads(item[0]) for item in db.execute(
                "SELECT event_json FROM round_events WHERE round_id=? ORDER BY sequence", (round_id,)
            ).fetchall()])
            if int(row["payout_minor"]) > 0 and not state.get("win_presented"):
                self._append_round_event_tx(db, round_id, round_id + ":win-presented", "WIN_PRESENTED",
                                            {"payout_minor": row["payout_minor"]})
            db.commit()
            return self.round_state(round_id)

    def journal_for_round(self, round_id):
        with self._connect() as db:
            rows = db.execute("SELECT * FROM journal WHERE round_id=? ORDER BY entry_id", (round_id,)).fetchall()
            return [dict(row) for row in rows]

    def reconcile_round(self, round_id):
        """Read-only local reconciliation of one round's state, operations and journal."""
        _require_identifier(round_id, "round_id")
        with self._connect() as db:
            round_row = db.execute("SELECT * FROM rounds WHERE round_id=?", (round_id,)).fetchone()
            if not round_row:
                raise InvalidRoundState("Unknown round")
            operations = db.execute(
                "SELECT * FROM operations WHERE round_id=? ORDER BY operation_id", (round_id,)
            ).fetchall()
            journal = db.execute(
                "SELECT * FROM journal WHERE round_id=? ORDER BY entry_id", (round_id,)
            ).fetchall()

        issues = []
        expected_actions = {
            "BET_RESERVED": ["DEBIT"],
            "OUTCOME_COMMITTED": ["DEBIT"],
            "SETTLED": ["CREDIT", "DEBIT"],
            "REFUNDED": ["DEBIT", "REFUND"],
        }.get(round_row["status"])
        actual_actions = sorted(item["action"] for item in operations)
        if expected_actions is None:
            issues.append("unknown round status")
        elif actual_actions != sorted(expected_actions):
            issues.append("operation actions do not match round status")

        operation_by_id = {item["operation_id"]: item for item in operations}
        journal_ids = [item["operation_id"] for item in journal]
        if len(journal_ids) != len(set(journal_ids)):
            issues.append("duplicate journal operation identifier")
        if set(journal_ids) != set(operation_by_id):
            issues.append("journal and operation identifiers do not match")

        entry_rules = {
            "BET_DEBIT": ("DEBIT", -int(round_row["bet_minor"])),
            "PAYOUT_CREDIT": ("CREDIT", int(round_row["payout_minor"])),
            "BET_REFUND": ("REFUND", int(round_row["bet_minor"])),
        }
        for entry in journal:
            operation = operation_by_id.get(entry["operation_id"])
            rule = entry_rules.get(entry["entry_type"])
            if operation is None or rule is None:
                issues.append("journal entry has no matching operation or known entry type")
                continue
            expected_action, expected_delta = rule
            expected_amount = abs(expected_delta)
            if operation["action"] != expected_action or operation["amount_minor"] != expected_amount:
                issues.append("operation action or amount disagrees with journal entry")
            if entry["delta_minor"] != expected_delta:
                issues.append("journal delta disagrees with round state")
            if entry["account_id"] != round_row["account_id"] or entry["currency"] != round_row["currency"]:
                issues.append("journal account or currency disagrees with round")
            if operation["round_id"] != round_id:
                issues.append("operation belongs to a different round")

        if round_row["status"] == "SETTLED":
            credits = [item for item in operations if item["action"] == "CREDIT"]
            if len(credits) != 1 or round_row["settlement_operation_id"] != credits[0]["operation_id"]:
                issues.append("settlement operation does not match the committed credit")
        elif round_row["settlement_operation_id"] is not None:
            issues.append("non-settled round has a settlement operation identifier")
        if int(round_row["payout_minor"]) > int(round_row["max_payout_minor"]):
            issues.append("round payout exceeds its reserved payout cap")

        journal_delta = sum(int(item["delta_minor"]) for item in journal)
        if round_row["status"] == "SETTLED":
            expected_delta = int(round_row["payout_minor"]) - int(round_row["bet_minor"])
        elif round_row["status"] == "REFUNDED":
            expected_delta = 0
        else:
            expected_delta = -int(round_row["bet_minor"])
        if journal_delta != expected_delta:
            issues.append("journal net delta disagrees with round status")

        try:
            event_state = replay_events(round_id, self.round_events(round_id))
            expected_event_status = {
                "BET_RESERVED": "BET_RESERVED",
                "OUTCOME_COMMITTED": "OUTCOME_COMMITTED",
                "SETTLED": "ENDED",
                "REFUNDED": "ENDED",
            }.get(round_row["status"])
            if event_state["status"] != expected_event_status:
                issues.append("event stream terminal state disagrees with wallet round status")
            if event_state.get("rng_commitment") != round_row["rng_commitment"]:
                issues.append("event RNG commitment disagrees with wallet round")
            if event_state.get("generator_version") != round_row["generator_version"]:
                issues.append("event RNG version disagrees with wallet round")
            if event_state.get("debit_minor") != round_row["bet_minor"]:
                issues.append("event debit amount disagrees with wallet round")
            if event_state.get("mode") != round_row["mode"]:
                issues.append("event mode disagrees with wallet round")
            if round_row["outcome_json"]:
                outcome_hash = hashlib.sha256(round_row["outcome_json"].encode("utf-8")).hexdigest()
                if event_state.get("outcome_sha256") != outcome_hash or event_state.get("payout_minor") != round_row["payout_minor"]:
                    issues.append("event outcome digest or payout disagrees with wallet round")
                if event_state.get("engine_version") != round_row["engine_version"]:
                    issues.append("event engine version disagrees with wallet round")
            if round_row["status"] in ("SETTLED", "REFUNDED") and not event_state.get("ended"):
                issues.append("terminal wallet round lacks END_ROUND event")
        except (EventContractError, ValueError, TypeError, KeyError):
            issues.append("round event stream is invalid or cannot be replayed")

        return {
            "round_id": round_id,
            "status": round_row["status"],
            "ok": not issues,
            "journal_delta_minor": journal_delta,
            "expected_delta_minor": expected_delta,
            "operation_count": len(operations),
            "journal_entry_count": len(journal),
            "issues": issues,
        }

    def reconcile_account(self, account_id):
        """Reconcile one local account balance against its opening balance and all round journals.

        Legacy accounts receive a reconstructed opening balance only when the existing
        journal explains the stored balance. If that baseline is unavailable, this
        method fails closed and reports the missing evidence.
        """
        _require_identifier(account_id, "account_id")
        with self._connect() as db:
            account = db.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
            if not account:
                raise LedgerError("Unknown account")
            journal = db.execute(
                "SELECT * FROM journal WHERE account_id=? ORDER BY entry_id", (account_id,)
            ).fetchall()
            round_ids = [row[0] for row in db.execute(
                "SELECT round_id FROM rounds WHERE account_id=? ORDER BY rowid", (account_id,)
            ).fetchall()]

        issues = []
        opening = account["opening_balance_minor"]
        if type(opening) is not int or opening < 0:
            issues.append("account opening balance is unavailable; historical baseline cannot be proven")
            expected_balance = None
        else:
            expected_balance = opening + sum(int(item["delta_minor"]) for item in journal)
            if expected_balance < 0 or expected_balance > MAX_SQLITE_INTEGER:
                issues.append("opening balance plus journal exceeds the supported account balance range")
                expected_balance = None
            elif expected_balance != int(account["balance_minor"]):
                issues.append("account balance disagrees with opening balance plus journal net delta")

        for entry in journal:
            if entry["currency"] != account["currency"]:
                issues.append("journal currency disagrees with account currency")
                break

        round_reports = []
        for round_id in round_ids:
            report = self.reconcile_round(round_id)
            round_reports.append(report)
            if not report["ok"]:
                issues.append("round %s failed local reconciliation" % round_id)

        return {
            "account_id": account_id,
            "currency": account["currency"],
            "opening_balance_minor": opening,
            "current_balance_minor": int(account["balance_minor"]),
            "journal_delta_minor": sum(int(item["delta_minor"]) for item in journal),
            "expected_balance_minor": expected_balance,
            "journal_entry_count": len(journal),
            "rounds_checked": len(round_reports),
            "ok": not issues,
            "issues": issues,
        }
