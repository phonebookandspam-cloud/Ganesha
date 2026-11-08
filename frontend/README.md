# Frontend Engineering Preview

This page is a static, non-wagering visual preview. It intentionally disables Spin, bet adjustment and both Buy controls. The displayed symbol board is an art layout, not a generated outcome.

The page must not be described as a Stake Engine game, approved release, playable real-money product or certified Math implementation. The local reference API is separate and is not called for wagers from this page.

The active preview uses nine newly authored v15 SVG assets listed in `assets/ASSET_PROVENANCE.json`; the v14 source-workspace art is retained as legacy files and is no longer referenced by the active frontend manifest. The v15 SVGs have workspace creation provenance, but the project license, owner rights confirmation and Provider publication rights remain unresolved. Do not publish or redistribute any art until rights are confirmed.

## Offline candidate build

Create a new, non-wagering candidate without changing `config.js`, `frontend-build/` or the running Preview:

```sh
npm run build:frontend:offline -- --output artifacts/FRONTEND_BUILD_OFFLINE_<unique-name>
```

The build uses the separate `config.offline.js`, requires all Provider, round, demo, fixture, runtime, wagering and Bonus Buy capabilities to remain disabled, refuses an existing output path, runs `tools/verify_frontend_build.mjs`, and writes a source/file SHA-256 integrity record beside the candidate. Use a new output name for every build; do not replace an earlier candidate. This is local engineering evidence only, not a Stake upload, Provider approval, signed release or permission to redistribute assets. The ordinary `build:frontend` path remains fail-closed when the current `config.js` is `local-development`.
