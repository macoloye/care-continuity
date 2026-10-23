"""Durable delivery tests use only synthetic payloads and in-process transports."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from care_continuity import AccessDenied, CareApplication, Conflict, Operation, RequestState, SessionService, SQLiteStore
from care_continuity.outbox import DeliveryResult, OutboxService
from care_continuity.store import SCHEMA, SESSION_SCHEMA, FOLLOWUP_RESOLUTION_SCHEMA, KNOWLEDGE_PILOT_SCHEMA, QUALIFICATION_SCHEMA


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'care.sqlite'
        self.store = SQLiteStore(self.path)
        self.addCleanup(lambda: self.store.close())
        self.now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        self.clock = lambda: self.now
        self.app = CareApplication(self.store, self.clock)
        self.sessions = SessionService(self.store, self.clock)
        self.owner = self.sessions.issue('owner')
        self.recipient = self.sessions.issue('supporter')
        self.app.add_member(self.owner, member='supporter', role='supporter')
        self.memory = self.app.remember(self.owner, text='Synthetic preference')
        self.request = self.app.create_request(self.owner, recipient='supporter', purpose='visit',
            message='Synthetic request', idempotency_key='example', memory_ids=(self.memory.id,))
        self.grants = []
        for member in ('supporter',):
            for resource, resource_id, operations in (
                ('request', self.request, (Operation.READ, Operation.ACT) if member == 'supporter' else (Operation.READ, Operation.SHARE)),
                ('memory', self.memory.id, (Operation.READ, Operation.SHARE))):
                for operation in operations:
                    grant = self.app.grant(self.owner, recipient=member, purpose='visit', resource_type=resource,
                        resource_id=resource_id, operation=operation, expires_at=self.now + timedelta(hours=1))
                    self.grants.append((member, resource, operation, grant))
        self.app.authorize_delivery_provider(self.owner, self.request, provider='provider',
                                             expires_at=self.now + timedelta(hours=1))
        self.grants.extend((g['recipient'], g['resource_type'], Operation(g['operation']), g['id'])
                           for g in self.app.sharing(self.owner) if g['recipient'] == 'provider')
        self.app.queue(self.owner, self.request)
        self.worker = OutboxService(self.store, self.clock)

    def enqueue(self):
        return self.app.enqueue_delivery(self.owner, self.request, provider='provider')

    def test_provider_authorization_is_separate_idempotent_and_owner_only(self):
        before = len(self.app.sharing(self.owner))
        self.app.authorize_delivery_provider(self.owner, self.request, provider='provider',
                                             expires_at=self.now + timedelta(hours=1))
        self.assertEqual(before, len(self.app.sharing(self.owner)))
        self.assertNotIn('provider', [member['member'] for member in self.app.members(self.owner)])
        with self.assertRaises(AccessDenied):
            self.app.authorize_delivery_provider(self.recipient, self.request, provider='other',
                                                 expires_at=self.now + timedelta(hours=1))

    def test_receipt_is_not_acceptance_and_worker_has_no_open_transaction(self):
        job = self.enqueue()
        self.assertEqual(job, self.enqueue())
        with self.assertRaises(Conflict):
            self.app.dispatch(self.owner, self.request)
        calls = []
        def send(key, payload):
            self.assertFalse(self.store.connection.in_transaction)
            self.assertEqual(job, key)
            self.assertEqual('Synthetic preference', payload.context[0].text)
            calls.append(key)
            return DeliveryResult.RECEIVED
        self.worker.run_one(provider='provider', send=send)
        self.assertIsNone(self.worker.run_one(provider='provider', send=send))
        self.assertEqual([job], calls)
        self.assertEqual(RequestState.DELIVERED, self.app.read_request(self.owner, self.request).state)
        self.app.transition(self.recipient, self.request, state=RequestState.ACCEPTED)
        self.assertEqual('received', self.app.deliveries(self.owner)[0]['state'])
        self.assertEqual([], self.app.deliveries(self.recipient))

    def test_provider_disclosure_permission_is_required(self):
        for member, resource, operation, grant in self.grants:
            if member == 'provider' and resource == 'request' and operation == Operation.SHARE:
                self.app.revoke(self.owner, grant)
        with self.assertRaises(AccessDenied):
            self.enqueue()
        self.assertEqual([], self.app.deliveries(self.owner))

    def test_final_authorization_blocks_revoked_or_changed_context(self):
        self.enqueue()
        self.app.revise(self.owner, self.memory.id, text='Changed', expected_revision=1)
        self.worker.run_one(provider='provider', send=lambda *args: self.fail('Must not send stale context'))
        self.assertEqual('blocked', self.app.deliveries(self.owner)[0]['state'])

    def test_revocation_before_send_blocks_provider(self):
        self.enqueue()
        for member, resource, operation, grant in self.grants:
            if member == 'provider':
                self.app.revoke(self.owner, grant)
        self.worker.run_one(provider='provider', send=lambda *args: self.fail('Must not send revoked payload'))
        self.assertEqual('blocked', self.app.deliveries(self.owner)[0]['state'])

    def test_cancel_during_send_is_not_overwritten_by_receipt(self):
        self.enqueue()
        def send(*args):
            self.app.transition(self.owner, self.request, state=RequestState.CANCELLED)
            return DeliveryResult.RECEIVED
        self.worker.run_one(provider='provider', send=send)
        self.assertEqual(RequestState.CANCELLED, self.app.read_request(self.owner, self.request).state)
        self.assertEqual('received', self.app.deliveries(self.owner)[0]['state'])

    def test_safe_retries_use_same_id_and_stop_after_three_attempts(self):
        job = self.enqueue()
        calls = []
        def send(key, payload):
            calls.append(key)
            return DeliveryResult.NOT_SENT
        for _ in range(3):
            self.worker.run_one(provider='provider', send=send)
            self.assertIsNone(self.worker.run_one(provider='provider', send=send))
            self.now += timedelta(minutes=1)
        self.assertEqual([job] * 3, calls)
        self.assertEqual('failed', self.app.deliveries(self.owner)[0]['state'])

    def test_exception_is_ambiguous_and_does_not_persist_text_or_resend(self):
        self.enqueue()
        def send(*args):
            raise TimeoutError('PRIVATE PAYLOAD must never be stored')
        self.worker.run_one(provider='provider', send=send)
        self.now += timedelta(minutes=10)
        self.assertIsNone(self.worker.run_one(provider='provider', send=lambda *args: self.fail('No resend')))
        self.assertEqual('unknown', self.app.deliveries(self.owner)[0]['state'])
        self.assertNotIn('PRIVATE PAYLOAD', '\n'.join(self.store.connection.iterdump()))
        with self.assertRaises(Conflict):
            self.app.dispatch(self.owner, self.request)

    def test_crash_recovery_does_not_steal_and_resend(self):
        job = self.enqueue()
        def crash(*args):
            raise SystemExit('simulated worker crash')
        with self.assertRaises(SystemExit):
            self.worker.run_one(provider='provider', send=crash)
        self.store.close()
        self.store = SQLiteStore(self.path)
        self.worker = OutboxService(self.store, self.clock)
        self.assertIsNone(self.worker.run_one(provider='provider', send=lambda *args: self.fail('Lease active')))
        self.now += timedelta(minutes=5)
        self.assertIsNone(self.worker.run_one(provider='provider', send=lambda *args: self.fail('Crash outcome ambiguous')))
        row = self.store.connection.execute('SELECT state FROM delivery_jobs WHERE id=?', (job,)).fetchone()
        self.assertEqual('unknown', row['state'])
        self.assertEqual('unknown', self.store.connection.execute('SELECT outcome FROM delivery_attempts').fetchone()[0])

    def test_wrong_provider_and_nested_transaction_do_not_send(self):
        self.enqueue()
        self.assertIsNone(self.worker.run_one(provider='wrong', send=lambda *args: self.fail('Wrong provider')))
        with self.store.transaction(), self.assertRaises(Conflict):
            self.worker.run_one(provider='provider', send=lambda *args: self.fail('Open transaction'))
        with self.assertRaises(AccessDenied):
            self.app.enqueue_delivery(self.recipient, self.request, provider='provider')
        self.app.logout(self.owner)
        with self.assertRaises(AccessDenied):
            self.enqueue()


    def unknown_job(self):
        job = self.enqueue()
        self.worker.run_one(provider='provider', send=lambda *args: DeliveryResult.UNKNOWN)
        return job

    def test_reconciliation_receipt_preserves_unknown_attempt_and_is_idempotent(self):
        job = self.unknown_job()
        def lookup(key):
            self.assertEqual(job, key)
            self.assertFalse(self.store.connection.in_transaction)
            return DeliveryResult.RECEIVED
        self.assertEqual('received', self.worker.reconcile(job, provider='provider', lookup=lookup))
        self.assertEqual('received', self.worker.reconcile(job, provider='provider',
                         lookup=lambda *args: self.fail('Already resolved')))
        self.assertEqual(RequestState.DELIVERED, self.app.read_request(self.owner, self.request).state)
        self.assertEqual('unknown', self.store.connection.execute('SELECT outcome FROM delivery_attempts').fetchone()[0])
        actions = [row['action'] for row in self.store.connection.execute('SELECT action FROM events')]
        self.assertEqual(1, actions.count('delivery.reconciled.received'))

    def test_definitive_not_sent_retries_with_original_key(self):
        job = self.unknown_job()
        self.assertEqual('pending', self.worker.reconcile(job, provider='provider',
                         lookup=lambda key: DeliveryResult.NOT_SENT))
        self.assertIsNone(self.worker.run_one(provider='provider', send=lambda *args: self.fail('Backoff')))
        self.now += timedelta(minutes=1)
        calls = []
        def send(key, payload):
            calls.append(key)
            return DeliveryResult.RECEIVED
        self.worker.run_one(provider='provider', send=send)
        self.assertEqual([job], calls)
        self.assertEqual(2, self.app.deliveries(self.owner)[0]['attempts'])

    def test_reconciliation_not_sent_cannot_bypass_revocation(self):
        job = self.unknown_job()
        for member, resource, operation, grant in self.grants:
            if member == 'provider':
                self.app.revoke(self.owner, grant)
        self.assertEqual('blocked', self.worker.reconcile(job, provider='provider',
                         lookup=lambda key: DeliveryResult.NOT_SENT))
        self.assertIsNone(self.worker.run_one(provider='provider', send=lambda *args: self.fail('Revoked')))

    def test_reconciliation_receipt_preserves_cancellation(self):
        job = self.unknown_job()
        self.app.transition(self.owner, self.request, state=RequestState.CANCELLED)
        self.assertEqual('received', self.worker.reconcile(job, provider='provider',
                         lookup=lambda key: DeliveryResult.RECEIVED))
        self.assertEqual(RequestState.CANCELLED, self.app.read_request(self.owner, self.request).state)

    def test_unavailable_or_failed_lookup_never_retries(self):
        job = self.unknown_job()
        with self.assertRaises(AccessDenied):
            self.worker.reconcile(job, provider='wrong', lookup=lambda *args: self.fail('Wrong provider'))
        with self.store.transaction(), self.assertRaises(Conflict):
            self.worker.reconcile(job, provider='provider', lookup=lambda *args: self.fail('Transaction'))
        def fail(key):
            raise TimeoutError('SECRET LOOKUP ERROR')
        for lookup in (fail, lambda key: DeliveryResult.UNKNOWN, lambda key: 'invalid'):
            self.assertEqual('unknown', self.worker.reconcile(job, provider='provider', lookup=lookup))
        self.assertNotIn('SECRET LOOKUP ERROR', '\n'.join(self.store.connection.iterdump()))
        self.assertIsNone(self.worker.run_one(provider='provider', send=lambda *args: self.fail('No retry')))

    def test_stale_reconciliation_cannot_override_another_resolution(self):
        job = self.unknown_job()
        def lookup(key):
            self.worker.reconcile(job, provider='provider', lookup=lambda key: DeliveryResult.RECEIVED)
            return DeliveryResult.NOT_SENT
        self.assertEqual('received', self.worker.reconcile(job, provider='provider', lookup=lookup))
        self.assertEqual(1, self.app.deliveries(self.owner)[0]['attempts'])

    def test_reconciliation_keeps_retry_budget(self):
        job = self.enqueue()
        for _ in range(3):
            self.worker.run_one(provider='provider', send=lambda *args: DeliveryResult.UNKNOWN)
            state = self.worker.reconcile(job, provider='provider', lookup=lambda key: DeliveryResult.NOT_SENT)
            self.now += timedelta(minutes=1)
        self.assertEqual('failed', state)
        self.assertIsNone(self.worker.run_one(provider='provider', send=lambda *args: self.fail('Budget exhausted')))


class OutboxMigrationTests(unittest.TestCase):
    def legacy(self, path):
        db = sqlite3.connect(path)
        db.executescript(SCHEMA + SESSION_SCHEMA + FOLLOWUP_RESOLUTION_SCHEMA + KNOWLEDGE_PILOT_SCHEMA + QUALIFICATION_SCHEMA)
        db.execute('PRAGMA user_version=5')
        db.execute("INSERT INTO requests VALUES ('r','owner','supporter','visit','Example','queued','key','old','old')")
        db.commit()
        return db

    def test_upgrade_preserves_request_and_reopens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'care.sqlite'
            self.legacy(path).close()
            for _ in range(2):
                with SQLiteStore(path) as store:
                    self.assertEqual(8, store.connection.execute('PRAGMA user_version').fetchone()[0])
                    self.assertEqual('Example', store.connection.execute('SELECT message FROM requests').fetchone()[0])
                    self.assertEqual(0, store.connection.execute('SELECT count(*) FROM delivery_jobs').fetchone()[0])

    def test_failed_upgrade_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'care.sqlite'
            db = self.legacy(path)
            db.execute('CREATE TABLE delivery_attempts (incompatible TEXT)')
            db.commit()
            db.close()
            with self.assertRaises(sqlite3.OperationalError):
                SQLiteStore(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(5, db.execute('PRAGMA user_version').fetchone()[0])
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='delivery_jobs'").fetchone())
                self.assertEqual('Example', db.execute('SELECT message FROM requests').fetchone()[0])
