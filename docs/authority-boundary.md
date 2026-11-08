# Authority Boundary — Full Scratch V1

Status: `BLOCKED_FROM_STAKE_RELEASE`.

## Confirmed user-authority constraints from the later RC10 reconciliation

Source: `qa/work_20261101_ver1_release_candidate_rc10/worktree/qa/RC10_MATH_USER_AUTHORITY_RECONCILIATION_20261101.json` (2026-11-01), with supporting Markdown beside it.

- Initial BASE reveal: exactly 3 literal Lotus Scatter awards exactly 10 Free Spins.
- 0–2 Scatter do not award that exact-3 feature.
- 4–5 Scatter do not award that exact-3 feature. Whether another feature applies is unspecified.
- 6+ Scatter behavior is unspecified and blocked.
- Free Spins retrigger behavior is unspecified and blocked.
- The original user-supplied JSON inventory recorded six symbols: Wild_Ganesha, Scatter_Lotus, High_Elephant, High_Mouse, Low_A, Low_K.
- The original raw JSON is not present in the current accessible workspace; exact five 13-stop reel strips, line coordinates and payout data cannot be hashed or consumed from the source.
- The original JSON did not provide approved probability weights, full Wild expansion/multiplier rules, a canonical generator, Provider approval or Golden Vectors.
- The current eight-symbol V1 draft adds Modak and Chakra; the source/approval lineage for that change is not established.

## Draft-005 features that are NOT approved

The Full Scratch V1 draft introduced all of the following without canonical source/Provider approval:

- BASE progressive 3/4/5+ Scatter awards of 10/12/15 Free Spins.
- Free Spins retriggers of +5/+7/+10 and a 50-spin cap.
- New five-reel stop weights and an 8-symbol set.
- Wild expansion/multiplier composition, including a Divine Surge multiplier.
- 57.766× MAGIC BUY and 112.420× EPIC BUY prices with 25/50 starting spins.
- A terminal 50,000× Divine Jackpot event.

These are hypothetical research proposals. They are not interchangeable with the Stake title's user-authoritative Math. In particular, the current draft runtime and exact audit must not be used to claim compliance with the BASE Exact-3 rule.

## Disposition

- The current Math audit, Monte Carlo and crosscheck artifacts are retained for engineering history only and marked `SUPERSEDED_NOT_RELEASE_EVIDENCE`.
- The visual frontend now states the known Exact-3 rule and explicitly marks unspecified rules; it disables all wager and Buy controls.
- The active local `free_spins_awarded()` now returns exactly 10 only for BASE count=3, returns 0 for counts 0–2, and raises `UnspecifiedMathRule` for 4/5, 6+ and all retrigger cases. This is a fail-closed guard, not a claim that 4/5 have no other feature; a round encountering an unresolved case is aborted/refunded by the local reference service.
- Draft-005 BASE awards 10/12/15 and retrigger +5/+7/+10 are not present in the active `GameConfig`; no 4/5 Scatter or retrigger award tuple is available to the active engine.
- The local reference API is not exposed as a public wagering interface.
- The historical Draft-005 MAGIC/EPIC cost and spin-count values are no longer present in active `GameConfig`, `simulation.py`, or `round_ev.py`. Full-round EV, Free Spins EV and Monte Carlo now fail closed without approved 4+ Scatter, retrigger and Buy rules. Bonus Buy execution requires an explicit Math-port `resolve_bonus_buy_terms` result; the default `DraftMathPort` supplies no such terms, so both Buy modes fail before debit. Test-only ports may supply fixture terms for contract tests, but this is not canonical Math approval or a production purchase path.
- No Books/LUT, RC10 files, SDK, Studio state or Provider settings were modified by this Full Scratch work.

## Stake stateless-game policy reconciliation — 2026-11-04

The current official Stake Engine Approval Guidelines state that Engine games are strictly stateless and prohibit jackpots, gamble features, continuation and early cashout. The previous Draft-005 terminal Divine Jackpot therefore cannot be treated as a viable Stake feature. The local draft evaluator now emits `jackpot_triggered=false` and applies only its explicitly noncanonical per-spin cap; the GameEngine rejects any MathPort result that attempts to trigger a jackpot. This is a policy guard, not a replacement for canonical Math.

