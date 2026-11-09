# Ganesha and The Magic — Release Recovery Audit (2026-11-09)

## Executive disposition

`BLOCKED_NOT_UPLOAD_READY` — no Stake Math package or Stake Front package is currently releasable. No `math/` or `front/` submission directory was generated, no Stake Studio upload was performed, and no Provider approval or production RGS settlement was observed.

The prior 493-test baseline has now been re-run after Math Builder approval hardening. The current full `make test` run completed with 496/496 passing tests (463 Python + 33 Frontend/SDK/RGS). R6 remains preserved; R7 is a subsequent local offline build. Neither R6 nor R7 is a wagering frontend or a Stake-ready package.

## Git / source scope

- Repository: `https://github.com/phonebookandspam-cloud/Ganesha`
- Working branch: `integration/ganesha-full-release-2026-11-09`
- Last confirmed remote HEAD before this audit's current local edits: `aaf59f967b45effb96fb6ead20093794b7e722e5`
- The remote branch list was inspected. It contains `main`, `sync/full-scratch-v1-r12d-2026-11-08`, `integration/stake-engine-skills-2026-11-09`, and this release-integration branch. No additional remote branch containing the missing canonical Math source was found by the repository recovery work.
- `main` and existing candidate branches were not changed; no force push was performed.
- Full Scratch V1 and historical `dist/`/`qa/` recovery directories were read-only sources. Existing Math archives, Books, LUTs and audit artifacts were not overwritten.

## Canonical Math source recovery

The original raw user Math JSON dated 2026-09-27 and its original bytes remain unavailable. The retained RC10 recovery record says the original raw message body was not returned by prior-conversation retrieval. Its search covered 410 ZIP archives and 65,321 text/JSON/Markdown entries without recovering the original Math JSON or source arrays.

The recovery worker compared historical RC3–RC10 and Exact3 revision candidates. All compared candidates contain the same seven Math payload files with identical SHA-256 values. A second recovery pass found six later V52.8 Math audit ZIPs (R12/R13/R26/R37/R44/R45); all six also contain the exact same seven payload hashes. Version labels and later audit reports therefore do not represent regenerated or corrected Math.

Historical archive identities:

- RC10 Math ZIP: `5a7aaa4c51955efedb60c70d92704861f4439c591c084c65b13c9b65ac43e94c`
- RC10 source-evidence ZIP: `c7104a5f989fca82f7757befd5d90032fd1a4708d3fcf2b339fcfd64f30397ca`
- Provenance supplement: `432c9eb84b089d502dc592872f8f86c6f5adba27f933a20ad511bf18c6c57141`
- R8 partial `generator_input_manifest.json`: SHA-256 `00f428170c8988627471b082b124586afc48f788a3d08277570af3055745d47a`
- R8 historical semantic audit: SHA-256 `cb2b6e6213b6f51cc78d75a9db0e234278eb3c2d5ac04e1044040649f968e083`
- RC10 source recovery evidence: SHA-256 `16753d6be2ce12d096018f7af7ba82b3d2e77d8a136900d062b1dea83734c5ed`

The canonical 58-field manifest is absent (58/58 canonical fields unavailable). The R8 partial manifest is explicitly `PARTIAL_EVIDENCE_ONLY_NOT_CANONICAL_OR_APPROVED`; 44/58 fields are missing, source references do not resolve from its extracted root, and it contains no complete `publish_artifacts` declarations.

### Historical Books/LUT findings

Across the historical package, 300,000 Books and 300,000 LUT rows were parsed. Ordered IDs and `payoutMultiplier` values match for all three modes. This proves only internal package parity, not correct inputs, current game semantics or Provider approval.

All 14 historical candidate versions share these payload hashes:

| File | SHA-256 |
|---|---|
| `books_BASE.jsonl.zst` | `6de7a9c8d47da103803f2508d316cd61d0adc44917eeae361ad00ff2b93040a2` |
| `books_MAGICBUY_V36.jsonl.zst` | `c3d9417a6495ab25fa4806986fd3be82b1184169927f7ca184e6beba8994cbec` |
| `books_EPICBUY_V37.jsonl.zst` | `cd84aa1291535f04d2294309b655a522b17529336d2f8f877705f085f193c20f` |
| `lookUpTable_BASE_0.csv` | `b97c65f8936bfdaa818bc0e5432f9be13393a7ca9abecc44b531c9ed49a6e8f6` |
| `lookUpTable_MAGICBUY_V36_0.csv` | `04257b4bbeefbd5729d75a39f15b812a40e177672c4588daa5fb45eb30fe917b` |
| `lookUpTable_EPICBUY_V37_0.csv` | `826df2e3bc4959a865e4293d0d645145656789a98ee7f0ab2356c89ac346e126` |
| `index.json` | `1c9dcf4915a3899a35dc970b1c0f8bc5f5f09c4feb3d387cf5dc4461859ac2dd` |

