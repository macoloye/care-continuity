"""SQLite persistence. Transactions serialize authorization with each write."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, subject TEXT NOT NULL, kind TEXT NOT NULL,
    text TEXT NOT NULL, source TEXT NOT NULL, confirmed INTEGER NOT NULL,
    revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS memory_history (
    memory_id TEXT NOT NULL REFERENCES memories(id), revision INTEGER NOT NULL,
    text TEXT NOT NULL, source TEXT NOT NULL, confirmed INTEGER NOT NULL,
    changed_at TEXT NOT NULL, PRIMARY KEY(memory_id, revision)
);
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY, subject TEXT NOT NULL, recipient TEXT NOT NULL,
    purpose TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL,
    operation TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS grants_lookup ON grants
    (subject, recipient, purpose, resource_type, resource_id, operation);
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY, subject TEXT NOT NULL, recipient TEXT NOT NULL,
    purpose TEXT NOT NULL, message TEXT NOT NULL, state TEXT NOT NULL,
    idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE(subject, idempotency_key)
);
CREATE TABLE IF NOT EXISTS request_context (
    request_id TEXT NOT NULL REFERENCES requests(id),
    memory_id TEXT NOT NULL REFERENCES memories(id), revision INTEGER NOT NULL,
    PRIMARY KEY(request_id, memory_id)
);
CREATE TABLE IF NOT EXISTS events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL,
    actor TEXT NOT NULL, resource_id TEXT NOT NULL, action TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, kind TEXT NOT NULL,
    source TEXT NOT NULL, contributor TEXT NOT NULL, reviewer TEXT,
    review_due TEXT, status TEXT NOT NULL DEFAULT 'draft'
);
PRAGMA user_version = 1;
"""


class SQLiteStore:
    """One connection per thread; use a file path for durable records."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(str(path), isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            # Serialize startup too: another process may be upgrading this file.
            with self.transaction() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2):
                    raise ValueError(f"Unsupported database schema: {version}")
                if version == 0:
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            db.execute(statement)
                if version < 2:
                    for statement in SESSION_SCHEMA.split(";"):
                        if statement.strip():
                            db.execute(statement)
                    db.execute("PRAGMA user_version = 2")
        except BaseException:
            self.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        # Nested service calls join the application transaction via savepoints.
        nested = self.connection.in_transaction
        savepoint = "sp_" + uuid4().hex
        self.connection.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
        try:
            yield self.connection
            if nested:
                self.connection.execute(f"RELEASE {savepoint}")
            else:
                self.connection.commit()
        except BaseException:
            if nested:
                self.connection.execute(f"ROLLBACK TO {savepoint}")
                self.connection.execute(f"RELEASE {savepoint}")
            else:
                self.connection.rollback()
            raise

    def event(self, subject: str, actor: str, resource_id: str, action: str, at: str) -> None:
        # Deliberately exclude care text from audit events.
        self.connection.execute(
            "INSERT INTO events(subject, actor, resource_id, action, occurred_at) VALUES (?, ?, ?, ?, ?)",
            (subject, actor, resource_id, action, at),
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


SESSION_SCHEMA = """
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY, actor TEXT NOT NULL,
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE care_circle (
    subject TEXT NOT NULL, member TEXT NOT NULL, role TEXT NOT NULL,
    added_at TEXT NOT NULL, removed_at TEXT, PRIMARY KEY(subject, member)
);
CREATE TABLE followups (
    request_id TEXT PRIMARY KEY REFERENCES requests(id),
    due_at TEXT NOT NULL, alternative TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""
