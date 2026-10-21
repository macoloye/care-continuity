# Knowledge pilot

The service foundation for milestone 3 supports private submissions, independent review,
and a public catalogue of current experience and procedure cards. The local browser
interface exposes submission, inspection, review, search and withdrawal. No fixture or command-line example is a genuinely reviewed care card.

Each submission records its contributor, source citation, audience, care setting, language,
limitations, and submission time. Publication requires a separate explicit authorization
and written evidence of publication rights. Reviewers record evidence of their source,
privacy, and scope checks and set a future review deadline. First publication time is
preserved when a card is reviewed again; each review remains in its private history.

Audience describes who the content is useful for. It does not restrict access: published
cards are available to everyone through the low-level catalogue. Organization-only or
restricted publications are not supported. Rights evidence and review notes are visible
only to the contributor and host-configured reviewers, including after withdrawal.

## Run a synthetic example

Run this from the repository root after installation, or with `PYTHONPATH=src`:

```python
from datetime import datetime, timedelta, timezone
from care_continuity import CareApplication, SessionService, SQLiteStore

with SQLiteStore() as store:
    app = CareApplication(store, reviewers=frozenset({"example-reviewer"}))
    sessions = SessionService(store)
    # Trusted host only: real sessions require verified identities before issuance.
    author = sessions.issue("example-author")
    reviewer = sessions.issue("example-reviewer")
    reader = sessions.issue("example-reader")
    card = app.submit_knowledge(
        author, title="Example visit experience", kind="experience",
        body="In this invented example, a supporter asked about visit timing.",
        source="Synthetic repository example", audience="Supporters",
        setting="Home visits", language="en", limitations="Not care guidance",
        publication_rights="Original synthetic text supplied for this demonstration",
        publication_authorized=True,
    )
    assert app.search_knowledge(reader) == ()
    assert app.knowledge_submissions(reader) == ()
    assert app.knowledge_submissions(reviewer)[0].id == card
    app.review_knowledge(
        reviewer, card, review_due=datetime.now(timezone.utc) + timedelta(days=7),
        privacy_checked=True, scope_checked=True,
        evidence="Synthetic example checked for attribution, privacy and limited scope",
    )
    assert app.search_knowledge(reader)[0].source == "Synthetic repository example"
    assert len(app.knowledge_evidence(author, card)["reviews"]) == 1
    app.withdraw_knowledge(author, card)
    assert app.search_knowledge(reader) == ()
```

Session validation and each service operation share a transaction. A revoked or expired
session cannot submit, inspect drafts, review, or withdraw. A contributor cannot review
their own card, even if configured as a reviewer. Review notes and publication-rights text
are stored in editorial tables, never audit events. These tables need the same storage
protection as the rest of the database.

Withdrawal removes a card from subsequent searches immediately. It cannot recall copies
already read or exported. A withdrawn card cannot be reviewed back into publication;
submit a replacement for independent review. An overdue card is also excluded from search,
but an authorized independent reviewer can renew it with new evidence and a future deadline.

## Existing databases and callers

Schema version 5 upgrades versions 1–4 transactionally. Cards from versions 1–3 retain their content
and status, but have no invented publication dates, rights evidence, or metadata. They are
excluded from search. Submit a new complete card and review it to make that content available
again; the original remains accessible through the private submissions API.

Low-level `KnowledgeService.submit` now requires `audience`, `setting`, `language`,
`limitations`, and `publication_rights`. `review` now requires `evidence`. The demonstration
and tests use these fields explicitly. There is no automatic migration that fabricates
permissions or review evidence.

## Remaining pilot work

The milestone remains in progress. It still needs verified identity
integration, external verification of credential evidence, and 10–15 genuinely reviewed
cards from authorized contributors. Reviewer IDs are host configuration; neither a configured
ID nor written evidence proves credentials or publication rights. Professional guidance
publication remains disabled. The person responsible for the pilot must establish those
review arrangements before collecting real contributions.

## Browser workflow

Run `care-continuity-web` and choose Mei. Open **Knowledge → Contribute a card**,
complete the metadata and publication-rights fields with synthetic content, and explicitly
authorize publication after review. **Submit private draft** opens the stored card and its
private evidence. Other ordinary profiles cannot inspect the draft.

Leave the profile and choose **Sam (demo reviewer)**. Open **Knowledge → Submissions**,
select the card, inspect its exact content and rights evidence, and record source, privacy
and scope checks. Set a review interval of 1–365 days and choose **Record review and publish**.
The card now appears in the library. Its private evidence does not appear in search results.
A contributor or reviewer can withdraw it from its inspection page.

Sam is a local demonstration identity, available through the same unverified profile chooser
as the other profiles. It is not a professional qualification or production login. Reviewer
authority is configured by the host and enforced by services on every action. Professional
guidance is not offered in the submission form and cannot be published through a forged form.

## Qualification records

The trusted host can configure independent qualification verifiers. They record evidence of
checks performed outside this software, scoped to an exact card kind, setting and language.
This does not contact a credential issuer or prove identity. Qualifying someone does not
add them to the editorial reviewer list. Evidence is private to that reviewer and the
host-configured verifiers; contributors see only the qualification ID linked to a review.

```python
from datetime import datetime, timedelta, timezone
from care_continuity import CareApplication, SessionService, SQLiteStore

with SQLiteStore() as store:
    app = CareApplication(store, reviewers=frozenset({"editor"}),
                          qualification_verifiers=frozenset({"verifier"}))
    sessions = SessionService(store)
    # Synthetic identities only; production issuance requires verified identity.
    verifier = sessions.issue("verifier")
    editor = sessions.issue("editor")
    qualification = app.record_qualification(
        verifier, reviewer="editor", kind="procedure", setting="Home", language="en",
        evidence="Synthetic external-check reference; not a real credential",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        idempotency_key="example-check-1",
    )
    assert app.qualifications(editor, reviewer="editor")[0]["active"]
    app.revoke_qualification(verifier, qualification)
    assert not app.qualifications(editor, reviewer="editor")[0]["active"]
```

Pass `qualification_id` to `review_knowledge` to bind an experience or procedure review to
an active, matching record. The review deadline cannot outlast qualification expiry. Search
rechecks the linked qualification on every call; revocation or expiry hides dependent cards.
Renewal requires a current matching record and cannot silently remove this dependency.
Withdrawal remains available. Nothing recalls copies already seen.

The existing browser demo supports ordinary experience and procedure review. Qualification
recording and qualified renewals currently use the session-bound API; the browser configures
no qualification verifiers. Professional guidance remains disabled even with a qualification
record. The migration preserves version-4 cards and reviews with null qualification links,
without inventing qualification evidence or changing their existing search behavior.
