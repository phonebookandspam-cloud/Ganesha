# Canonical Math recovery checklist — Ganesha Full Scratch V1

**Status:** BLOCKED — original 2026-09-27 Math JSON / official Stake Studio export not recovered.

The recovery evidence is recorded in `artifacts/RC10_SOURCE_RECOVERY_EVIDENCE.json`. The source archive contains a partial `generator_input_manifest.json` with 58 required canonical fields; all 58 are missing. The previous search covered 410 ZIP archives and 65,321 text/JSON/Markdown entries without recovering the raw canonical Math JSON.

## Missing authority groups

The canonical manifest reports **58 required fields, 58 missing**. The partial source manifest does not enumerate the 58 fields individually, so this checklist does not invent a per-field count. It does identify the following concrete empty or incomplete groups:

| Source group | Evidence currently present | Missing / unresolved |
|---|---|---|
| Generator | No generator payload | Exact generator source/version, commit and canonical provenance |
| SDK | Generic `engineio/math-sdk` repository commit and dependency-lock hash recovered | Exact original game generator inputs and proof that this generic SDK checkout generated the canonical game math |
| Game configuration | Empty object | Complete canonical dimensions, paylines count, target RTP, volatility, wager and payout configuration |
| Modes | BASE, MAGICBUY_V36 and EPICBUY_V37 names recovered | All three mode-specific reel strips and probability models |
| Paytable / paylines / symbols | Empty objects | Complete symbol definitions, integer payouts, paylines and symbol mapping |
| Feature rules | Partial user-authority reconciliation | Wild semantics, 4+ Scatter, 6+ Scatter, Free Spins retrigger, termination and all Buy-mode feature rules |
| RNG | Empty object | RNG algorithm, seed derivation, stop weighting and reproducibility contract |
| Purchase costs | Historical `1.0× / 100× / 100×` values observed in an old index | User-defined target is BASE ×1 / MAGIC ×100 / EPIC ×500; canonical Math, mode distributions, eligibility and Provider authorization remain unavailable |
| Golden vectors | Empty object | BASE, Free Spins, Buy-mode and maximum-payout input/output vectors |
| Provider approval | No receipt or approval ID | Actual Math upload receipt and game-specific Provider approval |
| Front contract | Historical Front path and SHA-256 recovered | Current production Front/RGS contract and Provider acceptance |

The recovered generic SDK metadata and historical Front hash are provenance clues only; they do not reduce the 58 missing canonical manifest fields to a complete Math authority.

## Known rules versus unresolved rules

- User-authoritative: exactly 3 Scatter in BASE awards exactly 10 Free Spins.
- Current user-authoritative: 3 Scatter = 10 Free Spins; 4 Scatter = 12 Free Spins; 5 Scatter invokes the existing `EPICBUY_V37` feature embedded inside the already-paid BASE round, without another debit or Play, and remains BASE settlement; 6+ Scatter fails closed.
- Current user-defined independent purchase multipliers: MAGIC BUY = ×100 and EPIC BUY = ×500. Both remain disabled pending canonical Math and Provider approval.
- The partial manifest's 100× / 100× observations are historical and conflict with the current EPIC ×500 requirement. They are not approved current prices and do not authorize changing Books/LUT or implementing either Buy mode.
- 96.50% RTP and 50,000× maximum payout remain design targets, not verified values.
- The previous Draft-005 Divine Jackpot path is incompatible with Stake's published stateless-game approval requirements. A 50,000× target must be proven as a permitted single-bet outcome or redesigned with Provider clearance; no reachability or frequency is currently established.

## Exact material required from the user / original owner

1. The original raw Math JSON dated 2026-09-27, ideally the exact file as exported; do not re-save or normalize it before preserving the original bytes and SHA-256.
2. If that file is unavailable, the official Stake Studio Math export plus its complete generator/source archive and SDK/tool versions.
3. The exact mode-specific reel strips, stop weights, symbol mapping, paylines and paytable, including the original units and integer scaling.
4. The complete approved feature rules: Wild expansion, Scatter thresholds, Free Spins awards/retrigger/termination, each Buy mode price and feature outcomes, multiplier order, round/payout cap.
5. The RNG/seed derivation contract and Provider Golden Vectors for BASE, Free Spins, all Buy modes and maximum payout cases.
6. Canonical Books/LUT generation inputs, canonical `index.json` or source manifest, and any prior Math upload receipt / Provider approval identifier.

## Current independent work that does not replace canonical inputs

