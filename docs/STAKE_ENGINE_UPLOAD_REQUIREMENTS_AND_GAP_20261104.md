# Stake Engine Upload Requirements and Current Gaps

**Inspection date:** 2026-11-04
**Project:** Ganesha and The Magic — Full Scratch V1
**Workspace HEAD inspected:** `a6e7997e469730f67c10b9f5657c5a1edfbfb2c2` (`main`)
**Disposition:** `NOT_UPLOAD_READY / BLOCKED_FROM_STAKE_RELEASE`

This document consolidates the current Stake Engine publication requirements from official documentation and compares them with this workspace and the two-folder package previously produced. It is a requirements/gap record, not a claim of Stake approval.

## 1. Official references reviewed

1. Math required files: https://github.com/engineio/docs/blob/main/src/routes/faq/math/what-files-are-required/+page.svx
2. Math file format: https://stake-engine.com/docs/math/math-file-format
3. Math quick start: https://stake-engine.com/docs/math/quick-start
4. Math output files: https://stake-engine.com/docs/math/source-files/outputs
5. Math game structure: https://stake-engine.com/docs/math/high-level-structure/game-structure
6. Math overview: https://stake-engine.com/docs/math
7. Frontend SDK: https://stake-engine.com/docs/front-end
8. Frontend getting started: https://stake-engine.com/docs/front-end/getting-started
9. Frontend file structure: https://stake-engine.com/docs/front-end/file-structure
10. Frontend approval communication: https://stake-engine.com/docs/approval-guidelines/front-end-communication
11. General approval guidelines: https://stake-engine.com/docs/approval-guidelines
12. Game replay requirements: https://stake-engine.com/docs/approval-guidelines/game-replay-requirements
13. Stake publication workflow: https://stake.games/blog/what-is-engine

Engine documentation is the controlling technical source. Third-party tutorials and historical project ZIPs are not substitutes for current official specifications.

## 2. What is uploaded

Stake Engine uses **two separate imports** and two approval tracks:

- **Math:** upload the contents of the publication directory containing `index.json`, every referenced lookup CSV and every referenced compressed Books file.
- **Front End:** upload the contents of the assembled static frontend build directory: entry HTML plus every referenced JavaScript, CSS, image, font and other runtime asset.

This is not one combined source-code ZIP. Python modules, tests, local API, SQLite ledger, development server, audit reports and documentation are not substitutes for either upload artifact.

After importing both, use the dashboard Publish Game flow and select both Math and Front End versions, then submit the separate Math and Front End approval requests. Import success is not approval or production activation.

## 3. Math upload contract

For **each game mode**, at least three mutually consistent files are required. All must be in the selected Math upload directory and filenames must match `index.json` exactly.

### 3.1 `index.json`

- Exact, case-sensitive filename: `index.json`.
- Must be at the root of the selected Math upload directory, not one directory deeper.
- JSON object containing a `modes` array.
- Each mode declares `name`, `cost`, `events` and `weights`.
- `events` names the matching `.jsonl.zst` Books file; `weights` names the matching CSV lookup table.
- Every referenced file must exist in the upload root.
- Mode names and cost multipliers must reflect approved product/bet modes. Do not infer or copy costs from historical artifacts.

Illustrative schema only — values and filenames below are not approved for this title:

```json
{
  "modes": [
    {
      "name": "<approved_mode_name>",
      "cost": 1.0,
      "events": "books_<approved_mode_name>.jsonl.zst",
      "weights": "lookUpTable_<approved_mode_name>_0.csv"
    }
  ]
}
```

### 3.2 Lookup table CSV

- One CSV per mode, named exactly as referenced by `index.json`.
- Each row contains three unsigned integer (`uint64`) fields: simulation/result ID, round selection probability/weight, payout multiplier.
- No header row.
- Payout multipliers must exactly match the corresponding Books records. Stake extracts and hashes payout values for verification; mismatches fail verification.
- Weights must be unsigned integers representing the approved distribution. No floating-point values, rounded percentages, negative weights or hand-edited approximations.