Current user-contract incompatibilities confirmed by re-reading the old BASE Books. The historical board scan used the archived decoder assumption that numeric symbol ID `1` is Lotus Scatter; the original symbol-ID map is not present in the recovered Math archive, so the board-count partition remains diagnostic rather than authenticated source authority:

- Under that decoder assumption, 1,095 four-Scatter Books start 10 Free Spins; current authority requires 12.
- Under that decoder assumption, 72 five-Scatter Books start 10 Free Spins; current authority requires the embedded `EPICBUY_V37` sequence inside the already-paid BASE round, no second debit/Play, BASE settlement.
- These 1,167 Books cannot be reused under the current Scatter contract. Independently, every one of the 8,475 historical BASE `freeSpinStart` events declares 10 spins, which is incompatible with the current 4-Scatter award and 5-Scatter embedded-EPIC contract.
- 1,694 BASE Books contain historical `retrigger` events; retrigger remains fail closed.
- BASE `finalWin.amount` uses mixed observed units: 87,783 records match `amount × 100 = payoutMultiplier`, while 12,217 match `amount = payoutMultiplier`.
- The historical BASE LUT has 45,235 payout-increment violations against the pinned SDK rule.
- Historical BASE symbol IDs are numeric while Buy-mode Books use symbol strings; the mapping is absent from the archive.
- Historical index prices are BASE ×1 / MAGIC ×100 / EPIC ×100. EPIC ×100 conflicts with the current user requirement ×500.

### Later V52.8 Math audit candidates — same payload, more diagnostics

The six later archives and their ZIP SHA-256 values are:

- R13 current Math audit: `53125f72712a86bb5d550623058c8bc06f3a6a79f69ed1a5d50a11d68387a656`
- R37 independent Math SDK audit: `59f4cf61a517fcc12abf68c3c66de63f340eeab80857d1a4141099f687debeaf`
- R26 Math independent audit: `db4c3f59ffe93c09e6383e39239c0146673107c975f2155f368d625dc63eb92d`
- R12 Math sample evidence: `836b0a1e92139be199f7d0ce6d6a1f0c7f825b378a1b192f65212d49564da80d`
- R44 persistent-settlement Math audit: `0dccc77efadad197cb7874f269363045664c136dd6445c0d66057d9942186e54`
- R45 settlement-guard cross-mode audit: `ffcd73b81035c3a83fe43297d1ea350a77494ec2a17f3bf52a420f8d4b7c795d`

All six contain byte-identical BASE/MAGIC/EPIC Books, LUTs and `index.json` to the V51.2/RC10 payload. The R45 audit independently verifies 100,000/100,000 Book-to-LUT ID/payout mappings per mode, a 10^12 weight sum per mode and no negative/zero weights. It explicitly states that this is not official RNG/SDK or production distribution certification.

Historical weighted distribution metrics (not current approved Math):

| Mode | Cost in old index | Historical RTP | Variance of return multiple | SD | Max payout | Max-win probability | Feature frequency (weighted) |
|---|---:|---:|---:|---:|---:|---:|---:|
| BASE | ×1 | 96.50% | 1,314.0310658244 | 36.2495664226 | 50,000× base bet | 1×10⁻⁷ (1 in 10M) | 0.1089273967% |
| MAGICBUY_V36 | ×100 | 96.50% | 6.2509400826 | 2.5001880095 | 50,000× base bet / 500× purchase | 1×10⁻⁷ | 100% |
| EPICBUY_V37 | ×100 | 96.50% | 8.0635819229 | 2.8396446825 | 50,000× base bet / 500× purchase | 1×10⁻⁷ | 100% |

The BASE feature frequency is the weighted probability of any historical `freeSpinStart` Book, calculated by joining each Book ID to its LUT weight (8,475 feature Books, total weight 1,089,273,967 of 1,000,000,000,000). It is not a current 3/4/5-Scatter frequency. Both Buy modes have `freeSpinStart` in all 100,000 Books and every historical event declares 10 spins.

