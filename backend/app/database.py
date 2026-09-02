"""
SQLite database setup with SQLAlchemy.
"""

import os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from pathlib import Path

# Database file location (override with DATABASE_PATH env var for Docker/custom setups)
_env_path = os.environ.get("DATABASE_PATH", "").strip()
if _env_path:
    DATABASE_PATH = Path(_env_path)
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
    DATABASE_PATH = Path(__file__).parent.parent / "audio_compliance.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # Needed for SQLite with FastAPI
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency for getting database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables and apply lightweight migrations."""
    from . import models  # Import models to register them
    Base.metadata.create_all(bind=engine)
    _apply_migrations()


def _apply_migrations():
    """
    Add columns that were introduced after a DB was first created.

    Each table is asked about separately. A table that does not exist yet is
    skipped rather than being treated as a reason to stop: `create_all` will
    have made it with every column already, and an early return over one table
    used to mean the next one's columns were never checked.
    """
    tables = set(inspect(engine).get_table_names())
    if "jobs" in tables:
        _migrate_jobs()
    if "violations" in tables:
        _migrate_violations()
    if "tasks" in tables:
        _migrate_tasks()


def _migrate_tasks():
    """
    Constrain the queue to one outstanding task of each kind per job.

    A new *table* needs nothing here - `create_all` makes it complete. An index
    added to a table that already exists does, and this one is not additive the
    way a column is: `CREATE UNIQUE INDEX` fails outright if the data already
    violates it, and a failed migration must not be what stops the server
    booting.

    So duplicates are resolved first, oldest kept. The oldest is the one the
    caller was actually told about - a duplicate is the loser of a race between
    two requests, and the worker would have run it as a second render over the
    same output path.
    """
    inspector = inspect(engine)
    if any(idx["name"] == "uq_tasks_job_kind" for idx in inspector.get_indexes("tasks")):
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM tasks
                WHERE id NOT IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY job_id, kind
                                   ORDER BY created_at, id
                               ) AS rn
                        FROM tasks
                    )
                    WHERE rn = 1
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_job_kind "
                "ON tasks (job_id, kind)"
            )
        )


def _migrate_violations():
    """
    Give the two "do not apply this unreviewed" flags columns of their own.

    They existed on the detectors' dataclasses long before they existed here,
    and reached the reviewer only as a sentence bolted onto `reasoning` - which
    could not be filtered, sorted, or told apart from the model's own words.
    Existing rows default to false: nothing recorded the flag when they were
    written, and inventing a true would put a warning on a suggestion no
    detector ever doubted.
    """
    existing = {col["name"] for col in inspect(engine).get_columns("violations")}
    with engine.begin() as conn:
        for column in ("is_approximate", "is_ambiguous"):
            if column in existing:
                continue
            conn.execute(text(f"ALTER TABLE violations ADD COLUMN {column} BOOLEAN DEFAULT 0"))
            conn.execute(text(f"UPDATE violations SET {column} = 0 WHERE {column} IS NULL"))


def _migrate_jobs():
    inspector = inspect(engine)
    existing = {col["name"] for col in inspector.get_columns("jobs")}
    with engine.begin() as conn:
        # `bsm_mode` (a boolean) was generalized into `preset` (a nullable id).
        # Add the new column, carry old rows over, then retire the old one.
        if "preset" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN preset VARCHAR"))
            if "bsm_mode" in existing:
                conn.execute(
                    text("UPDATE jobs SET preset = 'income-claims' WHERE bsm_mode = 1")
                )

        # Export moved onto the worker queue and needs its own state, kept apart
        # from `status` so a failed export cannot destroy a completed review.
        if "export_status" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN export_status VARCHAR DEFAULT 'none'"))
            # Rows created before this column existed may already have an export
            # on disk; the filesystem probe in routes/audio.py still finds it.
            conn.execute(text("UPDATE jobs SET export_status = 'none' WHERE export_status IS NULL"))
        if "export_error" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN export_error TEXT"))

        # The transcript used to be discarded once analysis was done. Old rows
        # keep a NULL here: it cannot be backfilled without re-transcribing, and
        # the route answers 404 rather than pretending the recording was silent.
        if "transcript" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN transcript TEXT"))

        # Export staleness. `edit_revision` starts at 0 for every existing row -
        # the counter only has to be monotonic per job, not meaningful across
        # them. `export_revision` stays NULL even on a row marked 'ready':
        # nothing recorded which edit set that file came from, and inventing a
        # match would claim an export is current on no evidence. NULL is read as
        # "provenance unknown", which keeps those rows downloadable exactly as
        # they are today; the first edit after this migration bumps them into
        # the tracked world.
        if "edit_revision" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN edit_revision INTEGER DEFAULT 0"))
            conn.execute(text("UPDATE jobs SET edit_revision = 0 WHERE edit_revision IS NULL"))
        if "export_revision" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN export_revision INTEGER"))
    if "bsm_mode" in existing:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE jobs DROP COLUMN bsm_mode"))
        except Exception:
            # DROP COLUMN needs SQLite 3.35+. Leaving the stale column is
            # harmless: the ORM no longer maps it and it is nullable.
            pass
