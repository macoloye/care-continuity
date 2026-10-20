"""Longitudinal scenarios with an adjustable clock."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from care_continuity import (
    AccessDenied, Conflict, ConsentService, DelegationService, KnowledgeService,
    MemoryKind, MemoryService, Operation, RequestState, SQLiteStore,
)


class CareScenarios(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.clock = lambda: self.now
        self.consent = ConsentService(self.store, self.clock)
        self.memory = MemoryService(self.store, self.consent, self.clock)
        self.requests = DelegationService(self.store, self.consent, self.memory, self.clock)
        self.knowledge = KnowledgeService(self.store, reviewers=frozenset({"reviewer"}), clock=self.clock)
        self.preference = self.memory.remember(actor="mei", subject="mei", source="mei",
                                               text="Keep visits short.", confirmed=True)

    def grant(self, resource_id=None, operation=Operation.READ, resource_type="memory", recipient="worker", purpose="visit"):
        return self.consent.grant(actor="mei", subject="mei", recipient=recipient, purpose=purpose,
                                  resource_type=resource_type, resource_id=resource_id or self.preference.id,
                                  operation=operation, expires_at=self.now + timedelta(days=1))

    def request(self, *, approve=True):
        request_id = self.requests.create(actor="mei", subject="mei", recipient="worker", purpose="visit",
                                          message="Please visit on Saturday.", idempotency_key="saturday",
                                          memory_ids=(self.preference.id,))
        if approve:
            for operation in (Operation.READ, Operation.SHARE):
                self.grant(operation=operation)
            for operation in (Operation.READ, Operation.ACT):
                self.grant(request_id, operation, "request")
        return request_id

    def card(self, kind="experience", authorized=True):
        return self.knowledge.submit(contributor="writer", title="Visit experience",
                                     body="An example account for testing.", kind=kind, source="Example record",
                                     publication_authorized=authorized)

    def review(self, card):
        self.knowledge.review(card, actor="reviewer", review_due=self.now + timedelta(days=7),
                              privacy_checked=True, scope_checked=True)

    def test_private_by_default(self):
        self.assertEqual((), self.memory.summary(subject="mei", actor="daughter", purpose="visit"))
        with self.assertRaises(AccessDenied):
            self.memory.read(self.preference.id, actor="worker", purpose="visit")

    def test_permission_is_bound_to_recipient_purpose_and_person(self):
        self.grant()
        self.assertEqual(self.preference, self.memory.read(self.preference.id, actor="worker", purpose="visit"))
        for actor, purpose in (("daughter", "visit"), ("worker", "research")):
            with self.assertRaises(AccessDenied):
                self.memory.read(self.preference.id, actor=actor, purpose=purpose)
        other = self.memory.remember(actor="ali", subject="ali", source="ali", text="Private routine")
        with self.assertRaises(AccessDenied):
            self.memory.read(other.id, actor="worker", purpose="visit")

    def test_correction_updates_summary_and_retains_owner_history(self):
        self.grant()
        self.memory.revise(self.preference.id, actor="mei", text="Longer visits are welcome.", expected_revision=1)
        self.assertEqual("Longer visits are welcome.", self.memory.summary(subject="mei", actor="worker", purpose="visit")[0].text)
        self.assertEqual(2, len(self.memory.history(self.preference.id, actor="mei")))
        with self.assertRaises(AccessDenied):
            self.memory.history(self.preference.id, actor="worker")

    def test_stale_edit_does_not_overwrite_new_preference(self):
        self.memory.revise(self.preference.id, actor="mei", text="New preference", expected_revision=1)
        with self.assertRaises(Conflict):
            self.memory.revise(self.preference.id, actor="mei", text="Stale edit", expected_revision=1)

    def test_observation_does_not_overwrite_persons_wishes(self):
        self.memory.remember(actor="mei", subject="mei", source="worker", kind=MemoryKind.OBSERVATION,
                             text="Mei stayed longer today.")
        self.assertEqual("Keep visits short.", self.memory.read(self.preference.id, actor="mei", purpose="manage").text)
        with self.assertRaises(ValueError):
            self.memory.remember(actor="mei", subject="mei", source="worker", text="She prefers long visits.")

    def test_relative_cannot_grant_or_change_permission(self):
        grant = self.grant()
        with self.assertRaises(AccessDenied):
            self.consent.revoke(actor="daughter", grant_id=grant)
        with self.assertRaises(AccessDenied):
            self.consent.grant(actor="daughter", subject="mei", recipient="daughter", purpose="visit",
                               resource_type="memory", resource_id=self.preference.id, operation=Operation.READ,
                               expires_at=self.now + timedelta(days=1))

    def test_permission_expires_at_exact_boundary(self):
        self.grant()
        self.now += timedelta(days=1)
        self.assertEqual((), self.memory.summary(subject="mei", actor="worker", purpose="visit"))

    def test_invalid_expiry_and_nonexistent_resource_are_rejected(self):
        with self.assertRaises(ValueError):
            self.consent.grant(actor="mei", subject="mei", recipient="worker", purpose="visit",
                               resource_type="memory", resource_id=self.preference.id, operation=Operation.READ,
                               expires_at=self.now.replace(tzinfo=None))
        with self.assertRaises(AccessDenied):
            self.grant("missing")

    def test_revoke_removes_current_summary(self):
        grant = self.grant()
        self.assertEqual(1, len(self.memory.summary(subject="mei", actor="worker", purpose="visit")))
        self.consent.revoke(actor="mei", grant_id=grant)
        self.assertEqual((), self.memory.summary(subject="mei", actor="worker", purpose="visit"))

    def test_forgetting_purges_history_and_redacts_linked_message(self):
        request_id = self.request()
        self.requests.queue(request_id, actor="mei")
        self.memory.forget(self.preference.id, actor="mei")
        self.assertEqual((), self.memory.summary(subject="mei", actor="mei", purpose="manage"))
        self.assertEqual(0, self.store.connection.execute("SELECT count(*) FROM memory_history").fetchone()[0])
        row = self.store.connection.execute("SELECT message, state FROM requests WHERE id=?", (request_id,)).fetchone()
        self.assertEqual(("", "cancelled"), tuple(row))
        with self.assertRaises(AccessDenied):
            self.requests.read(request_id, actor="worker")

    def test_no_approval_means_no_delivery(self):
        request_id = self.request(approve=False)
        with self.assertRaises(AccessDenied):
            self.requests.queue(request_id, actor="mei")
        with self.assertRaises(AccessDenied):
            self.requests.read(request_id, actor="worker")

    def test_read_permission_does_not_allow_sharing_or_acting(self):
        request_id = self.request(approve=False)
        self.grant()
        self.grant(request_id, Operation.READ, "request")
        with self.assertRaises(AccessDenied):
            self.requests.queue(request_id, actor="mei")
        self.grant(request_id, Operation.ACT, "request")
        with self.assertRaises(AccessDenied):
            self.requests.queue(request_id, actor="mei")
        self.grant(operation=Operation.SHARE)
        self.requests.queue(request_id, actor="mei")

    def test_full_loop_and_retries_do_not_duplicate_events(self):
        request_id = self.request()
        self.requests.queue(request_id, actor="mei")
        self.requests.queue(request_id, actor="mei")
        self.assertEqual(RequestState.DELIVERED, self.requests.dispatch(request_id, actor="mei"))
        self.requests.dispatch(request_id, actor="mei")
        for state in (RequestState.ACCEPTED, RequestState.COMPLETED):
            self.requests.transition(request_id, actor="worker", state=state)
            self.requests.transition(request_id, actor="worker", state=state)
        actions = [event["action"] for event in self.requests.history(actor="mei", subject="mei")]
        for state in ("queued", "delivered", "accepted", "completed"):
            self.assertEqual(1, actions.count(f"request.{state}"))

    def test_unanswered_request_stays_delivered(self):
        request_id = self.request()
        self.requests.queue(request_id, actor="mei")
        self.requests.dispatch(request_id, actor="mei")
        self.now += timedelta(hours=2)
        self.assertEqual(RequestState.DELIVERED, self.requests.read(request_id, actor="mei").state)
        with self.assertRaises(Conflict):
            self.requests.transition(request_id, actor="worker", state=RequestState.COMPLETED)

    def test_revocation_blocks_queued_handover(self):
        request_id = self.request()
        self.requests.queue(request_id, actor="mei")
        for grant in self.consent.list_grants(actor="mei", subject="mei"):
            if grant["operation"] == "share":
                self.consent.revoke(actor="mei", grant_id=grant["id"])
        self.assertEqual(RequestState.BLOCKED, self.requests.dispatch(request_id, actor="mei"))

    def test_expiry_blocks_completion_and_old_message_access(self):
        request_id = self.request()
        self.requests.queue(request_id, actor="mei")
        self.requests.dispatch(request_id, actor="mei")
        self.requests.transition(request_id, actor="worker", state=RequestState.ACCEPTED)
        self.now += timedelta(days=1)
        with self.assertRaises(AccessDenied):
            self.requests.transition(request_id, actor="worker", state=RequestState.COMPLETED)
        with self.assertRaises(AccessDenied):
            self.requests.read(request_id, actor="worker")

    def test_correction_blocks_previously_approved_context(self):
        request_id = self.request()
        self.requests.queue(request_id, actor="mei")
        self.memory.revise(self.preference.id, actor="mei", text="No visits this week.", expected_revision=1)
        self.assertEqual(RequestState.BLOCKED, self.requests.dispatch(request_id, actor="mei"))

    def test_cancellation_prevents_execution(self):
        request_id = self.request()
        self.requests.queue(request_id, actor="mei")
        self.requests.transition(request_id, actor="mei", state=RequestState.CANCELLED)
        self.assertEqual(RequestState.CANCELLED, self.requests.dispatch(request_id, actor="mei"))
        with self.assertRaises(Conflict):
            self.requests.transition(request_id, actor="worker", state=RequestState.ACCEPTED)

    def test_idempotency_key_is_scoped_and_payload_checked(self):
        request_id = self.request()
        self.assertEqual(request_id, self.request(approve=False))
        with self.assertRaises(Conflict):
            self.requests.create(actor="mei", subject="mei", recipient="worker", purpose="visit",
                                  message="Different message", idempotency_key="saturday")

    def test_other_persons_memory_cannot_enter_request(self):
        other = self.memory.remember(actor="ali", subject="ali", source="ali", text="Ali's private preference")
        self.consent.grant(actor="ali", subject="ali", recipient="mei", purpose="visit", resource_type="memory",
                           resource_id=other.id, operation=Operation.READ, expires_at=self.now + timedelta(days=1))
        with self.assertRaises(AccessDenied):
            self.requests.create(actor="mei", subject="mei", recipient="worker", purpose="visit", message="Visit",
                                  idempotency_key="cross-person", memory_ids=(other.id,))
        self.assertEqual(0, self.store.connection.execute("SELECT count(*) FROM requests").fetchone()[0])

    def test_draft_and_withdrawn_knowledge_are_not_retrieved(self):
        card = self.card()
        self.assertEqual((), self.knowledge.search())
        self.review(card)
        self.assertEqual("experience", self.knowledge.search()[0].kind)
        self.knowledge.withdraw(card, actor="reviewer")
        self.assertEqual((), self.knowledge.search())

    def test_overdue_knowledge_stops_appearing(self):
        self.review(self.card())
        self.now += timedelta(days=7)
        self.assertEqual((), self.knowledge.search())

    def test_publication_requires_separate_authorization_and_review(self):
        with self.assertRaises(AccessDenied):
            self.card(authorized=False)
        card = self.card()
        with self.assertRaises(AccessDenied):
            self.knowledge.review(card, actor="writer", review_due=self.now + timedelta(days=7),
                                  privacy_checked=True, scope_checked=True)
        with self.assertRaises(ValueError):
            self.knowledge.review(card, actor="reviewer", review_due=self.now + timedelta(days=7),
                                  privacy_checked=False, scope_checked=True)

    def test_professional_guidance_cannot_bypass_qualified_review(self):
        with self.assertRaises(Conflict):
            self.review(self.card(kind="guidance"))
        self.assertEqual((), self.knowledge.search())

    def test_audit_events_do_not_store_care_text(self):
        self.memory.revise(self.preference.id, actor="mei", text="Private replacement", expected_revision=1)
        self.memory.forget(self.preference.id, actor="mei")
        events = repr(self.requests.history(actor="mei", subject="mei"))
        self.assertNotIn("Private replacement", events)
        self.assertNotIn("Keep visits short.", events)

    def test_file_database_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "care.sqlite"
            with SQLiteStore(path) as store:
                service = MemoryService(store, ConsentService(store, self.clock), self.clock)
                item = service.remember(actor="mei", subject="mei", source="mei", text="A durable preference")
            with SQLiteStore(path) as store:
                service = MemoryService(store, ConsentService(store, self.clock), self.clock)
                self.assertEqual("A durable preference", service.read(item.id, actor="mei", purpose="manage").text)


if __name__ == "__main__":
    unittest.main()
