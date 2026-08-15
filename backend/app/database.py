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
    if "bsm_mode" in existing:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE jobs DROP COLUMN bsm_mode"))
        except Exception:
            # DROP COLUMN needs SQLite 3.35+. Leaving the stale column is
            # harmless: the ORM no longer maps it and it is nullable.
            pass
