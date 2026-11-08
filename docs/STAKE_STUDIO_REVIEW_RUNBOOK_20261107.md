# Ganesha and The Magic — Stake Engine Studio review runbook

**Status:** prepared, not executed. This is not an upload or approval certificate.

## Current R12 handoff state — 2026-11-07

- Overall release status: `BLOCKED_NOT_UPLOAD_READY`. No Stake Studio upload, Provider sandbox test or approval has occurred.
- Latest preserved Frontend candidate: `artifacts/STAKE_FRONTEND_R98_PRODUCTION_ONLY_R9_20261107.zip`, SHA-256 `2ff26b987b7d9b5eb12fe4f0952c8756be29e7b4c623447af0daf9b1815b868c` (195 files; directory/ZIP byte identity and package verifier passed). It is Frontend-only, not a complete Stake submission.
- R9 asset-rights audit found 177 image/audio assets, only 9 content-hash matches against the current Full Scratch provenance inventory and zero cleared for redistribution. Do not upload or redistribute until the owner/rights-holder evidence is resolved.
- Current Full Scratch offline build: `artifacts/FRONTEND_BUILD_OFFLINE_R12C_20261107/`, 19 files, 2 JavaScript bundles, 8 symbols and 4 WAV files. The Vite build now aliases the `./config.js` module to the selected offline config, and the verifier rejects a local-development endpoint in the compiled bundle. It is explicitly a local non-wagering engineering preview, not the R98 Stake Frontend package or Provider approval.
- Local Chrome 156 browser QA at 320 CSS px passed reflow/DOM checks: no horizontal overflow, unnamed controls, undersized targets, broken images, failed requests, console errors or exceptions; disabled wagering/Bonus Buy controls and visible skip-link focus were verified. This is not full WCAG 2.2 AA, screen-reader, desktop 200% zoom or physical iOS/Android acceptance.
- Current SBOM: `artifacts/SBOM_STAKE_CANDIDATE_20261107_R12.cdx.json` (66 npm, 9 Python build, 1 Python test and 22 Full Scratch assets). Local npm audit and pip-audit scans report zero known vulnerabilities. Project licensing and asset redistribution remain unresolved.
- Current Scatter contract: 3=10 Free Spins; 4=12 Free Spins; 5=embedded `EPICBUY_V37` inside the already-paid BASE round with no additional debit/Play and BASE settlement; 6+=fail closed. Free Spins retrigger is unsupported. Five-Scatter remains fail-closed until the provider-authoritative embedded payload and BASE payout conversion are supplied.
- R98 Replay/Wild/Scatter local contract suites remain 24/24 and 59/59 PASS. These are local fixtures/contracts, not Provider or Studio acceptance.
- Full Scratch cap/settlement boundary: local per-spin cap 1,000,000 milli and round cap 50,000,000 milli are independently enforced. BASE over round cap rejects before feature resolution; each feature spin is checked against the per-spin cap, then its credited award is bounded by remaining round cap. Guarded startup and `GuardedWalletLedger` repeat the outcome validation; over-cap wallet rounds refund before settlement. `WalletLedger` now closes SQLite connections at context exit. Targeted engine-cap plus financial-evidence tests: 18/18 PASS with ResourceWarnings enabled and zero ResourceWarnings. These local limits do not establish canonical Math or Provider payout-unit approval.
- Latest Python suite is 456/456 PASS and Node RGS suite is 33/33 PASS. No physical-device, full WCAG 2.2 AA, Provider ledger or Stake Studio test has been performed.

## 0. Current package status

