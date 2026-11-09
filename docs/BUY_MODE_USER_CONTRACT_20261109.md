# Ganesha Buy-mode user contract — 2026-11-09

## Binding user requirements

| Mode | User-defined purchase multiplier | Release state |
|---|---:|---|
| BASE | ×1 | Canonical Math still unverified |
| MAGIC BUY (`MAGICBUY_V36`) | **×100** | Disabled pending canonical Math and Provider approval |
| EPIC BUY (`EPICBUY_V37`) | **×500** | Disabled pending canonical Math and Provider approval |

These multipliers are immutable product requirements for future implementation and validation. They do not, by themselves, prove that the existing Books/LUT distributions are correct at those prices or that Stake/Provider has approved either mode.

## Separate five-Scatter behavior

BASE 5 Scatter invokes the existing `EPICBUY_V37` feature payload *inside the already-paid BASE round*. It is not an independent EPIC BUY transaction: no additional debit, no second `/wallet/play`, and settlement remains BASE. The canonical embedded payload and its BASE-unit payout conversion are unavailable; therefore 5 Scatter remains fail-closed. Never reuse the independent EPIC purchase cost or payout units without an authoritative conversion.

## Required implementation controls

- `tools/build_stake_math_package.py` rejects any manifest whose declared BASE/MAGIC/EPIC multipliers are not exactly 1/100/500.
- `tools/verify_stake_package.py math-dir` and `math-zip` apply the same Ganesha-specific mode/cost contract after structural Books/LUT checks.
- Front displays ×100 and ×500 only as locked user-defined target prices. The controls remain disabled; this is not a Provider pricing configuration.
- Existing historical index files that show MAGIC ×100 and EPIC ×100 are mismatched with this user contract and must not be submitted or silently edited. Their Books/LUTs require canonical regeneration from approved inputs.
- Do not change RTP, probability distributions, variance, volatility, payout tails, max-win frequency, Books, LUTs, or purchase-mode feature sequences to make the new multipliers appear valid.

## Release blocker

The original canonical Math JSON, canonical generator and approved inputs, Provider Golden Vectors, Provider approval, and the 5-Scatter embedded EPIC payload/BASE-unit conversion remain unavailable. The contract validator prevents a future price inversion; it does not remove these authority blockers.
