# Project checklist — done and next

Updated 23 October 2026. **This is the only progress checklist.** [Architecture](architecture.md) explains the code; the [original proposal](elderly-project-plan.md) explains the product idea.

**[x] = done for the stated task. [ ] = unfinished or not yet verified.** Code completion and release checks are separate tasks. The local demo is implemented; release verification remains open.

## Done

- [x] Core services: memory revisions, consent, request lifecycle and SQLite storage.
- [x] Local browser app: profiles, sharing, observations, care circle, history and export.
- [x] Knowledge tools: private submissions, reviews, qualifications and withdrawal.
- [x] D1 — startup: seed examples once and preserve changes when reopening the database.
- [x] D2 — suggestions: preview disclosure, generate locally, edit/discard and save a private draft. Reviews expire and are tied to the session.
- [x] D3 — delivery: approve a configured simulator, inspect outcomes and reconcile uncertain sends through a host-only runner.
- [x] D4 — attention: show outstanding actions, choose permission duration and recover editable input after validation errors.
- [x] Write startup and demonstration regression tests.

Evidence: [startup implementation](../src/care_continuity/demo.py), [review handles](../src/care_continuity/reviews.py), [browser routes](../src/care_continuity/web.py), [attention view](../src/care_continuity/demo_views.py), [startup tests](../tests/test_demo_startup.py) and [workflow tests](../tests/test_demo_workflows.py). These ticks record code inspected in the working tree, including uncommitted changes.

## Next — do these in order

- [ ] **1. Run checks:** run the full tests and both CLI tours; fix failures and record results.
- [ ] **2. Finish the guide:** document suggestion review, attention and the host delivery simulator in the [browser walkthrough](web.md).
- [ ] **3. Verify the demo:** complete the scenario checklist below using synthetic records and a persistent disposable database.
- [ ] **4. Check accessibility:** keyboard, narrow layout, zoom and an actual screen reader; record findings and unresolved issues. Get participant feedback on status labels and sharing decisions.
- [ ] **5. Check installation:** install in a clean environment and run the app. Build/install a wheel if packaging or entry points change.
- [ ] **6. Close D5 — release verification:** record results and remaining limits, then have the project owner review the demo.

The implementation maintainer owns checks and documentation. Participants provide usability feedback; the project owner reviews readiness. No target dates are assigned.

Run from the repository root:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m care_continuity.cli
PYTHONPATH=src python3 -m care_continuity.cli_sessions
```

## D5 — release scenario pack

Tick each scenario only after recording its result. Existing test code alone does not complete this release checklist.

- [ ] Start, edit, forget and restart: no duplicates, restored memories or restored relationships; legacy data and migration rollback are preserved.
- [ ] Remember, correct and inspect provenance.
- [ ] Submit a worker observation; accept or dismiss it while preserving authorship.
- [ ] Generate, edit and discard a suggestion; nothing is sent.
- [ ] Save a suggestion privately, separately approve sharing, then accept and complete support. Duplicate saves must not duplicate requests.
- [ ] Change/forget a source, log out, expire a review or restart: stale output cannot be saved; recovery is clear.
- [ ] Revoke provider consent before generation/delivery: no pending disclosure proceeds.
- [ ] Simulate received, definitely-not-sent and unknown outcomes. Refresh/restart must not resend an uncertain job; trusted reconciliation must preserve cancellation and revocation. Receipt is separate from human acceptance.
- [ ] Leave a request unanswered, reach its follow-up time and record the person's decision. Attention links lead to the right action.
- [ ] Withdraw a knowledge card; it disappears from retrieval.
- [ ] Switch profiles, expire a session and submit stale/tampered forms: no cross-person disclosure or unauthorized change. Generated text stays inert and absent from logs.
- [ ] Complete the main flows by keyboard; inspect narrow layout and zoom; record screen-reader findings. Verify safe validation recovery, exact permission expiry, cancellation and refusal.

## Later — outside this demo release

- [ ] Select **one live integration** after reviewing demo findings: a text model or a delivery provider. Define retention, timeouts, costs, retries and failure recovery; test with synthetic data first.
- [ ] Add verified sign-in, account mapping and authorization for setup and representative access before a real care-data pilot or network deployment.
- [ ] Complete pilot preparation: threat model, retention/backups, named operator and care partner, escalation and incident procedures, and consented user evaluation.
- [ ] Collect 10–15 real reviewed knowledge cards with rights evidence and accountable reviewers. Complete external credential verification; fixtures do not count. Any cited-answer feature needs source-fidelity checks.
- [ ] Add voice after text flows are usable and audio disclosure/retention is defined. Verify text parity, pacing, interruptions and misheard refusals with older adults.

Unscheduled ideas: temporary preferences (define expiry first), reviewable handover briefs (preserve provenance and invalidate stale sources), and optional “Did this help?” notes (person-controlled retention, no automatic health inference).

Payments, medication changes, sensors, autonomous outreach, broad health-record integration and clinical claims remain outside this release.

## Verification record

No new tests or browser checks were run during these documentation updates. The user reported “done” after receiving run instructions; individual commands and results were not specified, so release checks remain unticked.

Earlier documentation recorded 155 passing tests on Python 3.14.6 before the latest demo changes. This is historical evidence, not a result for the current working tree. CI is configured for Python 3.11–3.14.

When completing a check, record: **date · command or manual steps · environment · result · remaining issues**. Tick only that completed task. Automated tests do not establish usability or clinical effectiveness.
