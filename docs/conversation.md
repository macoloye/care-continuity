# Model suggestion boundary

`ConversationService` provides a session-bound foundation for replaceable text-model
adapters. No live model or browser conversation interface is configured. Adapters are
trusted host code, configured by provider identity at construction; clients cannot
supply a callback or endpoint. Their returned content is untrusted.

The first supported task is drafting a support message from one to twenty selected
memory revisions. Before `authorize`, the interface must preview the exact selected
text, its provenance, the configured provider, purpose `draft-support-request`, and
expiry. Authorization grants that provider memory read and share only. Identical
approval retries reuse active grants with the same expiry. Grants appear in the ordinary
sharing view and can be revoked there. Neither membership nor action authority is added.

```python
from datetime import datetime, timedelta, timezone
from care_continuity import CareApplication, SessionService, SQLiteStore
from care_continuity.conversation import ConversationService

with SQLiteStore() as store:
    app = CareApplication(store)
    token = SessionService(store).issue('example-owner')  # Synthetic trusted host.
    memory = app.remember(token, text='I prefer short visits agreed in advance.')
    selected = ((memory.id, memory.revision),)

    def example_model(context):
        assert len(context.memories) == 1
        assert not store.connection.in_transaction
        return {'kind': 'request_draft', 'message': 'Could we agree a time for a short visit?'}

    conversation = ConversationService(store, adapters={'example-model': example_model})
    # A real interface must preview this exact disclosure and obtain the person's approval.
    conversation.authorize(token, provider='example-model', selections=selected,
                           expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    suggestion = conversation.suggest(token, provider='example-model', selections=selected)
    assert suggestion.dependencies == selected
    assert app.requests(token) == []  # No request is saved or sent.
    app.add_member(token, member='example-supporter', role='supporter')
    # After the person reviews the text, recipient, purpose and all source context:
    draft = conversation.save_draft(token, suggestion,
        reviewed_message='Could we agree a time for a short visit?',
        recipient='example-supporter', purpose='visit', idempotency_key='review-1')
    assert app.read_request(token, draft).state.value == 'draft'
    # Sharing still requires the ordinary exact-draft preview and separate approval.
```

Generation rechecks session, ownership, purpose-specific read/share consent and pinned
revisions in a transaction, then calls the adapter outside the transaction. It repeats
those checks before returning the suggestion. Revocation, expiry, forgetting, changed
revisions or an ended session prevent subsequent return. The model receives only the
selected memory records (including source and confirmation status) and fixed purpose;
it receives no bearer token, service handle, other memories, or client free-text prompt.

The output must have exactly `kind: request_draft` and a nonblank `message` of at most
4,000 characters. Action fields and other kinds are rejected. Instructions within the
message remain inert text. A host must render it as escaped, untrusted proposed content,
never as markup, a command, or evidence of consent. Schema validation is not a factual
or clinical quality check. Adapters must preserve provenance in their prompts and be
evaluated separately for content quality and handling malicious source text.

Suggestions are ephemeral: no prompts, copied context or results are persisted or logged.
Provider exceptions become a generic error without a chained payload. Automatic retries
are not performed. There is no derived-artifact cache to invalidate. Returned objects,
provider retention and already in-flight disclosure cannot be recalled; a host must discard
old suggestions after a context or permission change and never silently persist them.

## Save a reviewed suggestion

`save_draft(token, suggestion, reviewed_message=..., recipient=..., purpose=...,
idempotency_key=...)` saves only the explicitly reviewed message. It does not use the
original generated message as a fallback, contact the model again, add grants, queue,
or deliver. The person must review the message, chosen supporter, purpose and every
source memory before invoking this operation. Sharing still requires the existing
exact-draft preview and separate `approve_request` step.

The host must retain the original suggestion's provider and complete dependency list;
these are trusted orchestration inputs, not editable model or client fields. A
`RequestSuggestion` is a value object, not a signed approval or proof of model origin.
No browser endpoint accepting serialized suggestions is exposed. A future browser
integration needs a protected, invalidatable review mechanism before accepting edits.

Saving rechecks the session, memory ownership, pinned revisions, model-provider consent
and current supporter membership in the same transaction as creating the draft. If any
check fails, nothing is saved. All source memories become draft context, even if the
reviewed message does not quote them; the later sharing preview must include them.
The existing forgetting behavior therefore redacts the derived draft message and cancels
unfinished requests when any source is forgotten. Saved drafts follow the ordinary request
lifecycle and retention rules, while unsaved model output remains ephemeral.

The same idempotency key and reviewed content return the existing request without another
creation event. Changed content conflicts. Session, permissions and source revisions are
checked even on a retry; a previously saved request does not authorize stale reuse.

Live adapters, retention/timeout contracts, proposal approval UI, conversational free-text
consent and model-quality evaluation remain future work.
