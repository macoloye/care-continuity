# Technical implementation plan

Status: core, session-bound services, local text interface, worker contribution and approval inboxes, follow-up resolution, and knowledge pilot services and browser workflow implemented, with qualification records and durable delivery outbox added 21 October 2026. Product requirements come from the [project plan](../elderly-project-plan.md).

## First implementation

Build a small Python package around SQLite and a deterministic CLI tour. Python makes the components easy to reuse in assistant applications and evaluation scripts. SQLite keeps the first version runnable without a server. Neither choice commits later interfaces to a model provider.

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

Future model adapters must receive a purpose-specific, already authorized context bundle. The provider itself is a recipient requiring consent. Model output may propose changes; it cannot commit memories, grant access, or execute support actions directly. Derived artifacts will need dependency IDs, revision tracking, and invalidation before they can be cached.

## Milestones

| Milestone | Deliverables | Exit criteria | Status |
| --- | --- | --- | --- |
| 1. Deterministic core | Library, local walkthroughs, SQLite persistence, scenario tests, contributor docs | All three workflows run; correction, revocation, expiry, deletion, and retries have executable checks | Implemented |
| 2. Accessible text application | Verified sessions; memory, sharing, request and history views; draft approval; export; worker contribution inbox | A person can inspect and correct memory, refuse sharing, cancel help, and identify who accepted it; keyboard and screen-reader checks pass | Implemented locally, including worker contribution and approval inboxes and follow-up resolution; identity-provider integration and accessibility evaluation with users pending |
| 3. Knowledge pilot | Card schema with audience, setting, language, limitations, publication and review dates; authenticated contributor/reviewer workflow; qualified-review records | 10–15 genuinely reviewed cards, private submission review, citations and withdrawal tests; no fixture counted as reviewed care content | Service foundation implemented: metadata, private session-bound editorial workflow, browser contribution and review, rights evidence, review history, scoped qualification attestations and withdrawal. Verified identity, external credential verification and 10–15 real reviewed cards pending |
| 4. Conversation and external delivery | Replaceable text-model interface, provider consent, structured proposals, durable outbox, delivery adapters, overdue-request follow-up | Prompt injection cannot bypass services; ambiguous transport failures do not duplicate actions; lack of acceptance is surfaced | Durable outbox foundation implemented with provider consent, leases, attempt records, bounded safe retries, and ambiguous-outcome handling. Trusted receipt reconciliation and private browser delivery status implemented; session-bound model suggestions and explicitly reviewed draft saving implemented; live model adapter, external transport and browser delivery approval pending |
| 5. Voice and longitudinal evaluation | Replaceable transcription/speech interface, pacing and interruption handling, refusal confirmation, multi-session scenarios | Same three workflows work through voice; misheard refusal and interruption tests pass; accessibility testing includes older adults | Planned |
| 6. Partner readiness | Threat model, retention controls, identity and representative verification, local escalation procedures, operational ownership | Named care partner reviews workflows and limits; deployment checks and incident process are agreed | Planned |

## Next implementation order

1. Connect a verified identity provider to session issuance and account selection. The current service validates bearer sessions but intentionally does not implement login or identity proofing.
2. Test the existing text interface with screen readers, complete keyboard traversal, zoom, and older adults. Improve form recovery, configurable permission duration, and purpose selection based on findings.
3. Connect the knowledge pilot workflow to verified reviewer identities. Metadata, private rights evidence, and review history are implemented; evidence text records an attestation and does not independently verify it. Scoped qualification records now retain external-check evidence and enforce expiry and revocation on linked cards. Verified identity and external credential verification remain prerequisites for professional guidance. Collect 10–15 real cards only after these human review arrangements are established. See [knowledge pilot](knowledge.md).
4. Add a model adapter after the manual workflows are usable. Run the same scenarios against each adapter; keep deterministic permission tests separate from model-quality evaluations.

## Verification

The current suite contains 133 tests. Model-boundary tests cover exact disclosure, pinned revisions, private context, in-flight invalidation, inert model commands, atomic approval retries and sanitized provider failures. Reviewed-draft tests cover separate sharing approval, changed permissions and revisions, idempotent saves, recipient membership and forgetting all source dependencies. Core scenarios cover expiry, isolation, conflicting observations, deletion, revocation, retries, worker observation contribution, and knowledge withdrawal. Application and migration tests cover sessions, exports, follow-up planning and resolution, observation review, membership removal, and atomic upgrades from versions 1–5. Outbox tests cover provider disclosure consent, safe retries, crash recovery, ambiguous outcomes, stale context, in-flight cancellation, receipt reconciliation, stale lookup fencing, reconciliation retry budgets and distinct delivery/acceptance states. Qualification tests cover independent verifier authority, private evidence, exact scope, expiry, revocation, retry safety, dependent search invalidation, and migration rollback. Knowledge pilot tests cover metadata and citations, private editorial evidence, independent review, session revocation, terminal withdrawal, review renewal, legacy-card exclusion, and migration rollback. Web tests cover private delivery status, receipt versus acceptance, read-only uncertainty refresh, and preview-to-completion flows, stale approvals, escaped content, CSRF checks, profile isolation, observation forms, and real loopback HTTP checks for headers and cross-origin requests.

CI is configured for Python 3.11–3.14. Local verification on this implementation used Python 3.14.6. The suite shows software behavior; it does not establish clinical effectiveness, usability, or suitability for deployment.
