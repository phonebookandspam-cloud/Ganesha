# Security Review Bundle — Ganesha Full Scratch V1

**Revision:** 2026-11-04 / V15 frontend asset integration  
**Classification:** Local engineering evidence for independent review; **not** an independent security assessment, penetration-test report, production approval, or G5 PASS.

## 1. Scope and system boundary

The reviewed local system consists of the browser preview, static HTTP adapter, non-financial GameRuntime, GameEngine/MathPort, Presentation reducer, local RoundService, SQLite Wallet ledger, HMAC request verification, nonce registry, event reducer/hash chain, and local release/build tooling. The browser is untrusted. The local HTTP service is a development reference implementation bound to loopback. SQLite is the local financial-ledger authority only for the test/reference path. Stake Provider RGS, production Wallet, KMS/HSM, hosted authentication, deployment ingress, and external audit/monitoring are outside the connected system boundary and are not implemented or verified here.

## 2. Data flow and trust boundaries

```text
Untrusted browser
  ├─ static preview / fixture presentation (no financial calls)
  ├─ optional local Runtime API ──> GameRuntime + injected deterministic test MathPort
  └─ guarded SDK adapter (default-off; Authenticate-only application use)

Local reference HTTP adapter
  ├─ HMAC-SHA256 request verifier + persistent nonce registry
  ├─ RoundService ──> GameEngine ──> Presentation / event reducer
  └─ WalletLedger ──> SQLite transactions, journal, fencing leases, recovery

External, currently disconnected:
  Stake Provider RGS / Provider Wallet / production key custody / hosted operations
```

The local Runtime API is non-financial and stores a separate projection. It is not a Wallet transaction or a Provider round. The SDK lifecycle adapter is default-off; ambiguous Play/Event/EndRound states are not automatically resent. The local RoundService and SQLite tests do not establish cross-host or Provider exactly-once behavior.

## 3. Threat register

| Asset / boundary | Threat | Impact | Existing local control and evidence | Owner for closure | Residual risk / required evidence |
|---|---|---|---|---|---|
| Wallet balance and journal | Duplicate debit, credit or refund | Financial loss / incorrect balance | SQLite `BEGIN IMMEDIATE`, unique operation/round/journal IDs; fault-injection matrix and wallet regression suite | Wallet engineer | Production Wallet contract, provider idempotency and distributed transaction tests |
| Round ownership | Cross-account access or stale recovery worker | Unauthorized round mutation / double settlement | Account-scoped session mapping; per-round fencing token checked inside mutation transactions; stale-token and lease tests | RGS/Wallet engineer | Provider round ownership/correlation contract and multi-host fencing |
| Request authenticity | Body/path tampering, nonce replay, session theft | Unauthorized API operation | HMAC-SHA256 binds method/path/canonical body/timestamp/nonce; persistent one-time nonce registry; replay tests | Security engineer | Production identity/session binding, TLS, distributed nonce storage, rotation, expiry policy and independent review |
| Outcome integrity | Client supplies stops/outcome/payout or rewrites committed result | Manipulated payout | Strict request schema; server-side RNG; immutable `OUTCOME_COMMITTED`; deterministic replay and presentation validation | Game/Math engineer | Provider-signed outcome provenance, canonical Math and independently reviewed RNG contract |
| Event stream | Event reorder, deletion, duplicate IDs or hash tampering | Incorrect payout/feature state; audit gap | Contiguous sequence, unique event IDs, SHA-256 chain, reducer replay, ledger reconciliation tests | Game/Wallet engineer | Hash chain is not signed/WORM storage; external anchoring and immutable audit retention |
| Persisted Runtime | SQLite snapshot/outcome/cache tampering | Incorrect restored presentation or duplicate operation | Schema v3, input fingerprint, MathPort re-resolution, replayed outcome/events/final state; restore tamper tests | Runtime engineer | File-system threat model, backup/restore controls, production DB hardening and independent review |
| Secrets / RNG key | Source leakage, weak custody, predictable or rotated key mismatch | Forged requests or biased/predictable outcomes | No production secret in browser/source; local HMAC generator uses injected secret | Security / platform owner | KMS/HSM, entropy governance, key rotation, key separation, ceremony, audit and independent RNG certification |
| Settlement response | Lost/ambiguous EndRound acknowledgement and automatic retry | Duplicate settlement | Adapter blocks ambiguous settlement and does not auto-retry; SDK 0.1.32 mock-contract tests | Provider integration owner | Provider round-history API, unique correlation, settlement query and signed provider contract |
| Availability | Oversized requests, abuse, resource exhaustion | Service outage / ledger contention | 65,536-byte request cap, strict schema validation, loopback-only dev server, SQLite lock handling | Platform/SRE owner | Production rate limits, WAF, quotas, circuit breakers, distributed load and soak tests |
| Currency and payout | Minor-unit or rounding mismatch | Under/overpayment | Integer minor units and explicit local half-up conversion tests | Wallet / Provider owner | Provider currency exponent, supported currencies, rounding and maximum-payment contract |
| Frontend supply chain | Malicious/compromised asset or dependency | XSS, tracking, user deception, build compromise | Local assets, restrictive CSP, dependency lockfile/SBOM, fail-closed preview controls | Frontend / release owner | Full SAST/DAST, dependency provenance/signature, asset rights, hosted CSP and penetration testing |
| User protection / legal | Unapproved real-money operation or inadequate age/RG controls | Legal/regulatory harm | Preview explicitly non-wagering; Spin/Bet/Buy disabled; no Provider wallet connection | Operator / legal owner | Jurisdiction, operator authorization, age verification, self-exclusion, limits, privacy, terms and legal sign-off |