- Latest Frontend engineering candidate: `artifacts/STAKE_FRONTEND_R98_PRODUCTION_ONLY_R9_20261107.zip`.
- SHA-256: `2ff26b987b7d9b5eb12fe4f0952c8756be29e7b4c623447af0daf9b1815b868c`.
- Frontend directory and ZIP structural verification: PASS (195 files, no structural issues).
- R9 is a Frontend-only candidate. It deliberately does not contain an approved Math package.
- **Do not activate for real-money play or request final game approval yet.** BASE Math currently fails the pinned validator, the CVaR limit, and Scatter/retrigger contracts. The 5-Scatter embedded EPIC payload is unavailable.
- R9 may be used for a non-financial technical inspection only if Studio accepts a frontend-only package and the project owner clears the asset/SDK rights. If Studio requires a complete Math/Frontend pair, do not substitute legacy Books/LUT; wait for canonical Math.

## 1. Required external prerequisites

1. Stake Engine Studio access for the game owner/reviewer.
2. Provider-authorized non-financial RGS staging endpoint and test credentials.
3. Provider Golden Vectors and authoritative round/replay fixtures.
4. Canonical Math generator, approved reel strips/probability/paytable/payline/RNG inputs, approved payout precision rule, and a provider-authoritative 5-Scatter EPICBUY_V37 embedded payload with BASE payout-unit conversion.
5. Written confirmation of server-side duplicate Play/EndRound suppression, timeout reconciliation, wallet ledger and refund/reversal semantics.
6. Asset creator and redistribution-rights confirmation, project license decision, trusted release signing key, and legal/Responsible Gambling approval.

## 2. Upload and launch

1. Do not upload while `BLOCKED_NOT_UPLOAD_READY` remains. If a separately authorized non-financial Studio inspection is later approved, confirm the SHA-256 of R9 before selecting it; do not use R4–R8 or legacy Math as a substitute.
2. If Studio permits frontend-only technical inspection and the project owner clears the asset/SDK rights, keep the game in a non-financial review/staging state. If it requires Math, stop at the missing-Math gate.
3. When canonical Math is available, upload a separate Math package containing `index.json`, the BASE/MAGICBUY_V36/EPICBUY_V37 compressed Books and matching LUT files, with independent pinned-SDK validation and hashes.
4. Launch only with Studio/Provider-issued parameters. The game must consume `sessionID`, `rgs_url`, `lang`, and `device` from the launch URL; never hardcode a production RGS host or session.
5. Replay launch must use `replay=true`, `game` UUID, `version`, `mode`, `event`, and `rgs_url`. No player session is required for replay.
6. Use only Provider-issued test balances and test credentials. Do not use a personal wallet or real-money balance for validation.

## 3. Runtime and visual verification

| Scenario | Required observation | Evidence |
|---|---|---|
| Initial launch | Authenticate succeeds; balance, bet levels, mode costs and explicit round state match Provider response | Redacted Authenticate request/response and Studio log |
| BASE loss | One Play/debit; authoritative 5x3 board stops; zero payout closes round without EndRound | Book ID, Play response, ledger row |
| BASE positive win | Final Book payout equals `payoutMultiplier`; one EndRound; one credit; round closes | Book, Event markers, EndRound response, ledger rows |
| WILD single movement | The same Ganesha symbol image/tag node moves from source reel cell to destination reel cell, same row; no board-fixed overlay | Studio recording and final 5x3 Book |
| WILD expansion | Destination reel has exactly three authoritative Wild cells; one full-height Ganesha portrait is anchored to the middle cell | Studio recording and Book events |
| Consecutive WILD moves | The expanded portrait itself moves to the next authoritative destination; no stale source overlay or coordinate fallback | Studio recording, event indices and boards |
| 3 Scatter | Exactly 10 Free Spins; every spin has an authoritative 5x3 board; correct final payout | Provider-approved Book/event ID and Studio recording |
| 4 Scatter | Exactly 12 Free Spins; legacy 10-spin Book rejected | Provider-approved Book/event ID and Studio recording |
| 5 Scatter | Embedded EPICBUY_V37 sequence remains inside the paid BASE round; no second debit and no additional Play; settlement mode stays BASE | Provider Golden Vector, RGS trace and ledger proof |
| 5 Scatter without payload | Fail closed before presentation/settlement; no second debit or Play | Rejection log and zero additional ledger entries |
| 6+ Scatter | Fail closed before settlement | Provider fixture and rejection log |
| Free Spins retrigger | Fail closed; no extra spins are added | Provider fixture and rejection log |
| Cap boundary | Per-spin and round cap enforced by Math, GameEngine, GuardedWallet and Wallet; no silent clamp | Boundary vectors and ledger proof |
| Replay | Public GET only; no Authenticate/Play/Event/EndRound; replay Book finalWin equals RGS `payoutMultiplier`; no wagering UI | Replay URL, RGS response, Studio recording |
| Replay without amount | Shows multiplier and cost multiplier without inventing zero bet/cash values | Replay URL with amount omitted |
| Replay mismatch | Rejects before final win display; no fabricated result | Deliberately mismatched Provider fixture |

