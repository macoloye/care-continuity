"""Synthetic qualification attestations and dependent publication checks."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from care_continuity import AccessDenied, CareApplication, Conflict, SessionService, SQLiteStore
from care_continuity.store import SCHEMA, SESSION_SCHEMA, FOLLOWUP_RESOLUTION_SCHEMA, KNOWLEDGE_PILOT_SCHEMA


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        self.clock = lambda: self.now
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.app = CareApplication(self.store, self.clock, reviewers=frozenset({'editor'}),
                                   qualification_verifiers=frozenset({'verifier'}))
        self.sessions = SessionService(self.store, self.clock)
        self.tokens = {actor: self.sessions.issue(actor) for actor in ('writer', 'editor', 'verifier', 'stranger')}
        self.card = self.app.submit_knowledge(self.tokens['writer'], title='Example', body='Synthetic body',
            kind='procedure', source='Example citation', audience='Supporters', setting='Home', language='en',
            limitations='Fixture only', publication_rights='Original fixture', publication_authorized=True)

    def record(self, actor='verifier', **changes):
        fields = dict(reviewer='editor', kind='procedure', setting='Home', language='en',
                      evidence='Private external credential check reference', expires_at=self.now + timedelta(days=30),
                      idempotency_key='check-1')
        return self.app.record_qualification(self.tokens[actor], **(fields | changes))

    def review(self, qualification_id, **changes):
        fields = dict(review_due=self.now + timedelta(days=7), privacy_checked=True, scope_checked=True,
                      evidence='Synthetic editorial review', qualification_id=qualification_id)
        self.app.review_knowledge(self.tokens['editor'], self.card, **(fields | changes))

    def test_private_records_independent_verifier_and_idempotent_retry(self):
        for actor in ('writer', 'editor', 'stranger'):
            with self.assertRaises(AccessDenied):
                self.record(actor)
        with self.assertRaises(AccessDenied):
            self.record(reviewer='verifier')
        qualification = self.record()
        self.assertEqual(qualification, self.record())
        with self.assertRaises(Conflict):
            self.record(evidence='Changed evidence')
        for actor in ('editor', 'verifier'):
            rows = self.app.qualifications(self.tokens[actor], reviewer='editor')
            self.assertEqual(1, len(rows))
            self.assertTrue(rows[0]['active'])
        with self.assertRaises(AccessDenied):
            self.app.qualifications(self.tokens['writer'], reviewer='editor')
        events = repr([dict(row) for row in self.store.connection.execute('SELECT * FROM events')])
        self.assertNotIn('Private external credential check reference', events)

    def test_exact_scope_and_full_review_interval(self):
        for changes in ({'reviewer': 'writer'}, {'kind': 'experience'}, {'setting': 'Hospital'}, {'language': 'fr'}):
            qualification = self.record(**(changes | {'idempotency_key': repr(changes)}))
            with self.assertRaises(AccessDenied):
                self.review(qualification)
        qualification = self.record()
        with self.assertRaises(AccessDenied):
            self.review(qualification, review_due=self.now + timedelta(days=31))
        self.assertEqual([], self.app.knowledge_evidence(self.tokens['writer'], self.card)['reviews'])
        self.review(qualification, review_due=self.now + timedelta(days=30))
        self.assertEqual(self.card, self.app.search_knowledge(self.tokens['stranger'])[0].id)

    def test_revocation_hides_dependent_card_and_renewal_requires_qualification(self):
        qualification = self.record()
        self.review(qualification)
        with self.assertRaises(AccessDenied):
            self.app.revoke_qualification(self.tokens['editor'], qualification)
        self.app.revoke_qualification(self.tokens['verifier'], qualification)
        self.app.revoke_qualification(self.tokens['verifier'], qualification)
        self.assertEqual(qualification, self.record())  # A retry cannot un-revoke it.
        self.assertFalse(self.app.qualifications(self.tokens['editor'], reviewer='editor')[0]['active'])
        self.assertEqual((), self.app.search_knowledge(self.tokens['stranger']))
        with self.assertRaises(AccessDenied):
            self.review(qualification)
        with self.assertRaises(Conflict):
            self.review(None)
        replacement = self.record(idempotency_key='check-2')
        self.review(replacement)
        self.assertEqual(self.card, self.app.search_knowledge(self.tokens['stranger'])[0].id)
        history = self.app.knowledge_evidence(self.tokens['writer'], self.card)['reviews']
        self.assertEqual({qualification, replacement}, {row['qualification_id'] for row in history})
        self.assertNotIn('Private external credential', repr(history))

    def test_expiry_and_revoked_sessions(self):
        qualification = self.record(expires_at=self.now + timedelta(days=7))
        self.review(qualification)
        self.now += timedelta(days=7)
        self.tokens = {actor: self.sessions.issue(actor) for actor in self.tokens}
        self.assertEqual((), self.app.search_knowledge(self.tokens['stranger']))
        self.assertFalse(self.app.qualifications(self.tokens['editor'], reviewer='editor')[0]['active'])
        with self.assertRaises(AccessDenied):
            self.review(qualification)
        self.app.logout(self.tokens['verifier'])
        with self.assertRaises(AccessDenied):
            self.record(idempotency_key='new')
        with self.assertRaises(AccessDenied):
            self.app.revoke_qualification(self.tokens['verifier'], qualification)

    def test_invalid_evidence_and_dates_and_guidance_remains_disabled(self):
        for fields in ({'evidence': ' '}, {'expires_at': self.now}, {'expires_at': datetime(2030, 1, 1)},
                       {'idempotency_key': ''}, {'kind': 'unknown'}):
            with self.assertRaises(ValueError):
                self.record(**fields)
        qualification = self.record(kind='guidance')
        self.store.connection.execute("UPDATE knowledge SET kind='guidance' WHERE id=?", (self.card,))
        with self.assertRaises(Conflict):
            self.review(qualification)
        self.assertEqual((), self.app.search_knowledge(self.tokens['stranger']))


class QualificationMigrationTests(unittest.TestCase):
    def legacy(self, path):
        db = sqlite3.connect(path)
        db.executescript(SCHEMA + SESSION_SCHEMA + FOLLOWUP_RESOLUTION_SCHEMA + KNOWLEDGE_PILOT_SCHEMA)
        db.execute('PRAGMA user_version = 4')
        db.execute("""INSERT INTO knowledge (id,title,body,kind,source,contributor)
            VALUES ('card','Example','Preserved body','procedure','Example','writer')""")
        db.execute("INSERT INTO knowledge_reviews VALUES ('review','card','editor','Preserved review','old','future')")
        db.commit()
        return db

    def test_upgrade_preserves_existing_records_and_new_records_survive_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'care.sqlite'
            self.legacy(path).close()
            with SQLiteStore(path) as store:
                from care_continuity.qualifications import QualificationService
                service = QualificationService(store, verifiers=frozenset({'verifier'}))
                qid = service.record(actor='verifier', reviewer='editor', kind='procedure', setting='Home',
                    language='en', evidence='Example evidence', expires_at=datetime(2100,1,1,tzinfo=timezone.utc),
                    idempotency_key='key')
            with SQLiteStore(path) as store:
                self.assertEqual(6, store.connection.execute('PRAGMA user_version').fetchone()[0])
                self.assertEqual('Preserved body', store.connection.execute('SELECT body FROM knowledge').fetchone()[0])
                self.assertEqual('Preserved review', store.connection.execute('SELECT evidence FROM knowledge_reviews').fetchone()[0])
                self.assertEqual(qid, store.connection.execute('SELECT id FROM reviewer_qualifications').fetchone()[0])

    def test_failed_upgrade_rolls_back_without_losing_old_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'care.sqlite'
            db = self.legacy(path)
            db.execute('ALTER TABLE knowledge_reviews ADD COLUMN qualification_id TEXT')
            db.commit()
            db.close()
            with self.assertRaises(sqlite3.OperationalError):
                SQLiteStore(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(4, db.execute('PRAGMA user_version').fetchone()[0])
                self.assertNotIn('qualification_id', {row[1] for row in db.execute('PRAGMA table_info(knowledge)')})
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='reviewer_qualifications'").fetchone())
                self.assertEqual('Preserved body', db.execute('SELECT body FROM knowledge').fetchone()[0])
