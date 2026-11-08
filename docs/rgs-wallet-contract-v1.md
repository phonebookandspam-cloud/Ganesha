# RGS / Wallet Contract V1 — Local Reference

Status: `LOCAL_REFERENCE_ONLY`; no Stake/Provider production contract is claimed.

## Client request
`POST /api/v1/rounds` accepts exactly these JSON fields:
- `round_id`: globally unique round identifier
- `operation_id`: unique debit operation identifier
- `bet_minor`: positive integer base wager in currency minor units
- `mode`: `BASE`, `MAGIC_BUY`, or `EPIC_BUY`

Authentication is carried separately in `X-Session-ID`, `X-Timestamp`, `X-Nonce` and `X-Signature` headers. The session ID is only a lookup key; the corresponding 32-byte-or-longer HMAC secret is held server-side and is not emitted into `config.js` or browser code. The signature binds the HTTP method, exact request path and canonical JSON body. This is a local trusted-host protocol, not the Stake/Provider wire contract.

The client cannot submit reel stops, payout, Free Spins count, multiplier, balance or outcome events. Unknown fields are rejected.

## Authentication
The local adapter accepts an opaque session ID mapped server-side to an account and HMAC secret. `X-Signature` is verified over method/path/body plus timestamp and nonce; a persistent SQLite nonce registry rejects replay. No HMAC secret is exposed to the browser or static preview config. Production must use the Provider's actual session/authentication contract, TLS, key rotation and provider-signed messages.

## Round lifecycle
1. `BET_RESERVED`: unique `round_id`; atomic integer debit; unique debit `operation_id`.
2. `OUTCOME_COMMITTED`: immutable canonical outcome JSON and integer payout persisted.
3. `SETTLED`: atomic credit; unique settlement operation ID; one settlement per round.
4. `REFUNDED`: only a reserved round with no committed outcome may be refunded.

Retry with the same operation ID returns the recorded result. A different debit operation for an existing round is rejected. A settled round cannot be credited again. An outcome cannot be overwritten.

## RNG and recovery
The server-side HMAC weighted stop generator derives a source-bound generator version from the exact RNG implementation and probability-input source bytes, then derives each reel stop from the secret key, that version, round ID, spin number and reel number. The Game Engine build version is separately derived from the Game Engine, Math Port, Math evaluator, configuration and RNG source bytes. Both versions and the round commitment are stored before outcome calculation. A reserved round is replayed only when both versions and the HMAC commitment match; if the code or RNG version changed before outcome commitment, the local recovery path refunds rather than applying a different engine to the old round. The client never selects outcomes. The browser frontend does not receive the HMAC secret; any embedding integration must use a trusted server-side proxy to authenticate readback requests, and no such proxy is included here.

## Currency
Ledger amounts are integer minor units. The local reference adapter converts milli-bet payouts to minor units using integer half-up rounding. This is a provisional local rule; production currency exponent, rounding, min/max bet, payout ceiling and conversion must be defined by the Provider contract and included in math certification.

## Local round reconciliation
`WalletLedger.reconcile_round(round_id)` performs a read-only consistency check across the local round row, operation records, journal entries and replayed event stream. `WalletLedger.reconcile_account(account_id)` additionally compares the current account balance with the verified opening balance plus the net of all journal entries and checks every round belonging to the account. New accounts persist their opening balance at creation. A legacy account migrated from a schema without an opening-balance field is deliberately left with an unknown (`NULL`) baseline; account-level reconciliation fails closed until an operator can establish the historical opening value from independent records. Neither method reconciles a distributed ledger or any Provider-side balance.

## Local payout ceiling
`RoundService` derives a per-round payout ceiling from the base wager and the current draft `CONFIG.max_round_win_milli`, stores it on the reserved round, and the SQLite ledger checks it both when committing the outcome and again before settlement. Retries must match the original ceiling. This is a local defense-in-depth control only: the 50,000× value remains an unapproved design target, and the production ceiling, currency rounding and Provider settlement limits must come from the approved contract.

