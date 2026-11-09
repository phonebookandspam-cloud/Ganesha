# Math Specification V1 — Draft 005 (Superseded)

**NOT RELEASE EVIDENCE**

Status: `SUPERSEDED_NOT_RELEASE_EVIDENCE`. This document records a hypothetical research design. It is not the canonical Math for the Stake Engine title and must not be used to generate or publish Books/LUT.

## Why this draft is superseded

The draft's progressive 3/4/5+ awards conflict with the current user-authoritative contract: 3 = 10 Free Spins; 4 = 12 Free Spins; 5 invokes the existing embedded EPIC feature in BASE (blocked pending canonical Provider payload and BASE-unit conversion); 6+ and retriggers fail closed. Independent MAGIC BUY ×100 and EPIC BUY ×500 are also user-defined, but both remain disabled pending canonical Math and Provider approval. The draft's probability weights, Wild multipliers, symbol inventory and Divine Jackpot remain noncanonical. See [`authority-boundary.md`](authority-boundary.md), [`SCATTER_FEATURE_CONTRACT_20261107.md`](SCATTER_FEATURE_CONTRACT_20261107.md), and [`BUY_MODE_USER_CONTRACT_20261109.md`](BUY_MODE_USER_CONTRACT_20261109.md).

The exact RTP, variance and jackpot probabilities in `artifacts/math_audit_v1.json` were computed under those draft assumptions. They are not valid release evidence. The Monte Carlo and crosscheck share the same payout evaluator, omit observed jackpot mass and cannot independently validate rare-tail RTP/CVaR.

## Historical draft configuration

- 5 reels × 3 visible rows; 20 draft payline paths.
- 8 proposed symbols: `WILD_GANESHA`, `SCATTER_LOTUS`, `ELEPHANT`, `MOUSE`, `MODAK`, `CHAKRA`, `A`, `K`.
- Five proposed 13-stop strips with integer weights.
- Draft progressive Scatter awards and retriggers (rejected as Stake authority).
- Draft Buy costs 57.766× and 112.420× (not approved; not the original 100× Buy contract).
- Draft Wild expansion and Divine Jackpot behavior (not approved).

The active local engine enforces the current rules: BASE 3 Scatter returns 10 Free Spins; 4 returns 12; 5 raises `EmbeddedEpicFeatureUnavailable` until the canonical embedded payload and BASE-unit conversion exist; 6+ and unauthorized Free Spins retriggers fail closed. This local implementation does not certify the draft reels, weights, paylines, paytable, Wild behavior, Buy modes or RTP.

## Arithmetic notes for historical reproducibility only

The code's historical payout scale is `991861/1000000`. `engine.py` applies nearest-milli rounding independently to each winning payline before summing line wins. The earlier text value `9983/10000` was inconsistent and is not the code value. This correction fixes a documentation mismatch only; it does not validate the scale or rounding stage as canonical.

The draft's weighted Monte Carlo uses the same `evaluate_board()` implementation as the exact per-spin enumeration. It is a stochastic repeat of the same evaluator, not an independent implementation. Its sample-normal confidence interval is unreliable for the rare 50,000× tail because no jackpots were observed in the stored samples. Empirical CVaR therefore omits the unseen jackpot mass.

## Required canonical inputs

See [`authority-boundary.md`](authority-boundary.md) and the original RC10 58-field input contract. The raw original Math JSON, exact input hashes, canonical generator, approved probability profiles, golden vectors and Provider approval are still required.
