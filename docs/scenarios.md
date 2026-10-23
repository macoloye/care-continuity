# Care needs and scenario coverage

All records and people used by the tests are example data. Run `python -m unittest discover -s tests -v` after installing the package. Scenario names below refer to methods in [test_scenarios.py](../tests/test_scenarios.py).

| Person's need | Expected behavior | Executable coverage |
| --- | --- | --- |
| "I want some privacy." | Nobody gains access just by being family or staff. | `test_private_by_default`, `test_relative_cannot_grant_or_change_permission` |
| "Keep my record separate." | A worker's access has a specific person, purpose, and resource. | `test_permission_is_bound_to_recipient_purpose_and_person`, `test_other_persons_memory_cannot_enter_request` |
| "My wishes can change." | Current summaries use corrections; stale edits fail. | `test_correction_updates_summary_and_retains_owner_history`, `test_stale_edit_does_not_overwrite_new_preference` |
| "That is their observation, not my preference." | Another account remains separate. | `test_observation_does_not_overwrite_persons_wishes` |
| "Show me what others noticed." | Circle-member observations wait in the person's private review inbox; acceptance keeps attribution; dismissal and withdrawal remove them. | `test_worker_observation_stays_separate_until_accepted`, `test_worker_observation_awaits_owner_acceptance` |
| "Only until tomorrow." | Access stops at the exact expiry time. | `test_permission_expires_at_exact_boundary`, `test_invalid_expiry_and_nonexistent_resource_are_rejected` |
| "Stop sharing this." | New summaries and pending handovers respect revocation. | `test_revoke_removes_current_summary`, `test_revocation_blocks_queued_handover` |
| "Forget what I told you." | Forgotten text cannot reappear through history or linked messages. | `test_forgetting_purges_history_and_redacts_linked_message` |
| "Ask before involving someone." | A draft is inaccessible until explicitly approved and delivered. | `test_no_approval_means_no_delivery`, `test_read_permission_does_not_allow_sharing_or_acting` |
| "Tell me whether someone agreed." | Delivery, acceptance, and completion stay distinct. | `test_full_loop_and_retries_do_not_duplicate_events`, `test_unanswered_request_stays_delivered` |
| "Check before acting on old plans." | Changed context and expired authority stop follow-through. | `test_correction_blocks_previously_approved_context`, `test_expiry_blocks_completion_and_old_message_access` |
| "I can change my mind." | Cancellation stops unfinished requests. | `test_cancellation_prevents_execution` |
| "Don't ask twice because the connection failed." | Repeated calls do not duplicate requests or lifecycle events. | `test_idempotency_key_is_scoped_and_payload_checked`, `test_full_loop_and_retries_do_not_duplicate_events` |
| "Tell me what happened after." | A due follow-up can be closed with a recorded outcome; replanning starts a fresh one; no reminder is sent. | `test_followup_resolution_records_outcome_and_clears_flag`, `test_followup_outcome_can_be_recorded` |
| "Use guidance I can trust." | Draft, overdue, and withdrawn cards are excluded; source kinds remain visible. | `test_draft_and_withdrawn_knowledge_are_not_retrieved`, `test_overdue_knowledge_stops_appearing` |
| "My story isn't automatically public." | Publication and review are separate decisions. | `test_publication_requires_separate_authorization_and_review` |
| "Don't call an anecdote professional advice." | Guidance cannot bypass qualified review. | `test_professional_guidance_cannot_bypass_qualified_review` |
| "Remember without leaving private text in logs." | Persistent memory survives reopening; audit events omit care text. | `test_file_database_survives_reopen`, `test_audit_events_do_not_store_care_text` |

## Scenarios still needed

The product plan extends beyond this core. Keep these requirements open until the corresponding interface or adapter exists:

- **Misheard refusal:** transcription changes "don't send" to "send". A consequential action needs a clear confirmation; uncertain speech cannot authorize it.
- **Let me finish:** long pauses and corrections do not interrupt or discard the person's request.
- **One decision at a time:** a person can inspect memory and sharing choices with a keyboard or screen reader, without completing a long form.
- **No reply:** after an agreed deadline, the person sees that nobody accepted and can choose an alternative. Deadline display and recording a follow-up outcome are implemented; a complete multi-day browser walkthrough and care-partner resolution remain open.
- **Cited answer:** generated advice reflects the retrieved card, preserves its evidence label, and does not override individual wishes.
- **Live model-provider consent:** synthetic adapter tests already withhold unauthorized context and recheck permissions after generation. Repeat these scenarios against the selected live adapter before pilot use.
- **Derived-copy invalidation:** a future search index, generated brief, or notification loses access when any dependency is revoked or deleted.
- **Representative dispute:** authority is verified through a human process. A family claim or diagnosis alone does not transfer control.
- **Quiet week:** absent conversations do not create a mood label or trigger unwanted contact.

These are acceptance requirements, not passing tests or implemented features. The application layer persists follow-up deadlines, alternatives, and recorded outcomes, and the local interface presents them. Resolving an overdue request through a care-partner workflow remains open.

The local text interface now displays due follow-up plans, explicit sharing previews, and observation review. User evaluation, speech scenarios, and full accessibility checks remain open. [test_web.py](../tests/test_web.py) contains controller and HTTP tests for the browser adapter, including cross-origin rejection, CSRF, stale drafts, escaped content, observation forms, and inbox revocation.

## Application contracts

[test_application.py](../tests/test_application.py) adds tests around the core services:

- Session digests, invalid tokens, expiry, logout, and prevention of actor overrides.
- Membership without implied access, required membership for application grants, and removal across overlapping grants and unfinished tasks.
- Worker observation contribution: review inbox, acceptance with attribution, dismissal, withdrawal, and contributor isolation.
- Recipient isolation, stale and revoked inbox filtering, and readable owner metadata.
- Owner-only follow-up planning, deadline boundaries, recorded outcomes, and no automatic contact.
- Account export that excludes session secrets and forgotten text, including linked follow-up alternatives.
- Nested transaction rollback and atomic database upgrades from version 1.

The [next release scenario pack](next-release-plan.md#d5--release-scenario-pack) adds a complete local browser demonstration, persistence checks, and simulated model/delivery failure paths. Startup and demonstration workflow test sources now exist, but the full release checks remain pending; see the release plan for current implementation status and missing evidence.