## Durable event and recovery contract
The local ledger persists the versioned event stream described in [`game-state-event-contract-v1.md`](game-state-event-contract-v1.md). Debit reservation, outcome commitment, settlement and refund each append their corresponding lifecycle facts inside the same SQLite transaction as the ledger mutation. `RoundService.recover_round()` resumes an outcome-committed round by settling the stored outcome without rerunning RNG; a still-reserved HMAC round is replayed only when the configured secret/version matches the persisted commitment. Test-vector rounds without persisted vectors are refunded. A monotonic per-round fencing token rejects stale local workers. These controls are not a distributed Provider contract and do not prove exactly-once across services.

## Explicit limitations
- SQLite is a single-node reference ledger, not a horizontally scaled production wallet.
- Local HMAC-signed session map is a trusted-host development adapter, not browser authentication or Provider authentication.
- No real funds, payment processor, Stake RGS endpoint, provider ledger or production callback is connected.
- No claim of exactly-once across distributed services; local transaction/idempotency tests cover this reference implementation only.


## Official Stake Engine TypeScript client boundary — 2026-11-04

The frontend build pins the official `stake-engine` npm client at `0.1.32` (Beta) and Vite at `6.4.5` in `package-lock.json`. `frontend/stake-rgs-adapter.js` constructs `RGSClient({ url: window.location.href })` from the Provider launch URL and calls the SDK's `Authenticate()` method. It validates the returned integer balance, currency, min/max/step/default bet levels, jurisdiction booleans and active-round metadata without numeric or boolean coercion. Bet-level validation mirrors the pinned SDK's actual `Play()` check (`amount % stepBet === 0`) rather than assuming a minBet-offset progression. It preserves the opaque `round.state` and does not attempt to interpret or settle it.

The application calls `Authenticate()` only. `frontend/stake-rgs-adapter.js` implements guarded `play`, `event`, `endRound` and `reconnect` methods against the exact SDK calls, but `enableFinancialLifecycle` defaults to `false` and the application does not pass it. Enabling the test boundary now requires four trusted callbacks: `verifyRoundState`, `verifyRoundCompletion`, `verifyAmbiguousPlayOwnership` and `verifyEventAcknowledgement`. `verifyRoundState` must return a verified replay proof with an explicit `lastEvent` value (`string` or `null`); a boolean is insufficient because the SDK's `Round.event` semantics are not documented. Ambiguous Play recovery additionally requires Provider-backed unique Round ownership, not merely matching amount/mode. Ambiguous Event recovery requires a trusted decoder to prove the exact opaque marker; `round.event` alone is not accepted as proof. Play is restricted to `BASE` and exact authenticated bet levels; Buy modes are rejected. EndRound is rejected unless the completion verifier accepts the final Outcome/Feature Trace/Presentation/payout projection. The browser UI retains all wagering controls disabled and offers a fresh-client Authenticate-only reconnect button.

The pinned SDK's `Play()` sets an internal active-round flag before dispatching `/wallet/play`. If `fetch()` or response parsing throws after dispatch, the SDK does not clear that flag. A subsequent `Play()` on the same instance is rejected as “round is already active”. The adapter treats every post-dispatch Play exception as ambiguous (including SDK errors whose remote commit status cannot be independently proven), drops the client instance and never resends on it. `Event()` and `EndRound()` response loss are treated the same way. Reconnect always constructs a fresh client and calls Authenticate. After ambiguous Play, an active round must pass trusted replay, match the exact dispatched BASE mode/amount, and pass a separate Provider-backed unique ownership verifier before adoption; amount/mode equality alone is insufficient because another tab can submit the same bet. If no authoritative correlation exists, the verifier must return false and the adapter remains blocked. If no active round is returned after an ambiguous financial request, the adapter remains blocked in `AMBIGUOUS_*_RECONCILIATION_REQUIRED` because Authenticate's balance alone cannot prove whether a zero-payout Play or settlement committed. No next Play is allowed until authoritative reconciliation exists.

