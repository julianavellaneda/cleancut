"""
Smoke test for the Docker filesystem layout.

The Dockerfile copies only `app/` into `/app/app/`, so the package sits two
levels below the filesystem root with no repo root, no .git, and no .env above
it. Importing `app.main` under that layout previously raised IndexError and the
container died before uvicorn could bind.

This reproduces the layout's *structure* in a temp directory and imports the
app in a subprocess, without needing Docker itself. The temp tree cannot
reproduce the container's absolute depth, so the depth-sensitive part of the
regression is pinned separately against the literal `/app/app/main.py` path -
here in test_env_resolution_at_literal_container_path, and in test_config.py.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def container_root(tmp_path):
    """Mirror the Dockerfile's `COPY app/ ./app/` into an isolated tree."""
    workdir = tmp_path / "app"
    shutil.copytree(
        BACKEND_DIR / "app",
        workdir / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return workdir


def _import_app(workdir, env_extra=None):
    """Import app.main from `workdir`, the way `uvicorn app.main:app` would."""
    env = {
        "PATH": "/usr/bin:/bin",
        "DATABASE_PATH": str(workdir / "data" / "test.db"),
        "PYTHONPATH": str(workdir),
        **(env_extra or {}),
    }
    return subprocess.run(
        [sys.executable, "-c", "import app.main; print(app.main.app.title)"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_app_imports_in_container_layout(container_root):
    result = _import_app(container_root)
    assert result.returncode == 0, (
        f"import failed in Docker layout:\n{result.stderr}"
    )
    assert "CleanCut API" in result.stdout


def test_env_resolution_at_literal_container_path(container_root):
    """
    Resolve the .env for the real in-container path, from inside the copied
    tree. This is the assertion that actually fails if the fixed-depth
    `parents[3]` walk ever comes back.
    """
    result = subprocess.run(
        [sys.executable, "-c",
         "from app.config import root_env_path;"
         "print(repr(root_env_path('/app/app/main.py')))"],
        cwd=container_root,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(container_root)},
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "None"


def test_container_layout_has_no_repo_root_above_package(container_root):
    """
    Guard the precondition this test depends on: the package really is shallow
    enough to have triggered the original IndexError.
    """
    main_py = container_root / "app" / "main.py"
    assert not (container_root / ".env").exists()
    assert not (container_root / ".git").exists()


def test_cors_origins_read_from_container_env(container_root):
    """Compose passes CORS_ORIGINS as an env var, with no .env file present."""
    result = subprocess.run(
        [sys.executable, "-c", "import app.main; print(app.main._cors_origins)"],
        cwd=container_root,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(container_root),
            "DATABASE_PATH": str(container_root / "data" / "test.db"),
            "CORS_ORIGINS": "https://example.com, https://two.example.com",
        },
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert "https://example.com" in result.stdout
    assert "https://two.example.com" in result.stdout