### 3.3 Compressed Books `.jsonl.zst`

- One zStandard-compressed JSON Lines file per mode, named exactly as referenced in `index.json`.
- Each uncompressed line is one simulation outcome JSON object.
- Required top-level fields: `id` (simulation number), `events` (ordered event array consumed by the frontend), and `payoutMultiplier` (integer payout multiplier).
- `id` must correspond to the lookup-table row ID.
- `payoutMultiplier` must exactly equal the third CSV field for that ID.
- Events must fully describe the result the frontend is expected to present and match the frontend event contract.
- Upload compressed Books, not Python source, uncompressed debug books or arbitrary JSON.

### 3.4 Required Math directory shape

One mode example:

```text
MATH/
├── index.json
├── books_<mode>.jsonl.zst
└── lookUpTable_<mode>_0.csv
```

For N modes, repeat the Books/LUT pair for every mode and list every mode in the single root `index.json`. No entry may reference a missing or differently named file.

### 3.5 Required Math integrity checks

- Strictly parse `index.json`; reject duplicate mode names and duplicate filenames.
- Verify every reference resolves to a regular file in the upload root; reject nested-path ambiguity and path traversal.
- Decompress every `.jsonl.zst` and parse every JSONL record.
- Validate required fields, integer ranges, unique IDs and ID correspondence between Books and CSV.
- Compare payout multipliers exactly by ID, not merely by aggregate RTP or sorted value list.
- Validate CSV weights as unsigned integers within `uint64` and against the approved distribution contract.
- Independently recalculate RTP, hit rate, variance/volatility, tail and maximum-win frequencies from the exact uploaded artifacts.
- Verify mode costs and mode semantics against signed/approved Math authority.
- Record SHA-256 for inputs and outputs; bind generator version, source inputs, configuration and outputs in a provenance manifest.
- Generate representative Golden Vectors and replay each event sequence through the frontend.

The official Math quick start recommends large simulation sets (100k+ per mode as production-oriented guidance) to improve outcome diversity. This is not a substitute for canonical rules, approved probabilities or exact verification.

## 4. Front End upload contract

### 4.1 Upload artifact

Upload a built/static frontend directory, not the Python source tree. It must contain `index.html`, all bundled JavaScript entry/chunks, CSS and every referenced runtime asset (images, SVGs, fonts, audio, loader/worker/WASM files where applicable). Stake's own frontend SDK is PixiJS/Svelte-based; custom frontends are allowed if they meet the static-file and RGS contract.

### 4.2 Assets and paths

- Every file referenced by HTML, CSS, JavaScript, manifests or runtime asset loaders must exist in the uploaded build.
- Paths must work from the actual hosted base path, not only localhost.
- No broken image, SVG, font, animation, audio or chunk references.
- Official Front End approval guidance states that all images and fonts must be loaded from the Engine Content Delivery Network (CDN). Current local `./assets/...` paths do not prove this requirement is met.
- Use unique visual/audio assets. Assets supplied with Stake's sample web-SDK games are not approved for publication.
- Confirm creator, rights holder, license, modification rights and redistribution/publication rights for every visual/audio/font asset and trademark. An SVG's presence in a ZIP does not establish rights or compliance.
- SVG is an asset format, not a substitute for Math `index.json`. An error mentioning `svg` must be mapped to its exact filename and upload path before classifying it as a missing asset, bad reference or unsupported file handling issue.

### 4.3 Frontend approval checks

Official guidance checks for visual/layout/animation/asset-loading defects, standard UI components and clear game communication, consistency with game rules, mobile usability, mini-player/popout layout integrity, Engine CDN loading for images/fonts, unique assets and IP/copyright compliance. RTP, max-win, feature and Buy claims must not be presented as certified facts unless approved. Paytable, symbols, win presentation and feature transitions must agree with approved Math and Books events.

### 4.4 RGS integration