## 4. Existing verification evidence

- `docs/security-threat-model.md`: local assets, trust boundaries, threats and production gaps.
- `docs/WALLET_RGS_FAULT_INJECTION_MATRIX_20261104.md`: named fault-injection tests and local SQLite boundary limitations.
- `docs/authority-boundary.md`: authoritative Math constraints and fail-closed disposition.
- `artifacts/INDEPENDENT_DRAFT_MATH_AUDIT_20261104.json`: Draft-only evaluator/reference scope; not canonical approval.
- `artifacts/DRAFT_MATH_INDEPENDENT_CROSSCHECK_20261104_R2_draft_only.json`: source-hash-matched resolved-domain crosscheck; not Provider Golden Vectors.
- `artifacts/WORKSPACE_EVIDENCE_MANIFEST_20261104_V15_R1.json`: unsigned local workspace inventory; not signed release provenance.

Previously reported local Wallet fault-injection coverage includes process exits after Debit/Outcome/Credit/Refund, lost responses after Credit/Refund commit, event-sequence deletion, tamper detection and fencing. Local stress evidence is 24 workers × 50 rounds (1,200/1,200 local SQLite settlements, zero errors); this does not represent distributed load or a Provider environment.

## 5. Mandatory independent-review questions

1. Can any untrusted browser input affect RNG stops, Math mode, payout, round ownership, event order, or settlement authority?
2. Are HMAC key generation, entropy, storage, rotation, revocation and incident response acceptable for the production threat model?
3. Can process crash, network partition, concurrent workers or stale leases produce duplicate financial effects across multiple hosts?
4. Can a full SQLite file rewrite, backup rollback or journal tampering be detected using an external trust anchor?
5. Can an ambiguous Provider Play/Event/EndRound be uniquely reconciled without resending a financial operation?
6. Are payout/currency limits enforced identically by canonical Math, GameEngine, Provider Wallet and settlement ledger?
7. Are hosted privacy, retention, access logging, abuse controls, monitoring, alerting, recovery and disaster-response controls adequate?
8. Are all shipped assets and dependencies legally redistributable and independently reviewable?

## 6. G5 disposition and external evidence required

**G5 remains BLOCKED.** The project owner/operator must provide the production deployment and identity architecture, KMS/HSM key-custody evidence, Provider authentication and signed-callback contract, distributed nonce/idempotency design, production logging/monitoring/backup/restore controls, and an independent security review with penetration-test findings and remediation sign-off. Local tests and this document are preparation material only; they cannot substitute for that assessment.
