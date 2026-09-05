"""
Tests for the hand-rolled column migration in database.py.

Two generations of schema drift are covered here:

1. A database predating the analysis-mode flag entirely must gain `preset`
   on startup rather than erroring on every query.
2. A database carrying the older boolean `bsm_mode` column must have its rows
   carried over to the `preset` id that replaced it.
3. A database from before export moved onto the worker queue must gain
   `export_status` and `export_error`, defaulting to "no export yet".
4. A database from before the transcript was persisted must gain `transcript`,
   left NULL because it cannot be reconstructed without re-transcribing.
5. A database from before exports were revision-tracked must gain
   `edit_revision` (0) and `export_revision` (NULL, "provenance unknown").
6. A database from before the review flags were columns must gain
   `is_approximate` and `is_ambiguous` on **violations** - the first migration
   that touches a second table.
7. A database whose `tasks` table predates the one-outstanding-task-per-kind
   constraint must gain the index - and, unlike every case above, this one is
   not additive: the index cannot be created over data that already violates
   it, so the duplicates have to go first.
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

LEGACY_VIOLATIONS_TABLE = """
CREATE TABLE violations (
    id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES jobs(id),
    text TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    label TEXT,
    rule_violated TEXT,
    severity TEXT,
    reasoning TEXT,
    status TEXT DEFAULT 'pending',
    action TEXT DEFAULT 'cut'
)
"""

BSM_JOBS_TABLE = LEGACY_JOBS_TABLE.replace(
    "    waveform_data TEXT\n",
    "    waveform_data TEXT,\n    bsm_mode BOOLEAN DEFAULT 0\n",
)


def _build_db(tmp_path, monkeypatch, name, create_sql, rows):
    db_path = tmp_path / name
    conn = sqlite3.connect(db_path)
    for statement in ([create_sql] if isinstance(create_sql, str) else create_sql):
        conn.execute(statement)
    for sql in rows:
        conn.execute(sql)
    conn.commit()
    conn.close()

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "engine", engine)
    return engine


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    """A database from before any analysis-mode column existed."""
    engine = _build_db(
        tmp_path, monkeypatch, "legacy.db", LEGACY_JOBS_TABLE,
        ["INSERT INTO jobs (id, filename, status) VALUES ('old-job', 'a.mp3', 'completed')"],
    )
    yield engine
    engine.dispose()


@pytest.fixture
def bsm_db(tmp_path, monkeypatch):
    """A database still carrying the retired boolean `bsm_mode` column."""
    engine = _build_db(
        tmp_path, monkeypatch, "strict_mode.db", BSM_JOBS_TABLE,
        [
            "INSERT INTO jobs (id, filename, bsm_mode) VALUES ('strict-job', 'a.mp3', 1)",
            "INSERT INTO jobs (id, filename, bsm_mode) VALUES ('prompt-job', 'b.mp3', 0)",
        ],
    )
    yield engine
    engine.dispose()


@pytest.fixture
def legacy_violations_db(tmp_path, monkeypatch):
    """A database from before the review flags were columns on `violations`."""
    engine = _build_db(
        tmp_path, monkeypatch, "violations.db",
        [LEGACY_JOBS_TABLE, LEGACY_VIOLATIONS_TABLE],
        [
            "INSERT INTO jobs (id, filename, status) VALUES ('j', 'a.mp3', 'completed')",
            "INSERT INTO violations (id, job_id, text, start_time, end_time, status) "
            "VALUES ('v', 'j', 'like', 1.0, 1.2, 'accepted')",
        ],
    )
    yield engine
    engine.dispose()


def _columns(engine):
    return {c["name"] for c in inspect(engine).get_columns("jobs")}


def _violation_columns(engine):
    return {c["name"] for c in inspect(engine).get_columns("violations")}


def test_legacy_db_is_missing_the_column(legacy_db):
    """Precondition - without this the migration test proves nothing."""
    assert "preset" not in _columns(legacy_db)


def test_migration_adds_preset(legacy_db):
    database._apply_migrations()
    assert "preset" in _columns(legacy_db)


def test_migration_preserves_existing_rows(legacy_db):
    database._apply_migrations()
    with legacy_db.begin() as conn:
        row = conn.execute(
            text("SELECT id, filename, preset FROM jobs WHERE id = 'old-job'")
        ).fetchone()
    assert row[0] == "old-job"
    assert row[1] == "a.mp3"
    assert row[2] is None  # no preset means prompt mode


def test_migration_is_idempotent(legacy_db):
    """Startup runs this every boot - a second pass must not error."""
    database._apply_migrations()
    database._apply_migrations()
    assert "preset" in _columns(legacy_db)


def test_legacy_db_is_missing_the_export_columns(legacy_db):
    """Precondition for the export-state migration below."""
    assert "export_status" not in _columns(legacy_db)
    assert "export_error" not in _columns(legacy_db)


def test_migration_adds_the_export_columns(legacy_db):
    database._apply_migrations()
    assert {"export_status", "export_error"} <= _columns(legacy_db)


def test_existing_rows_default_to_no_export(legacy_db):
    """
    An old row may well have an export sitting on disk, but the column cannot
    know that; "none" is the honest answer and the filesystem probe behind
    /export/download still serves the file.
    """
    database._apply_migrations()
    with legacy_db.begin() as conn:
        row = conn.execute(
            text("SELECT export_status, export_error FROM jobs WHERE id = 'old-job'")
        ).fetchone()
    assert row[0] == "none"
    assert row[1] is None


def test_export_column_migration_is_idempotent(legacy_db):
    database._apply_migrations()
    database._apply_migrations()
    assert {"export_status", "export_error"} <= _columns(legacy_db)


def test_legacy_db_is_missing_the_transcript_column(legacy_db):
    """Precondition for the transcript migration below."""
    assert "transcript" not in _columns(legacy_db)


def test_migration_adds_the_transcript_column(legacy_db):
    database._apply_migrations()
    assert "transcript" in _columns(legacy_db)


def test_existing_rows_have_no_transcript(legacy_db):
    """
    It cannot be backfilled without re-transcribing, so an old row keeps NULL
    and the endpoint answers 404 rather than claiming the recording was silent.
    """
    database._apply_migrations()
    with legacy_db.begin() as conn:
        value = conn.execute(
            text("SELECT transcript FROM jobs WHERE id = 'old-job'")
        ).scalar()
    assert value is None


def test_transcript_column_migration_is_idempotent(legacy_db):
    database._apply_migrations()
    database._apply_migrations()
    assert "transcript" in _columns(legacy_db)


def test_legacy_db_is_missing_the_revision_columns(legacy_db):
    """Precondition for the export-staleness migration below."""
    assert "edit_revision" not in _columns(legacy_db)
    assert "export_revision" not in _columns(legacy_db)


def test_migration_adds_the_revision_columns(legacy_db):
    database._apply_migrations()
    assert {"edit_revision", "export_revision"} <= _columns(legacy_db)


def test_existing_rows_start_at_revision_zero_with_no_known_export(legacy_db):
    """
    The counter only has to be monotonic per job, so 0 is a fine starting point
    for every old row. `export_revision` stays NULL even where a file exists:
    nothing recorded which edits produced it, and claiming a match would mark a
    file current on no evidence. NULL reads as "provenance unknown", which keeps
    the existing download working.
    """
    database._apply_migrations()
    with legacy_db.begin() as conn:
        row = conn.execute(
            text("SELECT edit_revision, export_revision FROM jobs WHERE id = 'old-job'")
        ).fetchone()
    assert row[0] == 0
    assert row[1] is None


def test_revision_column_migration_is_idempotent(legacy_db):
    database._apply_migrations()
    database._apply_migrations()
    assert {"edit_revision", "export_revision"} <= _columns(legacy_db)


def test_legacy_db_is_missing_the_review_flag_columns(legacy_violations_db):
    """Precondition for the review-flag migration below."""
    assert "is_approximate" not in _violation_columns(legacy_violations_db)
    assert "is_ambiguous" not in _violation_columns(legacy_violations_db)


def test_migration_adds_the_review_flag_columns(legacy_violations_db):
    database._apply_migrations()
    assert {"is_approximate", "is_ambiguous"} <= _violation_columns(legacy_violations_db)


def test_existing_suggestions_carry_no_review_flags(legacy_violations_db):
    """
    Nothing recorded the flag when these rows were written, so false is the
    only honest answer: a true would put "check this one" on a suggestion no
    detector ever doubted, and on an accepted row it would be a warning about
    a decision already made.
    """
    database._apply_migrations()
    with legacy_violations_db.begin() as conn:
        row = conn.execute(
            text("SELECT is_approximate, is_ambiguous FROM violations WHERE id = 'v'")
        ).fetchone()
    assert not row[0]
    assert not row[1]


def test_review_flag_migration_is_idempotent(legacy_violations_db):
    database._apply_migrations()
    database._apply_migrations()
    assert {"is_approximate", "is_ambiguous"} <= _violation_columns(legacy_violations_db)


def test_a_database_with_no_violations_table_still_migrates_jobs(legacy_db):
    """
    The two tables are asked about separately. Before this, one early return
    covered the whole function, so a table missing from a database was a reason
    to stop rather than a reason to skip.
    """
    assert "violations" not in inspect(legacy_db).get_table_names()

    database._apply_migrations()

    assert "preset" in _columns(legacy_db)


def test_bsm_mode_rows_are_backfilled_to_a_preset(bsm_db):
    """A job that ran in the old strict boolean mode keeps running that rulebook."""
    database._apply_migrations()
    with bsm_db.begin() as conn:
        presets = dict(
            conn.execute(text("SELECT id, preset FROM jobs")).fetchall()
        )
    assert presets["strict-job"] == "income-claims"
    assert presets["prompt-job"] is None


def test_bsm_mode_column_is_retired(bsm_db):
    database._apply_migrations()
    assert "bsm_mode" not in _columns(bsm_db)


def test_bsm_migration_is_idempotent(bsm_db):
    database._apply_migrations()
    database._apply_migrations()
    assert "preset" in _columns(bsm_db)
    with bsm_db.begin() as conn:
        value = conn.execute(
            text("SELECT preset FROM jobs WHERE id = 'strict-job'")
        ).scalar()
    assert value == "income-claims"


def test_init_db_adds_the_task_table_to_an_existing_database(legacy_db):
    """
    The durable queue arrived as a whole table rather than a column, so it is
    `create_all` and not `_apply_migrations` that has to pick it up on a
    database that predates it. An existing install must gain `tasks` on the
    next boot; without it every enqueue would fail on a missing table.
    """
    assert "tasks" not in inspect(legacy_db).get_table_names()

    database.init_db()

    assert "tasks" in inspect(legacy_db).get_table_names()
    assert {"id", "kind", "job_id", "state", "attempts"} <= {
        c["name"] for c in inspect(legacy_db).get_columns("tasks")
    }


# A `tasks` table from before the uniqueness constraint. Same columns, no index.
UNCONSTRAINED_TASKS_TABLE = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    job_id TEXT REFERENCES jobs(id),
    file_path TEXT,
    edit_action TEXT,
    prompt TEXT,
    preset TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP
)
"""


