# Local HMAC stop-generator versioning contract — 2026-11-09

## Current behavior

`src/ganesha/math/rng.py::implementation_version()` computes the version string by hashing the raw bytes of both `src/ganesha/math/rng.py` and `src/ganesha/math/config.py`. The hash input is the relative path, NUL byte, complete file bytes, and NUL byte for each file. The result is prefixed with `hmac-sha256-stop-v1:`.

That version string is included in both the round commitment and every stop-vector HMAC context. Consequently, **even a comment-only or whitespace-only edit to either file changes the RNG version, commitment, and generated stop vectors**. This is observable behavior, not merely metadata.

## 2026-11-09 regression diagnosis

A documentation-only comment change in `config.py` changed the implementation version and caused `test_draft_rng_golden_vector_is_version_bound` to fail. The comment change was reverted. The approved local golden vector remains unchanged. No stop weights, HMAC inputs, rejection-sampling logic, or Math probabilities were changed.

## Change control

- Do not make cosmetic edits to `rng.py` or `config.py` without treating the change as an RNG version migration.
- Any intentional migration requires an explicit new version, regenerated deterministic test vectors, replay compatibility tests, round-recovery tests, and Provider approval before production use.
- The local HMAC generator and its golden vectors are engineering fixtures, not Provider Golden Vectors or proof of Stake Engine RNG approval.
- This contract does not authorize changes to canonical Math, Books, LUT, RTP, volatility, payout tails, or purchase multipliers.
