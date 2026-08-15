"""
Tests for the hand-rolled column migration in database.py.

`bsm_mode` was added after the first databases were created, so an existing
audio_compliance.db from before that change must gain the column on startup
rather than erroring on every query.
"""

import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

import app.database as database


LEGACY_JOBS_TABLE = """
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    original_filename TEXT,
    media_type TEXT DEFAULT 'audio',
    prompt TEXT,
    status TEXT DEFAULT 'pending',
    auto_fix BOOLEAN DEFAULT 0,
    auto_scrub BOOLEAN DEFAULT 0,
    duration_seconds REAL,
    language TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT,
    waveform_data TEXT
)
"""


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    """A pre-bsm_mode database with one row already in it."""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(LEGACY_JOBS_TABLE)
    conn.execute(
        "INSERT INTO jobs (id, filename, status) VALUES ('old-job', 'a.mp3', 'completed')"
    )
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "engine", engine)
    yield engine
    engine.dispose()


def _columns(engine):
    return {c["name"] for c in inspect(engine).get_columns("jobs")}


def test_legacy_db_is_missing_the_column(legacy_db):
    """Precondition - without this the migration test proves nothing."""
    assert "bsm_mode" not in _columns(legacy_db)


def test_migration_adds_bsm_mode(legacy_db):
    database._apply_migrations()
    assert "bsm_mode" in _columns(legacy_db)


def test_migration_preserves_existing_rows(legacy_db):
    database._apply_migrations()
    with legacy_db.begin() as conn:
        row = conn.execute(
            text("SELECT id, filename, bsm_mode FROM jobs WHERE id = 'old-job'")
        ).fetchone()
    assert row[0] == "old-job"
    assert row[1] == "a.mp3"
    assert not row[2]  # defaults to false, not NULL-crashing


def test_migration_is_idempotent(legacy_db):
    """Startup runs this every boot - a second pass must not error."""
    database._apply_migrations()
    database._apply_migrations()
    assert "bsm_mode" in _columns(legacy_db)


def test_migration_noop_on_empty_database(tmp_path, monkeypatch):
    """No jobs table yet (fresh install) - must return quietly."""
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setattr(database, "engine", engine)
    database._apply_migrations()  # must not raise
    assert "jobs" not in inspect(engine).get_table_names()
    engine.dispose()


def test_database_path_env_override(tmp_path, monkeypatch):
    """
    Docker Compose mounts a volume and points DATABASE_PATH at it; the parent
    directory may not exist yet.
    """
    import importlib

    target = tmp_path / "nested" / "dir" / "compose.db"
    monkeypatch.setenv("DATABASE_PATH", str(target))
    reloaded = importlib.reload(database)
    try:
        assert reloaded.DATABASE_PATH == target
        assert target.parent.is_dir()
    finally:
        monkeypatch.undo()
        importlib.reload(database)