The 50,000× target remains a maximum-payout design target, not a jackpot authorization. Any future route must be an approved outcome within a single stateless bet and must be supported by canonical paytable/feature inputs, exact probability evidence and Provider settlement limits. The current draft's 1,000× per-spin cap and Exact-3-only 10 Free Spins do not prove a 50,000× route. No such route or frequency is claimed.

Official source reviewed 2026-11-04: https://stake-engine.com/docs/approval-guidelines

## Required before Stake Math work resumes

1. Reattach the original 2026-09-27 user Math JSON or exact source file; record raw bytes and SHA-256.
2. Recover the exact approved symbol set, reel strips, 20 paylines and paytable.
3. Obtain approved probability models and all mode-specific input files.
4. Obtain authoritative Scatter 4/5 alternative behavior, 6+ policy, retrigger, Wild expansion/multiplier and Buy rules.
5. Obtain the canonical generator, version, source hash, RNG derivation and Provider-approved Golden Vectors.
6. Bind all inputs to a source manifest and approval references before generating or changing Books/LUT.

No local draft value should be substituted for a missing authority record.

## Additional ZIP evidence inspected on 2026-11-03

The following archives were inspected read-only. Their SHA-256 values bind the evidence described below:

| Archive | SHA-256 | Relevant contents / disposition |
|---|---|---|
| `Ganesha_and_The_Magic_Modak_V1.0_RC10_EXACT3_R8_20261101_MATH.zip` | `5a7aaa4c51955efedb60c70d92704861f4439c591c084c65b13c9b65ac43e94c` | Contains seven `library/publish_files/` files: index, 3 Books and 3 LUTs. Full audit is `artifacts/RC10_R8_HISTORICAL_MATH_AUDIT_20261104.json`; Books/LUT IDs and payouts match, but 45,235 BASE LUT payout rows violate the pinned SDK increment rule and BASE finalWin units are mixed. |
| `Ganesha_and_The_Magic_Modak_V1.0_RC10_EXACT3_R8_20261101_SOURCE_EVIDENCE.zip` | `c7104a5f989fca82f7757befd5d90032fd1a4708d3fcf2b339fcfd64f30397ca` | Contains generated Books/LUT and `math/generator_input_manifest.json`; that manifest is explicitly `PARTIAL_EVIDENCE_ONLY_NOT_CANONICAL_OR_APPROVED`, with empty generator, game config, reel strips, probability models, paytable, paylines, symbols and Golden Vectors. |
| `Ganesha_and_The_Magic_Modak_V1.0_RC10R1_MATH_PROVENANCE_SUPPLEMENT_R2_20261101.zip` | `432c9eb84b089d502dc592872f8f86c6f5adba27f933a20ad511bf18c6c57141` | Contains `RC10_CANONICAL_SOURCE_RECOVERY_20261101.json`; records 410 ZIP archives and 65,321 text/JSON/Markdown entries scanned, with no original user Math JSON or raw reel-strip source recovered. It confirms the original user JSON was historically supplied but its raw bytes and arrays are unavailable in this session. |

The same provenance supplement records the 58-field canonical generator manifest as missing all 58 fields. The partial R8 manifest observes 100× MAGIC/EPIC Buy costs from the existing index, but explicitly states Provider approval is absent. This does not convert an observed index value into Provider approval. The user's intended 100× Buy target must not be confused with a Provider-approved contract.

This inspection did not extract or modify the original RC10 worktree, Books, LUT, index, SDK, Studio or Provider state.

Additional recovery attempts on 2026-11-03:

- Three Dropbox searches for the original Ganesha Math JSON, reel strips/paylines/paytable and prior MATH_UPLOAD_FIXED source returned zero results.
- Prior conversation retrieval for conversation `c0` confirmed only the fact that the complete JSON was sent at `2026-09-27T09:07:11Z`; it did not return the literal payload.
- A prior assistant output is summarized as reporting BASE RTP approximately `286.8004513955%`. This is an unverified secondary calculation, not an accepted Math result. It is a warning that the original arrays may conflict with the stated 96.50% target; it cannot be adjudicated without the raw JSON.

These findings are recorded in `artifacts/RC10_SOURCE_RECOVERY_EVIDENCE.json`. They do not authorize reconstruction or rebalancing.

## RC10 Exact3 R8 package reinspection — 2026-11-04

