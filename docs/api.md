# Service API

Import public services and value types from `care_continuity`. See [the command-line tour](../src/care_continuity/cli.py) for a complete composition example.

## Trusted application boundary

The low-level services assume their caller has authenticated `actor`. A user-controlled string must never be passed through as an authenticated identity. Interfaces should use the [session-bound application API](application.md), which resolves the actor internally. `subject` identifies the person whose record is involved; knowing their ID grants no access. The person is the only supported consent authority in this version.

The SQLite connection is an internal persistence interface, not a protected API. Anyone with database or process access can bypass service checks. Knowledge reviewer IDs are configured by the host application. Publication and review flags are explicit caller attestations, not automated verification of rights, privacy, or qualifications.

## Memory

`remember` requires the person's authorization and preserves the supplied source and kind. Preferences must be attributed to the person. `confirmed=False` means the record has not been confirmed; it does not infer consent to store or share it. Storage authorization comes from the owner call, while sharing requires grants.

`revise` changes content while retaining its original kind and source. It requires `expected_revision`. To record a different person's account, create a separate observation. `history` is owner-only. `summary` returns only current, permitted records and is also the initial structured memory export; it does not export the whole care account.

`forget` removes historical text, blanks the current record, revokes memory grants, and redacts messages in linked requests. Those unfinished requests become cancelled. Completed requests retain their completion metadata. Reading a request with deleted context fails; the owner can still inspect metadata through delegation `history`.

Use context links whenever request text derives from a memory. The library cannot detect someone manually copying private text into an unrelated message. Callers must not persist or expose returned records after authority changes without rechecking access.

Circle members record observations with `observe`, which requires active membership and leaves the record unconfirmed and private to the person. `observations_pending` is the person's review inbox. `observation_accept` confirms the record while preserving the contributor as its source; `observation_dismiss` and `observation_withdraw` remove an unreviewed observation before it reaches any summary or export. `observations_by` shows a contributor only their own submissions and their review status.

## Consent

```python
from datetime import datetime, timedelta, timezone
from care_continuity import Operation

grant_id = consent.grant(
    actor="mei", subject="mei", recipient="worker", purpose="visit",
    resource_type="memory", resource_id=item.id,
    operation=Operation.READ,
    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
)
consent.revoke(actor="mei", grant_id=grant_id)
```

Resource types are `memory` and `request`. Grants match exact IDs and purpose strings. Purpose strings should be stable application-defined values, not arbitrary model prose. Expiry is exclusive: permission is invalid at its expiry timestamp. Datetimes must have timezone information.

For a handover, the recipient needs `read` and `act` on the request, plus `read` and `share` on each linked memory. Here `share` means the person permits disclosure of that memory in a handover to this recipient. It does not authorize the recipient to send it to someone else. Another recipient requires their own grants.

Revoking a grant does not revoke a separate overlapping grant. The sharing interface should display all effective grants when offering to end a person's access. `list_grants` currently returns raw grant metadata, including expired and revoked entries.

## Delegation

`create` saves a draft and returns its ID. The exact message is the approval preview. It is immutable; changing it requires a new request. `idempotency_key` is unique within the person's requests. An identical retry returns the existing ID; a different payload with the same key raises `Conflict`.

`queue` checks disclosure and action permissions. `dispatch` checks them again and either makes the request available in the local mailbox or marks it blocked. Calling `dispatch` again does not create another delivery event. No email, SMS, push notification, or external action occurs.

The named recipient uses `transition` to accept a delivered request and then complete it. They cannot jump from delivery to completion. The person can cancel unfinished requests. A delivered request without a response stays delivered; automatic reminders and alternatives are not implemented.

`read` resolves current authority and the pinned context revisions each time. A recipient can read only delivered, accepted, or completed requests, and only while authorized. If context changes, retrieval fails until the person makes a new approved request. Owner `history` exposes metadata without requiring old context to remain usable.

## Knowledge