- Use the actual Stake Engine/RGS session and API integration contract.
- Do not ship development endpoints, localhost URLs, local test APIs, browser-held secrets, fake wallets, mock Providers or hard-coded test outcomes as production integration.
- Validate launch/session parameters, balance, bet selection, play response, end-round/settlement, errors, reconnect/recovery and replay against the current SDK/RGS contract.
- Test the hosted iframe and mini-player, including mobile scaling.
- The present Full Scratch page is intentionally a non-wagering engineering preview with financial controls disabled. It is not an RGS-connected playable frontend.

## 5. Game and approval policy constraints

The official general approval guidelines state that Engine games are **stateless**: each bet must be independent of previous outcomes. The published guidelines prohibit jackpots, gamble features, continuation and early cashout options.

- The proposed terminal **50,000× Divine Jackpot** conflicts with the published stateless-game restriction as currently described. Do not submit it unless Stake provides explicit written clarification/exception and the mechanic is redesigned to comply.
- Remove or obtain explicit clearance for any mechanic that carries state/value across separate bets, depends on a previous result, continues a prior bet, or offers gamble/early cashout.
- Free Spins belonging to one independently resolved bet must be represented within that round's static Books/events, not as unbounded cross-bet continuation. Exact feature behavior still requires approved Math.
- Math and Front End are separately versioned and approved. Changes require the matching version and approval workflow.
- The approval request requires a short game-theme/mechanics blurb for promotional/game-description use.
- Stake may reject or request changes at its discretion; successful import is not acceptance.

## 6. Current Ganesha Full Scratch V1 facts

### 6.1 Workspace/package

- Workspace: `/shared/Ganesha_and_The_Magic_V49_USER_MUSIC/Ganesha_Full_Scratch_V1`.
- Inspected HEAD: `a6e7997e469730f67c10b9f5657c5a1edfbfb2c2`, branch `main`.
- Workspace has uncommitted changes and untracked test/browser evidence. The prior upload ZIP was built from selected working-tree files, not a clean commit snapshot.
- Previous two-folder package: `/Users/Shared/Ganesha_StakeEngine_UPLOAD_MATH_Front_20261104.zip`. Its top-level folder names were `MATH` and `Front`; ZIP integrity passed.

### 6.2 Math — blocked

- Package `MATH/` contains Python source modules (`ganesha/math`, `ganesha/game`, `ganesha/demo`), not Stake static publication files.
- `MATH/index.json` is absent. No `.jsonl.zst` Books or `lookUpTable_*.csv` files are included. Therefore `ERR_MISSING_FILE: index.json` is expected and this is not a valid Stake Math upload.
- Historical V46/RC10 artifacts contain an `index.json` and some Books/LUT files, but they are research/historical artifacts and are not automatically canonical or approved for this Full Scratch V1 build.
- `docs/authority-boundary.md` records that the raw user-supplied 2026-09-27 Math JSON is unavailable in the accessible workspace; exact reel strips, paylines and paytable cannot be authenticated from raw bytes.
- User-authoritative rule: exactly 3 Lotus Scatter on the initial BASE reveal awards exactly 10 Free Spins. 4/5 alternative behavior, 6+ behavior and retrigger behavior are unspecified. Do not invent them.
- Current eight-symbol draft adds Modak and Chakra beyond the six-symbol original inventory; source/approval lineage is not established.
- Draft-005 probability weights, RTP calculations, 57.766×/112.420× Buy costs, 25/50 Buy spin counts and jackpot assumptions are quarantined research, not approved Math.
- `math-audit` deliberately fails closed because canonical inputs and Provider Golden Vectors are missing.

### 6.3 Front End — not a Stake-ready build

Current source tree:

```text
frontend/
├── index.html
├── app.js
├── style.css
└── assets/
    ├── a_icon_v14.svg
    ├── chakra_icon_v14.svg
    ├── elephant_icon_v14.svg
    ├── ganesha_temple_scene_v14.png
    ├── ganesha_wild_v14.svg
    ├── k_icon_v14.svg
    ├── lotus_scatter_v14.svg
    ├── modak_icon_v14.svg
    ├── mouse_icon_v14.svg
    └── ASSET_PROVENANCE.json
```

