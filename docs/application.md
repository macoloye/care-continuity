# Session-bound application API

`CareApplication` is the entry point used by the [local text interface](web.md) and available to future voice adapters. Its methods accept a session token, derive the actor from that session, and call the existing services. Client payloads cannot choose an actor. Session validation and the operation share one transaction, including membership and permission checks.

## Bootstrap and use

```python
from care_continuity import CareApplication, SessionService, SQLiteStore

with SQLiteStore() as store:
    # Example only. Production issuance follows verified login.
    token = SessionService(store).issue("mei")
    app = CareApplication(store)
    app.remember(token, text="Breakfast after 8 suits me.", confirmed=True)
    app.add_member(token, member="lina", role="supporter")
    account = app.export(token)
    app.logout(token)
```

Session issuance is a privileged integration API, not a login endpoint. It does not verify names, passwords, or identity documents. A host must map a verified identity-provider account to a stable actor ID before issuing a token. Do not expose `issue` to an untrusted client or accept an actor ID as proof of identity.

Tokens are random bearer secrets. Only their SHA-256 digests are stored. They expire after eight hours by default, with a maximum lifetime of one day. Logout revokes the token; existing application objects recheck it on every call. Never put a token in a URL, care record, analytics event, or log. A future HTTP adapter must provide transport security, secure session storage, and request-origin protections. None is implemented here.

## Available operations

| Area | Methods | Behavior |
| --- | --- | --- |
| Memory | `remember`, `revise`, `forget`, `memories` | Own preference writes; recipient reads filtered by person and purpose |
| Circle | `add_member`, `remove_member`, `members` | Owner-managed relationships; no implied disclosure |
| Sharing | `grant`, `revoke`, `sharing` | Exact grants to active members; current effective status shown |
| Requests | `create_request`, `read_request`, `approve_request`, `queue`, `dispatch`, `transition` | Existing approval and lifecycle rules with session-derived identity |
| Views | `inbox`, `requests` | Filtered recipient content and owner metadata views |
| Follow-up | `plan_followup` | Persist an owner-selected deadline and alternative before acceptance |
| Export | `export` | Consistent JSON-compatible account snapshot |
| Session | `logout` | Idempotent revocation |

Membership roles are `supporter`, `worker`, and `coordinator`. They describe a relationship and confer no permissions. The application requires active membership before creating a grant or request. Low-level services remain usable without a circle, but an explicit removal blocks new grants until the member is added again.

Removing a member revokes **all** their grants for this person, across purposes and resources, and cancels unfinished requests. Completed records keep their state, while recipient access is revoked. Adding the member back does not restore old grants or cancelled requests. Cancellation updates the local record; it cannot stop a real-world activity already in progress.

## Request views and follow-up

After showing the draft's exact recipient, message, context, purpose, and expiry, an interface can call `approve_request`. This creates the displayed permissions and delivers locally in one transaction. Stale context and already handled drafts fail without creating new grants. Use the lower-level grant, queue, and dispatch methods when an integration needs those steps separately.

An inbox lists only requests the current recipient can still read. Revoked, stale, draft, blocked, and cancelled items are omitted, including their metadata. A stale context therefore does not leak through an inbox preview.

The owner's `requests` view includes IDs, recipient, state, timestamps, and follow-up status even if context has changed or been deleted. Such entries have `content_available=False`, `message=None`, and empty context. The person can inspect the status and prepare a replacement without reviving old text.

`plan_followup` records a future deadline and an alternative chosen by the person. At the deadline, an unanswered draft, queued, or delivered request has `needs_followup=True`. Acceptance or cancellation clears that derived flag. This is a view calculated when called, not a scheduler or notification service. The alternative is owner-only and does not authorize sending another request.

## Export and deletion

`export` returns format version 1 with current memories and their retained revision histories, sharing records, circle membership, owner request views, and audit events. It includes only the authenticated person's account. Sessions, token hashes, other people's records, and the public knowledge catalogue are excluded. Use `json.dumps(account)` to serialize it.

Deleted memory and revision text are excluded. Forgetting also redacts linked request messages and their follow-up alternatives, which may contain copied care text. Stale request content is omitted while lifecycle metadata remains. This is an account data export, not a database backup or a restore format. An export already saved elsewhere cannot be recalled.

## Database upgrade

Opening a version 1 database upgrades it to version 2 in a transaction, adding sessions, circle membership, and follow-up tables without rewriting existing care records. Reopening version 2 is a no-op. Unknown versions fail closed. Failed upgrades roll back the schema and version marker together.

Service transactions now support nesting through SQLite savepoints. The application holds the outer transaction so a session revocation or circle removal cannot interleave between authorization and the corresponding database operation. Keep network calls outside these transactions.