`submit` requires audience, setting, language, limitations, a source citation, publication-rights evidence, and a separate `publication_authorized=True` attestation. Submission creates a private draft and records who authorized publication and when. An independently configured reviewer calls `review` with privacy and scope attestations, written evidence, and a future review deadline. Reviews are retained as separate records; renewal preserves the first publication date. Self-review is denied. Experience stays labelled `experience`; review does not establish clinical evidence.

`submissions(actor=...)` and `evidence(card_id, actor=...)` expose drafts and editorial records only to their contributor or a configured reviewer. Public search never includes rights evidence or review notes. The contributor or a reviewer may withdraw a card; withdrawal is idempotent and terminal. A replacement needs a new submission and review. See the [knowledge pilot guide](knowledge.md) for an executable session-bound example and migration behavior.

`search` retrieves current reviewed experience and procedure cards with a literal case-insensitive substring match. It returns source and review metadata, not a generated answer. Draft, withdrawn, and overdue cards are excluded on every call. Professional guidance publication is intentionally disabled pending qualified-review support.

## Errors and storage

- `AccessDenied`: resource unavailable or authority insufficient. Avoid exposing whether hidden records exist.
- `Conflict`: stale memory revision, reused idempotency key, or invalid state transition.
- `ValueError`: invalid input, such as an empty message or naive datetime.

Use one `SQLiteStore` per thread and close it with a context manager. Service transactions can nest inside an application transaction using savepoints. Schema version 6 is initialized automatically; version 1–5 databases upgrade transactionally. Legacy knowledge records remain stored but require a new submission with metadata and rights evidence before appearing in search. Unknown versions are rejected.

## Reviewer qualification records

`QualificationService` in `care_continuity.qualifications` records externally checked
qualifications. The host configures `verifiers`; no verifier is configured by default.
`record` requires an independent verifier, reviewer identity, exact card kind, setting and
language, private evidence, future expiry and an idempotency key. Retrying the same key and
payload returns the original record, including after revocation. Changed payloads conflict.
Records are immutable; replacement checks get a new key and record.

`list_records` permits only the reviewer concerned or a configured verifier. `revoke` is
verifier-only and idempotent. `require` checks exact scope and coverage of a review deadline.
Evidence never enters audit events or public cards. Qualification records do not confer
editorial reviewer authority or establish that an issuer actually verified a credential.

`KnowledgeService.review` and `CareApplication.review_knowledge` accept an optional
`qualification_id`. A linked record must cover the reviewer, kind, setting, language and
whole review interval. Revocation or expiry excludes the dependent card from subsequent
searches. Review history retains the original qualification ID. Renewal may replace it with
a current matching record, but cannot drop the requirement. Existing unqualified experience
and procedure reviews keep their behavior. Professional guidance stays disabled.

## External delivery foundation

The trusted `OutboxService` worker and session-bound `authorize_delivery_provider`,
`enqueue_delivery`, and `deliveries` APIs implement explicit provider disclosure, durable
jobs, bounded safe retries and ambiguous-outcome handling. Existing `dispatch` remains
local-only and refuses requests already assigned to an outbox job. See the
[delivery contract and example](delivery.md). No external transport is configured.

`OutboxService.reconcile(job_id, provider=..., lookup=...)` resolves unknown delivery
outcomes using a trusted receipt adapter outside database transactions. It sends only the
job ID to the lookup. Definitive non-delivery may requeue within the existing attempt budget
after fresh authorization; unknown results never resend. Original attempts are retained,
and resolution is recorded in metadata-only events. This is a privileged host API, not an
owner-supplied receipt flag. See the [receipt contract](delivery.md#limits-and-remaining-work).

`deliveries(token)` also returns each job’s recipient and current `request_state` in the
same owner-scoped read. The browser uses these metadata fields to distinguish transport
receipt from human acceptance without copying request text.

See [model suggestions](conversation.md) for the session-bound `ConversationService`,
explicit provider authorization, adapter contract, ephemeral suggestions and explicit
`save_draft` review. Saving rechecks authority and every source revision, preserves source
dependencies for forgetting, and creates no sharing grants or delivery jobs.