- Eight SVG symbol files and one PNG scene asset exist. The prior upload's `Front/assets/` contains these files; they are not missing from that package.
- Current `frontend/index.html` references `./config.js`; the previous upload copy removed that line. `app.js` reads `window.GANESHA_CONFIG` and disables all wagering controls. Removing the script avoids a missing local config request but does not implement Stake RGS integration.
- Current page explicitly identifies itself as an unofficial non-wagering engineering preview. It contains a scripted/static board and local demo/runtime fixtures, not a finished Stake frontend.
- No project license is selected and art creator/redistribution rights are unverified (`docs/license-status.md`, `frontend/assets/ASSET_PROVENANCE.json`). Publication is blocked pending rights clearance.
- Relative local asset paths have not been migrated to or verified on Engine CDN.
- The 96.50% RTP and 50,000× max-win are marked unverified targets, not certification; they must not be represented as approved facts.

## 7. Exact file patterns for a future upload

### Math directory

For every approved mode, at minimum:

- `index.json`
- `books_<mode>.jsonl.zst`
- `lookUpTable_<mode>_0.csv`

No mode may be published until its canonical source, probability model, event rules, payout calculation, cost multiplier and approval are established.

### Front End directory

- `index.html`;
- all built JavaScript bundles/chunks and runtime manifests;
- all CSS bundles;
- every referenced SVG/PNG/WebP/JPEG image;
- all required fonts and audio;
- any required loader/worker/WASM files;
- every asset path validated against Engine CDN hosting and actual RGS launch context.

The current three source files plus assets are a preview source tree, not a validated production build directory.

## 8. Supporting evidence documents to prepare

These are project/provider evidence records, not necessarily files uploaded into Math or Front End imports:

1. **Canonical Math source package:** original user JSON, raw-byte SHA-256, symbol inventory, reel strips, paylines, paytable, stop/probability models, feature and Buy rules.
2. **Math authority/approval record:** Stake/Provider-approved rules, mode names/costs, max win, feature constraints, RTP target and sign-off.
3. **Generator provenance manifest:** generator repository/version/commit, dependencies, RNG/seed derivation, config hashes, input hashes and output hashes.
4. **Math verification report:** independent exact RTP/variance/hit-rate/tail calculations, payout/weight consistency, ID uniqueness, decompression/schema checks and per-mode statistics.
5. **Golden Vectors:** Provider-approved vectors for normal loss, normal win, Scatter trigger, Free Spins, Wild behavior, maximum payout and each approved Buy mode.
6. **Event-to-frontend contract:** every event type/order/payload, board shape, payout semantics, feature state and animation mapping.
7. **Frontend acceptance report:** desktop, mobile, landscape, mini-player/popout, loading/error/reconnect/replay, broken-asset, accessibility and RGS integration checks.
8. **Asset rights schedule:** file, creator, rights holder, license, modification/redistribution/publication permissions and evidence reference for every asset/font/audio/trademark.
9. **Game description blurb:** concise theme/mechanics summary consistent with approved game rules.
10. **Approval submission record:** exact Math/Front End version IDs, source hashes, submitted versions, reviewer feedback and written acceptance.
11. **Release manifest:** hashes of exact upload directories, toolchain/build identifiers, test results and sign-off; keep separately from upload contents.

## 9. Pre-upload checklist

### Math

- [ ] Canonical source JSON/raw bytes recovered and SHA-256 recorded.
- [ ] All game rules and modes explicitly approved.
- [ ] Stateless-game restriction reviewed; prohibited mechanics removed or cleared in writing.
- [ ] Generator and probability inputs approved and reproducible.
- [ ] `index.json` at upload root.
- [ ] Every mode's `.jsonl.zst` Books file present and decompresses.
- [ ] Every mode's lookup CSV present and valid.
- [ ] IDs and payout multipliers match exactly between Books and CSV.
- [ ] Per-mode RTP, hit rate, variance and tail metrics independently verified.
- [ ] Golden Vectors pass.
- [ ] All upload file hashes recorded.

