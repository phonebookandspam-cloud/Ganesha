# Math Specification V1 — Draft 005 (Superseded)

**NOT RELEASE EVIDENCE**

Status: `SUPERSEDED_NOT_RELEASE_EVIDENCE`. This document records a hypothetical research design. It is not the canonical Math for the Stake Engine title and must not be used to generate or publish Books/LUT.

## Why this draft is superseded

The draft conflicts with later user-authority reconciliation for BASE Scatter: it proposes 3/4/5+ = 10/12/15 Free Spins, while the authoritative boundary is exactly 3 = 10 Free Spins and 4/5 must not award that exact-3 feature. The draft also assumes retrigger behavior, Wild multipliers, new weighted strips, an 8-symbol inventory, Buy prices and a Divine Jackpot without canonical approval. See [`authority-boundary.md`](authority-boundary.md).

The exact RTP, variance and jackpot probabilities in `artifacts/math_audit_v1.json` were computed under those draft assumptions. They are not valid release evidence. The Monte Carlo and crosscheck share the same payout evaluator, omit observed jackpot mass and cannot independently validate rare-tail RTP/CVaR.

## Historical draft configuration

- 5 reels × 3 visible rows; 20 draft payline paths.
- 8 proposed symbols: `WILD_GANESHA`, `SCATTER_LOTUS`, `ELEPHANT`, `MOUSE`, `MODAK`, `CHAKRA`, `A`, `K`.
- Five proposed 13-stop strips with integer weights.
- Draft progressive Scatter awards and retriggers (rejected as Stake authority).
- Draft Buy costs 57.766× and 112.420× (not approved; not the original 100× Buy contract).
- Draft Wild expansion and Divine Jackpot behavior (not approved).

The active engine now has a fail-closed authority guard: BASE exactly 3 Scatter returns 10 Free Spins; 4/5 and 6+ raise an unspecified-rule error, and retrigger Scatter raises an unspecified-rule error. The 10/12/15 and +5/+7/+10 values remain only as quarantined historical config data and are not consumed by this guard. This does not certify the remaining draft reels, weights, paylines, paytable, Wild behavior, Buy modes or RTP.

## Arithmetic notes for historical reproducibility only

The code's historical payout scale is `991861/1000000`. `engine.py` applies nearest-milli rounding independently to each winning payline before summing line wins. The earlier text value `9983/10000` was inconsistent and is not the code value. This correction fixes a documentation mismatch only; it does not validate the scale or rounding stage as canonical.

The draft's weighted Monte Carlo uses the same `evaluate_board()` implementation as the exact per-spin enumeration. It is a stochastic repeat of the same evaluator, not an independent implementation. Its sample-normal confidence interval is unreliable for the rare 50,000× tail because no jackpots were observed in the stored samples. Empirical CVaR therefore omits the unseen jackpot mass.

## Required canonical inputs

See [`authority-boundary.md`](authority-boundary.md) and the original RC10 58-field input contract. The raw original Math JSON, exact input hashes, canonical generator, approved probability profiles, golden vectors and Provider approval are still required.
