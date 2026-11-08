# Security Threat Model — Full Scratch V1

## Assets
Wallet balances and journal, round state/outcome, RNG secret, signing secret, player session mapping, math configuration and release artifacts.

## Trust boundaries
Browser/client is untrusted. The local HTTP adapter is a development service. Wallet SQLite is the local ledger authority. Provider RGS/Wallet is external and currently not connected.

## Threats and current controls
| Threat | Current control | Remaining gap |
|---|---|---|
| Client changes outcome/stops/payout | strict request schema; no stop fields accepted; server-side RNG | production API gateway/provider integration |
| Request tampering/replay | opaque non-secret session ID; HMAC-SHA256 over method, path, canonical body, timestamp and nonce; persistent one-time nonce registry; operation IDs make retries idempotent; HMAC secret is server-side only | distributed nonce store, key rotation and Provider authentication contract |
| Duplicate debit/credit | SQLite `BEGIN IMMEDIATE`, unique operation IDs and round IDs, unique journal entries | multi-node database transaction and provider-side idempotency |
| Event reorder/tamper | schema-v1 reducer, contiguous sequence, SHA-256 hash chain and replay checks | hash chain is not a signature/WORM log; full-database rewrite and external anchoring are not prevented |
| Stale recovery worker | persisted monotonic per-round fencing token; a non-null, positive current token and unexpired lease are mandatory inside the SQLite transaction for `commit_outcome`, `record_feature_progress`, `settle_round`, `refund_reserved_round` and `record_win_presented`; idempotent replays of outcome/credit/refund mutations also revalidate the current token before returning | separate-process crash-injection tests terminate immediately after Debit, Outcome, Credit and Refund and verify local restart/reconciliation; this is a single-host SQLite guarantee only and does not provide distributed consensus, cross-host clock discipline or Provider fencing |
| Outcome overwrite | immutable `OUTCOME_COMMITTED` state | external signed result provenance |
| Lost settlement response | persisted event/ledger state; outcome-committed recovery settles stored outcome without rerunning RNG; terminal replay returns prior result | provider request/ledger trace, distributed recovery and external reconciliation |
| RNG prediction/manipulation | HMAC-SHA256 weighted stop generator; secret not stored in source | production KMS/HSM, key rotation, entropy governance and independent RNG certification |
| Insufficient funds | atomic balance check and debit | concurrency/scale/load validation |
| Currency rounding mismatch | integer minor units and explicit local half-up rule | provider-specific currency contract and cross-currency tests |
| Secret leakage | no secrets in repository or browser | deployment secret manager, rotation and incident response |
| Denial of service | body size limit and request validation | rate limiting, WAF, quotas, circuit breakers and load tests |

## Required before production
TLS, provider-authenticated sessions, KMS/HSM-backed secrets, key rotation, signed provider callbacks, database HA/backup/restore, distributed idempotency, rate limiting, dependency/SAST/DAST review, penetration testing, audit logging, alerting, disaster recovery and provider-approved security test vectors.