## 4. Settlement and recovery tests

1. Verify one active round per session and explicit active/inactive state from Authenticate.
2. Verify zero-payout Play closes without EndRound; positive-payout Play remains active until EndRound.
3. Disconnect after Play request but before response. Re-authenticate and reconcile authoritative round state; do not retry Play merely because the browser timed out.
4. Disconnect during EndRound. Re-authenticate and compare round state and balance against the expected wager/payout delta. Do not issue a second EndRound until Provider confirms the first outcome.
5. Verify nonce/signature rejection and replay prevention at the actual Provider endpoint, not only in local Python tests.
6. Verify one debit per Play, one payout credit per winning round, and exact ledger/balance reconciliation. Refund/reversal tests must follow the Provider's written contract.
7. Verify Event checkpoints allow replay/recovery to resume without repeating a debit, win or settlement.

The current public SDK wire format contains no operation-level idempotency key. Local client locks and durable markers are containment only; Provider-side atomic idempotency and authoritative request-status lookup must be demonstrated by the Provider.

## 5. Physical-device and UI review

- Desktop Chrome/Firefox/Safari supported versions.
- iOS Safari and Android Chrome, portrait and landscape.
- Stake popout/small replay view.
- Sound on/off, mute, bet-level changes, mode confirmation, autoplay confirmation and keyboard/space interaction.
- Keyboard focus, contrast, text scaling, reduced-motion behavior and WCAG 2.2 AA checks.
- Confirm no clipped WILD portrait, no hidden symbol labels, no fixed overlays, no stale Scatter payout table and no unsupported retrigger copy. Verify the 3=10 / 4=12 / 5=embedded BASE / 6+=fail-closed contract exactly.

## 6. Evidence bundle to retain

- Exact Frontend ZIP and SHA-256; exact Math ZIP and SHA-256 when approved.
- `index.json`, Books/LUT manifests and individual SHA-256 hashes.
- Pinned Math SDK commit, validator output, RTP/variance/CVaR/max-win-frequency report and Provider Golden Vectors.
- SDK npm signature/integrity proof and local-fork delta.
- Studio upload version, launch parameters (secrets redacted), Studio logs and review findings. None exist yet; do not create placeholders that imply upload.
- RGS request/response traces with session/token/PII redacted; request correlation IDs and round IDs.
- Wallet ledger debit/credit/refund rows and before/after balances.
- Replay event IDs covering loss, win, big win, max win, 3/4/5/6+ Scatter, Wild movement/expansion and error recovery.
- Physical-device matrix, accessibility results, screenshots/recordings, security report, SBOM, trusted signature and hosted CI attestation.

## 7. Approval gate

Do not mark PASS until all of the following are independently evidenced: canonical Math passes the pinned official validator and the approved payout precision rule; all BASE/BUY distributions meet the accepted RTP/variance/CVaR/max-win requirements; Scatter and retrigger Books match the user-authorized contract; Provider Wallet settlement/idempotency/refund semantics pass live staging tests; R9 Frontend is accepted by Studio; all required event IDs replay correctly; assets/licenses/legal/RG/accessibility are approved; source/build/SBOM/signature/CI attestations bind to the exact submitted hashes.
