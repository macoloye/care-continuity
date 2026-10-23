"""All-or-nothing approval of an external handover, without a network call."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from care_continuity import AccessDenied, CareApplication, Conflict, RequestState, SessionService, SQLiteStore
from care_continuity.outbox import DeliveryResult, OutboxService


class ExternalApprovalTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        self.clock = lambda: self.now
        self.app = CareApplication(self.store, self.clock, delivery_providers=frozenset({'transport'}))
        sessions = SessionService(self.store, self.clock)
        self.owner = sessions.issue('owner')
        self.supporter = sessions.issue('supporter')
        self.app.add_member(self.owner, member='supporter', role='supporter')
        self.memory = self.app.remember(self.owner, text='Synthetic preference')
        self.request = self.app.create_request(self.owner, recipient='supporter', purpose='visit',
            message='Synthetic request', memory_ids=(self.memory.id,), idempotency_key='draft')
        self.expiry = self.now + timedelta(hours=1)

    def approve(self, **kwargs):
        return self.app.approve_external_request(self.owner, self.request,
            **(dict(provider='transport', expires_at=self.expiry) | kwargs))

    def test_exact_scopes_and_separate_worker_receipt(self):
        job = self.approve()
        grants = self.app.sharing(self.owner)
        self.assertEqual(8, len(grants))
        expected = {('supporter', 'request', 'read'), ('supporter', 'request', 'act'),
                    ('supporter', 'memory', 'read'), ('supporter', 'memory', 'share'),
                    ('transport', 'request', 'read'), ('transport', 'request', 'share'),
                    ('transport', 'memory', 'read'), ('transport', 'memory', 'share')}
        self.assertEqual(expected, {(g['recipient'], g['resource_type'], g['operation']) for g in grants})
        self.assertTrue(all(g['purpose'] == 'visit' and g['expires_at'] == self.expiry.isoformat() for g in grants))
        self.assertEqual(RequestState.QUEUED, self.app.read_request(self.owner, self.request).state)
        self.assertEqual('pending', self.app.deliveries(self.owner)[0]['state'])
        self.assertEqual(0, self.app.deliveries(self.owner)[0]['attempts'])
        self.assertEqual(['supporter'], [m['member'] for m in self.app.members(self.owner)])
        with self.assertRaises(Conflict):
            self.app.dispatch(self.owner, self.request)
        calls = []
        def send(key, payload):
            calls.append(key)
            self.assertFalse(self.store.connection.in_transaction)
            self.assertEqual('Synthetic preference', payload.context[0].text)
            return DeliveryResult.RECEIVED
        OutboxService(self.store, self.clock).run_one(provider='transport', send=send)
        self.assertEqual([job], calls)
        self.assertEqual(RequestState.DELIVERED, self.app.read_request(self.owner, self.request).state)

    def test_failure_at_job_creation_rolls_back_grants_queue_and_events(self):
        before = self.app.export(self.owner)
        with patch.object(OutboxService, 'enqueue', side_effect=RuntimeError('Synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.approve()
        self.assertEqual(before, self.app.export(self.owner))
        self.assertEqual([], self.app.deliveries(self.owner))
        self.approve()
        self.assertEqual(1, len(self.app.deliveries(self.owner)))

    def test_unknown_provider_and_default_configuration_deny_approval(self):
        before = self.app.export(self.owner)
        with self.assertRaises(AccessDenied):
            self.approve(provider='https://client-supplied-endpoint.invalid')
        with self.assertRaises(AccessDenied):
            CareApplication(self.store, self.clock).approve_external_request(
                self.owner, self.request, provider='transport', expires_at=self.expiry)
        self.assertEqual(before, self.app.export(self.owner))

    def test_owner_session_and_membership_checks(self):
        with self.assertRaises(AccessDenied):
            self.app.approve_external_request(self.supporter, self.request,
                                             provider='transport', expires_at=self.expiry)
        self.app.remove_member(self.owner, member='supporter')
        with self.assertRaises((AccessDenied, Conflict)):
            self.approve()
        self.app.logout(self.owner)
        with self.assertRaises(AccessDenied):
            self.approve()
        self.assertEqual(0, self.store.connection.execute('SELECT count(*) FROM grants').fetchone()[0])

    def test_stale_context_and_expiry_leave_draft_unchanged(self):
        before = self.app.export(self.owner)
        with self.assertRaises(ValueError):
            self.approve(expires_at=self.now)
        self.assertEqual(before, self.app.export(self.owner))
        self.app.revise(self.owner, self.memory.id, text='Changed', expected_revision=1)
        before = self.app.export(self.owner)
        with self.assertRaises(Conflict):
            self.approve()
        self.assertEqual(before, self.app.export(self.owner))
        self.assertEqual([], self.app.deliveries(self.owner))

    def test_repeated_approval_never_renews_or_duplicates(self):
        self.approve()
        before = self.app.export(self.owner)
        jobs = self.app.deliveries(self.owner)
        with self.assertRaises(Conflict):
            self.approve(expires_at=self.expiry + timedelta(days=1))
        self.assertEqual(before, self.app.export(self.owner))
        self.assertEqual(jobs, self.app.deliveries(self.owner))
