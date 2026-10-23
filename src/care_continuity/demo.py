"""Synthetic fixture installation and host-only transport simulation."""

import argparse
from pathlib import Path

from .application import CareApplication
from .circle import CircleService
from .directory import DirectoryService
from .domain import Conflict
from .outbox import DeliveryResult, OutboxService
from .sessions import SessionService
from .store import SQLiteStore

MODEL = 'local-suggestion-simulator'
TRANSPORT = 'local-delivery-simulator'


def install_examples(store: SQLiteStore) -> None:
    """Seed only a fresh, explicitly eligible database, atomically and once.

    Upgraded databases are marked preserved by migration and are never reseeded.
    A fresh core-only database with records is also preserved rather than mixed
    with fixture data. The marker, not an empty-memory heuristic, controls replay.
    """
    with store.transaction() as db:
        state = db.execute("SELECT state FROM app_setup WHERE key='demo-v1'").fetchone()[0]
        if state != 'eligible':
            return
        occupied = any(db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone()
                       for table in ('people', 'memories', 'requests', 'care_circle', 'knowledge', 'sessions'))
        if occupied:
            db.execute("UPDATE app_setup SET state='preserved' WHERE key='demo-v1'")
            return
        directory = DirectoryService(store, CircleService(store))
        for key, name, kind in (('mei', 'Mei', 'person'), ('lina', 'Lina', 'carer'),
                                ('worker', 'Alex (visiting worker)', 'carer'),
                                ('reviewer', 'Sam (demo reviewer)', 'reviewer')):
            directory.ensure_person(person_id=key, name=name, kind=kind)
        app = CareApplication(store)
        token = SessionService(store).issue('mei')
        app.add_member(token, member='lina', role='supporter')
        app.add_member(token, member='worker', role='worker')
        app.remember(token, text='I prefer breakfast after 8.', confirmed=True)
        app.remember(token, text='Agree a time first and keep visits short.', confirmed=True)
        app.logout(token)
        db.execute("UPDATE app_setup SET state='seeded' WHERE key='demo-v1'")


def suggest(context):
    """Fixed example output: not AI, no network and no inferred clinical advice."""
    return {'kind': 'request_draft', 'message': 'Could we agree a time for a short visit?'}


def main() -> None:
    parser = argparse.ArgumentParser(description='Host-only local delivery simulator; never contacts a provider')
    parser.add_argument('--db', required=True)
    parser.add_argument('--outcome', choices=[r.value for r in DeliveryResult], required=True)
    parser.add_argument('--reconcile', metavar='JOB_ID')
    args = parser.parse_args()
    if not Path(args.db).is_file():
        parser.error('Use an existing disposable local demo database')
    with SQLiteStore(args.db) as store:
        marker = store.connection.execute("SELECT state FROM app_setup WHERE key='demo-v1'").fetchone()
        if not marker or marker[0] != 'seeded':
            raise Conflict('Simulation requires a database initialized with local examples')
        worker = OutboxService(store)
        result = DeliveryResult(args.outcome)
        if args.reconcile:
            state = worker.reconcile(args.reconcile, provider=TRANSPORT, lookup=lambda _: result)
            print(f'Simulated reconciliation: {state}')
        else:
            job = worker.run_one(provider=TRANSPORT, send=lambda *_: result)
            print(f'Simulated delivery job: {job or "none ready"}')


if __name__ == '__main__':
    main()
