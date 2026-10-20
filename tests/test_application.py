"""Application contracts, session lifecycle, and database upgrade coverage."""

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from care_continuity import AccessDenied, CareApplication, Conflict, Operation, RequestState, SessionService, SQLiteStore
from care_continuity.store import SCHEMA


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
        self.clock = lambda: self.now
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.sessions = SessionService(self.store, self.clock)
        self.app = CareApplication(self.store, self.clock)
        self.mei = self.sessions.issue("mei")
        self.worker = self.sessions.issue("worker")
        self.ali = self.sessions.issue("ali")
        self.memory = self.app.remember(self.mei, text="Keep visits short.", confirmed=True)

    def grant(self, resource_id, operation, resource_type="memory"):
        return self.app.grant(self.mei, recipient="worker", purpose="visit", resource_type=resource_type,
                              resource_id=resource_id, operation=operation, expires_at=self.now + timedelta(days=1))

    def request(self, *, deliver=True):
        self.app.add_member(self.mei, member="worker", role="worker")
        for operation in (Operation.READ, Operation.SHARE):
            self.grant(self.memory.id, operation)
        request = self.app.create_request(self.mei, recipient="worker", purpose="visit", message="Please visit.",
                                          idempotency_key="visit", memory_ids=(self.memory.id,))
        for operation in (Operation.READ, Operation.ACT):
            self.grant(request, operation, "request")
        self.app.queue(self.mei, request)
        if deliver:
            self.app.dispatch(self.mei, request)
        return request

    def test_session_secrets_are_not_stored_or_exported(self):
        stored = repr([tuple(row) for row in self.store.connection.execute("SELECT * FROM sessions")])
        exported = json.dumps(self.app.export(self.mei))
        self.assertNotIn(self.mei, stored)
        self.assertNotIn(self.mei, exported)
        self.assertNotIn("token_hash", exported)
        self.assertEqual("mei", self.sessions.resolve(self.mei))

    def test_expiry_and_logout_apply_to_existing_application_instance(self):
        self.app.logout(self.worker)
        self.app.logout(self.worker)
        with self.assertRaises(AccessDenied):
            self.app.inbox(self.worker)
        self.now += timedelta(hours=8)
        with self.assertRaises(AccessDenied):
            self.app.export(self.mei)

    def test_invalid_tokens_and_lifetimes(self):
        for token in ("", "unknown", "x" * 257, None):
            with self.assertRaises(AccessDenied):
                self.app.export(token)
        for lifetime in (timedelta(0), timedelta(days=2)):
            with self.assertRaises(ValueError):
                self.sessions.issue("mei", lifetime=lifetime)

    def test_identity_cannot_be_overridden_by_payload(self):
        with self.assertRaises(TypeError):
            self.app.remember(self.worker, actor="mei", text="Forged preference")
        with self.assertRaises(AccessDenied):
            self.app.revise(self.worker, self.memory.id, text="Forged edit", expected_revision=1)
        self.assertEqual([], self.app.export(self.worker)["memories"])

    def test_membership_alone_does_not_disclose(self):
        self.app.add_member(self.mei, member="worker", role="worker")
        self.assertEqual((), self.app.memories(self.worker, subject="mei", purpose="visit"))
        self.assertEqual([], self.app.members(self.worker))
        self.grant(self.memory.id, Operation.READ)
        self.assertEqual(1, len(self.app.memories(self.worker, subject="mei", purpose="visit")))

    def test_application_grants_require_active_member(self):
        with self.assertRaises(AccessDenied):
            self.grant(self.memory.id, Operation.READ)
        with self.assertRaises(AccessDenied):
            self.app.create_request(self.mei, recipient="worker", purpose="visit", message="Visit", idempotency_key="1")

    def test_removal_revokes_overlapping_grants_and_cancels_work(self):
        request = self.request(deliver=False)
        self.grant(self.memory.id, Operation.READ)
        self.app.remove_member(self.mei, member="worker")
        self.assertTrue(all(not grant["active"] for grant in self.app.sharing(self.mei)))
        self.assertEqual(RequestState.CANCELLED, self.app.dispatch(self.mei, request))
        self.assertEqual((), self.app.inbox(self.worker))
        self.app.add_member(self.mei, member="worker", role="supporter")
        self.assertEqual((), self.app.memories(self.worker, subject="mei", purpose="visit"))

    def test_recipient_actions_and_inbox_remain_isolated(self):
        request = self.request()
        self.assertEqual(1, len(self.app.inbox(self.worker)))
        self.assertEqual((), self.app.inbox(self.ali))
        with self.assertRaises(AccessDenied):
            self.app.transition(self.ali, request, state=RequestState.ACCEPTED)
        self.app.transition(self.worker, request, state=RequestState.ACCEPTED)
        self.app.transition(self.worker, request, state=RequestState.COMPLETED)
        self.assertEqual("completed", self.app.requests(self.mei)[0]["state"])

    def test_inbox_drops_revoked_and_stale_requests(self):
        self.request()
        self.app.revise(self.mei, self.memory.id, text="No visits this week.", expected_revision=1)
        self.assertEqual((), self.app.inbox(self.worker))
        view = self.app.requests(self.mei)[0]
        self.assertFalse(view["content_available"])
        self.assertIsNone(view["message"])

    def test_revocation_removes_delivered_request_from_inbox(self):
        request = self.request()
        grant = next(item for item in self.app.sharing(self.mei)
                     if item["resource_id"] == request and item["operation"] == "read")
        self.app.revoke(self.mei, grant["id"])
        self.assertEqual((), self.app.inbox(self.worker))
        with self.assertRaises(AccessDenied):
            self.app.read_request(self.worker, request)

    def test_followup_marks_unanswered_without_acting(self):
        request = self.request()
        self.app.plan_followup(self.mei, request, due_at=self.now + timedelta(hours=1),
                               alternative="Ask me whether to invite Lina instead.")
        self.assertFalse(self.app.requests(self.mei)[0]["needs_followup"])
        self.now += timedelta(hours=1)
        view = self.app.requests(self.mei)[0]
        self.assertTrue(view["needs_followup"])
        self.assertEqual("delivered", view["state"])
        self.app.transition(self.worker, request, state=RequestState.ACCEPTED)
        self.assertFalse(self.app.requests(self.mei)[0]["needs_followup"])

    def test_followup_is_owner_only_and_validates_lifecycle(self):
        request = self.request()
        with self.assertRaises(AccessDenied):
            self.app.plan_followup(self.worker, request, due_at=self.now + timedelta(hours=1), alternative="Contact Lina")
        with self.assertRaises(ValueError):
            self.app.plan_followup(self.mei, request, due_at=self.now, alternative="Contact Lina")
        self.app.transition(self.worker, request, state=RequestState.ACCEPTED)
        with self.assertRaises(Conflict):
            self.app.plan_followup(self.mei, request, due_at=self.now + timedelta(hours=1), alternative="Contact Lina")

    def test_forget_removes_related_text_from_export(self):
        request = self.request()
        self.app.plan_followup(self.mei, request, due_at=self.now + timedelta(hours=1), alternative="Keep visits short.")
        self.app.forget(self.mei, self.memory.id)
        exported = self.app.export(self.mei)
        self.assertNotIn("Keep visits short.", json.dumps(exported))
        self.assertEqual([], exported["memories"])
        self.assertEqual("cancelled", exported["requests"][0]["state"])
        self.assertFalse(exported["requests"][0]["content_available"])

    def test_nested_failure_rolls_back_all_service_work(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.app.remember(self.mei, text="Should not persist")
                raise RuntimeError("Fail the application operation")
        self.assertEqual(1, len(self.app.export(self.mei)["memories"]))
        self.assertFalse(self.store.connection.in_transaction)


class MigrationTests(unittest.TestCase):
    def test_v1_upgrade_preserves_records_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "care.sqlite"
            db = sqlite3.connect(path)
            db.executescript(SCHEMA)
            db.execute("INSERT INTO memories VALUES ('m', 'mei', 'preference', 'Breakfast at 8', 'mei', 1, 1, 'old', 'old', 0)")
            db.commit()
            db.close()
            for _ in range(2):
                with SQLiteStore(path) as store:
                    self.assertEqual(2, store.connection.execute("PRAGMA user_version").fetchone()[0])
                    token = SessionService(store).issue("mei")
                    self.assertEqual("Breakfast at 8", CareApplication(store).export(token)["memories"][0]["text"])

    def test_failed_migration_rolls_back_without_version_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "care.sqlite"
            db = sqlite3.connect(path)
            db.executescript(SCHEMA)
            db.execute("CREATE TABLE care_circle (incompatible TEXT)")
            db.commit()
            db.close()
            with self.assertRaises(sqlite3.OperationalError):
                SQLiteStore(path)
            db = sqlite3.connect(path)
            try:
                self.assertEqual(1, db.execute("PRAGMA user_version").fetchone()[0])
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='sessions'").fetchone())
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
