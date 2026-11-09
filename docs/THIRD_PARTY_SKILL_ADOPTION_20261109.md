# Third-party Stake Engine reference review and skill adoption

Date: 2026-11-09

Source snapshot: Full Scratch V1 local source HEAD `a6e7997e469730f67c10b9f5657c5a1edfbfb2c2` (worktree changes were overlaid without copying generated `artifacts/`, `dist/`, `node_modules/`, local databases or secrets).

Remote parent: `integration/stake-engine-skills-2026-11-09` at `450535018a9f06ad823fed22039a78338131af60`.

Active safe branch: `integration/ganesha-full-release-2026-11-09`.

## Repositories reviewed

| Reference | Role | Adopted use | Restrictions / caveats |
|---|---|---|---|
| https://github.com/engineio/math-sdk | Official Stake Engine Math SDK | Exact pinned validator, Books/LUT serialization, weighted distribution calculations, package validation | SDK is a generic framework, not Ganesha's canonical Math inputs. Pin exact commit; never regenerate game math from examples. |
| https://github.com/topics/stakeengine | GitHub topic discovery | Discovery only; can locate additional ecosystem projects | Topic membership is not verification, endorsement, SDK authority, or license evidence. |
| https://github.com/egorfedorov/Slot-Casino-Game-Developer-Skills-for-Stake-Engine | Third-party agent skill collection | Workflow decomposition, explicit Math/RGS/UX/compliance gates, evidence-oriented reporting | GitHub repository API reports `license: null`; no LICENSE file was found. Do not vendor its SKILL.md, scripts, or references wholesale. Its example event shape and approval checklist are not Provider contracts and may conflict with Ganesha rules. |
| https://github.com/furic/stake-engine-client | Third-party TypeScript RGS client | Independent cross-check of endpoint shapes, response types, amount conversion, and replay surface | `package.json` declares `MIT`, but GitHub repository metadata reports `license: null` and no LICENSE file was found. Do not add dependency or copy source wholesale. Not official and not proof of Provider behavior. |
| https://github.com/engineio/ts-client | Official Stake Engine TypeScript client | Primary comparison point for the project's pinned `stake-engine` client and request lifecycle | Keep exact package version/lockfile integrity pinned; Beta/client limitations remain. |

## Adopted project skills

Original Ganesha-specific instructions are added under `.agents/skills/`:

- `ganesha-stake-engine/SKILL.md`
- `ganesha-math-auditor/SKILL.md`
- `ganesha-rgs-integrator/SKILL.md`

They are intentionally project-specific rather than copies of the upstream skill files. They encode the Ganesha authority hierarchy, immutable game rules, exact pinned SDK requirements, financial-unit boundaries, deterministic event playback, fail-closed behavior, and reporting requirements.

## Technical findings and integration decisions

### 1. Currency units: separate API money from Math multipliers

The third-party `stake-game-developer` skill and `furic/stake-engine-client/src/constants.ts` both describe API amounts at 1,000,000 units per displayed currency unit and Book multipliers at x100. The client constant is `API_AMOUNT_MULTIPLIER = 1000000`, `BOOK_AMOUNT_MULTIPLIER = 100`.

This agrees with the current Ganesha SDK contract fixtures (e.g. 0.10 USD represented as 100,000 API units) and the existing Math SDK audit's x100 payout representation. The new skill makes these separate domains explicit and also prohibits confusing either with the local SQLite ledger's currency minor units. Production use still requires Provider confirmation.

### 2. Do not adopt the third-party generic event shape as the Provider wire contract

The third-party skill describes an event object with `index`, `type`, and `fields`. The Ganesha project uses a versioned internal event stream, while the pinned official SDK's `Event()` method accepts an opaque string marker. Those are different interfaces. The integration skill explicitly prohibits sending a guessed JSON event schema to `/bet/event` or treating undocumented `round.event` as acknowledgement proof.

### 3. Math validator precision remains a hard gate

The existing pinned-SDK audit records the exact official Math SDK commit `141b4e89065ac4400769709a919259a923430c4d`. Its `utils/rgs_verification.py::verify_lookup_format` requires integer payouts, positive payouts of at least 10, and payout increments of 10. Existing Ganesha evidence reports 45,235 BASE LUT precision failures, while MAGICBUY_V36 and EPICBUY_V37 each have zero. This adoption does not alter Books/LUT or round payout values. The Math auditor skill requires exact-pin validation and explicit escalation of the unresolved precision conflict.

### 4. Do not import third-party game approval assumptions

The third-party approval checklist contains generic examples such as retrigger awards and generic RTP/hit-rate guidance. Ganesha's user-approved rules explicitly disable unauthorized retriggers, require 3 Scatter = 10 Free Spins and 4 Scatter = 12 Free Spins, and disable 5 Scatter unless the exact Provider-authoritative embedded EPIC payload and BASE-unit conversion are supplied. The user-approved Ganesha contract overrides the generic checklist.

### 5. RGS client is a reference, not a replacement

`furic/stake-engine-client` offers typed endpoint wrappers and a replay helper, but it is not the official SDK. Ganesha already pins the official `stake-engine` package and has guarded lifecycle handling for active rounds and ambiguous requests. The third-party client is used only as an independent contract cross-check; no new runtime dependency is introduced.

## What changed

- Added three original project-specific agent skills under `.agents/skills/`.
- Added this provenance and adoption record.
- Added `docs/skill-adoption/README.md` as the skills index.
- Corrected the repository README and authority-boundary document to point to the later 2026-11-07 Scatter addendum, rather than leaving the earlier Exact-3-only interpretation presented as current.
- Explicitly constrained the Stake upload boundary to the two deliverable roots `math/` and `front/`. Math and Front End remain separate Studio imports/approval tracks; all SKILLs, source, tests, QA, SBOM, provenance, audit evidence and engineering tools stay in the repository and are not upload contents.
- No third-party source code, skills, or runtime dependencies were copied. The project-local Ganesha skills are original instructions. The current branch separately updates the Ganesha Math builder/verifier to enforce the user-authoritative ×100/×500 cost contract and keeps Front purchases locked.

## Validation status

- Source review: complete for the referenced repository READMEs, selected skill references, Math SDK Books formatting guide, pinned Math SDK validator, and third-party RGS client implementation/type surface.
- Skills are Markdown instruction assets; no runtime code is executed by installing them.
- Focused runtime tests: not run in this documentation-only change.
- Full Python/Node suites and release gate: not run.
- Provider staging/production validation: not run.
- Publication status remains `BLOCKED_NOT_UPLOAD_READY`.

## Source URLs

- https://github.com/engineio/math-sdk
- https://github.com/engineio/math-sdk/blob/141b4e89065ac4400769709a919259a923430c4d/utils/rgs_verification.py
- https://github.com/topics/stakeengine
- https://github.com/egorfedorov/Slot-Casino-Game-Developer-Skills-for-Stake-Engine
- https://github.com/furic/stake-engine-client
- https://github.com/furic/stake-engine-client/blob/main/src/constants.ts
- https://github.com/furic/stake-engine-client/blob/main/src/client.ts
- https://github.com/engineio/ts-client


## 2026-11-09 Ganesha-specific contract integration

The project-local build and package verification path now enforces the user-authoritative independent purchase multipliers: BASE ×1, MAGIC BUY ×100, EPIC BUY ×500. The frontend shows these only as locked target prices; it does not enable either purchase. The BASE 5-Scatter embedded EPIC feature remains a separate BASE settlement path and is blocked without the canonical Provider payload and BASE-unit conversion. The Ganesha Math builder and package verifier reject the historical ×100/×100 index.
