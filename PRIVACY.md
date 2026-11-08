# Privacy and Local Data Handling

This engineering preview has no analytics, advertising SDK, remote API, payment processor or Provider connection. The frontend is served by a local loopback-only development server. The page does not submit gameplay requests; all wagering controls are disabled.

The default preview server does not create a wallet database, nonce database, browser session or wager record. The isolated reference ledger and authenticated round API are exercised only by tests, which create temporary SQLite files under the operating system temporary directory and remove them at test teardown. Those records are not real wallet or payment data. The default server exposes only static files and a health endpoint; the wager API returns 404 with ROUND_API_DISABLED_IN_PREVIEW.

A future hosted release requires a separate privacy/data-retention review, a named data controller/contact, and a published privacy notice. The current document describes local preview behavior only.
