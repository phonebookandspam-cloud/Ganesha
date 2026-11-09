# Ganesha and The Magic — Full Scratch Engineering Preview

This is an isolated engineering prototype created separately from the preserved RC8B/RC9/RC10/RC10R1 candidate tree. It is **not** the Stake Engine submission build and must not be represented as an approved, certified or production-ready game.

## Current status

`INTERNAL_ENGINEERING_PREVIEW_ONLY — PUBLICATION_BLOCKED — NOT_PROVIDER_APPROVED — NOT_REAL_MONEY_READY`

The browser page includes a **scripted visual demo**: DEMO SPIN calls a loopback-only, wallet-free endpoint that returns fixed 5×3 presentation fixtures and ordered reel-stop events. These fixtures are not RNG outcomes, Math results, wins, Free Spins awards or probability samples. Bet adjustment and Buy remain disabled. The separate SQLite/RGS adapter is a development reference implementation and is not connected to Stake, a Provider, payment processor or real funds.

## Authority boundary

The current V1 math and feature configuration is a hypothetical draft, not a transcription of the original user-supplied Math. Current user-authoritative BASE rules are: 3 Lotus Scatter = 10 Free Spins; 4 = 12 Free Spins; 5 = the existing embedded `EPICBUY_V37` feature inside the already-paid BASE round (no second debit or Play; BASE settlement), currently blocked pending the Provider-authoritative payload and BASE-unit conversion; 6+ and Free Spins retriggers fail closed. Independent purchase prices are MAGIC BUY ×100 and EPIC BUY ×500; both remain locked pending canonical Math and Provider approval. Historical ×100/×100 Math indexes and old Exact-3-only notes are superseded. See [`docs/authority-boundary.md`](docs/authority-boundary.md), [`docs/SCATTER_FEATURE_CONTRACT_20261107.md`](docs/SCATTER_FEATURE_CONTRACT_20261107.md), and [`docs/BUY_MODE_USER_CONTRACT_20261109.md`](docs/BUY_MODE_USER_CONTRACT_20261109.md).

The original 2026-09-27 user Math JSON raw bytes are not currently available in this workspace. Its exact reel strips, paylines and paytable must not be reconstructed from generated Books, LUTs, artwork or this draft.

## Product design targets (not certified)
- 5×3 presentation and 20 paylines (the original line coordinates are not currently source-verified)
- 96.50% RTP target (not a verified or approved result)
- 50,000× target (not a verified maximum payout probability or certified payout)
- BASE / Free Spins / Bonus Buy design areas (rules remain incomplete)
- Independent Math, Game, frontend, local RGS and Wallet reference boundaries

The 8-symbol art inventory in this preview is a proposed visual set. The original user Math inventory recorded in the authority reconciliation had six symbols; provenance/approval for additions is not established.

## Repository map
- `src/ganesha/math`: draft reels, weights, paytable and research calculations
- `src/ganesha/game`: local draft state machine
- `src/ganesha/demo`: isolated in-memory scripted presentation sessions; no financial or Math dependency
- `src/ganesha/rgs`: local HTTP reference adapter
- `src/ganesha/wallet`: SQLite demo ledger only
- `src/ganesha/security`: local request/replay primitives
- `frontend`: non-wagering visual demo and read-only financial-round snapshot bridge
- `provider`: integration boundary documentation only; no production adapter or credentials
- `tests`: local unit/integration tests for this prototype
- `docs`: architecture, authority boundary, draft Math and release gates
- `.agents/skills`: original Ganesha-specific Stake Engine, Math audit and RGS engineering workflows; internal engineering assets, not Stake upload contents

## Publication status

See DISCLAIMER.md, PUBLICATION_CHECKLIST.md, and run make release-check. The publication gate evaluates source, hosted preview and Stake/real-money tracks separately. Current status is BLOCKED; do not distribute or deploy this project.

## Local development

Python 3.9+; standard-library runtime. `make test` runs the local unittest suite. `make serve` starts a loopback-only visual demo server with in-memory scripted sessions. It creates no wallet, nonce database, browser credential or financial wager endpoint. See [`docs/local-run.md`](docs/local-run.md).

No production RGS, Wallet, payment, Stake Engine, analytics or external network endpoint is configured. Do not enter real personal or payment information.
