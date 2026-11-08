# Build and Reproducibility

## Scope

The repository is source code plus a static non-wagering engineering preview. No public binary, hosted deployment, Stake upload or wagering use is authorized. The Python wheel contains importable reference modules, not a complete game package. The source distribution contains the frontend, assets, provider boundary documents, tests and build tooling; neither artifact is a Stake Engine upload package.

## Pinned toolchain

- Python: 3.13.17 for the current hardened build toolchain. The project package minimum is Python 3.11; Python 3.9/3.10 are end-of-life and are no longer supported build targets.
- Runtime Python dependencies: standard library only.
- Frontend runtime: plain HTML/CSS/JavaScript with no runtime CDN. The reproducible Vite build/test toolchain uses the 66-package npm lock graph.
- Node.js: 22.23.4; npm installs only from `package-lock.json`.
- Test runner: standard-library `unittest`.
- Complete pinned Python build environment: `pip==26.3`, `build==1.4.4`, `importlib-metadata==8.7.1`, `packaging==26.3`, `pyproject-hooks==1.3.3`, `setuptools==84.1.0`, `tomli==2.5.0`, `wheel==0.48.0`, `zipp==3.23.1`.
- Pinned Python test dependency: `zstandard==0.25.0`.

## Reproduction commands

    python3 -m pip install -r requirements-build.txt
    python3 -m pip install -r requirements-test.txt
    npm ci
    npm audit --audit-level=low
    make package SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)
    make sbom
    make release-manifest
    make test
    python3 -m compileall -q src tests dev_server.py qa_release_gate.py
    npm run test:frontend-rgs
    npm run build:frontend:offline -- --output artifacts/FRONTEND_BUILD_OFFLINE_<unique-name>
    git diff --check

The `math-audit` target intentionally fails closed because canonical user Math, approved probability profiles and Provider Golden Vectors are missing. `math-audit-draft` writes only superseded research artifacts and is not release evidence.

## Historical recorded verification (2026-11-04)

Two independent clean clones of tested commit `f1a0187d985c3a48181e773c5eaa55c40ca681dc` were built with the pinned toolchain and `SOURCE_DATE_EPOCH=1793758133`. Both clones ran **132 tests, 0 failures** and produced byte-identical wheel, normalized sdist and CycloneDX SBOM.

| Artifact from tested commit `f1a0187` | SHA-256 |
|---|---|
| Wheel | `447acfa1169d001414cb66f261c6d806480be6c0df8d0fab4584fdda9358749b` |
| Normalized sdist | `5385838e92c319a9ebd6f264694c307fe658e05ed907c4fbe318aac492610bec` |
| SBOM | `daafd09121ba69008ab2caa7b26122742e88d6abf03085aeb7a790c912c5b365` |
| Git archive | `18e7daa4db31d7d5c7b5e215f4f2de2a9b7b2f6d2e9eb9b2a79cc7f70d86e0ad` |

| Clean clone | Test result | Duration |
|---|---:|---:|
| A | 132 PASS | 17.065 s |
| B | 132 PASS | 16.812 s |

For the release snapshot at commit `80babf8708e33135fa89159588ba7d201b47cee5`, the evidence JSON `artifacts/BUILD_REPRODUCIBILITY_20261103.json` recorded a 111-entry tracked-source SHA-256 manifest (excluding itself), tested/source-manifest commit `f1a0187d985c3a48181e773c5eaa55c40ca681dc`, toolchain, source epoch, clean-clone results and artifact hashes. The evidence commit was a descendant of the tested commit; the release gate verifies ancestry and exact current source-manifest equality. The JSON is regenerated after tracked changes, so it remains the authoritative latest snapshot.

The release artifacts for snapshot commit `80babf8` were stored under `dist/80babf8/`:

| Artifact from current HEAD `80babf8` | SHA-256 |
|---|---|
| Wheel | `447acfa1169d001414cb66f261c6d806480be6c0df8d0fab4584fdda9358749b` |
| Normalized sdist | `5385838e92c319a9ebd6f264694c307fe658e05ed907c4fbe318aac492610bec` |
| SBOM for snapshot `80babf8` | `7c7f2befb514a84c4c65e9c799b64eb8a2d515a0c6acd1f7f052d4ddbd0a6954` |
| `RELEASE_MANIFEST.json` (unsigned) | `dc0f43452db6e5abc7ba7791beb3f1b4cde62f04393873b6783042279ad1a5a9` |

The wheel and sdist match the clean-clone evidence. The SBOM was regenerated for snapshot `80babf8`, so its hash differs from the SBOM built at the tested parent commit. The manifest binds that snapshot commit, 112 source files, build-evidence hash, SBOM, wheel/sdist hashes and artifact sizes. Its status is `UNSIGNED_REQUIRES_OWNER_KEY_AND_TRUST_ANCHOR`; it is not a signed release.