Conditional arithmetic if the old EPIC payout distribution were left unchanged but its cost denominator changed from ×100 to the user-required ×500: RTP would be 19.30%, variance 0.3225432769, SD 0.5679289365, maximum payout 100× purchase cost, and expected net result −403.5 base-bet units per purchase. This is a diagnostic showing that changing only `index.json` cannot preserve 96.50%; it is not an approved EPIC distribution or a proposal to use the old data.

The historical audit reports 96.50% weighted RTP under the old index-cost and hundredths-unit assumptions for all three modes. That is not current RTP certification. In particular, the old Buy-mode mean was computed at ×100; simply applying an ×500 EPIC cost to unchanged historical payouts would change the arithmetic result to 19.30%, not preserve 96.50%. Neither value is an approved current EPIC RTP. No distribution or payout was edited to force a target.

The Math builder's actual generator execution remains unavailable because the canonical generator source is absent. The builder can assemble and verify already generated, hash-bound outputs; it cannot recreate source Math from Books/LUT/index.

### Math builder hardening

The previous builder treated any non-empty `*.approval_reference` string as sufficient. That was not an authentication check. The builder is now hardened:

- It requires a detached Ed25519 Provider approval record.
- The signed record binds the exact canonical manifest core and every per-field approval reference.
- It explicitly approves the 96.50% RTP target, 50,000× max-win target, EXTREME_HIGH volatility, BASE Scatter contract, and BASE/MAGIC/EPIC ×1/×100/×500 multipliers.
- Its public-key fingerprint must match the independently supplied `GANESHA_PROVIDER_MATH_TRUSTED_KEY_SHA256` environment trust anchor.
- A missing trust anchor, unsigned record, changed approval reference, invalid signature or wrong public key blocks the build.
- The 58 canonical fields remain unchanged. Test-only ephemeral keys are used only inside unit tests; no test key or fake approval is present in project release evidence.

This hardening does not supply the Provider's actual key or approval. The current partial manifest still fails preflight.

## Front R7 Engineering Preview

R6 was preserved. R7 was generated after correcting the 6+ Scatter error text; it remains a non-financial Engineering Preview.

- Path: `artifacts/FRONTEND_BUILD_OFFLINE_20261109_R7/`
- Files: 19
- Total bytes: 348,988
- Tree SHA-256: `d4012cb7c0c8b4741af9239cee2b5e0f6b3e7cdb3e16d9d369fb3413dfb5ef64`
- `manifest.json` SHA-256: `c500d52477486f28db8eba45482d897fe857ecbbc9720f58e9180b233ba09bc7`
- Integrity report SHA-256: `587996a0dbe6a0c6e814d67df5a5b839dec02d3a226d66f78e8eb1a0b7fb2766`
- `index.html` SHA-256: `ca5b4dd67d7db92b070bb2ea168dff7de7f7b582cc2ca0ae04f89df3511ffd67`
- Bundled SDK adapter SHA-256: `28f3f8b35887a2cd7caa48a81efc12897a30360d24f11d24faf40748c07f69bb`
- Vite 6.4.5 build: PASS; 8 symbols and 4 audio assets.
- `node tools/verify_frontend_build.mjs artifacts/FRONTEND_BUILD_OFFLINE_20261109_R7`: PASS.
- `python3 tools/verify_stake_package.py frontend-dir ...R7`: BLOCKED by design because the manifest declares Authenticate READ_ONLY and Play/Event/EndRound/Wagering/Bonus Buy unavailable.

R7 integrity binds its file hashes to the pre-edit branch HEAD `aaf59f967b45effb96fb6ead20093794b7e722e5` and records `source_worktree_dirty=true`. It is not a clean-clone exact-HEAD release build.

## Provider / RGS contract

The pinned npm SDK is `stake-engine@0.1.32` (ISC; lockfile integrity recorded in `package-lock.json`). The SDK request shapes are known:

- Authenticate: `/wallet/authenticate` with `{sessionID, language}`.
- Play: `/wallet/play` with `{sessionID, mode, amount}`.
- Event: `/bet/event` with `{sessionID, event}`; `event` is an opaque string.
- EndRound: `/wallet/end-round` with `{sessionID}`.

The SDK has no operation-level idempotency token for Play or EndRound, no dedicated Wagering or Bonus Buy method, and no documented game-specific Event payload schema. Its normalized Authenticate state omits the documented per-mode `gameModes`/`costMultiplier` data. `DisplayAmount` dividing by 1,000,000 is display formatting, not proof of the payout-unit contract.