- `src/ganesha/math/reference.py` is a separate evaluator that accepts explicit inputs; it does not define canonical inputs.
- `tools/math_reference_crosscheck.py` compared the quarantined draft evaluator with the independent reference over all 371,293 draft stop vectors. BASE: 367,000 determinate and 4,293 blocked 4+ Scatter vectors. FREE_SPINS: 340,000 determinate and 31,293 blocked retrigger vectors. Zero mismatches. These are combinatorial draft counts, not weighted probabilities, RTP, hit frequency or Provider Golden Vectors.
- `src/ganesha/math/rng.py` provides deterministic HMAC stop generation using draft weights; this does not authorize financial play.
- `GameRuntime`, Presentation and SQLite Wallet integrity checks remain local engineering foundations. They do not authorize the missing feature math or production Provider contract.

**Fail-closed rule:** until the original authority is supplied and reconciled, no canonical `index.json`, Books, LUT, RTP report, max-win probability, Bonus Buy execution or real-money round may be generated or enabled.


## Exact 58-field contract inventory

The field names below are copied from the recovered RC10 generator-input contract, not inferred. They remain required evidence; the R8 partial manifest is not accepted as a substitute.

```text
generator.name
generator.version
generator.source_entrypoint
generator.source_sha256
sdk.repository
sdk.commit
sdk.dependency_lock_path
sdk.dependency_lock_sha256
game_config.path
game_config.sha256
game_config.approval_reference
modes.BASE.reel_strips.path
modes.BASE.reel_strips.sha256
modes.BASE.reel_strips.approval_reference
modes.MAGICBUY_V36.reel_strips.path
modes.MAGICBUY_V36.reel_strips.sha256
modes.MAGICBUY_V36.reel_strips.approval_reference
modes.EPICBUY_V37.reel_strips.path
modes.EPICBUY_V37.reel_strips.sha256
modes.EPICBUY_V37.reel_strips.approval_reference
paytable.path
paytable.sha256
paytable.approval_reference
paylines.path
paylines.sha256
paylines.approval_reference
symbols.path
symbols.sha256
symbols.approval_reference
feature_rules.path
feature_rules.sha256
feature_rules.approval_reference
feature_rules.scatter_policy
feature_rules.six_plus_scatter_policy
feature_rules.retrigger_policy
modes.BASE.probability_model.path
modes.BASE.probability_model.sha256
modes.BASE.probability_model.approval_reference
modes.MAGICBUY_V36.probability_model.path
modes.MAGICBUY_V36.probability_model.sha256
modes.MAGICBUY_V36.probability_model.approval_reference
modes.EPICBUY_V37.probability_model.path
modes.EPICBUY_V37.probability_model.sha256
modes.EPICBUY_V37.probability_model.approval_reference
rng.algorithm
rng.version
rng.seed_derivation
purchase_costs.BASE.multiplier
purchase_costs.BASE.approval_reference
purchase_costs.MAGICBUY_V36.multiplier
purchase_costs.MAGICBUY_V36.approval_reference
purchase_costs.EPICBUY_V37.multiplier
purchase_costs.EPICBUY_V37.approval_reference
golden_vectors.path
golden_vectors.sha256
golden_vectors.approval_reference
front_contract.path
front_contract.sha256
```

The expected canonical manifest (`math/generator_input_manifest.json`) is absent: 58/58 canonical fields remain missing. The separately recovered R8 partial manifest contains some observations but is marked `PARTIAL_EVIDENCE_ONLY_NOT_CANONICAL_OR_APPROVED`; the new preflight reports 44 of 58 fields absent within that partial object, unresolved source-file links, and no explicit per-mode `publish_artifacts` SHA declarations.

## Fail-closed index build pipeline

Run `PYTHONPATH=src python3 tools/build_stake_math_package.py preflight <canonical-manifest.json>` before any build. A build requires all 58 fields, matching hashes for source inputs and Books/LUT outputs, explicit approval references, and `status=CANONICAL_SOURCE_VERIFIED`. Then `build <manifest> <new-MATH-dir> <new-MATH.zip>` creates only a previously absent output pair and re-runs directory and extracted-ZIP contract checks. Existing candidate outputs are never overwritten. This pipeline is implemented and covered by temporary-directory tests; it does not bypass missing source authority.

The exact RC10 R8 semantic audit is recorded in `artifacts/RC10_R8_HISTORICAL_MATH_AUDIT_20261104.json`. It confirms full Books/LUT row parity but identifies SDK payout increment violations, mixed BASE `finalWin` amount units, and historical retrigger events.