A read-only reinspection corrected an incomplete file listing in the earlier recovery notes. `../dist/Ganesha_and_The_Magic_Modak_V1.0_RC10_EXACT3_R8_20261101_MATH.zip` (19,094,264 bytes; SHA-256 `5a7aaa4c51955efedb60c70d92704861f4439c591c084c65b13c9b65ac43e94c`) contains seven `library/publish_files/` entries: `index.json`, three `.jsonl.zst` Books files and three CSV LUTs. The exact 477-byte index names BASE at 1.0x and MAGICBUY_V36 / EPICBUY_V37 at 100.0x.

This is historical generated-package evidence, not recovered canonical source Math. The companion `Ganesha_and_The_Magic_Modak_V1.0_RC10_EXACT3_R8_20261101_SOURCE_EVIDENCE.zip` contains a generator-input manifest explicitly marked `PARTIAL_EVIDENCE_ONLY_NOT_CANONICAL_OR_APPROVED`: generator, game_config, all three mode reel strips and probability models, paytable, paylines, symbols, RNG and Golden Vectors are empty. The two 100x Buy prices are explicitly described as observed historical index values without Provider approval. Thus this historical index cannot be copied into the current Full Scratch MATH package as an authorized configuration. The full read-only audit is now complete in `artifacts/RC10_R8_HISTORICAL_MATH_AUDIT_20261104.json`: all 300,000 Books and 300,000 LUT rows were parsed; ordered IDs and payout values match; event indices and board shapes pass. The archive nevertheless fails the pinned SDK payout-increment rule in 45,235 BASE LUT rows, BASE `finalWin.amount` units are mixed, and 1,694 BASE retrigger events conflict with the unresolved retrigger authority. Exact archive and per-file hashes are recorded in `artifacts/RC10_SOURCE_RECOVERY_EVIDENCE.json`.


## Canonical index build gate — 2026-11-04

`tools/build_stake_math_package.py` implements a fail-closed 58-field manifest preflight and matched-set MATH directory/ZIP builder. It requires all 58 fields, hash-linked source files, explicit approval-reference fields, an exact BASE/MAGICBUY_V36/EPICBUY_V37 publish-artifact declaration, per-artifact SHA-256, and `status=CANONICAL_SOURCE_VERIFIED`. It generates `index.json` only from the manifest's explicit mode costs and generator-declared Books/LUT files, then runs the full directory verifier and ZIP-extraction verifier. It refuses existing output paths. It does not authenticate the external approver; approval references remain evidence pointers to be independently checked.

The recovered R8 partial manifest is not a canonical manifest. Its declared status is `PARTIAL_EVIDENCE_ONLY_NOT_CANONICAL_OR_APPROVED`; preflight finds 44 of 58 fields absent in that partial object, three source paths unresolved from its extraction root, and no `publish_artifacts` declarations. The canonical manifest at the expected source path is absent, so canonical completeness remains 58/58 missing. No current MATH index was synthesized.

The existing candidate `MATH/index.json` is 18 bytes and contains `{{"modes":[]}}`; it is invalid by the non-empty mode contract. Existing `MATH.zip` and `FRONT.zip` are preserved engineering archives, not upload-ready Stake packages.


## Independent Draft Math fail-closed audit — 2026-11-04

`artifacts/INDEPENDENT_DRAFT_MATH_AUDIT_20261104.json` records a fresh exhaustive check of the current independent draft inputs. The deterministic engine and separate reference agree on all resolved stop vectors: BASE 367,000 resolved / 4,293 blocked (4+ Scatter), Free Spins 340,000 resolved / 31,293 blocked (3+ Scatter/retrigger); zero evaluator mismatches in the resolved domains. HMAC-SHA256 rejection-sampling replay is deterministic under an ephemeral test key; production entropy/key management is not certified.

The active draft config no longer contains 4/5 Scatter award tuples or MAGIC/EPIC Buy prices. Full-round RTP, feature EV, Buy RTP, hit frequency, variance, volatility, payout/streak distributions and max-win frequency are not computed. With the current draft per-spin cap of 1,000x, one BASE spin plus exactly ten Free Spins and no retrigger, the maximum possible draft round payout is 11,000x. The 50,000x design target is therefore unreachable under the current draft rules; this is not a statement about missing canonical Math.