The local adapter defaults financial lifecycle off. Enabling it requires four trusted verifiers for round-state replay, completion, ambiguous Play ownership and Event acknowledgement. These must be Provider-backed. Local mocked-fetch tests do not prove production Wallet semantics, exactly-once settlement, Provider mode support or transport-loss reconciliation.

## Quality, license and operations evidence

- Historical R9 asset audit: 177 media files; 0 redistribution-cleared; 177 unresolved; no LICENSE/NOTICE/ASSET_PROVENANCE rights package.
- Historical third-party inventory: 66 npm and 10 Python packages. Metadata/integrity is inventory evidence, not full redistribution clearance. Project LICENSE remains unselected.
- Historical SBOM completeness and scanned npm/Python dependency vulnerability audit passed for their recorded R12 scope; they are not a signed exact-HEAD release attestation.
- Current project security contact, public terms, hosted privacy/operations, legal operator/jurisdiction, age/self-exclusion/limits, full WCAG 2.2 AA, physical-device acceptance and production RGS are not proven.
- Chrome was present but no remote-debugging listener was available on the inspected ports; the current R7 accessibility reflow/assistive-technology test was not run. Old accessibility evidence was not copied and represented as current.
- Local signing tools require OpenSSL 3, but the active system `openssl` is LibreSSL 3.3.6. No trusted release-signing key was available.

## Release Gate snapshot

The current complete 24-check release gate snapshot is `BLOCKED`: ten checks passed and fourteen remain blocked. Passing evidence-integrity checks do not clear approval or rights gates. The current snapshot is `/tmp/ganesha_release_gate.json` from 2026-11-09 11:02 JST; it is local diagnostic output, not a release artifact.

Blocked checks:

1. `project_license`
2. `asset_redistribution_rights`
3. `build_reproducibility`
4. `local_accessibility_reflow`
5. `local_worktree_reproducibility`
6. `signed_release_manifest_and_sbom`
7. `ci_workflow`
8. `security_contact_and_public_terms`
9. `hosted_privacy_and_operations`
10. `accessibility_and_physical_devices`
11. `canonical_math_and_provider_approval`
12. `production_rgs_wallet_contract`
13. `stake_studio_approval_and_activation`
14. `real_money_legal_and_rg_controls`

## Verification performed in this continuation

- Full `make test` after Math Builder approval hardening: Python `Ran 463 tests ... OK`; Frontend/SDK/RGS Node suite `33/33` PASS; aggregate `496/496` PASS, exit code 0. The three tests added since the prior 493-test baseline exercise the Provider approval trust-anchor/signature boundary.
- Focused Python tests before the approval hardening: 19 Math Engine, 44 Game Presentation, 17 Game Runtime, 7 Math Builder; all passed.
- Focused Node tests: 33 Frontend RGS/SDK/presentation/lifecycle tests passed with the shared Full Scratch `node_modules` symlink present. The symlink was removed after the run.
- Math Builder approval-hardening suite: 10/10 tests passed, including missing trust anchor, tampered approval reference, wrong trust key, signed test fixture, package build, no-overwrite and multiplier mismatch.
- R7 Vite build and Node build verifier: PASS.
- Stake package verifier: BLOCKED for the explicitly disabled financial capabilities.
- Current Math preflight: BLOCKED; the partial R8 manifest remains 44/58 fields missing and lacks a signed Provider approval bundle.

`python3 tools/verify_stake_package.py frontend-dir artifacts/FRONTEND_BUILD_OFFLINE_20261109_R6`: BLOCKED; 19 files, READ_ONLY Authenticate only, Play/Event/EndRound/Wagering/Bonus Buy unavailable.

The same Stake package verifier on R7: BLOCKED for the same declared non-financial capabilities. The independent offline build verifier for R7 returns PASS (19 files, 8 symbols, 4 audio assets); this is build integrity only.

The current `qa_release_gate.py` snapshot: 10/24 PASS and 14/24 BLOCKED. Blockers include project/asset rights, current reproducibility evidence, accessibility, signed release provenance, hosted operations, canonical Math/Provider approval, production RGS, Stake Studio approval and legal/RG controls.

## Submission record

- Math folder generated: NO.
- Front folder generated: NO (R7 is an offline build directory, not a release `front/` package).
- Stake Studio Math upload: NO.
- Stake Studio Front upload: NO.
- Provider Math approval: NO.
- Production RGS verification: NO.
- Stake game-specific approval/activation: NO.