`Event(eventValue)` is an opaque string at the SDK boundary. This project does not invent a Provider event payload schema: the guarded adapter forwards a caller-supplied marker unchanged and blocks a marker already present in the verified replay proof. A lost Event response requires fresh Authenticate and trusted round-state replay plus a separate `verifyEventAcknowledgement` callback proving that the exact pending marker was persisted. The SDK only types `round.event` as an optional string; its Provider meaning is undocumented, so that field alone is not used to resolve ambiguity. If the verifier cannot prove the exact marker, Event, Play and EndRound remain blocked pending authoritative round-history reconciliation; the adapter never skips or resends the uncertain marker. The caller's replay verifier must define sequence/order semantics using an independently approved Provider round-state schema. `EndRound()` has no client-supplied idempotency key; its request is only `{sessionID}` and its response contains only the new balance. It is gated by the trusted completion verifier, and an ambiguous EndRound is never retried automatically.

The current SDK type/normalization also omits `config.gameModes`, while the current RGS overview documents mode-specific `costMultiplier` and `maxBet`. Therefore mode-specific Buy pricing and limits cannot be safely integrated from the normalized SDK response and remain disabled pending a verified contract/type resolution.

This is a guarded SDK lifecycle boundary, not a complete production RGS implementation. Its SDK-method orchestration is unit-tested with mocked fetch, but no live Provider request has been made. Before enabling Play, the project needs canonical Math and versioned outcome/event schema, a full `round.state` replay decoder, deterministic presentation reconciliation, Provider Event marker rules, round-history reconciliation after ambiguous no-active responses, settlement and recovery rules, production session validation, and a trusted signed release/approval attestation. The client package is Beta and requires Provider compatibility confirmation.

The non-financial `GameRuntime` browser flow separately persists its pending `session_id` and `request_id` in per-tab `sessionStorage`. If the browser loses a Play response after the local SQLite commit, the UI reads `GET /api/runtime/sessions/{session_id}` and replays the stored 90-event stream instead of creating another session. If the request was lost before dispatch and the durable snapshot remains `CREATED`, it retries with the exact same `request_id`; it does not generate a replacement ID. The local HTTP handler now treats a disconnected response socket as a lost response rather than attempting a second error response after a committed Runtime operation. This is a non-financial SQLite recovery path only.

Official references reviewed 2026-11-04:
- Stake Engine SDK: https://github.com/engineio/ts-client
- Stake Engine Web SDK: https://github.com/engineio/web-sdk
- Stake Engine API: https://stake-engine.com/docs/api
- Game replay requirements: https://stake-engine.com/docs/approval-guidelines/game-replay-requirements
- Approval guidelines: https://stake-engine.com/docs/approval-guidelines


## SQLite writer contention and local load evidence — 2026-11-04

`WalletLedger` no longer re-applies `PRAGMA journal_mode=WAL` on every short-lived connection. WAL is initialized once per database. Each connection uses a 250 ms SQLite busy timeout; `BEGIN IMMEDIATE` uses a bounded 30-second exponential-backoff retry before any transaction mutation. Only `SQLITE_BUSY`/`database is locked` failures at transaction acquisition are retried; mutation bodies are not replayed after partial execution. A focused test holds an external writer lock, verifies the retry counter increments, releases the lock and confirms the reservation succeeds.

A 24-worker × 50-round local SQLite stress run settled 1,200/1,200 rounds, replayed every event stream to terminal state, preserved the exact opening balance, left zero pending rounds and reported zero errors. The final run recorded 918 bounded begin retries, 53.03 rounds/second, p50 356.078 ms, p95 1,075.069 ms and max 2,097.280 ms. A pre-fix run reproduced `database is locked` and one pending round; that failure is retained in `artifacts/LOCAL_WALLET_LOAD_20261104_PRE_FIX2_24W.json`.

