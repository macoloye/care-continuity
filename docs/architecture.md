# Architecture

How the application is built. For completed work and next steps, use the [project checklist](next-release-plan.md).

## Design

The application is a small Python package around SQLite and a deterministic CLI tour. Python makes the components easy to reuse in assistant applications and evaluation scripts. SQLite keeps the first version runnable without a server. Neither choice commits later interfaces to a model provider.

The implementation covers three workflows: remember and revise, request support, and hand over and revoke. The local browser interface exposes these through labelled forms and an approval preview. It uses a local profile set and a local mailbox. Conversational input, verified login, and full accessibility evaluation remain open.

## Module boundaries

```text
Local text interface / future voice adapter
             |
Session-bound application API
             |
     memory   delegation   knowledge
        \       /
          consent
             |
        SQLite store
```

| Module | Responsibility | Must not do |
| --- | --- | --- |
| `domain` | Typed records, lifecycle values, errors, clock interface | Depend on a model or UI |
| `consent` | Resolve exact grants and expiry | Infer authority from relationships |
| `memory` | Store provenance, revisions, current views, and deletion | Turn an observation into a stated preference |
| `delegation` | Manage requests and recheck authority | Treat delivery as acceptance |
| `knowledge` | Keep submission, review, and retrieval separate | Publish personal memory automatically |
| `store` | Persist records and serialize service mutations | Decide who may access care text |
| `cli`, `cli_sessions` | Assemble services around a guided walkthrough | Present fixtures as reviewed care guidance |
| `sessions` | Issue and resolve revocable bearer sessions after verified identity | Treat a claimed actor ID as a login |
| `circle` | Manage relationships and end a member's access | Treat membership as permission |
| `directory` | Local people directory and relationship setup for the trusted setup console | Read care data, create grants, or act as a domain-wide administrator |
| `application` | Derive actors from sessions; expose account views, export, and follow-up plans | Accept client-supplied actor identities |
| `web`, `web_views` | Local HTTP forms, escaped rendering, and explicit approval previews | Expose a production login or bypass services |

Services receive a store and a clock. Tests advance the clock without sleeping. Constructors are the composition boundary; there is no agent framework or hidden global client. A repository protocol should be introduced when a second storage implementation is actually needed.

## Records and authority

**Memory** carries a subject, kind, source, text, confirmation flag, revision, and timestamps. Corrections use an expected revision to prevent lost updates. Historical text is available only to the person. Active care-circle members can record observations about the person; these stay private in the person's review inbox until the person accepts or dismisses them. Acceptance confirms review while keeping the contributor's attribution.

**Consent grants** bind one person, recipient, purpose, resource ID, operation, and expiry. `read`, `share`, and `act` are separate operations. The person retains access to their own records. This first version deliberately has no wildcard grants, delegated consent authority, or inferred emergency exceptions.

**Support requests** store an exact message, named recipient, purpose, idempotency key, and state. Context links pin memory IDs and revisions rather than copying memory text. The person previews the draft, grants access and action authority, then queues it. Disclosure of linked memory also requires `share` permission for that recipient and purpose.

```text
draft -> queued -> delivered -> accepted -> completed
            |
            +-> blocked

Any unfinished state -> cancelled (person only)
```

A blocked request requires a new approved draft. Editing an approved message in place is intentionally unsupported. A changed memory revision also requires a new draft. Pending and historical recipient views resolve current permissions; revocation can therefore stop access to a previously delivered local message.

**Knowledge cards** retain the contributor, source, kind, reviewer, review deadline, and status. Only reviewed, current experience and procedure cards are retrieved. Professional guidance is blocked from publication until qualified-review verification is implemented. Public and organization-only catalogues will need separate access rules before real contributions are accepted.

**Audit events** record actor, subject, resource ID, action, and time. They omit care text. They are useful for debugging and a future history view, but are not a tamper-proof audit system.

## Consistency and disclosure

Authorization checks and related writes occur in one SQLite transaction. Each connection belongs to one thread. Recipient request reads also run within a transaction, so permission and content checks use a consistent database view. Remote actions must never execute inside this database transaction.

The [durable delivery outbox](delivery.md) implements leased jobs, stable transport idempotency keys, attempt records, and authorization checks before sending. Trusted receipt reconciliation is implemented; a live provider and its receipt lookup adapter remain pending. Provider receipts must be distinct from human acceptance. Exactly-once remote delivery cannot be assumed; an ambiguous timeout must not produce an untracked resend.

The current implementation persists no generated summaries, embeddings, external notifications, or model prompts. Forgetting removes revision text, blanks the current memory, revokes its grants, and redacts linked request messages. It leaves identifiers and lifecycle metadata. SQLite free pages, backups, process memory, exports, and already viewed information are outside this logical deletion guarantee. A production retention policy and erasure process are required before real records are used.

The model-suggestion service enforces a purpose-specific, already authorized context bundle; live adapters remain pending. The provider itself is a recipient requiring consent. Model output may propose changes; it cannot commit memories, grant access, or execute support actions directly. Derived artifacts will need dependency IDs, revision tracking, and invalidation before they can be cached.

