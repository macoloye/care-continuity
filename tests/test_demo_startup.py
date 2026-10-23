"""Fixture lifecycle and schema-eight preservation checks."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from care_continuity import CareApplication, SQLiteStore
from care_continuity.web import WebApp
from care_continuity import store as schema


class DemoStartupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'demo.db'

    def test_reopen_preserves_corrections_forgetting_and_removed_relationships(self):
        with SQLiteStore(self.path) as store:
            web = WebApp(store)
            token = web.sessions.issue('mei')
            memories = web.app.export(token)['memories']
            web.app.revise(token, memories[0]['id'], text='Changed example', expected_revision=1)
            web.app.forget(token, memories[1]['id'])
            web.app.remove_member(token, member='worker')
            before = web.app.export(token)
        with SQLiteStore(self.path) as store:
            web = WebApp(store)
            after = web.app.export(token)
            before.pop("exported_at")
            after.pop("exported_at")
            self.assertEqual(before, after)
            self.assertEqual(2, store.connection.execute('SELECT count(*) FROM memories').fetchone()[0])
            for memory in web.app.export(token)['memories']:
                web.app.forget(token, memory['id'])
        with SQLiteStore(self.path) as store:
            web = WebApp(store)
            self.assertEqual([], web.app.export(token)['memories'])

    def test_seed_failure_rolls_back_and_can_retry(self):
        with SQLiteStore(self.path) as store:
            with patch.object(CareApplication, 'remember', side_effect=RuntimeError('fixture failure')):
                with self.assertRaises(RuntimeError):
                    WebApp(store)
            self.assertEqual('eligible', store.connection.execute('SELECT state FROM app_setup').fetchone()[0])
            self.assertEqual(0, store.connection.execute('SELECT count(*) FROM people').fetchone()[0])
            WebApp(store)
            self.assertEqual('seeded', store.connection.execute('SELECT state FROM app_setup').fetchone()[0])

    def legacy(self):
        db = sqlite3.connect(self.path)
        for script in (schema.SCHEMA, schema.SESSION_SCHEMA, schema.FOLLOWUP_RESOLUTION_SCHEMA,
                       schema.KNOWLEDGE_PILOT_SCHEMA, schema.QUALIFICATION_SCHEMA, schema.OUTBOX_SCHEMA,
                       schema.DIRECTORY_SCHEMA):
            db.executescript(script)
        db.execute("INSERT INTO people VALUES ('legacy', 'Existing person', 'person', '2026-10-21')")
        db.execute('PRAGMA user_version=7')
        db.commit()
        db.close()

    def test_legacy_installation_is_preserved_without_seed(self):
        self.legacy()
        for _ in range(2):
            with SQLiteStore(self.path) as store:
                web = WebApp(store)
                self.assertEqual(['legacy'], [p['id'] for p in web.directory.people()])
                self.assertEqual('preserved', store.connection.execute('SELECT state FROM app_setup').fetchone()[0])
                self.assertEqual(8, store.connection.execute('PRAGMA user_version').fetchone()[0])
                self.assertEqual(0, store.connection.execute('SELECT count(*) FROM memories').fetchone()[0])

    def test_migration_failure_rolls_back(self):
        self.legacy()
        with patch.object(schema, 'SETUP_SCHEMA', schema.SETUP_SCHEMA + '; INVALID SQL;'):
            with self.assertRaises(sqlite3.OperationalError):
                SQLiteStore(self.path)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(7, db.execute('PRAGMA user_version').fetchone()[0])
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='app_setup'").fetchone())
            self.assertEqual('Existing person', db.execute('SELECT name FROM people').fetchone()[0])
