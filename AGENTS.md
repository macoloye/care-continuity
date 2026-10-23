# Working on Care Continuity

These instructions apply to this repository and its subdirectories. Read the files relevant to the change before editing; preserve unrelated work.

## Project context

Care Continuity provides reusable memory, consent, knowledge, and delegation components for care assistants. The person receiving support controls their record and sharing decisions.

Start with [README.md](README.md) for setup and current features. Use [elderly-project-plan.md](docs/elderly-project-plan.md) for product intent, [docs/architecture.md](docs/architecture.md) for architecture, and [docs/next-release-plan.md](docs/next-release-plan.md) as the only checklist for completed work and next steps. Keep planned capabilities distinct from working code. Keep all plans and progress records under `docs/`; use [docs/README.md](docs/README.md) as the planning index and update release status when implementation changes.

The current browser application runs locally. Its profile chooser does not verify identity. Keep it bound to loopback; do not turn it into a public service as a side effect of another change.

## Architecture

Code lives in `src/care_continuity/`; tests live in `tests/`.

| Module | Owns |
| --- | --- |
| `domain.py` | Shared records, enums, errors, and clock types |
| `store.py` | SQLite schema, migrations, transactions, and metadata-only events |
| `consent.py` | Recipient, purpose, resource, operation, expiry, and revocation checks |
| `memory.py` | Provenance, revisions, current views, history, forgetting, and observation contribution |
| `conversation.py` | Provider-authorized context and ephemeral structured model suggestions |
| `outbox.py` | Provider disclosure checks, durable jobs, attempt outcomes and transport boundary |
| `delegation.py` | Request state transitions and authorization at delivery and action time |
| `qualifications.py` | Private external-check attestations, exact scope, expiry, and revocation |
| `knowledge.py` | Separate submission, review, retrieval, and withdrawal |
| `sessions.py`, `circle.py` | Bearer sessions and care-circle membership |
| `directory.py` | People directory and relationship setup behind the local console |
| `application.py` | Session-derived identity and operations composed across services |
| `web.py`, `web_views.py`, `static/` | Local HTTP boundary, escaped HTML, and presentation |

Keep policy decisions in the services. Web and future model or voice adapters call those services; they must not implement a second permission system. Add focused modules when responsibilities diverge. Avoid introducing a general agent framework or speculative abstraction.

## Rules to preserve

- Access is private by default. Family relationships, worker roles, and circle membership do not grant access. Scope permission to the person, recipient, purpose, resource, operation, and time.
- Reading, sharing in a handover, and acting are separate permissions. Recheck authority before delivery, acceptance, completion, and subsequent reads.
- Resolve the application actor from the session. Never trust an actor ID from form fields or another client payload. Session issuance is a privileged API used only after identity verification, or inside the local profile chooser.
- A preference, another person's observation, and an interpretation stay distinct. Preserve provenance; do not silently replace the person's wishes with someone else's account. A circle member's observation stays private to the person until accepted; acceptance confirms review, not authorship, and the contributor remains the source.
- Corrections use expected revisions. Request context pins memory revisions; a changed context requires a fresh approved draft rather than silently changing approved content.
- Draft, delivered, accepted, and completed mean different things. Retries must not duplicate requests, grants, or actions. An unanswered request must remain visibly unanswered.
- Revocation and forgetting must reach every application-controlled view and dependent copy. When adding caches, prompts, indexes, notifications, or exports, account for their dependencies and retention. Do not claim that logical deletion erases backups or recalls information already seen.
- Care text, session tokens, and prompts do not belong in logs or audit events. Use example data in fixtures, walkthroughs, issues, and screenshots.
- Knowledge publication needs separate authorization and review. Keep experience labelled as experience; exclude drafts, withdrawn cards, and overdue cards from retrieval. Professional guidance publication remains disabled until qualified-review support exists.
- A future model may propose content or actions. It cannot authorize storage, disclosure, or execution. Sending context to a model provider is itself a disclosure requiring appropriate permission.

## Implementation style

Use Python 3.11-compatible syntax; CI covers Python 3.11–3.14. The package currently has no runtime dependencies. Prefer the standard library when it fits, and add dependencies only when they solve a concrete need.

Annotate public APIs and shared records. Use names that describe care or application behavior. Add docstrings for contracts and comments for non-obvious decisions or boundaries; avoid narrating straightforward code.

Keep authorization checks and their database operations in one transaction. Nested operations use savepoints. Use parameterized SQL for values, one store connection per thread, and timezone-aware timestamps. Inject clocks into time-dependent behavior. Keep network calls outside database transactions.

Every schema change needs a versioned, transactional migration. Test preservation of existing records, reopening the upgraded database, and rollback after migration failure. Reject unsupported versions.

For browser changes, preserve labelled native controls, headings and landmarks, keyboard access, visible focus, responsive layout, HTML escaping, and explicit sharing previews. Keep mutations behind POST, session validation, and CSRF checks. Include new static assets in package data.

## Commands and verification

Run commands from the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
care-continuity
care-continuity-sessions
care-continuity-web
```

Without installation, use `PYTHONPATH=src python3 -m unittest discover -s tests -v`. Entry modules are `care_continuity.cli`, `care_continuity.cli_sessions`, and `care_continuity.web`.

The web application opens at `http://127.0.0.1:8765`. HTTP tests bind an ephemeral loopback port, so restricted environments may need local networking permission. Follow [docs/web.md](docs/web.md) for the browser walkthrough. Stop preview servers you started after verification.

Add meaningful regression scenarios for changes to authority, persistence, lifecycle, or disclosure. Test failure paths as well as the successful workflow. For UI changes, check the browser flow and keyboard behavior; do not infer accessibility conformance from passing HTML or service tests. Documentation-only edits need link and content checks rather than a new test suite.

If packaging or entry points change, build a wheel and verify installation and the affected command in a clean environment. Report checks actually run and any remaining limits; do not claim CI or user evaluation passed without evidence.

## Documentation and handoff

Write plain, specific prose. Explain behavior, decisions, and practical limits once, linking to the detailed source instead of repeating it. Avoid promotional language, filler, generated-sounding summaries, and comments that merely restate names.

Update the relevant API or workflow guide when behavior changes, and update the project checklist when task status changes. Preserve the original product proposal unless the task calls for revising it. Keep examples executable and self-contained where practical.

In the final handoff, state what changed, why it matters, what was verified, and any material unfinished work. Follow [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) for contribution and data-handling details.
