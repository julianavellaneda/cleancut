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

import re
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
    assert result.returncode == 0, f"import failed in Docker layout:\n{result.stderr}"
    assert "CleanCut API" in result.stdout


def test_env_resolution_at_literal_container_path(container_root):
    """
    Resolve the .env for the real in-container path, from inside the copied
    tree. This is the assertion that actually fails if the fixed-depth
    `parents[3]` walk ever comes back.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.config import root_env_path;"
            "print(repr(root_env_path('/app/app/main.py')))",
        ],
        cwd=container_root,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(container_root)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "None"


def test_container_layout_has_no_repo_root_above_package(container_root):
    """
    Guard the precondition this test depends on: the package really is shallow
    enough to have triggered the original IndexError.
    """
    main_py = container_root / "app" / "main.py"
    assert main_py.is_file(), "the copied tree must contain app/main.py"
    # Exactly two levels below the root - /app/app/main.py in the image. That
    # shallowness is what made the old fixed-depth `parents[3]` walk raise
    # IndexError, so it is the precondition the test above is only meaningful
    # against. `main_py` was computed here and never asserted on, which left
    # this guard silently guarding nothing.
    assert main_py.relative_to(container_root).parts == ("app", "main.py")
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


REPO_ROOT = BACKEND_DIR.parent


def _ignored_patterns(dockerignore: Path) -> set[str]:
    return {
        line.strip()
        for line in dockerignore.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def test_frontend_dockerignore_excludes_host_node_modules():
    """
    `frontend/Dockerfile` runs `npm ci` and then `COPY . .`, so a host
    `node_modules/` in the build context is copied straight over the one the
    image just installed - handing a Linux container macOS native binaries
    (sharp, unrs-resolver, fsevents). This is the correctness half of the
    .dockerignore work, and it is a one-line deletion away from coming back.
    """
    ignored = _ignored_patterns(REPO_ROOT / "frontend" / ".dockerignore")
    assert "node_modules/" in ignored
    assert ".next/" in ignored


def test_backend_dockerignore_excludes_media_and_venv():
    """
    The backend context is uploaded to the daemon whole, whatever the Dockerfile
    later COPYs. Without these the upload carried `.venv` (macOS wheels a Linux
    image cannot use) plus every recording, export and the SQLite database -
    customer audio going into an image build.
    """
    ignored = _ignored_patterns(REPO_ROOT / "backend" / ".dockerignore")
    for pattern in (".venv/", "uploads/", "exports/", "*.db"):
        assert pattern in ignored, f"{pattern} missing from backend/.dockerignore"


def test_frontend_build_fetches_no_fonts_over_the_network():
    """
    `next/font/google` downloads the face during `next build`, so a container
    build needed working DNS and reachable fonts.googleapis.com. Every face is
    committed under `src/app/fonts/` and loaded with `next/font/local`.

    The face list moves with the design; the `next/font/google` prohibition is
    the assertion this test exists for and does not.
    """
    layout = (REPO_ROOT / "frontend" / "src" / "app" / "layout.tsx").read_text()
    imports = [line for line in layout.splitlines() if line.startswith("import ")]
    assert not any("next/font/google" in line for line in imports)
    assert any("next/font/local" in line for line in imports)

    fonts = REPO_ROOT / "frontend" / "src" / "app" / "fonts"
    # Figtree body, Caprasimo display, GeistMono for timestamps. Each ships
    # beside its SIL OFL text, which is a condition of redistributing them.
    for face, licence in (
        ("Figtree-Variable.woff2", "FIGTREE-LICENSE.txt"),
        ("Caprasimo-Regular.woff2", "CAPRASIMO-LICENSE.txt"),
        ("GeistMono-Variable.woff2", "GEIST-LICENSE.txt"),
    ):
        assert (fonts / face).exists(), f"{face} missing from src/app/fonts/"
        assert (fonts / licence).exists(), f"{licence} missing from src/app/fonts/"


def test_backend_origin_is_not_resolved_at_build_time():
    """
    The backend proxy must be a route handler, never a `rewrites()` entry.

    Next evaluates `rewrites()` during `next build` and writes the resolved
    destination into `.next/routes-manifest.json`; `next start` routes from that
    manifest rather than re-reading next.config.ts. So a rewrite pointing at
    `process.env.BACKEND_ORIGIN` resolves in the *build* environment, which under
    `docker compose build` has no BACKEND_ORIGIN at all - baking in the
    `http://localhost:8000` default, which inside the frontend container is the
    frontend itself. Every API call in Compose failed.

    Pinned here rather than left to a comment because the broken version looked
    correct and was documented as working. A route handler runs per request, so
    the environment it reads is the running container's.
    """
    config = (REPO_ROOT / "frontend" / "next.config.ts").read_text()
    # Comments stripped first: the file *explains* why there is no rewrite here,
    # so a bare substring search would match the explanation and never the code.
    code = re.sub(r"/\*.*?\*/", "", config, flags=re.S)
    code = re.sub(r"//.*", "", code)
    assert "rewrites" not in code, (
        "next.config.ts declares a rewrite again. Rewrites are resolved at build "
        "time and cannot carry a runtime BACKEND_ORIGIN - use the route handler."
    )

    handler = REPO_ROOT / "frontend" / "src" / "app" / "api" / "[...path]" / "route.ts"
    assert handler.exists(), "The /api proxy route handler is missing."

    source = handler.read_text()
    # Both are what keep the origin a per-request read: without force-dynamic the
    # route can be evaluated once and cached, which is how the build-time bug
    # comes back wearing a different hat.
    assert 'export const dynamic = "force-dynamic"' in source
    assert 'export const runtime = "nodejs"' in source
    assert "process.env.BACKEND_ORIGIN" in source


def test_compose_passes_backend_origin_to_the_frontend_at_runtime():
    """
    The origin must arrive as an `environment:` entry, not a build `args:`.

    A build arg would make the image work in this Compose file and nowhere else:
    the published GHCR frontend would be pinned to whichever backend built it.
    """
    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "BACKEND_ORIGIN=${BACKEND_ORIGIN:-http://backend:8000}" in compose
