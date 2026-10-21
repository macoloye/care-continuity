"""Human-reviewed suggestions remain private drafts with live dependencies."""
import unittest
from datetime import datetime, timedelta, timezone

from care_continuity import AccessDenied, CareApplication, Conflict, RequestState, SessionService, SQLiteStore
from care_continuity.conversation import ConversationService


class SuggestionDraftTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        self.clock = lambda: self.now
        self.app = CareApplication(self.store, self.clock)
        sessions = SessionService(self.store, self.clock)
        self.owner = sessions.issue('owner')
        self.supporter = sessions.issue('supporter')
        self.app.add_member(self.owner, member='supporter', role='supporter')
        self.first = self.app.remember(self.owner, text='Synthetic short visit preference')
        self.second = self.app.remember(self.owner, text='Synthetic advance notice preference')
        self.selected = ((self.first.id, 1), (self.second.id, 1))
        self.calls = 0
        def model(context):
            self.calls += 1
            return {'kind': 'request_draft', 'message': 'Unreviewed generated message'}
        self.service = ConversationService(self.store, clock=self.clock, adapters={'model': model})
        self.service.authorize(self.owner, provider='model', selections=self.selected,
                               expires_at=self.now + timedelta(hours=1))
        self.suggestion = self.service.suggest(self.owner, provider='model', selections=self.selected)

    def save(self, **overrides):
        return self.service.save_draft(self.owner, self.suggestion, **(dict(
            reviewed_message='My reviewed visit request', recipient='supporter',
            purpose='visit', idempotency_key='review-1') | overrides))

    def test_reviewed_text_is_private_until_separate_approval(self):
        grants = self.app.sharing(self.owner)
        request_id = self.save()
        request = self.app.read_request(self.owner, request_id)
        self.assertEqual('My reviewed visit request', request.message)
        self.assertEqual(RequestState.DRAFT, request.state)
        self.assertEqual(set(self.selected), {(m.id, m.revision) for m in request.context})
        self.assertEqual(grants, self.app.sharing(self.owner))
        self.assertEqual((), self.app.inbox(self.supporter))
        self.assertEqual([], self.app.deliveries(self.owner))
        self.assertEqual(1, self.calls)
        with self.assertRaises(AccessDenied):
            self.app.read_request(self.supporter, request_id)
        self.app.approve_request(self.owner, request_id, expires_at=self.now + timedelta(hours=1))
        self.assertEqual(RequestState.DELIVERED, self.app.read_request(self.supporter, request_id).state)
        self.app.transition(self.supporter, request_id, state=RequestState.ACCEPTED)
        self.assertEqual(RequestState.ACCEPTED, self.app.read_request(self.owner, request_id).state)

    def test_retry_is_idempotent_but_changed_review_conflicts(self):
        request_id = self.save()
        self.assertEqual(request_id, self.save())
        with self.assertRaises(Conflict):
            self.save(reviewed_message='A different reviewed message')
        self.assertEqual(1, len(self.app.requests(self.owner)))
        events = self.app.export(self.owner)['events']
        self.assertEqual(1, sum(e['action'] == 'request.draft' for e in events))
        self.assertNotIn('My reviewed visit request', str(events))

    def test_revision_change_blocks_save_and_retry(self):
        self.save()
        self.app.revise(self.owner, self.second.id, text='Changed source', expected_revision=1)
        with self.assertRaises(Conflict):
            self.save()
        with self.assertRaises(Conflict):
            self.save(idempotency_key='new-key')
        self.assertEqual(1, len(self.app.requests(self.owner)))

    def test_revocation_and_expiry_block_persistence(self):
        grant = self.app.sharing(self.owner)[0]
        self.app.revoke(self.owner, grant['id'])
        with self.assertRaises(AccessDenied):
            self.save()
        self.service.authorize(self.owner, provider='model', selections=self.selected,
                               expires_at=self.now + timedelta(hours=1))
        self.now += timedelta(hours=2)
        with self.assertRaises(AccessDenied):
            self.save()
        self.assertEqual([], self.app.requests(self.owner))

    def test_session_and_recipient_authority_rechecked(self):
        with self.assertRaises(AccessDenied):
            self.service.save_draft(self.supporter, self.suggestion, reviewed_message='Forged',
                                   recipient='owner', purpose='visit', idempotency_key='forged')
        self.app.remove_member(self.owner, member='supporter')
        with self.assertRaises(AccessDenied):
            self.save()
        self.app.logout(self.owner)
        with self.assertRaises(AccessDenied):
            self.save()
        self.assertEqual(0, self.store.connection.execute('SELECT count(*) FROM requests').fetchone()[0])

    def test_every_dependency_participates_in_forgetting(self):
        request_id = self.save()
        self.app.forget(self.owner, self.second.id)
        row = self.store.connection.execute('SELECT message,state FROM requests WHERE id=?', (request_id,)).fetchone()
        self.assertEqual(('', 'cancelled'), tuple(row))
        with self.assertRaises(AccessDenied):
            self.save(idempotency_key='after-forgetting')
        self.assertNotIn('My reviewed visit request', str(self.app.export(self.owner)))

    def test_invalid_review_is_atomic(self):
        before = self.app.export(self.owner)
        for text in ('', '  ', 'x' * 4001, None):
            with self.subTest(text_type=type(text).__name__), self.assertRaises(ValueError):
                self.save(reviewed_message=text)
        with self.assertRaises(ValueError):
            self.save(purpose='')
        with self.assertRaises(AccessDenied):
            self.save(recipient='not-in-circle')
        self.assertEqual(before, self.app.export(self.owner))
