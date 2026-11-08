
## User-authorized Scatter and retrigger UI copy alignment — 2026-11-07

- Updated the Help/Rules text to state 3 Scatter = 10 Free Spins; 4 Scatter = 12; 5 Scatter requires the provider-authoritative embedded EPICBUY_V37 feature within the already-paid BASE round and remains disabled until payload + BASE payout-unit conversion exist; 6+ is rejected; retriggers are unauthorized and rejected.
- Removed the stale historical claim that a retrigger event adds +1 Free Spin.
- R98 Wild/Scatter contract test now includes four explicit help-copy assertions. Current result: 55/55 PASS; inline JavaScript syntax PASS.
- Independent audit of the historical R98 BASE Books against the exact pinned Math SDK found 1,095 four-Scatter Books still declaring 10 spins, 72 five-Scatter Books declaring 10 spins without embedded EPIC payload, and 1,694 Books containing unauthorized retrigger events. These are rejected by current Frontend validation; the old Books are not eligible for upload.
- See Full Scratch evidence `artifacts/MATH_AUDIT_PINNED_SDK_20261107.json` for pinned-validator, exact-weighted metrics, payout-quantum and Books/LUT results.
