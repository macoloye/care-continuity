# Durable delivery outbox

Milestone 4 now has a durable worker foundation. No external provider is configured, and
the browser continues to use the local mailbox. The outbox API is for a trusted host and
transport adapter; examples use synthetic data and an in-process transport.

## Approval and disclosure

Preview the exact request, pinned context, supporter, purpose, provider and expiry before
approving delivery. Grant the supporter request `read` and `act`, plus memory `read` and
`share` for each context item. `authorize_delivery_provider` separately grants the named
provider request and memory `read` and `share`. It grants no action authority or care-circle
membership. Provider grants appear in ordinary sharing views and can be revoked there.
Retries with identical provider scope and expiry reuse existing active grants.

Queue the approved request with `queue`, then call `enqueue_delivery`. Enqueue is idempotent
per request. A request cannot switch providers or use local `dispatch` after entering the
outbox. Enqueue and worker preparation both check current supporter and provider authority
and pinned memory revisions. Missing or revoked authority and stale context prevent sending.

```python
from datetime import datetime, timedelta, timezone
from care_continuity import CareApplication, Operation, SessionService, SQLiteStore
from care_continuity.outbox import DeliveryResult, OutboxService

with SQLiteStore() as store:
    app = CareApplication(store)
    sessions = SessionService(store)
    owner = sessions.issue("example-owner")  # Trusted host / synthetic identity only.
    app.add_member(owner, member="example-supporter", role="supporter")
    request = app.create_request(owner, recipient="example-supporter", purpose="visit",
                                 message="Synthetic visit request", idempotency_key="visit-1")
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    # A real interface must show the exact disclosure before these approvals.
    for operation in (Operation.READ, Operation.ACT):
        app.grant(owner, recipient="example-supporter", purpose="visit", resource_type="request",
                  resource_id=request, operation=operation, expires_at=expiry)
    app.authorize_delivery_provider(owner, request, provider="example-transport", expires_at=expiry)
    app.queue(owner, request)
    job = app.enqueue_delivery(owner, request, provider="example-transport")

    def example_transport(idempotency_key, payload):
        assert idempotency_key == job
        assert payload.message == "Synthetic visit request"
        assert not store.connection.in_transaction
        return DeliveryResult.UNKNOWN  # Simulate an ambiguous transport timeout.

    OutboxService(store).run_one(provider="example-transport", send=example_transport)
    assert app.deliveries(owner)[0]["state"] == "unknown"
    # Synthetic receipt lookup: a real adapter queries its provider using this ID only.
    OutboxService(store).reconcile(job, provider="example-transport",
                                  lookup=lambda key: DeliveryResult.RECEIVED)
    assert app.deliveries(owner)[0]["state"] == "received"
    assert app.read_request(owner, request).state.value == "delivered"
```

## Worker contract

Run `OutboxService.run_one(provider=..., send=...)` outside any database transaction.
Each worker uses its own store connection. Preparation takes one pending job under an
SQLite write transaction, rechecks consent, resolves context, and records a five-minute
lease and attempt. The network call takes place after that transaction commits.

The trusted adapter receives the stable job ID as its idempotency key and an authorized
`SupportRequest`. It must use provider-side idempotency and return one of these outcomes:

| Outcome | Meaning | Next behavior |
| --- | --- | --- |
| `RECEIVED` | Provider acknowledged receipt | Record receipt; mark request delivered only if still queued and authorized |
| `NOT_SENT` | Adapter guarantees no disclosure occurred | Retry after one minute, at most three attempts |
| `UNKNOWN` | Delivery may have happened | Stop automatic delivery; require reconciliation |

An ordinary exception or invalid result is treated as `UNKNOWN`; its text is never stored
or logged. If a worker crashes, another worker marks the expired sending lease unknown
instead of resending it. A late worker result cannot overwrite a job already recovered as
unknown. Provider receipt never means that a human accepted or completed the request.

Jobs and attempts persist identifiers, timestamps and outcomes only. They contain no care
text or cached payload. `deliveries` is an owner-only view of job metadata. Existing request
and memory services continue to govern subsequent access. Cancellation during an in-flight
send is preserved when the result arrives.

## Limits and remaining work

Consent is checked immediately before the transport call. Revocation cannot atomically
cancel an external operation already in flight or recall information already received.
The adapter must document its timeout, cancellation, retention and idempotency behavior.
A provider must be a trusted configured adapter identity, not an arbitrary client endpoint.
Do not log the payload, provider exception, tokens, or care text.

Unknown jobs stop automatic sending. A trusted host can call
`reconcile(job_id, provider=..., lookup=...)` to query a provider receipt using only the
stable job ID, outside a database transaction. The lookup must return `RECEIVED`,
`NOT_SENT` or `UNKNOWN`. Exceptions and invalid results leave the job unknown.

`NOT_SENT` must prove the original operation is definitively closed without delivery.
A missing receipt in an eventually consistent index is not sufficient: return `UNKNOWN`
unless the provider can guarantee no delayed original send remains possible. A definitive
negative result rechecks all consent and context, then schedules a retry after one minute
within the original three-attempt budget. Cancellation, revoked consent or stale context
blocks retry. `RECEIVED` records the receipt while preserving cancellation and rechecking
authority before marking the request delivered. Neither result accepts a request for a human.

The original unknown attempt is preserved. A separate metadata-only reconciliation event
records its resolution. Repeated reconciliation of a resolved job does not query the provider
again, and stale lookup results cannot overwrite a newer resolution or attempt. Do not create
a fresh request merely to retry an ambiguous send. Failed jobs also stop after
the bounded retries. The browser Deliveries page and session-bound API expose
pending, sending, received, blocked, failed and unknown states without conflating them with
human acceptance.

Model proposals, model-provider context authorization, an external transport with receipt lookup,
and browser delivery approval are still pending. Schema version 6 upgrades versions
1–5 transactionally without creating jobs for existing requests. No runtime dependency or
network provider was added.

## Browser status

Open **Deliveries** to see only your external delivery jobs, provider, attempt count,
and current request state. Receipt and human acceptance are shown separately. The page
contains no copied care text, lease tokens, or provider errors. Refreshing only reads status;
it never sends or reconciles a job. Uncertain outcomes explain why creating a duplicate
request is unsafe. Each job links to its request for existing cancellation and follow-up
controls, and to Sharing for revocation. Local inbox requests do not create delivery jobs.
