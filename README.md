# Care Continuity

Reusable memory, consent, and follow-through components for care assistants.

The person receiving support controls what is remembered and shared. A request stays visibly unfinished until the chosen supporter accepts and completes it. Permission checks run in ordinary application code, independently of any language model.

This repository is an early implementation of the [project proposal](docs/elderly-project-plan.md). It contains a Python library, command-line walkthroughs, a browser application, and executable scenarios.

## Run the command-line tour

Python 3.11 or later is required. The library has no runtime dependencies.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
care-continuity
care-continuity-sessions
python -m unittest discover -s tests -v
```

To try it without installing anything, from this directory:

```sh
PYTHONPATH=src python3 -m care_continuity.cli
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The tour follows Mei, her daughter Lina, and a visiting worker. Mei changes a preference, approves a garden visit, and withdraws the worker's access before a handover is delivered. It runs entirely in memory.

The sessions walkthrough exercises separate owner and caregiver sessions, a consent-filtered inbox, follow-up deadlines, account export, and care-circle removal. Without installation, run `PYTHONPATH=src python3 -m care_continuity.cli_sessions`.

## Try the browser interface

Run `care-continuity-web`, then open [the local application](http://127.0.0.1:8765). Without installation, use `PYTHONPATH=src python3 -m care_continuity.web`. Pass `--db PATH` to keep records in an SQLite file between runs; by default they are held in memory.

Choose a profile to edit memories, review sharing, approve a request, accept it from the caregiver's inbox, or record an observation for the person to review. The interface works without JavaScript. See the [walkthrough and implementation notes](docs/web.md).

## What works

| Component | Current behavior |
| --- | --- |
| Memory | Attributed preferences, observations, and interpretations; revisions; owner-only history; forgetting; current memory summaries; circle-member observations with owner approval. |
| Consent | Exact recipient, purpose, resource, operation, and expiry; explicit revocation; no automatic family or staff access. |
| Delegation | Draft, queue, local delivery, acceptance, completion, cancellation, and blocked delivery; idempotent retries. |
| Knowledge | Session-bound private submissions; audience, setting and language metadata; publication-rights evidence; independent review history; scoped qualification records with expiry and revocation; contributor withdrawal. |
| Delivery outbox | Durable jobs, separate provider consent, leases, safe retries, unknown outcomes and trusted receipt reconciliation; no live transport configured. |
| Model suggestions | Replaceable host-configured adapter boundary, explicit provider consent, selected revisions, structured suggestions and explicit reviewed-draft saving; no live model configured. |
| Persistence | SQLite records and transactions, with metadata-only audit events. |
| Application | Revocable bearer sessions, care-circle management, filtered inboxes, owner request views, follow-up deadlines and recorded outcomes, observation review, and account export. |
| Browser app | Memory editing, explicit sharing preview, request lifecycle, observation contribution and review, follow-up outcomes, care-circle removal, history, export, and knowledge contribution, review, search and withdrawal through local forms. A local setup console adds people and manages care-circle relationships. |

See the [documentation index](docs/README.md) for completed work, remaining release checks, and the ordered plan.

## Use a component

```python
from care_continuity import ConsentService, MemoryService, SQLiteStore

with SQLiteStore() as store:  # Pass a file path for persistence.
    consent = ConsentService(store)
    memory = MemoryService(store, consent)
    item = memory.remember(
        actor="mei", subject="mei", source="mei",
        text="I prefer breakfast after 8.", confirmed=True,
    )
    updated = memory.revise(
        item.id, actor="mei", text="Breakfast at 9 suits me better.",
        expected_revision=item.revision,
    )
    assert updated.revision == 2
```

Actor IDs in this example are supplied by trusted application code. They are not authentication credentials. An HTTP adapter must derive the actor from a verified session before calling the library.

- [Model suggestion boundary](docs/conversation.md)
- [Durable delivery API and limits](docs/delivery.md)
- [Knowledge pilot API and remaining requirements](docs/knowledge.md)
- [Next release: complete local demonstration](docs/next-release-plan.md)
- [Architecture](docs/architecture.md)
- [API behavior and boundaries](docs/api.md)
- [Session-bound application API](docs/application.md)
- [Care needs and scenario coverage](docs/scenarios.md)
- [Contributing](CONTRIBUTING.md)
- [Security and data handling](SECURITY.md)

Code and original repository documentation are available under the [MIT license](LICENSE). Linked third-party material retains its own terms.
