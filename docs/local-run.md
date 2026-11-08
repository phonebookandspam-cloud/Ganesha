# Local Preview Run

The default server is a loopback-only, non-wagering engineering preview. It binds to `127.0.0.1` and exposes the static page, allowlisted art assets, health endpoint, the legacy scripted visual demo, and a separate GameEngine presentation fixture API. The financial round API is disabled. No bearer token, RNG secret, SQLite wallet or nonce database is created by this server.

```bash
cd Ganesha_Full_Scratch_V1
PYTHONPATH=src python3 dev_server.py
```

Open http://127.0.0.1:8787.

- `DEMO SPIN` runs the original fixed 5×3 presentation script. It does not call GameEngine, Math or RNG.
- `PLAY ENGINE FIXTURE · TEST ONLY` creates an in-memory fixture session, calls the real `GameEngine` with the explicit fixed `PresentationFixtureMathPort`, resolves BASE with exactly 3 `SCATTER_LOTUS`, runs 10 Free Spins, and emits the separate presentation contract. The Frontend verifies the SHA-256 event chain and replays reel stops, Wild Expansion, multiplier and completion events.

The GameEngine fixture is deterministic and non-financial. Its fixed board, fixed symbol sequence and fixture payouts are not canonical Math, probability evidence, RNG outcomes, monetary wins or settlement. It has no Wallet, RoundService, account, debit, credit, refund or Provider dependency. The API is unauthenticated only because it is loopback-bound and carries no user or financial state; do not expose either demo API on a public interface. In-memory sessions are lost when the process restarts. Chrome/Playwright smoke evidence for the fixture path is stored in `artifacts/BROWSER_SMOKE_20261104_ENGINE_FIXTURE.json` and its PNG.

On normal shutdown the server removes the temporary `frontend/config.js` file. It contains only the local endpoint and false Provider/financial-API flags; it contains no credentials.

The local SQLite ledger and authenticated financial round API exist only as isolated reference code exercised by unit tests using temporary databases. They are not exposed by the preview server. Do not enable them in a hosted deployment.

To run tests: `make test`. The `math-audit` target deliberately exits with BLOCKED because canonical user Math and Provider approval inputs are unavailable. Draft exact, Monte Carlo and crosscheck reports all pass through the shared fail-closed quarantine writer: it stamps `SUPERSEDED_NOT_RELEASE_EVIDENCE`, sets `public_claims_permitted=false`, and only permits `artifacts/*_draft_only.json` destinations. It refuses the protected `math_audit_v1.json`, `monte_carlo_v1.json` and `math_crosscheck_v1.json` names, including when supplied through the Monte Carlo `--output` option. These are research-only artifacts and cannot be used for release claims.
