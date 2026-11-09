# Ganesha Math audit against pinned Stake Engine SDK — 2026-11-07

## Pinned validator

The exact pinned official Math SDK commit is `141b4e89065ac4400769709a919259a923430c4d` (2026-11-02, merge PR #123). Its `utils/rgs_verification.py::verify_lookup_format` requires integer payouts, positive payout >=10, and `payout % 10 == 0`.

The validator was fetched from `https://github.com/engineio/math-sdk` into an isolated `/tmp` checkout and executed against the existing R98 Math package. No Books or LUT files were modified.

The same pinned SDK's `RISK_CHECKS` implementation also evaluates top win (100,000x), cost multiplier (5,000x), standard deviation (60x), worst-0.1%-round CVaR (700x relative and 50,000x absolute), and tail-liability ratios (40x, 10,000x and combined). These are the SDK's published code constants, not a substitute for a written game-specific Provider decision.

## Results

| Mode | LUT rows | Payout quantum failures | Pinned validator | Books/LUT payout array |
|---|---:|---:|---|---|
| BASE | 100,000 | 45,235 | FAIL | PASS |
| MAGICBUY_V36 | 100,000 | 0 | PASS | PASS |
| EPICBUY_V37 | 100,000 | 0 | PASS | PASS |

All three modes have 100,000 Books, and their Books/LUT payout arrays match exactly. That is only a consistency result, not proof of correct probability inputs or game rules.

BASE exact weighted metrics, computed with the pinned SDK's distribution functions:

- RTP: 96.5%
- Variance: 1,314.031065824 x²
- Standard deviation: 36.2495664226x
- CVaR99.9%: 710.5480764122x (limit 700x — FAIL)
- Maximum win: 50,000x
- Maximum-win probability: 1e-7 (one in 10,000,000 rounds)

## Scatter and retrigger mismatch

The R98 BASE Books contain:

- 7,308 three-Scatter Books declaring 10 Free Spins.
- 1,095 four-Scatter Books declaring 10 Free Spins, while the user-authorized contract requires 12.
- 72 five-Scatter Books declaring a 10-spin Free Spins sequence, without a provider-authoritative embedded EPIC payload.
- 1,694 Books with a `retrigger` event. Retrigger is unauthorized and must fail closed.

There are 2,613 unique BASE Books incompatible with the current user contract (the 4/5-Scatter mismatch plus retrigger Books, with overlap counted once). R98 now rejects these at event validation; the Books themselves remain unsuitable for upload.

The current Frontend help text was corrected to state that retriggers are not authorized; it no longer advertises the historical +1-spin behavior.

## Unresolved payout precision conflict

The pinned validator requires `payout % 10 == 0`. The SDK's Book writer encodes `payoutMultiplier` as `int(round(payout_multiplier * 100, 0))`, and the published Math documentation gives `1150` as 11.5x. Official Math SDK issue #121, opened 2026-10-01, explicitly asks whether values such as 1, 6 and 11 are accepted or whether positive payouts must be multiples of 10; it remains open as of this audit.

This is a provider/validator ambiguity. Do not round, rescale, or alter Books/LUT payout values to silence the validator. Obtain a written provider ruling on accepted payout precision and the authoritative validator version first.

## Canonical source remains absent

The RC10 partial generator manifest is explicitly `PARTIAL_EVIDENCE_ONLY_NOT_CANONICAL_OR_APPROVED`. It has empty generator, game config, reel strips, probability models, paytable, paylines, symbols, RNG and Golden Vectors. No provider-authoritative embedded EPIC payload or approved Math inputs were found in the scanned archives. The public Math SDK repository is a generic framework, not the Ganesha game source.

## Decision

No Math package is approved for submission. Do not regenerate from invented inputs, edit compressed Books/LUT, normalize payouts, or enable 5 Scatter. Required next evidence: canonical generator source and launch entrypoint; approved reel strips and probability models; paytable/paylines/symbol rules; RNG/seed derivation; approved payout precision ruling; provider Golden Vectors; and the embedded 5-Scatter EPIC payload with BASE-unit conversion.

Machine-readable evidence: `artifacts/MATH_AUDIT_PINNED_SDK_20261107.json`.

## Buy-mode cost and weighted RTP addendum

The historical R98 `math/index.json` and Frontend `MODE` both set `MAGICBUY_V36` cost to 100 and `EPICBUY_V37` cost to 100. The 55% MAGIC BUY and 35% EPIC BUY figures in the UI are weighted non-zero outcome rates, not purchase cost multipliers. The weighted distribution calculations in this section are strictly historical observations at cost 100/100; they are **not valid results for the current user-defined cost contract** and must not be cited as current Buy-mode RTP or payout evidence.

- MAGICBUY_V36: variance 62,509.400826 x²; standard deviation 250.018800945x; CVaR99.9% 2,586.466156x; max 50,000x base / 500x purchase cost; max-win frequency 1/10,000,000.
- EPICBUY_V37: variance 80,635.819229 x²; standard deviation 283.964468252x; CVaR99.9% 2,601.726947x; max 50,000x base / 500x purchase cost; max-win frequency 1/10,000,000.

Under those historical 100/100 costs, both Buy modes exceed the SDK's standard-deviation and relative-CVaR thresholds; BASE exceeds the relative-CVaR threshold. These risk figures are historical and cannot be carried forward to the new MAGIC ×100 / EPIC ×500 contract. Tail-liability metrics and the complete SDK risk-check suite must be recomputed from the correct canonical distributions before release.

Machine-readable addendum: `artifacts/MATH_BUY_MODE_AUDIT_ADDENDUM_20261107.json`.

## Superseding user price contract — 2026-11-09

The user has now explicitly fixed the independent purchase multipliers as **MAGIC BUY ×100** and **EPIC BUY ×500**. The historical 100/100 index is therefore nonconforming. This does not authorize a cost-only index edit: the corresponding canonical mode probability model, Books, LUT, RTP, variance, volatility and tail metrics must be regenerated and Provider-verified from canonical inputs. The Ganesha builder and package verifier now fail closed unless the mode-cost contract is exactly BASE ×1 / MAGIC ×100 / EPIC ×500. Both Front controls remain disabled until canonical Math and Provider approval.

The BASE 5-Scatter path remains separate: it embeds the existing EPIC feature inside BASE, with no second debit or Play and BASE settlement. Its Provider-authoritative feature payload and BASE-unit conversion are still missing. See `docs/BUY_MODE_USER_CONTRACT_20261109.md` and `docs/SCATTER_FEATURE_CONTRACT_20261107.md`.
