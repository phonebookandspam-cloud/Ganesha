# Publication Checklist

This checklist is a release gate, not a statement that publication is authorized.

## Track A — Public source repository

- [ ] Current working tree is dirty and contains uncommitted changes. `artifacts/LOCAL_CLEAN_CLONE_REPRODUCIBILITY_20261104_R4.json` records two isolated local clones from HEAD plus the tracked worktree patch (255 Python + 33 Node tests and identical Vite output); it is not exact-commit signed CI, does not include untracked source, and is not release attestation. See `docs/release-gates.md` for the current layout-v2 browser evidence and remaining publication blockers.
- [ ] Owner-selected license is present and covers the intended source distribution.
- [ ] All asset creators, ownership and redistribution rights are confirmed; third-party notices are complete.
- [ ] Dependency/build tool versions are pinned; clean build and SBOM are generated.
- [ ] Security contact and vulnerability disclosure process are published.
- [ ] Trademark and non-affiliation language is reviewed.

## Track B — Hosted non-wagering preview

- [ ] Track A rights/ownership requirements are satisfied for every served asset.
- [ ] Hosting uses HTTPS, hardened origin configuration, security headers and monitoring.
- [ ] Privacy notice identifies the data controller/contact, actual data flows, retention and deletion process.
- [ ] Terms, disclaimer and support contact identify the responsible operator.
- [ ] No wager, purchase, wallet or payment route is deployed; this is verified externally.
- [ ] WCAG 2.2 AA, keyboard, screen-reader, contrast, responsive and physical-device checks pass.

## Track C — Stake Engine / real-money product

- [ ] Original canonical Math raw source and SHA-256 are present.
- [ ] Approved strips, symbols, paytable, 20 paylines, Scatter 4/5/6+, retrigger and Wild/multiplier semantics are source-bound.
- [ ] Canonical generator, probability inputs, Golden Vectors and Provider Math approval are verified.
- [ ] Books/LUT/index are regenerated only from approved inputs and independently audited.
- [ ] Production RGS/Wallet event contract, amount units, idempotency, fencing, settlement and recovery are proven.
- [ ] Studio/ACP registration, team permissions, upload receipt, iframe and game-specific Stake approval/activation are proven.
- [ ] Latest Front SHA passes browser/device/animation/audio/accessibility acceptance.
- [ ] Legal, jurisdictional, responsible-gambling, privacy, security and operational controls are approved.

Do not infer one track's readiness from another. A source repository or static preview passing its own checks does not imply Stake approval or real-money readiness.
