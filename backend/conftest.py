"""
Pytest configuration for the backend test suite.

Living at the backend root means pytest puts this directory on ``sys.path``,
so tests can ``import app.*`` the same way uvicorn does.

The DATABASE_PATH override must be set before anything imports ``app.database``,
which resolves the database location at module import time. Setting it here
keeps every test off the developer's real ``audio_compliance.db``.
"""

import os
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "ai_audio_editing_test.db"
os.environ["DATABASE_PATH"] = str(_TMP_DB)


def pytest_sessionstart(session):
    """Start every run from an empty database."""
    if _TMP_DB.exists():
        _TMP_DB.unlink()
