"""Pilot records are synthetic and never count as real reviewed care guidance."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from care_continuity import AccessDenied, CareApplication, Conflict, KnowledgeService, SessionService, SQLiteStore
from care_continuity.store import SCHEMA, SESSION_SCHEMA, FOLLOWUP_RESOLUTION_SCHEMA


class KnowledgePilotTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 20, tzinfo=timezone.utc)
        self.clock = lambda: self.now
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.sessions = SessionService(self.store, self.clock)
        self.app = CareApplication(self.store, self.clock, reviewers=frozenset({"reviewer", "writer"}))
        self.writer = self.sessions.issue("writer")
        self.reviewer = self.sessions.issue("reviewer")
        self.other = self.sessions.issue("other")
        self.fields = dict(title="Example visit", body="Synthetic experience", kind="experience",
                           source="Example source citation", audience="Supporters", setting="Home",
                           language="en", limitations="Fixture only", publication_rights="Original test text",
                           publication_authorized=True)

    def submit(self, **changes):
        return self.app.submit_knowledge(self.writer, **(self.fields | changes))

    def review(self, card, token=None, **changes):
        fields = dict(review_due=self.now + timedelta(days=7), privacy_checked=True,
                      scope_checked=True, evidence="Synthetic source, privacy and scope review")
        self.app.review_knowledge(token or self.reviewer, card, **(fields | changes))

    def test_private_submission_and_evidence_then_public_metadata(self):
        card = self.submit()
        self.assertEqual((), self.app.search_knowledge(self.other))
        self.assertEqual((), self.app.knowledge_submissions(self.other))
        self.assertEqual(card, self.app.knowledge_submissions(self.reviewer)[0].id)
        with self.assertRaises(AccessDenied):
            self.app.knowledge_evidence(self.other, card)
        self.review(card)
        result = self.app.search_knowledge(self.other, "EXAMPLE")[0]
        self.assertEqual(("Supporters", "Home", "en", "Fixture only", "Example source citation"),
                         (result.audience, result.setting, result.language, result.limitations, result.source))
        self.assertEqual(self.now.isoformat(), result.published_at)
        self.assertFalse(hasattr(result, "publication_rights"))
        evidence = self.app.knowledge_evidence(self.writer, card)
        self.assertEqual("writer", evidence["publication_rights"]["actor"])
        self.assertEqual("reviewer", evidence["reviews"][0]["reviewer"])

    def test_metadata_and_explicit_rights_are_required_atomically(self):
        for field in ("source", "audience", "setting", "language", "limitations", "publication_rights"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.submit(**{field: " "})
        for value in (False, "yes", 1):
            with self.assertRaises(AccessDenied):
                self.submit(publication_authorized=value)
        self.assertEqual((), self.app.knowledge_submissions(self.writer))

    def test_review_requires_independence_authority_and_evidence(self):
        card = self.submit()
        for token in (self.writer, self.other):
            with self.assertRaises(AccessDenied):
                self.review(card, token)
        for changes in ({"privacy_checked": False}, {"scope_checked": "yes"},
                        {"evidence": " "}, {"review_due": self.now}):
            with self.assertRaises(ValueError):
                self.review(card, **changes)
        self.assertEqual([], self.app.knowledge_evidence(self.writer, card)["reviews"])
        self.assertEqual((), self.app.search_knowledge(self.other))

    def test_withdrawal_is_terminal_and_owner_can_withdraw(self):
        card = self.submit()
        self.review(card)
        with self.assertRaises(AccessDenied):
            self.app.withdraw_knowledge(self.other, card)
        self.app.withdraw_knowledge(self.writer, card)
        self.app.withdraw_knowledge(self.writer, card)
        with self.assertRaises(Conflict):
            self.review(card)
        self.assertEqual((), self.app.search_knowledge(self.other))
        self.assertEqual(1, len(self.app.knowledge_evidence(self.writer, card)["reviews"]))

    def test_expiry_and_renewal_preserve_first_publication_and_review_history(self):
        card = self.submit()
        self.review(card)
        published = self.app.search_knowledge(self.other)[0].published_at
        self.now += timedelta(days=7)
        self.writer = self.sessions.issue("writer")
        self.reviewer = self.sessions.issue("reviewer")
        self.other = self.sessions.issue("other")
        self.assertEqual((), self.app.search_knowledge(self.other))
        self.review(card)
        self.assertEqual(published, self.app.search_knowledge(self.other)[0].published_at)
        self.assertEqual(2, len(self.app.knowledge_evidence(self.writer, card)["reviews"]))

    def test_session_revocation_stops_editorial_operations(self):
        card = self.submit()
        self.app.logout(self.reviewer)
        with self.assertRaises(AccessDenied):
            self.review(card)
        with self.assertRaises(AccessDenied):
            self.app.knowledge_submissions(self.reviewer)
        self.app.logout(self.writer)
        with self.assertRaises(AccessDenied):
            self.app.withdraw_knowledge(self.writer, card)
        with self.assertRaises(AccessDenied):
            self.submit()

    def test_guidance_stays_disabled_and_audit_omits_text(self):
        card = self.submit(kind="guidance")
        with self.assertRaises(Conflict):
            self.review(card)
        self.app.withdraw_knowledge(self.writer, card)
        events = repr([dict(row) for row in self.store.connection.execute("SELECT * FROM events")])
        for field in ("body", "publication_rights", "source"):
            self.assertNotIn(self.fields[field], events)


class KnowledgeMigrationTests(unittest.TestCase):
    def legacy(self, path):
        db = sqlite3.connect(path)
        db.executescript(SCHEMA + SESSION_SCHEMA + FOLLOWUP_RESOLUTION_SCHEMA)
        db.execute("PRAGMA user_version = 3")
        db.execute("""INSERT INTO knowledge VALUES
            ('legacy', 'Old title', 'Old body', 'experience', 'Old source', 'writer',
             'reviewer', '2100-01-01T00:00:00+00:00', 'reviewed')""")
        db.commit()
        return db

    def test_upgrade_preserves_legacy_but_requires_new_evidence_and_reopens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "care.sqlite"
            self.legacy(path).close()
            for _ in range(2):
                with SQLiteStore(path) as store:
                    self.assertEqual(8, store.connection.execute("PRAGMA user_version").fetchone()[0])
                    service = KnowledgeService(store, reviewers=frozenset({"reviewer"}))
                    self.assertEqual("Old body", service.submissions(actor="writer")[0].body)
                    self.assertEqual((), service.search())
                    with self.assertRaises(Conflict):
                        service.review("legacy", actor="reviewer",
                                       review_due=datetime(2100, 1, 1, tzinfo=timezone.utc),
                                       privacy_checked=True, scope_checked=True, evidence="New review")

    def test_failed_upgrade_rolls_back_columns_and_preserves_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "care.sqlite"
            db = self.legacy(path)
            db.execute("CREATE TABLE knowledge_reviews (incompatible TEXT)")
            db.commit()
            db.close()
            with self.assertRaises(sqlite3.OperationalError):
                SQLiteStore(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(3, db.execute("PRAGMA user_version").fetchone()[0])
                self.assertNotIn("audience", {r[1] for r in db.execute("PRAGMA table_info(knowledge)")})
                self.assertEqual("Old body", db.execute("SELECT body FROM knowledge").fetchone()[0])
