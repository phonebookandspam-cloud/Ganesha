---
name: ganesha-rgs-integrator
description: Integrate and audit Ganesha's Stake Engine frontend/RGS client lifecycle, wallet units, event markers, replay, reconnect, and ambiguous request recovery.
---

# Ganesha RGS Integrator Skill

## Contract baseline

- Use the exact pinned official `stake-engine` package in the lockfile as the implementation baseline. Record its version and package integrity before changing it.
- Use the official `engineio/ts-client` and current Stake Engine RGS documentation as primary public references. Treat `furic/stake-engine-client` as an independent, third-party cross-check only; do not add it as a dependency without a separate compatibility and license review.
- The RGS API money fields are integer micro-units in the current SDK/client evidence. Book payout multipliers are x100. These are not interchangeable.
- RGS `Event` is an opaque string at the SDK boundary. Provider semantics for the marker must be independently verified.

## Lifecycle invariants

1. Authenticate before any financial action; validate balance, currency, jurisdiction flags, bet limits, and restored active round without coercion.
2. Permit only the exact authenticated bet levels and modes whose cost/limits are verified. Reject unknown modes and client-supplied outcomes.
3. Serialize lifecycle actions; prevent concurrent Play/Event/EndRound calls from racing.
4. Treat any post-dispatch Play, Event, or EndRound transport/parse failure as ambiguous. Do not resend the same operation automatically.
5. Recreate the SDK client and Authenticate to read server state. Adopt a restored round only after a trusted replay proof and Provider-backed unique ownership/acknowledgement proof.
6. Do not infer Event acknowledgement from an undocumented `round.event` field. Do not infer settlement from balance movement alone.
7. Do not call EndRound until a trusted completion verifier proves terminal event sequence, final payout, and presentation projection. EndRound has no client idempotency key in the pinned client contract.
8. If authoritative reconciliation is unavailable, remain blocked and surface a clear recovery-required state.

## Implementation rules

- Keep the frontend stateless with respect to RNG and payout. Consume the immutable round result/event data.
- Validate URL launch parameters, constrain the RGS host/scheme to approved configuration, and avoid leaking session secrets.
- Use safe integers and explicit currency codes. Reject malformed or out-of-range responses.
- Preserve SDK response/event data needed for replay; do not coerce opaque Provider state into a locally invented schema.
- Keep the local SQLite wallet contract separate from the external Provider wallet contract.
- Mocked fetch tests verify request shape and local state transitions only. They do not prove Provider idempotency, ledger atomicity, refunds, or production settlement.

## Required tests

Cover Authenticate success/failure, active-round restore, Play request amount/mode, zero-payout closure, event ordering, EndRound preconditions, duplicate/concurrent calls, transport loss after each mutation, fresh-client reconciliation, malformed response rejection, replay state, and no-retry guarantees. Run the exact pinned SDK contract tests after every adapter change.
