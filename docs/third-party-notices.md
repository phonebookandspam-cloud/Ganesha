# Third-party notices and license inventory

## Current dependency inventory (R12)

`artifacts/THIRD_PARTY_LICENSE_INVENTORY_20261107_R12.json` records the exact locked npm packages, their versions, declared SPDX license identifiers, npm SHA-512 integrity values, locally available license-text files, and the pinned Python build/test distributions with their wheel `License-Expression` metadata and PyPI release artifact hashes.

| Dependency group | Count | Declared license metadata | Local scan |
|---|---:|---|---|
| npm lock graph | 66 | 63 MIT, 2 ISC, 1 BSD-3-Clause | All 66 declare a license; license text files were found for 12 installed packages |
| Python build | 9 | Recorded from exact pinned wheel metadata | pip-audit 2.10.0: no known vulnerabilities |
| Python test | 1 (`zstandard`) | BSD-3-Clause | pip-audit 2.10.0: no known vulnerabilities |

The npm audit completed with zero vulnerabilities. A separate pip-audit scan covered all 35 packages installed in the isolated build/test/audit environment and reported zero known vulnerabilities. This supersedes the R11 finding of six pip/setuptools advisories: pip is now 26.3 and setuptools is 84.1.0. These are local dependency-scan results, not a statement that the entire release security gate has passed.

## SDK provenance and license limitation

- Official package: `stake-engine@0.1.32`, declared ISC; registry tarball SHA-256 `55c2445e5aa0744dafef9d54f74b9f6ae2857dcfc868a14460a053a60cec4869` and registry SRI are recorded in `front/vendor/STAKE_ENGINE_SDK_PROVENANCE.md`.
- The vendored `front/vendor/stake-engine-0.1.32.js` SHA-256 is `f7f07e9982ecd1390d71e1473098cafc7bf295a15ab14f6738644dbe365903af`; the official package rebuild hash is `93217163a5677e3af9e8160d7699dac97d3f4d0de517ffa15a2949447f8d7113`. The local file is a fork, not the unmodified official SDK.
- The npm package declares ISC metadata but the downloaded package contains no LICENSE file or complete copyright notice. The local fork's recovery changes also require explicit review/acceptance before redistribution.

## Asset and project rights

The R9 Frontend package contains 177 image/audio assets (144 SVG, 21 PNG, 1 JPG, 8 OGG and 3 WAV). The R12 content-hash comparison found only 9 matches against the current Full Scratch 22-asset provenance manifest and zero assets with cleared redistribution rights. The R9 ZIP's upload manifest proves byte integrity, not authorship or license. See `artifacts/R9_ASSET_RIGHTS_AUDIT_20261107_R12.json` for per-file hashes and match status.

The project has no selected `LICENSE`. No project-wide redistribution grant has been established. A declared SPDX license or a matching content hash is not proof of copyright ownership, permission to modify, or permission to redistribute. The R9 Frontend package must not be publicly redistributed until the project owner and each relevant rights holder provide the required written rights evidence and the required notices are assembled.

## Scope and release status

The current CycloneDX SBOM is `artifacts/SBOM_STAKE_CANDIDATE_20261107_R12.cdx.json` (66 npm, 9 Python build, 1 Python test and 22 source assets). It is verified against the lockfile, requirements and current 22-asset provenance inventory. It does not certify the separate 177 media files in the R9 Frontend ZIP, clear project/asset rights, attest uncommitted source, or constitute a signed release SBOM. Historical R9/R11 SBOMs and candidate packages are preserved and are not overwritten.

**Redistribution remains BLOCKED.** The project license, R9 asset rights, full third-party license texts/notices, and SDK fork acceptance remain unresolved.