This is a local single-database concurrency result only. It is not a distributed exactly-once guarantee, production wallet benchmark, Provider test, accepted latency SLO or release-grade load/soak result.

## Local SQLite fault-injection coverage update — 2026-11-04

The current test suite maps the requested recovery boundaries as follows. These are local SQLite/process guarantees, not distributed Wallet or production RGS guarantees.

| Fault point | Exact regression tests | Recovery / assertion |
|---|---|---|
| Immediately after Debit | `test_process_exit_immediately_after_debit_recovers_by_refunding_test_round`; `test_service_process_exit_immediately_after_debit_commit_recovers`; `test_recovery_after_debit_replays_same_server_rng_and_settles_once` | A durable reserved round is either deterministically replayed with the original server RNG or refunded when its original test vectors are not persisted; balance and journal reconcile. |
| After Outcome commit | `test_process_exit_after_outcome_commit_recovers_same_outcome_and_settles`; `test_service_process_exit_immediately_after_outcome_commit_recovers`; `test_recovery_after_outcome_commit_settles_without_regenerating_outcome` | Recovery settles the immutable committed outcome without generating a replacement outcome. |
| Before Settlement | `test_service_process_exit_after_win_presented_before_settlement_recovers` | Recovery resumes after `WIN_PRESENTED`, then settles once. |
| After Credit / lost response | `test_process_exit_after_credit_commit_does_not_credit_twice`; `test_recovery_after_credit_commit_with_lost_response_does_not_credit_twice` | Recovery returns the committed settlement without a second credit or journal entry. |
| Before Refund commit | `test_process_exit_before_refund_commit_recovers_reserved_round_once` | A child process exits from the refund boundary before mutation; after lease expiry/reclaim, recovery refunds the reserved round once and replay remains idempotent. |
| After Refund / lost response | `test_process_exit_after_refund_commit_does_not_refund_twice`; `test_recovery_after_refund_commit_with_lost_response_does_not_refund_twice` | Recovery returns the committed refund without a second refund or journal entry. |
| Lease expiry / reclaim | `test_active_recovery_lease_is_exclusive_and_renewable`; `test_fencing_token_rejects_stale_worker_after_lease_reclaim`; `test_all_round_mutations_reject_expired_and_superseded_tokens` | Active lease exclusivity, renewal, generation increment, and stale-token rejection are verified. Expiry is injected by setting the persisted lease deadline to the past rather than waiting on wall-clock time. |
| Stale fencing token | `test_all_round_mutations_reject_expired_and_superseded_tokens`; `test_idempotent_outcome_replay_requires_current_fencing_token`; `test_idempotent_credit_and_refund_replays_reject_expired_tokens` | Every round mutation boundary rejects expired or superseded fencing generations, including idempotent replay. |
| Duplicate request concurrency | `test_concurrent_duplicate_debit_and_settlement_are_single_effect`; `test_concurrent_round_service_retries_have_single_financial_effect`; `test_server_rng_round_retry_is_idempotent` | Concurrent identical retries create one financial effect; account balance, round status and event replay reconcile. |
| Event gap / duplicate / replay | `test_round_reconciliation_detects_deleted_event_sequence`; `test_event_chain_tampering_is_reported_by_round_reconciliation`; `test_event_contract_is_persisted_and_replay_matches_ledger`; `test_round_journal_reconciliation_detects_tampering`; `test_round_journal_reconciliation_across_lifecycle` | Sequence gaps, altered event payloads and journal divergence fail reconciliation; valid streams replay to the terminal ledger state. |

The additional pre-Refund test closes a previously untested local process-exit boundary. It does not prove external wallet idempotency keys, distributed leases, cross-host fencing, provider transaction ordering, network partitions or exactly-once settlement outside this SQLite process.