### Front End

- [ ] Production build completed; upload directory is static and self-contained.
- [ ] Every referenced file exists and loads from Engine CDN.
- [ ] No localhost, development config, test fixture or mock Provider dependencies.
- [ ] Stake RGS session, play and settlement integration tested.
- [ ] Every Math event is rendered correctly.
- [ ] No unsupported/unapproved feature or payout claim is displayed.
- [ ] Mobile and mini-player/popout layouts pass.
- [ ] Unique assets and complete publication rights are confirmed.
- [ ] No console/network errors or broken assets.
- [ ] All frontend file hashes recorded.

### Submission

- [ ] Import Math directory contents.
- [ ] Import Front End build contents separately.
- [ ] Publish both versions in the dashboard.
- [ ] Submit Math approval and Front End approval.
- [ ] Include the game description blurb and required review scenario/event IDs.
- [ ] Retain written approval; do not equate successful import with production acceptance.

## 10. Current go/no-go

**NO-GO for Stake Engine upload at this time.**

The previous ZIP is a two-folder engineering-source handoff only. Its `MATH/` folder is Python source, not a Stake Math publication directory. The missing `index.json` is a real structural defect; adding a stale `index.json` alone would create further missing-reference errors. The `Front/` folder contains the SVG/PNG files, but its preview-only code, local configuration assumptions, relative asset paths, absent CDN validation, unverified asset rights and lack of actual RGS integration mean it is not a production Front End upload either.

The next valid action is to recover and approve canonical Math inputs and game rules, resolve the stateless-game/jackpot conflict with Stake, generate and independently validate Books/LUT/index as a matched set, then build and test a real RGS-connected static frontend with cleared assets. Do not fabricate Math files or reuse historical Books/LUT/index files as if approved.

## Official-source notes

- Math requirements specify the three required files and exact payout matching between CSV and Books.
- Math quick start places publication files under `library/publish_files/`; the contents of that directory are imported for Math.
- Math outputs distinguish uncompressed debug Books from compressed Books uploaded to and consumed by RGS.
- Front End approval requires unique assets, correct mobile/mini-player presentation, no broken assets/animations, and images/fonts loaded from Engine CDN.
- General approval guidelines state the stateless-game rule and restrictions on jackpots, gamble, continuation and early cashout.
- Stake's publication guide describes importing Math and Front End separately, publishing both, and submitting both approval requests.


## Addendum — official SDK, audio and current gate status (2026-11-04)

- Frontend now pins official `stake-engine@0.1.32` (Beta) and `vite@6.4.5`. The adapter performs read-only `Authenticate()` and validates balance, currency, bet levels, jurisdiction flags and active-round metadata. No `Play`, `EndRound` or `Event` method is exposed. The only browser RGS test uses a mocked response.
- The frontend includes four original deterministic procedural WAV effects and an accessible sound on/off control. Assets are served only through explicit allowlisted routes. The generated audio is reproducible, but project license selection and rights to redistribute the existing art assets remain outstanding.
- Vite refuses a production build if `frontend/config.js` contains local preview flags. `dev_server.py` uses a unique temporary SQLite file and restores the tracked fail-closed config at shutdown.
- A separate reference evaluator has been compared against the quarantined draft evaluator across all 371,293 five-reel stop vectors: BASE 367,000 determinate vectors + 4,293 correctly blocked 4+ Scatter vectors; FREE_SPINS 340,000 determinate vectors + 31,293 correctly blocked retrigger vectors; zero mismatches. These are combinatorial counts under draft strips, not canonical probabilities or RTP evidence.
- G1–G7 remain BLOCKED/UNVERIFIED as recorded in `docs/release-gates.md`; no external upload, Provider approval or activation occurred.

