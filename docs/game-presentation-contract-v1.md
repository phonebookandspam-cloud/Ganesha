# Game Presentation Event Contract V1

Status: `LOCAL_NON_FINANCIAL_PRESENTATION_CONTRACT`; not a Provider wire contract and not a wagering interface.

## Purpose

`ganesha.game.presentation` projects an already-resolved `GameEngine` BASE outcome into an ordered, replayable presentation stream. It is separate from `ganesha.game.events`, whose lifecycle includes Wallet reservation, outcome commitment and settlement. The presentation stream is non-financial and must never be used as evidence of a debit, credit, payout, RNG draw, canonical Math approval or Provider event.

The presentation event stream is unconditionally classified `NON_FINANCIAL_PRESENTATION_ONLY`; its builder and reducer reject any other classification. This is distinct from the outer `GameFixtureSessionStore` envelope (`TEST_FIXTURE_ONLY`) and `GameRuntime` envelope (`NON_FINANCIAL_SIMULATION`). `GameEngine` copies the injected MathPort's mutable `authority_status` attribute into its internal outcome, but this is only a caller-controlled claim, not provenance evidence, a trust anchor, or canonical/Provider approval. `GameRuntime` therefore removes `math_authority` from its public response and snapshot; the internal value remains available only for deterministic persisted-outcome reconciliation. `math_version` remains descriptive metadata, not approval evidence. The presentation builder ignores `outcome.math_authority` and never propagates it into the event stream. The builder accepts only a resolved BASE outcome. `GameFixtureSessionStore` uses a fixed `PresentationFixtureMathPort`; `GameRuntime` accepts an explicitly injected MathPort. Neither adapter contains RNG or approved probability weights. They deliberately do not implement MAGIC BUY or EPIC BUY: the current Engine contains draft purchase terms and spin counts that lack canonical Math/Provider authority.

## Lifecycle

```text
CREATED
  -> ROUND_PRESENTATION_STARTED
  -> BASE_REEL_STOPPED × 5
  -> BASE_OUTCOME_REVEALED
  -> [FEATURE_STARTED
      -> FEATURE_REEL_STOPPED × 5
      -> [WILD_EXPANSION_APPLIED]
      -> [MULTIPLIER_APPLIED]
      -> FEATURE_SPIN_RESOLVED]*
  -> [FEATURE_ENDED]
  -> ROUND_PRESENTATION_COMPLETED
```

- Reel stop events are strictly ordered by reel index and must reproduce the exact board in the corresponding outcome event.
- Feature spin numbers are contiguous. Each resolved spin consumes exactly one remaining spin. Free Spins with 0–2 Scatter do not trigger another award under the exact-3 threshold; 3+ Scatter/retrigger outcomes remain rejected because their behavior is not authorized.
- A Wild expansion event identifies unique reel indices and the display board. Every expanded reel must contain the configured `WILD_GANESHA` symbol; the resolved event must carry the same expanded reel set and display board, with three `WILD_GANESHA` symbols on every expanded reel.
- A multiplier event is required when the resolved multiplier exceeds 1; the resolved event must match it.
- Hash chaining and deterministic event IDs permit tamper detection and deterministic replay. They are not digital signatures, trusted timestamps, WORM retention or protection against a party able to rewrite the full stream and recompute its hashes.
- Completion reports the GameEngine's final capped round payout projection. The browser does not display it as a cash payout. It does not settle or credit funds.
- The local server exposes `POST /api/demo/game-sessions`, `POST /api/demo/game-sessions/{id}/rounds`, and `GET /api/demo/game-sessions/{id}` only when explicitly enabled on a loopback bind. Sessions are in-memory, request-idempotent and non-financial.
- The Frontend verifies the response contract, sequence, deterministic event IDs and SHA-256 event chain before rendering BASE stops, Free Spins, Wild Expansion, multiplier and completion events. The UI labels every result as non-financial and does not show money or payout. Current desktop/mobile/landscape Chrome smoke evidence is in `artifacts/BROWSER_SMOKE_20261104_ENGINE_FIXTURE.json` and its PNG.

## Exact-3 Scatter boundary

The contract independently checks the user-authorized BASE boundary against the projected board: exactly 3 `SCATTER_LOTUS` requires 10 Free Spins; 0–2 requires no exact-3 award; 4+ is rejected as unspecified. During Free Spins, 0–2 Scatter are non-triggering under the same exact-3 threshold; 3+ is rejected before resolution because retrigger behavior is not authorized. The reducer derives Scatter count from the raw stopped board and does not trust a caller-supplied count. Jackpot presentation is also disabled. No 4/5 reward, 6+ behavior, retrigger award, Buy price or Buy spin count is inferred.

## Validation

`tests/test_game_presentation.py` uses explicit fixture/development MathPorts and validates the GameEngine → presentation projection → replay path, ten Free Spins, 5×3 board agreement, Wild expansion, multiplier, payout-cap arithmetic, event ordering, deterministic IDs, hash tampering, duplicates and unspecified 4/5 Scatter rejection. `tests/test_game_simulation_events.py` separately validates the lifecycle summary, including exact feature exhaustion or payout-proven cap termination. These tests do not validate canonical Math, RNG, RTP, max payout, Wallet, RGS production behavior or Provider behavior. Browser playback validates only local non-financial outcomes.


## Integrity hardening (2026-11-04)

- BASE display cells must exactly equal the raw stopped board. Feature display cells must equal the raw board except that each explicitly expanded Wild reel (which must contain an original WILD) is rendered as three WILD cells; no other display mutation is accepted.
- Every feature round-payout projection must equal min(previous_round_total + this_spin_payout, configured_round_cap). The reducer updates cap state from that arithmetic, rejects further feature reels after the cap, and verifies the final cap flag against the final total.

- A Wild expansion event must follow all five feature reel stops and precede its multiplier event; the reducer accepts only the exact multiplier derived from the expanded Wild reel count. A multiplier cannot appear without a preceding Wild expansion.
