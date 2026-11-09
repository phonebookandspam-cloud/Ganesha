---
name: ganesha-stake-engine
description: Project-specific end-to-end engineering workflow for Ganesha and The Magic on Stake Engine. Use for any game, math, frontend, RGS, wallet, replay, QA, or release change.
---

# Ganesha Stake Engine Engineering Skill

## Authority order

1. User-approved Ganesha game rules and explicit corrections.
2. Provider-authoritative contracts, approved canonical Math inputs, and exact pinned official Stake Engine SDK/Math SDK versions.
3. Existing project contracts, tests, release gates, and immutable evidence.
4. Official Stake Engine documentation and source repositories.
5. Third-party clients, skills, examples, blog posts, and topic listings (reference only).

A lower-ranked source never overrides a higher-ranked contract. Record unresolved conflicts; fail closed rather than infer a rule.

## Mandatory workflow

1. Establish the exact repository, branch, commit, dirty state, and source manifest. Never reset, clean, checkout over, or overwrite a dirty user workspace.
2. Read `docs/authority-boundary.md`, `docs/game-state-event-contract-v1.md`, `docs/rgs-wallet-contract-v1.md`, `docs/MATH_AUDIT_PINNED_SDK_20261107.md`, `docs/SCATTER_FEATURE_CONTRACT_20261107.md`, and `docs/release-gates.md` before changing relevant layers.
3. Write the invariant and the failing regression test first. Preserve unrelated evidence and historical candidate outputs.
4. Validate Math/Books/LUT/index and provider contract before changing frontend playback or animation.
5. Keep game outcomes server/Math-authored. Frontend consumes validated event/state data and must not recompute payout, RNG, symbol stops, or feature awards.
6. Validate RGS lifecycle and ambiguous transport recovery. Never automatically retry a dispatched financial mutation whose commit status is unknown.
7. Run focused tests, then the complete relevant suite and release gate. Report exact commands, exit codes, counts, and unrun checks.
8. Update evidence/manifests only after the underlying source and tests are final. Never claim Provider approval or upload readiness from local mocks.

## Stake Engine upload boundary

- The only Stake Engine upload payload roots are the two deliverable folders: `MATH/` and `Front/` (the Math and Front End packages). Treat their contents as two separately versioned/imported deliverables, even if an owner creates a convenience archive containing both top-level folders.
- `MATH/` contains only the Stake publication files: root `index.json`, every referenced compressed `.jsonl.zst` Books file, and every referenced lookup `.csv` file. No Python generator/source, audit output, tests, docs, SKILLs, local databases, or development tooling belongs inside this upload folder.
- `Front/` contains only the assembled static Front End build: root `index.html` and all referenced runtime JS/CSS/assets/fonts/media/manifest files. No source-only tests, Python services, local API, SQLite wallet, docs, SKILLs, or development tooling belongs inside this upload folder.
- Agent skills, source code, QA, SBOM, provenance, audit evidence, release manifests, and CI files remain in the engineering repository and are used to build/verify the two deliverables; they are not uploaded to Stake Engine.
- Before any upload, independently verify the exact `MATH/` directory/ZIP and `Front/` directory/ZIP, their root layout, all transitive asset references, hashes, and the release gates. A combined convenience ZIP does not replace the two separate Studio imports or approvals.
- Never add a third upload folder or place project-root engineering files beside the two deliverable roots in an upload archive. Do not upload while `BLOCKED_NOT_UPLOAD_READY` remains.

## Immutable Ganesha game constraints

- MAGIC BUY cost multiplier is 100x; standalone EPIC BUY cost multiplier is 500x.
- BASE five-Scatter embedded EPIC feature is not a standalone EPIC purchase: it remains a BASE round, performs no second debit and no second Play, and settles as BASE.
- 3 Scatter awards 10 Free Spins; 4 Scatter awards 12 Free Spins.
- 5 Scatter stays disabled unless the exact Provider-authoritative embedded EPIC payload and BASE-unit conversion are present and verified.
- 6+ Scatter and unauthorized retriggers fail closed.
- Never change RTP, distributions, weights, reel strips, Books, LUT, payout precision, or purchase costs using invented or inferred inputs.
- Never merge to `main`, submit to Studio, upload, or publish unless the relevant explicit authorization and all required gates exist.

## Money and multiplier units

Keep these domains separate:

- RGS API money values: integer micro-units, with the current pinned client fixtures and cross-checked client using 1,000,000 units per displayed currency unit.
- Math/Book payout multipliers: integer x100 representation (e.g. 150 means 1.50x).
- Local SQLite ledger minor units: a separate local accounting unit governed by the local contract; do not assume it equals API micro-units.

Conversions must occur at named, tested boundaries with integer-safe arithmetic. Do not apply API scaling to a Book multiplier or Book scaling to a wallet amount. Confirm the active official SDK and Provider contract before relying on any conversion in production.

## Event and state contract

- Use the exact pinned official SDK contract for `/wallet/authenticate`, `/wallet/play`, `/bet/event`, and `/wallet/end-round`.
- The pinned client Event argument is an opaque string; do not invent a JSON event schema for the Provider wire call.
- The internal Ganesha event stream and the Provider's opaque event marker are different contracts. Validate and map them only through an explicit, versioned adapter.
- Preserve event order, round identity, replay determinism, terminal-state uniqueness, and payout projection invariants.
- No second Play while an active or ambiguous round exists. Ambiguous Play/Event/EndRound requires fresh authentication and trusted Provider-backed reconciliation; amount/mode equality or balance alone is not proof.

## Required validation

- Run `node --test tests/stake-engine-sdk-contract.test.mjs tests/frontend-rgs-adapter.test.mjs tests/stake-rgs-lifecycle.test.mjs` for RGS adapter changes.
- Run the relevant Math/Books/LUT and package-contract tests for Math changes.
- Run the full Python and Node suites plus `make release-check` before asserting a release gate passes.
- Reconcile the final source manifest, SBOM, package contents, and exact HEAD after any source change.

## Reporting

State what changed, what did not change, exact evidence, exact test totals, and remaining blockers. Distinguish local tests, SDK mocks, Provider staging tests, and production approval. A successful local test is not a Provider guarantee.
