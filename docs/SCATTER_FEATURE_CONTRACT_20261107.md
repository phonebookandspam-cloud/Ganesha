# BASE Scatter Feature Contract — current user authority as of 2026-11-09

## Authority

This addendum records the current explicit user instruction and supersedes the earlier draft rule that treated every BASE Scatter count above three as unspecified.

| BASE reveal Scatter count | Required behavior | Financial mode |
|---:|---|---|
| 0–2 | No feature | BASE |
| 3 | 10 Free Spins | BASE |
| 4 | 12 Free Spins | BASE |
| 5 | Existing `EPICBUY_V37` feature sequence | BASE |
| 6–15 | Fail closed; no rule authorized | BASE |

## Five-Scatter embedded EPIC contract

- Five Scatter selects the existing `EPICBUY_V37` feature math/sequence; it is not a new paid purchase mode.
- The feature is embedded in the already-paid BASE round. It must not create a second debit or a second Play request.
- The round remains `BASE` for RGS/Wallet settlement and accounting.
- The EPIC feature payout must be expressed in BASE-bet units and reconciled against the BASE round cap. Reusing an EPIC purchase-cost-denominated payout without an explicit unit conversion is prohibited.
- The provider Math payload must identify the EPIC feature sequence and its 10-spin progression. The local engine must not synthesize or hand-edit this sequence.

## Implementation boundary

- The 4-Scatter 12-spin award can be implemented as a user-authorized rule in the local draft engine and presentation contract.
- The 5-Scatter trigger is recognized as `EPICBUY_V37`, but this repository does not contain the canonical provider-generated embedded feature payload or an approved payout-unit conversion. Until both exist and are independently verified, the financial engine and settlement validator must fail closed on five Scatter.
- Six or more Scatter remain fail-closed.
- Free Spins retrigger behavior remains unspecified and disabled. This addendum does not authorize retriggers.
- This rule update does not establish canonical Math approval, RTP, volatility, CVaR, max-win frequency, or release readiness.