- Wallet contention addendum: a pre-fix 24-worker test reproduced `database is locked`; WAL is now initialized once and local `BEGIN IMMEDIATE` has bounded 30-second backoff. The post-fix 24-worker/1,200-round local SQLite run passed with zero errors and exact balance/replay reconciliation (53.03 rounds/s, p95 1,075.069 ms, 918 retries). This does not establish production or distributed exactly-once semantics and does not close G6.

## Official contract verification addendum — 2026-11-04

The following primary sources were retrieved during this continuation. These are the contract references used by `tools/verify_stake_package.py`:

- Math upload file contract: `engineio/docs`, `src/routes/faq/math/what-files-are-required/+page.svx` (retrieved blob SHA `72352d63723b8364f6b59812fe98bc21acf367b8`). Requires a non-empty `index.json` mode list; every mode references one `.jsonl.zst` Books file and one CSV LUT; every Books record contains `id`, `events`, and `payoutMultiplier`; CSV payout multipliers must match Books exactly.
- Math SDK verifier: `engineio/math-sdk`, commit `141b4e89065ac4400769709a919259a923430c4d`; `docs/rgs_docs/data_format.md` (blob SHA `67161ddfa4ec7c014fc67717f827ab7b7c42299e`) and `utils/rgs_verification.py` (blob SHA `d9a4d7d368410f08ea92441b22d8e627b3096075`). The executable verifier parses every CSV line as three numeric fields (no header row), requires integer weights/payouts, non-negative weights, a positive uint64-bounded weight sum, and payout values in zero-or-multiples-of-10 increments. Books are Zstandard JSONL and require `id`, `events`, and `payoutMultiplier`; the verifier compares the complete payout arrays in order. This SDK verifier also declares 96.0%–96.7% RTP submission limits, while the current general approval Math page states 90%–98%. Treat this as a versioned official-source discrepancy; do not silently choose a threshold for certification. The project's 96.50% value remains a design target, not a measured result.
- General build contract: `engineio/docs`, `src/routes/faq/getting-started/how-do-i-start/+page.svx` (blob SHA `de65a2cdc2a7dfb446bfbdf32974eefaec9213cf`). The submitted frontend must be fully static HTML/CSS/JS/assets, with no backend or server-side rendering, and is hosted on the Stake Engine CDN.
- Approval restrictions: `src/routes/docs/approval/+page.svx` (blob SHA `97201e6d21319287f0857eb271ba028f4c815d4e`). Stake games are stateless; jackpots, gamble features, continuation and early cashout are prohibited. This reinforces the local engine's fail-closed rejection of jackpot mechanics.
- Frontend approval: `src/routes/docs/approval/frontend-requirements/+page.svx` (blob SHA `26970092293fb328548ef68c142d3b735d5ac143`). Requires unique assets, no broken assets/animations, mobile and mini-player support, CDN-hosted images/fonts, accessible game rules, per-mode RTP/max win and paytable, usable bet levels, balance and win display, sound-off control, and spacebar bet mapping.
- RGS approval: `src/routes/docs/approval/rgs-requirements/+page.svx` (blob SHA `04b2ce8ec9f7b3872d9cdae100a2b9555ddef482`). Requires dynamic use of launch `rgs_url`; no hardcoded external RGS origin; strict static-only XSS policy.
- RGS API endpoints: `src/routes/docs/api/authenticate/+page.svx` (blob SHA `64f3e7100ecc870417df2c92ca01ed454c479e52`), `play` (`5e8dc4b59ec311b8525656a66fb3ac2295c94553`), `end-round` (`cd8ec5adb207cda0916f432cc5a074b317720867`) and `event` (`05c20f466eb18c45f771bce8eec57359275791c7`). Routes are `/wallet/authenticate`, `/wallet/play`, `/wallet/end-round`, and `/bet/event`. Authenticate supplies bet configuration and active-round state. Zero-payout rounds are automatically completed; End Round is required only for non-zero payouts. The RGS Math SDK documents six-decimal monetary precision.
- The pinned `stake-engine@0.1.32` SDK's `src/client.ts` normalizes `config.jurisdiction` to `jurisdictionFlags` for the adapter. The frontend's current Authenticate response validator is consistent with that SDK normalization; it is not a raw-wire schema.

