# Dependency Inventory

## Runtime

- Python standard library only.
- No third-party Python runtime dependency is declared in `pyproject.toml`.
- Browser code uses plain HTML/CSS/JavaScript and local SVG/PNG assets; no npm dependency or CDN is loaded. `frontend/config.js` is local runtime-generated configuration and is explicitly excluded from source distributions.
- No analytics, advertising, payment or remote API integration is configured.

## Build tooling

- `requirements-build.txt` pins the complete resolved build toolchain: `build==1.4.4`, `importlib-metadata==8.7.1`, `packaging==26.3`, `pip==26.3`, `pyproject-hooks==1.3.3`, `setuptools==84.1.0`, `tomli==2.5.0`, `wheel==0.48.0`, `zipp==3.23.1`.
- `setuptools==84.1.0` and `wheel==0.48.0` are the pinned PEP 517 backend requirements; the remaining packages pin the build frontend and its transitive dependencies. Python 3.11+ is required for this hardened build environment.
- `requirements-test.txt` pins `zstandard==0.25.0`, used by compressed Math fixture and package-contract tests. It is included in the CycloneDX SBOM with test-only scope and is not a Python runtime dependency.
- `tools/normalize_sdist.py` is a standard-library-only post-build normalizer for deterministic source archives.
- `tools/generate_sbom.py` creates a deterministic CycloneDX 1.5 SBOM from pinned build and test requirements, the complete npm lock graph, the declared standard-library-only runtime and the provenance inventory of frontend assets, including their recorded rights-status properties and Python SPDX license expressions.
- `tools/create_release_manifest.py`, `tools/sign_release_manifest.py` and `tools/verify_release_manifest.py` produce and verify source/artifact hashes with detached Ed25519 signatures; signing requires OpenSSL 3.x, an owner-managed private key and an independently approved public-key fingerprint. The local macOS environment reports LibreSSL 3.3.6, so local Ed25519 sign/verify is unavailable and has not been claimed as passing.
- `.github/workflows/ci.yml` runs clean-checkout tests/package/SBOM/manifest with read-only permissions, then uses a separate non-PR job for GitHub provenance attestations. Action refs are not yet pinned to full commit SHAs. No hosted run is claimed until its current-commit run and attestation are independently verified.
- Historical wheel and source-distribution builds used Python 3.9.6 and superseded vulnerable build-tool versions. The current hardened toolchain is Python 3.13.17 / pip 26.3 / setuptools 84.1.0; fresh build evidence is maintained separately and must not be conflated with the historical reproducibility record.
- No signed release bundle or owner-approved signing trust anchor has been published. The SBOM generator exists; generation alone does not establish license clearance or complete asset rights.

## Test tooling

- Python `unittest`, `compileall` and standard-library HTTP test clients.
- No pytest or Hypothesis dependency is required by the current test suite.

## Non-code assets

The active frontend manifest references nine newly authored v15 SVG assets (eight symbols and one temple background) plus four procedural WAV effects. Nine legacy v14 art files are retained in the workspace but are not referenced by the active frontend manifest. All 22 media files in the provenance inventory have SHA-256/byte-count records. The nine legacy image files retain unverified creator/rights status; the new SVGs have workspace creation provenance but still require project-owner rights confirmation and a project license. No asset is cleared for public redistribution.
