# Security and data handling

This is a local application. The browser interface uses a profile chooser, not verified login. It has no production server, encrypted storage, representative-authority verification, operational monitoring, or emergency service.

The web command binds only to `127.0.0.1` and uses an in-memory database unless `--db` is given. Anyone able to reach that process can select any profile. Never expose it through port forwarding, a tunnel, or public hosting. HTTP boundary controls and their limits are documented in [the web guide](docs/web.md).

The core checks permissions for every service access. The application layer validates revocable bearer sessions and derives actor IDs internally. Session issuance still trusts the host to verify identity first; there is no login or identity-provider integration. Direct session issuance and database access are privileged and must never be exposed to clients. The host also configures reviewer authority. Protect database files, process access, backups, and exports separately.

Deletion is logical: service-visible care text and linked request messages are removed, while identifiers and audit metadata remain. SQLite may retain previous bytes in free pages or backups. Returned Python objects and information someone has already read cannot be recalled. There is no secure-erasure guarantee.

No model or external message provider is configured. Adding either requires explicit disclosure consent, documented retention behavior, and tests that authorization changes stop pending use. Do not log prompts or care text by default.

## Reporting a problem

Do not include private care data or exploitable details in a public issue. Once this repository is hosted, maintainers should enable GitHub private vulnerability reporting and publish a verified private contact before accepting real deployments. No reporting address has been configured in this source snapshot.

Until that route exists, use only example reproductions when discussing problems publicly. Do not assume an unverified email address or public issue is a private reporting channel.
