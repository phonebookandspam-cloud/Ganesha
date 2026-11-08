# Architecture — Full Scratch V1

## Principles
1. Math is a pure deterministic domain: the same approved config, stop vector and feature state must produce the same events and payout. Current inputs remain Draft-005 research only.
2. Frontend never chooses or alters outcomes. A future connected frontend must render validated server events; the current frontend is a static non-wagering preview.
3. Game Engine owns domain transitions through an injectable Math Port; Wallet owns the monetary ledger; RGS coordinates authenticated round requests.
4. Every monetary command carries a unique operation ID and round ID. Database uniqueness plus atomic transactions enforce at-most-once ledger effects; retries return the committed result.
5. Provider-specific behavior is isolated behind an adapter. A local adapter is not evidence of production compatibility.
6. Maximum win is enforced in the domain and again at settlement. Any cap must be included in RTP math.
7. All RNG use is server-side and versioned. Test vectors pin RNG algorithm, seed derivation and output.

## Components
- `math`: current Draft-005 config/evaluator behind a narrow `Math Port`; canonical strips, weights, paytable, paylines and Provider Golden Vectors are still missing.
- `game`: versioned event reducer and deterministic replay; round lifecycle includes feature events, outcome immutability and terminal settlement/refund.
- `rgs`: local Authenticate/Play/readback adapter, round ownership, operation idempotency, recovery and fencing.
- `wallet`: local integer minor-unit accounting, atomic debit/credit/refund/event writes, append-only journal and per-round reconciliation; no distributed/account-opening-balance or Provider-ledger reconciliation.
- `security`: authenticated session binding, HMAC/signature verification, nonce/timestamp and replay rejection, schema validation.
- `frontend`: responsive non-wagering scripted visual demo plus read-only financial-round snapshot bridge.
- `demo`: separate wallet-free scripted presentation fixture service with its own `ganesha.demo.events` contract; it cannot create financial rounds or claim Math outcomes.

## Trust boundaries
Browser is untrusted. Provider/RGS is external. Wallet ledger is authoritative for money. Math config and build artifacts are content-addressed. Secrets are never stored in source or test fixtures.

## State / money invariants
- A round can be settled at most once.
- Total debit and credit journal entries are balanced and immutable.
- A retry with the same operation ID cannot create a second debit or credit.
- A new operation ID cannot settle an already settled round.
- Unknown or stale round state fails closed; no guessed payout or optimistic balance update.
- All amounts are integer minor units; conversion occurs only at the provider boundary under an explicit currency rule.

## Current implementation boundary

The local reference path persists a per-round payout ceiling and checks it at outcome commit and again before credit settlement. The value currently comes from the hypothetical Draft-005 configuration; this code-level guard does not certify the 50,000× target or replace a Provider-approved cap. Event persistence, replay, per-round recovery and fencing are local SQLite capabilities, not distributed guarantees. The Game Engine remains a draft outcome resolver, and the RGS/Wallet are local SQLite/HMAC references.

The default `dev_server.py` exposes only the loopback scripted demo API. Demo sessions are in-memory, request-ID-idempotent and intentionally carry no balance, bet, RNG stop, Math evaluation, award, payout, settlement or refund. The financial `RoundService` rejects server-generated rounds unless its injected Math port declares `CANONICAL_APPROVED`; the explicit test-only override is not enabled by the default server. The ledger independently checks service outcome mode and integer milli-bet payout conversion before committing a service-generated outcome. These controls prevent the current draft Math from being mistaken for an approved wagering engine; they do not complete the actual game. See `game-state-event-contract-v1.md`, `implementation-status.md` and `authority-boundary.md` before treating any component as release-ready.
