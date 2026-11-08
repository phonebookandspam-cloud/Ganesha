# Release Signing and Trust Anchor

Status: tooling implemented; no project-owner signing key or approved trust anchor has been supplied.

## Trust model

- The release manifest binds exact source commit/tree, tracked source SHA-256 values, the reproducibility-evidence digest, wheel/sdist hashes and the generated CycloneDX SBOM hash/size.
- The current CycloneDX inventory includes all 66 npm lock packages, 9 pinned Python build dependencies, 1 pinned Python test dependency and 22 Full Scratch asset records. Source-file hashes are bound separately by the release manifest; an unverified asset-rights field is not a license grant.
- R12 SBOM: `artifacts/SBOM_STAKE_CANDIDATE_20261107_R12.cdx.json` (66 npm, 9 Python build, 1 Python test and 22 Full Scratch assets). The R12 license/asset inventory and dependency scan are separate evidence; neither establishes redistribution rights or a signed release.
- A detached Ed25519 signature covers the exact manifest bytes. Do not edit or reformat the manifest after signing.
- The private key must remain outside the repository and CI logs. The public-key SHA-256 fingerprint must be independently approved by the project owner and supplied to verification out-of-band as `RELEASE_TRUSTED_KEY_SHA256`.
- A trust fingerprint stored only in the repository being verified is not an independent trust anchor and must never be used to authorize the signing key. No sample key or fingerprint is supplied because no owner-authorized key exists.
- GitHub build-provenance attestation is a separate control. It does not replace the owner-controlled Ed25519 signing identity.

## Owner-controlled signing steps

1. Build and test the exact clean source commit with the pinned toolchain.
2. Generate `dist/sbom.cdx.json` and `dist/RELEASE_MANIFEST.json`.
3. Supply an externally managed Ed25519 private key and matching public key to `make sign-release-manifest`.
4. Independently approve the printed public-key fingerprint through a channel outside this repository and CI run.
5. Run `make verify-release-manifest RELEASE_TRUSTED_KEY_SHA256=<approved-fingerprint>` from the exact source commit with a clean tracked checkout. The publication gate also requires this externally supplied fingerprint before it can verify a signed bundle.
6. Retain the manifest, signature, public key, SBOM, build artifacts and CI provenance together.

## Current hardened CI toolchain — 2026-11-07

- Python 3.13.17, pip 26.3, setuptools 84.1.0, build 1.4.4, wheel 0.48.0; test-only `zstandard==0.25.0`.
- Node.js 22.23.4, npm lockfile installation, `npm audit`, Python and Node regression suites, and a fail-closed non-wagering frontend preview build.
- GitHub Actions are pinned to full 40-character commit SHAs in `.github/workflows/ci.yml`. This is source hardening only; no hosted run or attestation has been observed.
- `artifacts/WORKTREE_BUILD_REPRODUCIBILITY_20261107_R12D.json` records two local clean-copy builds of a dirty source snapshot. It is not an exact tracked-HEAD clone or hosted attestation.

## Signing execution boundary

- The signing key must be supplied by the project owner through an approved external KMS/HSM or isolated signing workstation. Do not generate a sample key, commit a private key, add a key to the R9 ZIP, or use an unapproved GitHub secret as the project trust anchor.
- The owner must independently approve the Ed25519 public-key SHA-256 fingerprint out-of-band. `RELEASE_TRUSTED_KEY_SHA256` must be provided to verification from that independent trust channel, not from a repository file or the release artifact itself.
- Generate the release manifest only after exact source/build/SBOM hashes are final. Sign the exact manifest bytes. Any source, SBOM or artifact change requires a new manifest and signature.
- This macOS host's OpenSSL command reports LibreSSL 3.3.6; the existing signing scripts require OpenSSL 3.x. No signature has been generated. The pinned Ubuntu hosted workflow may run the scripts, but its success must be observed and attested before the gate can accept it.

## Environment limitation observed in this workspace

The current macOS `openssl` command reports `LibreSSL 3.3.6`, which does not support the Ed25519 `pkeyutl -rawin` flow used by these scripts. The scripts explicitly require OpenSSL 3.x and fail closed on LibreSSL. The GitHub workflow uses Ubuntu 22.04, but its hosted execution has not yet been observed. No signature or trust verification is claimed PASS.
