"""Delivery metadata is private and never claims human acceptance."""
import unittest
from datetime import datetime, timedelta, timezone

from care_continuity import Operation, RequestState, SQLiteStore
from care_continuity.outbox import DeliveryResult, OutboxService
from care_continuity.web import WebApp
from care_continuity import web_views


class DeliveryWebTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.web = WebApp(self.store)
        self.owner = self.web.sessions.issue('mei')
        self.reader = self.web.sessions.issue('lina')
        self.provider = 'Example <transport>'
        self.request = self.web.app.create_request(self.owner, recipient='lina', purpose='visit',
            message='Private synthetic care message', idempotency_key='delivery-web')
        expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        for operation in (Operation.READ, Operation.ACT):
            self.web.app.grant(self.owner, recipient='lina', purpose='visit', resource_type='request',
                resource_id=self.request, operation=operation, expires_at=expiry)
        self.web.app.authorize_delivery_provider(self.owner, self.request,
            provider=self.provider, expires_at=expiry)
        self.web.app.queue(self.owner, self.request)
        self.job = self.web.app.enqueue_delivery(self.owner, self.request, provider=self.provider)
        self.worker = OutboxService(self.store)

    def test_private_metadata_and_revoked_session(self):
        body = self.web.get('/deliveries', self.owner).body
        self.assertIn('Waiting to send', body)
        self.assertIn('Example &lt;transport&gt;', body)
        self.assertNotIn(self.provider, body)
        self.assertNotIn('Private synthetic care message', body)
        self.assertIn(f'/requests#request-{self.request}', body)
        self.assertIn(f'id="request-{self.request}"', self.web.get('/requests', self.owner).body)
        self.assertIn('No external deliveries', self.web.get('/deliveries', self.reader).body)
        self.web.app.logout(self.owner)
        self.assertNotIn('Example &lt;transport&gt;', self.web.get('/deliveries', self.owner).body)

    def test_receipt_acceptance_and_cancellation_are_distinct(self):
        self.worker.run_one(provider=self.provider, send=lambda *_: DeliveryResult.RECEIVED)
        body = self.web.get('/deliveries', self.owner).body
        self.assertIn('Provider received it', body)
        self.assertIn('Request: delivered', body)
        self.assertIn('No one has accepted', body)
        self.web.app.transition(self.reader, self.request, state=RequestState.ACCEPTED)
        body = self.web.get('/deliveries', self.owner).body
        self.assertIn('Request: accepted', body)
        self.assertNotIn('No one has accepted', body)
        self.web.app.transition(self.owner, self.request, state=RequestState.CANCELLED)
        body = self.web.get('/deliveries', self.owner).body
        self.assertIn('Request: cancelled', body)
        self.assertIn('does not recall', body)
        self.assertIn('Provider received it', body)

    def test_uncertainty_survives_read_only_refresh(self):
        self.worker.run_one(provider=self.provider, send=lambda *_: DeliveryResult.UNKNOWN)
        before = self.web.app.deliveries(self.owner)
        for _ in range(2):
            body = self.web.get('/deliveries', self.owner).body
            self.assertIn('Delivery uncertain', body)
            self.assertIn('Do not create a duplicate request', body)
            self.assertNotIn('Retry delivery', body)
        self.assertEqual(before, self.web.app.deliveries(self.owner))

    def test_every_worker_state_has_plain_language(self):
        item = self.web.app.deliveries(self.owner)[0]
        for state, phrase in [('pending', 'Waiting to send'), ('sending', 'Sending'),
                             ('received', 'Provider received it'), ('unknown', 'Delivery uncertain'),
                             ('blocked', 'Delivery stopped'), ('failed', 'Delivery attempts exhausted')]:
            with self.subTest(state=state):
                self.assertIn(phrase, web_views.deliveries([item | {'state': state}]))
        body = self.web.get('/deliveries', self.owner).body
        self.assertIn('aria-current="page">Deliveries', body)
        self.assertIn('<main id="main"', body)