def _task_indexes(engine):
    return {idx["name"] for idx in inspect(engine).get_indexes("tasks")}


@pytest.fixture
def duplicate_tasks_db(tmp_path, monkeypatch):
    """
    A `tasks` table carrying exactly what the missing constraint allowed: two
    export tasks for one job, written by two requests that raced.
    """
    engine = _build_db(
        tmp_path, monkeypatch, "dupes.db",
        [LEGACY_JOBS_TABLE, UNCONSTRAINED_TASKS_TABLE],
        [
            "INSERT INTO jobs (id, filename, status) VALUES ('j1', 'a.mp3', 'completed')",
            "INSERT INTO tasks (id, kind, job_id, created_at) "
            "VALUES ('t-first', 'export', 'j1', '2024-01-01 10:00:00')",
            "INSERT INTO tasks (id, kind, job_id, created_at) "
            "VALUES ('t-second', 'export', 'j1', '2024-01-01 10:00:01')",
            "INSERT INTO tasks (id, kind, job_id, created_at) "
            "VALUES ('t-other', 'reanalyze', 'j1', '2024-01-01 10:00:02')",
        ],
    )
    yield engine
    engine.dispose()


def test_the_task_uniqueness_index_is_added_to_an_existing_table(duplicate_tasks_db):
    assert "uq_tasks_job_kind" not in _task_indexes(duplicate_tasks_db)

    database._apply_migrations()

    indexes = inspect(duplicate_tasks_db).get_indexes("tasks")
    index = next(i for i in indexes if i["name"] == "uq_tasks_job_kind")
    assert index["unique"]
    assert index["column_names"] == ["job_id", "kind"]


