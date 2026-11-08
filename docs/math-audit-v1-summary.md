# Math Audit V1 — Draft-005 Historical Record

**SUPERSEDED — NOT RELEASE EVIDENCE**

The stored `math_audit_v1.json`, `monte_carlo_v1.json` and `math_crosscheck_v1.json` are retained only as historical research artifacts. They were generated from hypothetical Draft-005 inputs and rules that conflict with the later user-authoritative BASE Scatter boundary.

Independent review also identified:

1. BASE exact DP double-counts prior BASE payout on a Free Spins jackpot path: the DP treats the jackpot as an additional 50,000× feature payout, while the game engine sets the total round payout to the 50,000× round cap.
2. The stored “max-win probability” fields represent Divine Jackpot probability only. They do not include every possible path to the 50,000× accumulated round cap (EPIC has a non-jackpot cap path).
3. Monte Carlo uses the same `evaluate_board()` implementation as exact enumeration. It is not an independent math implementation.
4. No jackpot was observed in the stored samples; expected jackpot observations are below one per mode. Sample SD-based normal intervals and empirical CVaR do not represent the rare jackpot tail.
5. The artifacts do not bind results to SHA-256 identities for config, strips, weights, paylines, paytable, evaluator and generator.
6. The draft's Buy prices, progressive Scatter awards, retriggers and Wild multiplier are not user/Provider approved.

No RTP, variance, CVaR, jackpot probability or maximum-win claim from these artifacts is approved for public product claims. Do not rerun or regenerate them as if the source specification were authoritative.
