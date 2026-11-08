# Frontend Acceptance — Full Scratch V1

Current frontend is a responsive non-wagering visual demo. `DEMO SPIN` renders server-owned scripted presentation fixtures through a separate demo event contract. It does not generate RNG outcomes, evaluate Math, award features, calculate wins or place wagers. Bet adjustment and Buy controls remain disabled. The default development server exposes only the loopback demo API; the financial round API remains disabled.

## Implemented in the shell
- static 5×3 art board using the copied Ganesha Wild, Lotus Scatter and six other proposed symbol assets; this is not a sampled game outcome
- responsive desktop/tablet/mobile CSS with landscape layout
- safe-area insets, reduced-motion preference, keyboard focus-visible treatment, skip link, semantic controls and live status text
- bet adjustment and both Buy controls disabled; no financial round API route in the default server
- wallet-free demo session API with fixed 5×3 fixtures, five ordered reel-stop events, a board-reveal event, event sequence numbers and SHA-256 hash chaining
- duplicate demo request IDs return the original response without creating a second spin; sessions are in-memory and lost on server restart
- frontend requests one scripted fixture at a time, validates session identity/schema/contiguous sequence and renders each stopped reel; reduced-motion preference suppresses the reel-stop delay/animation
- no client-side stop selection or payout calculation
- explicit local-only / API-offline / non-wagering labels
- read-only `GaneshaRoundState.connect()` bridge accepts a snapshot only through an embedding host's server-mediated `readbackProvider` callback, validates the snapshot and per-event schema version, round identity, event type and contiguous sequence, then renders the latest server-derived 5×3 board plus feature progress, payout/settlement status and ordered event history; it clears stale board content when the snapshot has no committed board and does not create rounds, select outcomes or enable controls
- a local automated contrast audit checks eight explicitly listed foreground/background pairs; all are expected to exceed the 4.5:1 normal-text threshold. This is a bounded color-pair check, not a WCAG 2.2 AA conformance claim.

## Not yet verified
- creator/redistribution rights and final clearance for the copied Ganesha symbol art and cover assets
- browser screenshot and visual regression tied to current Full Scratch commit
- actual RNG-driven reel motion, winline, Wild expansion, Free Spins, multiplier and payout animation; current reel events are scripted presentation fixtures only
- sound/music licensing and playback timing
- iOS Safari physical-device safe-area, Android Chrome, desktop Safari/Chrome
- authenticated API session lifecycle, reconnect, timeout and reload recovery
- full WCAG 2.2 AA audit, keyboard-only and screen-reader testing, contrast measurement and localization

The read-only financial bridge does not accept bearer tokens or HMAC secrets in browser code. An embedding host must provide a `readbackProvider({roundId})` callback backed by its own authenticated server-side proxy; that proxy must call the local reference API using the documented HMAC protocol. No such host proxy is included in this repository. The scripted demo API is a separate unauthenticated loopback-only fixture service and must not be exposed publicly. No Provider integration or live Math-driven game is claimed.

The eight checked pairs are recorded in `tools/a11y_contrast_audit.py`. The automated check does not sample the full rendered gradients, every CSS state, focus indicator geometry, target spacing, browser zoom, assistive technology or physical devices. Full WCAG 2.2 AA remains unverified.

A browser UI pass cannot satisfy Math, Wallet, RGS or Provider approval gates. The API intentionally redacts private event envelope fields, so the browser does not independently verify the persisted SHA-256 hash chain; the server-side ledger replay/reconciliation remains the integrity check. Currency values are shown as integer minor units because currency exponent/formatting is not yet Provider-approved.