def test_duplicate_tasks_are_resolved_before_the_index_is_created(duplicate_tasks_db):
    """
    Oldest kept, and only within a kind.

    The oldest row is the one the caller was actually told about; a duplicate is
    the loser of a race, and running it would mean a second FFmpeg pass writing
    the same output path. Creating the index without this pass raises, and a
    failed migration is a server that will not boot.
    """
    database._apply_migrations()

    with duplicate_tasks_db.begin() as conn:
        rows = conn.execute(text("SELECT id, kind FROM tasks ORDER BY id")).fetchall()

    assert sorted(rows) == [("t-first", "export"), ("t-other", "reanalyze")]


def test_the_task_migration_is_idempotent(duplicate_tasks_db):
    """Every boot runs this. The second one must be a no-op, not an error."""
    database._apply_migrations()
    database._apply_migrations()

    assert "uq_tasks_job_kind" in _task_indexes(duplicate_tasks_db)


def test_the_task_migration_is_skipped_when_the_table_is_absent(legacy_db):
    """
    Per the per-table rule: a database with no `tasks` table is not an error,
    and must not stop the columns on other tables being checked.
    """
    database._apply_migrations()  # must not raise

    assert "tasks" not in inspect(legacy_db).get_table_names()
    assert "preset" in _columns(legacy_db)


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
