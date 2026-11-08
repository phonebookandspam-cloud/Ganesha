# Game State / Event Contract V1

Status: `LOCAL_PROVIDER_NEUTRAL_CONTRACT`; not a Provider-approved wire specification.

## Authority and versioning

- Contract schema version: `1` (`ganesha.game.events.SCHEMA_VERSION`).
- Unknown schema versions, event-envelope fields, event types, payload fields, invalid transitions, sequence gaps and broken hashes fail closed.
- V1 event payloads are strict: adding/removing fields requires a new schema version and an explicit migration.
- Replay is deterministic from the ordered event stream. The stream is SHA-256 hash chained (`previous_hash`, `event_hash`). This detects accidental or unsophisticated tampering; it is not a digital signature, external timestamp, WORM store or proof against an attacker who can rewrite the entire database and recompute every hash.
- Pre-event-ledger rows are not silently backfilled as if events had been captured at the time. Such historical rows require separate reconciliation and cannot claim V1 replay evidence.

## Lifecycle

Normal settlement:

```text
CREATED -> ROUND_OPENED -> BET_RESERVED -> RNG_COMMITTED
        -> [FEATURE_STARTED -> FEATURE_SPIN_RESOLVED* -> FEATURE_ENDED]
        -> OUTCOME_COMMITTED -> [WIN_PRESENTED] -> SETTLED -> END_ROUND
```

Refund:

```text
CREATED -> ROUND_OPENED -> BET_RESERVED -> RNG_COMMITTED -> REFUNDED -> END_ROUND
```

`WIN_PRESENTED` is an optional server-side presentation event emitted after a positive immutable outcome is committed and before settlement. It means the presentation event is available to the presentation layer; it is not proof that a browser rendered pixels or that a player saw it. It never changes wallet state. Refund is only valid before an outcome is committed. `SETTLED` and `REFUNDED` are mutually exclusive terminal financial results; `END_ROUND` closes either result.

## Modes and feature state

`ROUND_OPENED.mode` is one of `BASE`, `MAGIC_BUY`, `EPIC_BUY`. `FREE_SPINS` is a feature phase within a round, not a separate wallet debit mode. `FEATURE_STARTED` identifies the feature; each `FEATURE_SPIN_RESOLVED` must have a contiguous spin number and a remaining-spin count consistent with consumption and the event's retrigger amount. `FEATURE_ENDED` must match the accumulated spin count and feature payout. A round-cap termination is explicitly identified and is not treated as ordinary exhaustion.

This contract validates event arithmetic and order, not whether a retrigger, multiplier, reel stop or payout is mathematically authorized. Those values must come from the future canonical Math implementation.

## Event payloads

| Event | Required payload |
|---|---|
| `ROUND_OPENED` | `mode` |
| `BET_RESERVED` | `account_id`, `currency`, `debit_minor`, `operation_id` |
| `RNG_COMMITTED` | `commitment`, `generator_version` |
| `FEATURE_STARTED` | `feature=FREE_SPINS`, `initial_spins` |
| `FEATURE_SPIN_RESOLVED` | `spin_number`, five integer `stops`, `payout_milli`, `retrigger_awarded`, `remaining_spins`; optional validated `board` and Wild-expanded `display_board` |
| `FEATURE_ENDED` | `spins_played`, `payout_milli`, `termination_reason` |
| `OUTCOME_COMMITTED` | `outcome_sha256`, `payout_minor`, `engine_version`; canonical engine outcomes also carry `base_payout_milli`, `feature_payout_milli`, `total_payout_milli`; optional validated `base_board` and `base_display_board` |
| `WIN_PRESENTED` | `payout_minor` |
| `SETTLED` | `operation_id`, `credit_minor`, `currency` |
| `REFUNDED` | `operation_id`, `refund_minor`, `currency` |
| `END_ROUND` | `terminal_status` |

Every envelope also carries `schema_version`, `round_id`, contiguous `sequence`, unique `event_id`, `event_type`, `payload`, `previous_hash` and `event_hash`.

For canonical-engine-shaped outcomes, the committed milli-payout triplet is mandatory as a set. Replay checks `feature_payout_milli` against the sum of persisted `FEATURE_SPIN_RESOLVED.payout_milli`, and checks `total_payout_milli = base_payout_milli + feature_payout_milli`. The Engine records `payout_awarded_milli` per feature spin as the actual increment to the round total after round/jackpot caps; the Wallet persists that amount as the feature event payout. This distinction matters when a jackpot/cap awards the remaining distance to the round cap rather than the raw line-win amount. Older direct-ledger test fixtures without a canonical engine trace remain explicitly outside this stronger triplet contract.

## Persistence and integration

The local SQLite Wallet writes `ROUND_OPENED`, `BET_RESERVED` and `RNG_COMMITTED` in the same transaction as debit reservation. Outcome hash, payout and optional server-derived board are written in the same transaction as outcome commitment. Settlement/refund and their terminal events are each atomic with the corresponding balance and journal changes. Feature progress is persisted as an atomic local event batch before outcome commitment. `RoundService` returns the ordered event stream and replayed state; the local HTTP adapter exposes authenticated, account-scoped readback without returning account IDs, operation IDs or RNG commitments. The browser bridge validates the snapshot contract, round identity, event schema version, contiguous sequence, event types and basic payload shape. It renders the latest returned server-derived board and a read-only lifecycle/payout projection, clearing the board when the new snapshot has no committed board. Because the API redacts private event-envelope fields, the browser does not independently verify the persisted SHA-256 hash chain; integrity validation remains server-side through the ledger replay/reconciliation path. The bridge never creates or alters an outcome.

The local reference uses SQLite transactions, not a distributed event broker. Provider event names, signatures, idempotency keys, fencing semantics, retention and reconciliation remain to be mapped against an actual Provider contract.

## Recovery

- `BET_RESERVED`: re-run only if the original server-side HMAC secret/version reproduces the stored commitment; otherwise stop and require manual recovery. Test-vector rounds without persisted vectors are refunded, not re-simulated.
- `OUTCOME_COMMITTED`: never draw again; settle the immutable stored outcome.
- `SETTLED` / `REFUNDED`: return the durable prior result; no second balance mutation.
- Recovery leases increment a persisted per-round fencing token. Expired/superseded workers are rejected at outcome commit and settlement/refund. Lease expiry is local wall-clock behavior; multi-host clock discipline and distributed consensus are not provided.
- The RNG generator version is derived from the exact RNG implementation and probability-input source bytes; the round-processing version is derived from the Game Engine, Math Port, event reducer, Wallet Ledger, Math evaluator, configuration, RNG and RGS orchestration source bytes. A reserved round is replayed only when both persisted versions and the HMAC commitment match. A changed engine/generator build causes a pre-outcome pending round to be refunded rather than silently re-evaluated under new code.

## Verification scope

Unit and local SQLite integration tests exercise ordering, replay, hash tampering, recovery after debit/outcome commit, idempotent readback, stale fencing tokens, and refund/outcome races. They do not prove process-kill behavior at every CPU instruction, power-loss durability on every filesystem, multi-host failover, distributed exactly-once, Provider ledger atomicity or production wallet safety.
