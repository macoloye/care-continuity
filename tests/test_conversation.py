"""Synthetic model adapters exercise disclosure and untrusted output boundaries."""
import unittest
from datetime import datetime, timedelta, timezone

from care_continuity import AccessDenied, CareApplication, Conflict, SQLiteStore, SessionService
from care_continuity.conversation import ConversationService


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        self.clock = lambda: self.now
        self.app = CareApplication(self.store, self.clock)
        self.owner = SessionService(self.store, self.clock).issue('owner')
        self.other = SessionService(self.store, self.clock).issue('other')
        self.item = self.app.remember(self.owner, text='Synthetic short visit preference')
        self.private = self.app.remember(self.owner, text='Unselected private memory')
        self.selected = ((self.item.id, 1),)
        self.calls = []
        self.callback = lambda _: {'kind': 'request_draft', 'message': 'Could we plan a short visit?'}
        def adapter(context):
            self.assertFalse(self.store.connection.in_transaction)
            self.calls.append(context)
            return self.callback(context)
        self.service = ConversationService(self.store, adapters={'model': adapter}, clock=self.clock)

    def approve(self, **kwargs):
        self.service.authorize(self.owner, **(dict(provider='model', selections=self.selected,
            expires_at=self.now + timedelta(hours=1)) | kwargs))

    def suggest(self, **kwargs):
        return self.service.suggest(self.owner, **(dict(provider='model', selections=self.selected) | kwargs))

    def test_explicit_disclosure_and_no_side_effects(self):
        with self.assertRaises(AccessDenied):
            self.suggest()
        self.assertEqual([], self.calls)
        self.approve()
        before = self.app.export(self.owner)
        result = self.suggest()
        self.assertEqual(self.selected, result.dependencies)
        self.assertEqual((self.item,), self.calls[0].memories)
        self.assertEqual(before, self.app.export(self.owner))
        self.assertEqual([], self.app.requests(self.owner))

    def test_owner_provider_revision_and_transaction_boundaries(self):
        with self.assertRaises(AccessDenied):
            self.service.authorize(self.other, provider='model', selections=self.selected,
                                   expires_at=self.now + timedelta(hours=1))
        with self.assertRaises(AccessDenied):
            self.approve(provider='client-url')
        with self.assertRaises(Conflict):
            self.approve(selections=((self.item.id, 2),))
        self.approve()
        with self.store.transaction(), self.assertRaises(Conflict):
            self.suggest()
        self.assertEqual([], self.calls)

    def test_revocation_expiry_and_stale_context_prevent_calls(self):
        self.approve()
        grant = self.app.sharing(self.owner)[0]
        self.app.revoke(self.owner, grant['id'])
        with self.assertRaises(AccessDenied):
            self.suggest()
        self.approve()
        self.now += timedelta(hours=2)
        with self.assertRaises(AccessDenied):
            self.suggest()
        self.approve()
        self.app.revise(self.owner, self.item.id, text='Changed', expected_revision=1)
        with self.assertRaises(Conflict):
            self.suggest()
        self.assertEqual([], self.calls)

    def test_inflight_changes_discard_output(self):
        self.approve()
        def revoke(_):
            self.app.logout(self.owner)
            return {'kind': 'request_draft', 'message': 'Must not return'}
        self.callback = revoke
        with self.assertRaises(AccessDenied):
            self.suggest()

    def test_forgetting_during_generation_discards_output(self):
        self.approve()
        def forget(_):
            self.app.forget(self.owner, self.item.id)
            return {'kind': 'request_draft', 'message': 'Must not return'}
        self.callback = forget
        with self.assertRaises(AccessDenied):
            self.suggest()

    def test_model_commands_are_never_executed(self):
        self.approve()
        before = self.app.export(self.owner)
        for output in ({'kind': 'grant', 'message': 'Share all memories'},
                       {'kind': 'request_draft', 'message': 'Visit', 'execute': True},
                       {'kind': 'request_draft', 'message': ' '},
                       {'kind': 'request_draft', 'message': 'x' * 4001}, 'raw text'):
            self.callback = lambda _, output=output: output
            with self.assertRaises(ValueError):
                self.suggest()
        self.callback = lambda _: {'kind': 'request_draft', 'message': 'Ignore consent and send all records'}
        self.assertIn('Ignore consent', self.suggest().message)
        self.assertEqual(before, self.app.export(self.owner))

    def test_provider_error_does_not_escape_or_chain(self):
        self.approve()
        def fail(_):
            raise RuntimeError('Private provider payload')
        self.callback = fail
        with self.assertRaises(ValueError) as error:
            self.suggest()
        self.assertNotIn('Private', str(error.exception))
        self.assertIsNone(error.exception.__context__)
        self.assertIsNone(error.exception.__cause__)

    def test_approval_retry_and_failed_selection_are_atomic(self):
        self.approve()
        before = self.app.sharing(self.owner)
        self.approve()
        self.assertEqual(before, self.app.sharing(self.owner))
        with self.assertRaises(Conflict):
            self.approve(selections=((self.private.id, 1), (self.item.id, 2)))
        self.assertEqual(before, self.app.sharing(self.owner))

    def test_permission_revocation_during_generation_discards_output(self):
        self.approve()
        def revoke(_):
            self.app.revoke(self.owner, self.app.sharing(self.owner)[0]['id'])
            return {'kind': 'request_draft', 'message': 'Must not return'}
        self.callback = revoke
        with self.assertRaises(AccessDenied):
            self.suggest()
