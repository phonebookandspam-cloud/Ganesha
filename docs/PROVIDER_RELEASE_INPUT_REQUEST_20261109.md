# Provider / Stake release input request — Ganesha and The Magic

This is the exact external evidence required to move the current `BLOCKED_NOT_UPLOAD_READY` release to a verifiable submission. Do not send credentials in source files, chat text, Git commits or audit documents. Supply secrets through an approved secret manager or secure provider channel.

## A. Canonical Math authority

1. Original raw Math JSON dated 2026-09-27, byte-for-byte as exported, with original filename, source system, export timestamp and SHA-256. If unavailable, provide the official Stake Studio Math export and complete generator/source archive.
2. Exact generator name/version/entrypoint/source commit and SHA-256; exact Math SDK repository/commit; dependency lockfile and SHA-256; build environment/toolchain.
3. Approved BASE, `MAGICBUY_V36`, and `EPICBUY_V37` five-reel stop strips and probability/stop-weight models, including original units, symbol-ID mapping and all source approvals.
4. Approved 8-symbol definitions, paytable, all 20 paylines and exact row coordinates, integer payout scale, win evaluation order, Wild substitution/expansion and multiplier semantics.
5. Written approval of the target contract: RTP 96.50%, EXTREME_HIGH volatility, 50,000× maximum payout, BASE ×1, independent MAGIC ×100 and independent EPIC ×500. If Provider does not approve any target, return the approved replacement and written reason; do not edit distributions to fit.
6. Provider Golden Vectors for wins/losses, all three modes, 3/4/5/6+ Scatter, Free Spins, Wild movement/expansion, multiplier order, payout-cap boundary, max payout, zero payout and deterministic replay.
7. Canonical Books/LUT generation inputs and outputs, exact `index.json`, all output hashes, payout units, SDK validator version and written resolution of any payout-increment/precision rule conflicts.

## B. Five-Scatter embedded EPIC payload

Supply the existing Provider-authoritative `EPICBUY_V37` 10-spin feature payload for activation from BASE 5 Scatter, including:

- Exact trigger condition and payload/schema version.
- Complete event sequence, board/reel outcomes, Wild expansion and multiplier fields.
- Any feature-level state/remaining-spin fields and terminal condition.
- Explicit mapping from EPIC feature payout units into BASE-bet units.
- Confirmation that the trigger stays in the already-paid BASE round: no additional debit, no second Play, and BASE settlement.
- Golden Vectors covering the trigger, feature progression, final BASE payout and recovery after lost Event/settlement responses.

An independent EPIC purchase payload is not a substitute for this embedded BASE payload.

## C. Production RGS / Wallet contract

1. Versioned production/sandbox RGS contract and endpoint host; game launch parameter contract and supported jurisdictions/devices.
2. Secure sandbox credentials and test player/account. Do not commit secrets. Confirm key custody, rotation, session expiry and request signing/authentication.
3. Exact Play, Event, EndRound request/response schemas, error codes, timeout semantics, zero-payout closure and active-round restore behavior.
4. Server-side duplicate/timeout semantics: operation idempotency identifiers, unique round ownership proof, exactly-once debit/credit/settlement behavior, and authoritative round-history/reconciliation API.
5. Event marker schema, persistence acknowledgement, ordering/sequence and replay decoder. The SDK's `event` string is opaque and cannot be interpreted without this contract.
6. Currency exponent and amount-unit contract for bet, debit, payout, balance and display; rounding, max bet, max payout and mode cost multipliers.
7. Explicit supported mode identifiers and per-mode `costMultiplier`/`maxBet`, confirming BASE ×1, MAGICBUY_V36 ×100 and independent EPICBUY_V37 ×500.
8. Production incident/refund/reversal procedures for ambiguous Play, Event and EndRound responses.

## D. Provider trust and release evidence

1. Provider-signed Math approval record using the agreed Ed25519 approval format, covering the exact canonical manifest core, all per-field approval references, prices, Scatter rules, RTP, volatility and max-win target.
2. Provider public key and independently communicated SHA-256 fingerprint for `GANESHA_PROVIDER_MATH_TRUSTED_KEY_SHA256`.
3. Provider approval ID, issue date, scope, version, expiry/revocation procedure and the official approval portal/receipt URL.
4. Stake Studio game/project ID and upload permissions for separate `math/` and `front/` artifacts; confirmation of expected case-sensitive directory names and package layout.
5. A sandbox import/launch slot and test account for end-to-end replay, payout, zero-win, Buy and transport-failure verification.

## E. Non-Provider owner/legal evidence

These items must be supplied by the project owner/operator rather than inferred from Provider SDK behavior:

- Project LICENSE and owner-selected public terms.
- Creator/rights-holder and redistribution permission for every shipped asset; current historical R9 inventory has 177 unresolved media files and zero cleared.
- Responsible operator, security contact, privacy/data retention and operational support details.
- Jurisdiction, age gate, self-exclusion, limits, complaint/refund and Responsible Gambling controls.
- Full WCAG 2.2 AA evidence and physical iOS/Android acceptance records.

## Current fail-closed behavior

Until these inputs are received and independently validated:

- No canonical Math, Books, LUT or RTP report is generated.
- Independent Buy controls remain disabled.
- BASE 5 Scatter remains rejected before any second debit/Play or payout settlement.
- Free Spins retrigger remains fail closed; 6+ BASE Scatter fails closed.
- No production Play/Event/EndRound is sent.
- No Math or Front folder is uploaded to Stake Studio.
