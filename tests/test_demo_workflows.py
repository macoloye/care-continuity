"""Synthetic browser release scenarios and protected review handles."""
import re
import unittest
from datetime import timedelta
from html import unescape
from urllib.parse import parse_qs, urlsplit

from care_continuity import AccessDenied, Conflict, SQLiteStore
from care_continuity.domain import utc_now
from care_continuity import demo
from care_continuity.outbox import DeliveryResult, OutboxService
from care_continuity.web import WebApp


def hidden(html):
    return {k: unescape(v) for k, v in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', html)}


class DemoWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.now = utc_now()
        self.web = WebApp(self.store, clock=lambda: self.now)
        self.owner = self.web.sessions.issue('mei')
        self.other = self.web.sessions.issue('lina')
        self.memory = self.web.app.export(self.owner)['memories'][0]

    def post(self, path, token=None, **fields):
        token = token or self.owner
        data = {k: v if isinstance(v, list) else [str(v)] for k, v in fields.items()}
        data['csrf'] = [self.web.csrf(token)]
        return self.web.post(path, data, token)

    def preview(self):
        response = self.post('/suggestion/preview', memory=[self.memory['id']], hours=24)
        return parse_qs(urlsplit(response.headers['Location']).query)['handle'][0]

    def generate(self):
        handle = self.preview()
        self.post('/suggestion/generate', handle=handle)
        return handle

    def save(self, handle, message='Reviewed synthetic request'):
        return self.post('/suggestion/save', handle=handle, recipient='lina', message=message)

    def approval(self, target, provider='local'):
        body = self.web.get(target + '&hours=1&provider=' + provider, self.owner).body
        fields = hidden(body)
        return {k: fields[k] for k in ('id', 'expires', 'signature', 'provider')}

    def test_browser_suggestion_to_completion_without_implicit_sharing(self):
        handle = self.preview()
        self.assertEqual([], self.web.app.sharing(self.owner))
        preview = self.web.get('/suggestion/review?handle=' + handle, self.owner).body
        self.assertIn(self.memory['text'], preview)
        self.assertIn('source:', preview)
        self.post('/suggestion/generate', handle=handle)
        self.post('/suggestion/generate', handle=handle)
        self.assertEqual(2, len(self.web.app.sharing(self.owner)))
        saved = self.save(handle)
        self.assertEqual(saved.headers, self.save(handle).headers)
        self.assertEqual((), self.web.app.inbox(self.other))
        fields = self.approval(saved.headers['Location'])
        self.post('/request/approve', **fields)
        self.assertIn('Reviewed synthetic request', self.web.get('/inbox', self.other).body)
        self.post('/request/transition', token=self.other, id=fields['id'], state='accepted')
        self.post('/request/transition', token=self.other, id=fields['id'], state='completed')
        self.assertEqual('completed', self.web.app.requests(self.owner)[0]['state'])

    def test_discard_and_foreign_handles_never_save_or_share(self):
        handle = self.preview()
        for path in ('/suggestion/generate', '/suggestion/discard'):
            with self.assertRaises(AccessDenied):
                self.post(path, token=self.other, handle=handle)
        with self.assertRaises(AccessDenied):
            self.web.get('/suggestion/review?handle=' + handle, self.other)
        self.post('/suggestion/discard', handle=handle)
        self.assertEqual([], self.web.app.sharing(self.owner))
        self.assertEqual([], self.web.app.requests(self.owner))
        with self.assertRaises(AccessDenied):
            self.post('/suggestion/generate', handle=handle)

    def test_revocation_expiry_and_restart_drop_cached_reviews(self):
        handle = self.generate()
        grant = self.web.app.sharing(self.owner)[0]
        self.post('/sharing/revoke', id=grant['id'])
        self.assertNotIn(handle, self.web.reviews.entries)
        with self.assertRaises(AccessDenied):
            self.save(handle)
        handle = self.generate()
        self.now += timedelta(minutes=15)
        with self.assertRaises(AccessDenied):
            self.save(handle)
        handle = self.generate()
        self.web = WebApp(self.store, clock=lambda: self.now)
        with self.assertRaises(AccessDenied):
            self.save(handle)

    def test_source_changes_and_logout_invalidate_reviews(self):
        handle = self.generate()
        self.post('/memory/revise', id=self.memory['id'], revision=1, text='Changed')
        self.assertNotIn(handle, self.web.reviews.entries)
        handle = self.generate()
        self.post('/memory/forget', id=self.memory['id'])
        self.assertNotIn(handle, self.web.reviews.entries)
        self.memory = self.web.app.export(self.owner)['memories'][0]
        handle = self.generate()
        self.post('/logout')
        self.assertNotIn(handle, self.web.reviews.entries)

    def test_tampering_csrf_and_output_are_not_authority(self):
        handle = self.generate()
        with self.assertRaises(ValueError):
            self.post('/suggestion/save', handle=handle, recipient='lina', message='X', provider='other')
        with self.assertRaises(AccessDenied):
            self.web.post('/suggestion/generate', {'handle': [handle], 'csrf': ['wrong']}, self.owner)
        self.web.conversation.adapters[demo.MODEL] = lambda _: {'kind': 'request_draft', 'message': '<script>send()</script>'}
        another = self.generate()
        html = self.web.get('/suggestion/review?handle=' + another, self.owner).body
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertEqual([], self.web.app.requests(self.owner))

    def test_suggestion_validation_retains_input_without_saving(self):
        handle = self.generate()
        response = self.save(handle, ' ')
        self.assertEqual(400, response.status)
        self.assertIn('aria-describedby="review-error"', response.body)
        self.assertEqual([], self.web.app.requests(self.owner))
        self.assertEqual(303, self.save(handle).status)

    def test_signed_preview_cannot_change_provider_or_expiry(self):
        saved = self.save(self.generate())
        fields = self.approval(saved.headers['Location'])
        for changes in ({'provider': demo.TRANSPORT}, {'expires': (self.now + timedelta(days=6)).isoformat()}):
            with self.assertRaises(AccessDenied):
                self.post('/request/approve', **(fields | changes))
        self.assertEqual('draft', self.web.app.requests(self.owner)[0]['state'])
        self.assertEqual([], self.web.app.deliveries(self.owner))

    def test_simulated_unknown_refresh_reconciliation_and_cancellation(self):
        saved = self.save(self.generate())
        fields = self.approval(saved.headers['Location'], demo.TRANSPORT)
        result = self.post('/request/approve', **fields)
        self.assertEqual('/deliveries', result.headers['Location'])
        worker = OutboxService(self.store, lambda: self.now)
        job = worker.run_one(provider=demo.TRANSPORT, send=lambda *_: DeliveryResult.UNKNOWN)
        for _ in range(2):
            self.assertIn('Delivery uncertain', self.web.get('/deliveries', self.owner).body)
            self.assertIsNone(worker.run_one(provider=demo.TRANSPORT, send=lambda *_: self.fail('duplicate send')))
        self.assertIn('Delivery uncertain', self.web.get('/attention', self.owner).body)
        self.post('/request/transition', id=fields['id'], state='cancelled')
        worker.reconcile(job, provider=demo.TRANSPORT, lookup=lambda _: DeliveryResult.RECEIVED)
        self.assertEqual('cancelled', self.web.app.requests(self.owner)[0]['state'])
        self.assertEqual('received', self.web.app.deliveries(self.owner)[0]['state'])

    def test_attention_due_followup_and_observation_are_owner_only(self):
        saved = self.save(self.generate())
        fields = self.approval(saved.headers['Location'])
        self.post('/request/approve', **fields)
        self.post('/request/followup', id=fields['id'], hours=1, alternative='Ask later')
        self.web.app.observe(self.other, subject='mei', text='Synthetic observation')
        self.now += timedelta(hours=1)
        body = self.web.get('/attention', self.owner).body
        self.assertIn('Follow-up is due', body)
        self.assertIn('observations await your review', body)
        self.assertNotIn('Follow-up is due', self.web.get('/attention', self.other).body)
        self.post('/request/resolve', id=fields['id'], note='Chose to wait')
        self.assertNotIn('Follow-up is due', self.web.get('/attention', self.owner).body)

    def test_manual_validation_retains_selection_but_authority_failure_does_not(self):
        result = self.post('/request/draft', recipient='lina', message=' ', key='manual', memory=[self.memory['id']])
        self.assertEqual(400, result.status)
        self.assertIn('aria-describedby="draft-error"', result.body)
        self.assertIn(f'value="{self.memory["id"]}" checked', result.body)
        with self.assertRaises(AccessDenied):
            self.post('/request/draft', recipient='unknown', message=' ', key='manual')