### Machine-verifier implementation and current results

`tools/verify_stake_package.py` now provides independent source-directory and final-ZIP checks for Math and Frontend. ZIP validation checks entry paths, duplicate names, symlinks and CRC, extracts to a temporary directory, and reruns the relevant full directory validator. The Math validator rejects empty modes, path traversal, malformed/duplicate IDs, malformed uint64 rows, invalid Zstandard JSONL, and any mismatch in the complete ordered Books/LUT ID or payout arrays. The Frontend validator checks root `index.html`, static-only file types, case-sensitive local HTML/CSS/JS references, external origins, required launch parameters and the project's own engineering capability manifest. SDK symbol presence alone is not treated as proof that the game invokes Play/EndRound/Event.

Focused verifier tests: `PYTHONPATH=src python3 -m unittest tests.test_stake_package_contract -v` — 8/8 PASS. These tests create disposable synthetic fixtures only inside temporary test directories; no synthetic Math data is written to candidate packages.

Measured package results:

- Engineering `MATH/` source directory: BLOCKED, `ERR_MISSING_FILE: index.json`.
- Existing `MATH.zip`: BLOCKED, `ERR_MISSING_FILE: index.json` after ZIP extraction and revalidation.
- Current `frontend-build/`: static entrypoint, 19 files, local references and launch parameter literals validate; overall BLOCKED because the engineering manifest explicitly declares Authenticate-only and `play`, `end_round`, `event`, wagering and Bonus Buy unavailable. The SDK bundle contains endpoint strings, but this is not proof of game-level invocation.
- Existing `FRONT.zip`: BLOCKED because `index.html` is not at the extracted package root.

The checker is a local contract verifier, not a Stake importer or an approval oracle. A PASS would establish only the checks implemented from the cited sources. It cannot establish canonical Math authority, asset rights, CDN deployment, actual Stake RGS behavior, jurisdiction approval or Provider acceptance.


## Canonical index build and RC10 R8 full semantic audit — 2026-11-04

A new fail-closed builder is available: `tools/build_stake_math_package.py`. It consumes the recovered 58-field contract, requires every field and its hash-linked file, explicit approval references, an exact three-mode publish-artifact map with SHA-256 for each Books/LUT file, and `status=CANONICAL_SOURCE_VERIFIED`. It creates `index.json` from those explicit inputs only; no mode, price, filename, or probability is guessed. It then runs the Math directory verifier and extracts/re-runs the ZIP verifier. Existing destinations are refused. Focused tests cover the complete temporary fixture path, missing 58 fields, partial status, hash mismatch, unsafe paths and no-overwrite behavior.

R8 partial manifest preflight: status BLOCKED; 44/58 fields absent in the partial object, three file paths unresolved from the manifest root, no `publish_artifacts` declaration, and explicit noncanonical status. The canonical source manifest itself is absent (58/58 required fields missing).

Read-only R8 archive audit (`artifacts/RC10_R8_HISTORICAL_MATH_AUDIT_20261104.json`): 300,000 Books records and 300,000 LUT rows; ordered IDs and payout values match in all modes; 0 event-index or board-shape errors. The pinned SDK payout increment rule is violated by 45,235 BASE LUT rows. BASE Books contain 1,694 `retrigger` events. Within BASE, 87,783 `finalWin.amount` values match `payoutMultiplier / 100`, while 12,217 match raw `payoutMultiplier`; Buy modes use raw `payoutMultiplier` for all 200,000 `finalWin` events. This is an event payout-unit inconsistency, even though `baseGameWins + freeGameWins` matches the LUT scale. The weighted mean under the historical index costs computes to 96.50% in each mode only under the assumed hundredths-of-base-wager unit; this is an observation, not RTP certification, because provenance, unit semantics and approval are not established.

The R8 archive's MAGIC Books file is **3,311,622 bytes**, not 3,316,622 bytes; the exact size and SHA-256 are bound in the recovery evidence.