The package audit confirms that the wheel contains `ganesha.demo.game_fixture` and `ganesha.game.presentation`, the sdist includes `docs/license-status.md`, generated `frontend/config.js` is excluded, and no `License-File` metadata is asserted. This is packaging metadata only; it does not grant asset redistribution rights or select a project license.

## SBOM, manifest, signature and CI

- `make sbom` generates a deterministic CycloneDX 1.5 SBOM from the pinned Python build/test requirements, all 66 npm lock packages and the 22 Full Scratch frontend asset provenance records. Asset creator/rights status is included as provenance data, not interpreted as a license grant.
- `make release-manifest` binds the exact source commit/tree, every tracked source-file SHA-256, build-evidence SHA-256, wheel/sdist/SBOM hashes and artifact sizes. It refuses a dirty source checkout and refuses wheel/sdist bytes that differ from the two-clean-clone evidence. Build outputs are isolated under `dist/<short-commit>/` so a new build does not overwrite artifacts from earlier commits.
- `make sign-release-manifest RELEASE_SIGNING_PRIVATE_KEY=... RELEASE_SIGNING_PUBLIC_KEY=...` signs the exact manifest bytes with Ed25519 through OpenSSL. Keys must be supplied out of band; no private key is stored in the repository.
- `make verify-release-manifest RELEASE_TRUSTED_KEY_SHA256=...` verifies the detached signature, independently supplied public-key fingerprint, exact HEAD/tree, source-file hashes and artifact hashes. The fingerprint must be approved out of band; a trust anchor stored only inside this repository is not trusted.
- `.github/workflows/ci.yml` runs Python and Node tests, npm audit, the fail-closed offline preview build, package/SBOM generation and attestation in separate jobs. Every `actions/*` reference is pinned to a full 40-character commit SHA. This hardens the workflow definition but does not prove a hosted run occurred.
- The release gate rejects evidence commits that are not ancestors of the current HEAD and still requires exact source-manifest equality.

## Remaining release blockers

- No owner-signed release manifest or approved signing trust anchor has been published.
- CI workflow is defined, but no successful hosted run/attestation has been imported and independently verified for the integrated HEAD.
- Project license and asset redistribution rights are unresolved.
- The wheel is not the complete game package; the sdist is the source distribution.
- Math artifacts are explicitly superseded and are not evidence for canonical approved inputs.
- Reproducible packaging does not establish game correctness, security, Provider approval or deployment readiness.


## Exact-HEAD verification update (2026-11-04, commit 2ac7dc2)

The presentation-contract and local recovery hardening was committed as 2ac7dc24383d6bfdab92b9c86a61ef299490ce31. The main checkout ran 151 tests with zero failures. Two clean clones of that exact commit independently ran 151 tests and produced byte-identical wheel, normalized sdist and CycloneDX SBOM.

| Artifact | SHA-256 |
|---|---|
| Wheel | da54594ae7733461e542fdfd0fd444d235b92458e3db202ebc6fbcc4da88139f |
| Normalized sdist | 8d50c7cf58a30564c7d38127470c951e9aef0d4e4acdef79d489dbe11fe6ad42 |
| SBOM | 7bc38e3f7e5d81da5c671900af653f74f6ad4b097e3ff0a5fbfaf3cda0596bbd |

The historical clean-clone evidence above used Python 3.9.6, pip 25.3 and setuptools 82.0.1. That toolchain is superseded because its build dependencies were later found to contain six advisories. The current pinned toolchain is Python 3.13.17, pip 26.3 and setuptools 84.1.0; new exact-HEAD reproducibility evidence must be generated from two clean clones before the release gate can accept it. The historical hashes are retained as history and are not evidence for the hardened toolchain.

## Current R12 local reproducibility evidence (2026-11-07)

`artifacts/WORKTREE_BUILD_REPRODUCIBILITY_20261107_R12D.json` records two independent clean filesystem copies of the current source snapshot. Both copies use Python 3.13.17, pip 26.3, setuptools 84.1.0, build 1.4.4 and wheel 0.48.0. The source manifests, wheel SHA-256 and normalized sdist SHA-256 must match exactly. The sdist includes the npm lockfile, build/test requirements and all four provenance-listed WAV assets.

This is **local worktree reproducibility only**. The source checkout is dirty and contains untracked source files; the two copies are not Git clones and do not establish a clean tracked exact-HEAD build. No hosted CI attestation or trusted signature has been observed. The release gate therefore keeps exact-HEAD reproducibility and hosted CI as separate blocked requirements.
