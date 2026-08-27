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
    """Add columns that were introduced after a DB was first created."""
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return
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
