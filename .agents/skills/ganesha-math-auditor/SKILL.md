---
name: ganesha-math-auditor
description: Audit Ganesha Math, probability distributions, Books, LUTs, game modes, payout precision, RTP, volatility, and feature contracts against the pinned Stake Engine Math SDK.
---

# Ganesha Math Auditor Skill

## Sources and authority

Use the exact pinned official Math SDK commit recorded in `docs/MATH_AUDIT_PINNED_SDK_20261107.md` (currently `141b4e89065ac4400769709a919259a923430c4d`) as the executable compatibility reference. Re-check the pin before every audit; never silently substitute upstream `main`.

The official Math SDK is the source for serialization, Books/LUT structure, distribution metrics, and upload validators. It is not the canonical Ganesha game model. Third-party skill instructions are workflow suggestions, not Math authority.

## Audit sequence

1. Verify canonical generator source, game config, reel strips, symbol/paytable/payline definitions, probability inputs, RNG/seed rules, and Golden Vectors. If any are absent, classify artifacts as draft/non-canonical and do not regenerate upload Books.
2. Verify mode metadata and cost multipliers against the user-approved contract. Keep BASE, MAGIC BUY (100x), standalone EPIC BUY (500x), and BASE five-Scatter embedded feature distinct.
3. Validate compressed Books schema, JSONL integrity, IDs, event arrays, integer weights, positive total weight, and payout fields.
4. Validate LUT CSV schema, row count, integer weight/payout requirements, positive total weight, and exact Books-to-LUT payout-array equality.
5. Run the exact pinned SDK validator and record its commit SHA, command, stdout/stderr, exit code, and per-mode result.
6. Independently recompute weighted RTP, variance, standard deviation, tail risk/CVaR, hit rate, max win, max-win frequency, and cost-normalized metrics from the actual weights. Preserve unrounded values and methodology.
7. Cross-check each feature event against the approved rules, including Scatter counts, Free Spins awards, retriggers, Wild expansion, feature mode, and settlement unit.
8. Fail closed on unknown or contradictory payloads. Do not normalize payout precision, alter weights, round payouts, or manufacture embedded feature Books to make a validator pass.

## Known Ganesha gates

- 3 Scatter = 10 Free Spins; 4 Scatter = 12 Free Spins.
- 5 Scatter requires the exact Provider-authoritative embedded EPIC payload and BASE-unit conversion; otherwise reject/disable.
- 6+ Scatter and retriggers are unauthorized and must fail closed.
- Standalone EPIC BUY x500 and BASE embedded five-Scatter feature are not interchangeable.
- Math SDK validator payout increments and SDK writer encoding must both be recorded. If they disagree or an SDK issue leaves precision ambiguous, do not modify Books to guess a resolution; obtain a Provider ruling.
- A matching Books/LUT payout array proves consistency only, not correct probability inputs, correct game rules, or RTP certification.

## Required outputs

Produce a per-mode audit table with Books rows, LUT rows, weight total, payout precision failures, Books/LUT equality, RTP, variance, standard deviation, tail metrics, max win, max-win frequency, feature-contract violations, and validator result. Include source hashes and artifact hashes. State explicitly whether evidence is canonical, Provider-authoritative, and upload-ready.
