# Stake Engine public RGS contract evidence — 2026-11-07

## Sources

- RGS overview: https://stake-engine.com/docs/rgs
- Wallet endpoints: https://stake-engine.com/docs/rgs/wallet
- Public TypeScript client: https://github.com/engineio/ts-client
- Game-state events: https://stake-engine.com/docs/math/game-state-structure/events
- Math file requirements: https://stake-engine.com/docs/faq/math/what-files-are-required (also published in engineio/docs)

## Verified public API contract

1. Launch uses `sessionID` and `rgs_url`; the public RGS docs state `rgs_url` is a bare host name and must not be hardcoded. `lang`, `currency`, `device`, `social`, and `demo` may also be present.
2. `/wallet/authenticate` must precede wallet operations. It returns balance, bet configuration, jurisdiction flags and round state. The Wallet docs say `round` may be an active or last-completed round; the frontend must continue an active round.
3. `/wallet/play` receives `{sessionID, amount, mode}`. The amount is the base bet; actual debit is base bet multiplied by the configured mode `costMultiplier`.
4. RGS money amounts use six decimal places (`1.0` is `1,000,000`). Currency is display metadata.
5. A zero-payout Play response closes the round (`round.active=false`) and needs no EndRound. A positive-payout round remains active and must be settled with `/wallet/end-round`.
6. Only one active round is allowed per player session. `/bet/event` stores progress so an active round can be resumed; Authenticate returns the active round and the last recorded `round.event` marker.
7. Published request shapes expose no operation ID/idempotency key or round ID for Play/EndRound. The current official npm `stake-engine@0.1.32` client body shapes are `{sessionID, mode, amount}` for Play and `{sessionID}` for EndRound. Frontend local locks cannot establish provider-side atomic idempotency or prove a timed-out settlement was not committed.
8. Math publication requires `index.json`, a compressed JSONL Books file and a CSV LUT per mode. Books include `id`, `events`, `payoutMultiplier`; CSV IDs and payouts must match Books exactly.

## Implementation mapping and limits

- R98 uses the launch-provided RGS host and session ID; it does not hardcode an RGS origin.
- It calls Authenticate before Play, checks explicit round state, records Event markers while a round is active, and calls EndRound only for active rounds after final Book payout agrees with `payoutMultiplier`.
- Missing or ambiguous round state, uncertain Play/Event/EndRound outcomes, payout mismatch, malformed Books, missing authoritative 5x3 reveal/Free Spin boards, unsupported Scatter outcomes, and unauthorized retriggers fail closed.
- The SDK's public Play/EndRound wire shapes have no operation-level idempotency key. R98 therefore retains local transaction markers and refuses unsafe retries; this is safe containment, not a substitute for server-side idempotency.
- These are public Stake RGS interface facts. They do not disclose the production Operator Wallet's internal ledger contract, refund guarantees, idempotency implementation, key custody, or provider-specific embedded EPIC Math payload.

## Ganesha-specific unresolved provider dependencies

- BASE Books/LUT generated from canonical approved game inputs and a pinned Math SDK conformance run.
- Provider-authoritative 5-Scatter embedded EPICBUY_V37 event payload and exact BASE payout-unit conversion. Until supplied, 5 Scatter is rejected before rendering/settlement; no second Play or debit is permitted.
- 4-Scatter 12-spin canonical BASE Books, not legacy 10-spin Books. Existing old Books remain rejected.
- Provider-approved Golden Vectors for normal wins/losses, 3/4/5/6+ Scatter, Free Spins, Wild movement/expansion, cap boundary, max payout, zero payout and response-loss recovery.
- Provider confirmation of duplicate Play/EndRound semantics and authoritative round history/reconciliation after transport loss.

## Current release integration status — 2026-11-09

- The current Front R7 bundle pins `stake-engine@0.1.32` and is classified `BETA_READ_ONLY_AUTHENTICATE_ONLY`. It performs Authenticate only; Play, Event, EndRound, wagering and Bonus Buy remain disabled. The local SDK adapter has guarded method wrappers, but the app does not provide the four trusted verifiers required to enable them.
- The SDK exposes Authenticate, Play, Event and EndRound requests. It does not expose a separate Wagering or BonusBuy method. `Play` accepts a `mode` string, but this alone does not prove which mode names, multipliers or purchase modes the Provider has enabled for this game.
- The SDK's normalized Authenticate configuration does not expose the documented `gameModes` / per-mode `costMultiplier` data. Therefore the client cannot establish the Provider's MAGIC ×100 / EPIC ×500 configuration or validate mode-specific max bet from its normalized session object.
- The SDK request surface does not provide an operation-level idempotency key for Play or EndRound. `Event` accepts an opaque string; the SDK type does not define its game-specific event schema or prove server acknowledgement semantics. Ambiguous outcomes remain blocked pending Provider-backed ownership, event acknowledgement and round-history reconciliation.
- Current BASE authority is 3 Scatter = 10 Free Spins, 4 = 12, 5 = embedded EPICBUY_V37 in the already-paid BASE round with no second debit/Play and BASE settlement, and 6+ fail closed. The 5-Scatter Provider payload and BASE-unit conversion remain unavailable. Independent purchase prices are MAGIC ×100 and EPIC ×500; the historical ×100/×100 Books are rejected.
- Local SDK tests use mocked fetch. No production Provider RGS request, production Wallet settlement, signed Provider Golden Vector, or Stake Studio upload was performed.

## Exact Provider materials required to proceed

1. Versioned, game-specific RGS/Wallet contract and sandbox endpoint, session-launch requirements, authentication scheme and test credentials supplied through a secure secret channel (not committed or pasted into source).
2. Request/response schemas and authoritative semantics for Play, Event, EndRound, zero-payout completion, active-round restore, currency exponent, amount units, debit/credit rounding and payout ceilings.
3. Server-side idempotency/ownership guarantees for duplicate or timed-out Play and EndRound, a unique operation/round correlation field, and an authoritative round-history or settlement-reconciliation endpoint.
4. Provider Event marker schema, persistence acknowledgement semantics, event ordering and replay contract.
5. Provider-supported game mode identifiers and mode-specific costMultiplier/maxBet configuration, explicitly confirming BASE ×1, MAGICBUY_V36 ×100 and independent EPICBUY_V37 ×500.
6. Provider-authoritative embedded 5-Scatter EPICBUY_V37 payload, complete 10-spin sequence, event IDs/ordering, payout-unit conversion into BASE wager units, and settlement treatment.
7. Provider Golden Vectors and written Math approval for BASE, both independent Buy modes, 3/4/5/6+ Scatter, Free Spins, Wild expansion/multipliers, payout cap, max-win and transport-loss recovery.

## Release conclusion

The public frontend API mapping is implemented and local SDK-wire fixture tested. Production Provider/Operator Wallet semantics, canonical Math, embedded EPIC payload, live RGS settlement, and Stake Studio review remain unverified. This document is evidence of the public contract mapping only; it is not a Provider approval certificate.
