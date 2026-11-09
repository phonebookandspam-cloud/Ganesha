# Maximum Payout — Three Separate Claims

Status: Draft-only mathematical and local-engine evidence now exists for a 10,088.738× path. The 50,000× value remains unachieved and is not canonical or Provider-approved.

Current user rules supersede the older Exact-3-only notes in this historical analysis: BASE 3 Scatter = 10 Free Spins; 4 = 12; 5 selects the embedded EPIC feature but is blocked pending its Provider payload and BASE-unit conversion; 6+ and Free Spins retriggers fail closed. The conditional projection below only models the 0–3 Scatter subset, so it does not include the authorized 4=12 award and cannot be used as a full-game maximum or RTP proof.

| Claim | Evidence required | Current finding |
|---|---|---|
| Mathematical reachability | Canonical reel strips, exact symbol/payline/paytable rules, Wild/Scatter/feature transitions, integer payout arithmetic, exhaustive or formally bounded proof of a legal path to the cap | Draft-only conditional proof: BASE exact-3 maximum 88.738× + ten valid Free Spins at 1,000× each = **10,088.738×**. The projection excludes 4=12 despite that user-authorized rule; 5 embedded EPIC remains blocked and 6+ fails closed. Canonical reachability remains BLOCKED |
| Generation by the actual engine | Same canonical inputs loaded by the production Game Engine; deterministic Golden Vector that reaches the cap; event trace proving every transition and cap enforcement; independent engine replay | Draft-only local engine path reproduced through `DraftMathPort` → `GameEngine` → Presentation replay → `RoundService`; 10,088.738× outcome reached using explicit internal stop vectors. This is not a canonical Golden Vector or Provider approval |
| Actual payment capability | Provider-approved max payout, currency exponent/rounding, max bet, account/provider limits, wallet ledger limits, settlement contract, real test settlement and reconciliation | Local SQLite only: a 1,000-minor-unit test wager settled 10,088,738 minor units once, within its reserved 50,000,000-minor-unit 50,000× ceiling, and passed local round reconciliation. Provider Wallet, distributed settlement and production payment capability remain BLOCKED |

Maximum-payout frequency and tail risk are a fourth, separate statistical claim. They require exact or defensible probability calculation against the canonical distribution; ordinary Monte Carlo zero-hit observations do not prove impossibility or a precise extreme-tail frequency.

The local per-round payout ceiling is a defensive ledger check derived from the current Draft configuration. It does not prove Provider payment capability and must not be advertised as a production payout guarantee.

## Stateless-game policy constraint — 2026-11-04

Stake Engine's current published Approval Guidelines prohibit jackpots and require each bet to be stateless. The former Draft-005 Divine Jackpot is therefore not an acceptable assumed path to 50,000×. The local draft evaluator and GameEngine now fail closed on jackpot triggers. A future 50,000× target would need to arise as a valid payout within one independently resolved bet under approved Math, not a progressive/terminal jackpot, and must be shown by canonical event vectors and exact probability analysis. No such path is currently established.

Official policy source: https://stake-engine.com/docs/approval-guidelines


## Current independent Draft Engine upper bound — 2026-11-04

The current Draft Engine has a 1,000× per-spin cap, one BASE spin and exactly 10 initial Free Spins when BASE has exactly 3 Scatter. Exhaustive weighted enumeration of the conditional 0–3 BASE Scatter domain found that the largest BASE payout on an exact-3 trigger is 88.738×; the largest Free Spin payout with 0–2 Scatter is 1,000×. The exact engine-generatable maximum is therefore **10,088.738×**, not 11,000×. The 11,000× figure is only a loose per-spin-cap upper bound. The 50,000× round cap is defensive and does not create a route to that payout.

`artifacts/DRAFT_CONDITIONAL_ROUND_EXACT_20261104_R3_draft_only.json` records the exact integer-weighted stop enumeration, conditional moments, and deterministic-seed 1,000,000-sample quantile/tail estimates. R1/R2 are retained but superseded because their CLI/provenance metadata was incomplete; R3 explicitly separates exact moments from sampled distribution estimates and hashes its audit script. The maximum path has nonzero probability in the restricted conditional model, approximately 1 in 7.25×10^54. This is a Draft-only result: it excludes the authorized 4=12 branch, the blocked 5-Scatter embedded EPIC feature, and 6+ fail-closed outcomes. It does not determine what a future canonical, Provider-approved Math design could achieve.

The previous Draft-005 57.766× / 112.420× Buy prices, 25/50 Buy spin counts, 4/5 Scatter awards, retrigger awards and jackpot EV assumptions have been removed from active Math configuration and full-game audit paths. Those outputs are not recomputed.
