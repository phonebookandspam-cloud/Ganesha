# Security Notes

The included HTTP/SQLite implementation is a local reference adapter, not a production service. `dev_server.py` binds to `127.0.0.1` only. Do not expose it to a LAN, reverse proxy or public internet. Do not reuse development tokens or RNG secrets.

The local server is not a Stake/Provider RGS, not a production wallet and not a payment system. TLS, production identity/session management, distributed fencing, durable provider idempotency, secret rotation, structured audit logging, monitoring and incident response are not implemented or verified.

For security issues in this private prototype, report them to the project owner through the existing private collaboration channel. Do not include credentials, live customer data or production secrets in bug reports.
