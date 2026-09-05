"""
`services.exports` owns the export directory, and is the only module that does.

Six modules used to derive `Path(__file__).parent.parent.parent / "exports"`
for themselves, so where exports lived depended on how deep the file asking
happened to sit, and a test had to remember which five copies to patch. These
tests pin both halves of the fix: nobody else declares the constant, and every
consumer resolves it through this module at call time, so one patch moves the
whole app.
"""

import ast
from pathlib import Path

import pytest

import app.routes.admin as admin_routes
import app.routes.audio as audio_routes
import app.services.exports as exports
import app.services.retention as retention
import app.services.worker as worker
from app.models import Job

APP_DIR = Path(__file__).parent.parent / "app"


def _module_level_names(path: Path) -> set[str]:
    """Every name this module assigns at import time."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def test_only_exports_declares_export_dir():
    owners = [
        path.relative_to(APP_DIR).as_posix()
        for path in sorted(APP_DIR.rglob("*.py"))
        if "EXPORT_DIR" in _module_level_names(path)
    ]
    assert owners == ["services/exports.py"]


def test_no_module_binds_the_export_dir_as_a_default_argument():
    """
    A default argument is evaluated once, at import.

    `retention.job_files` used to take `export_dir: Path = EXPORT_DIR`, which
    captured the value before any test could point it somewhere else - the
    quiet way a "single owner" stops being one.
    """
    offenders = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            defaults = [
                d for d in node.args.defaults + node.args.kw_defaults if d is not None
            ]
            for default in defaults:
                if isinstance(default, ast.Name) and default.id == "EXPORT_DIR":
                    offenders.append(
                        f"{path.relative_to(APP_DIR).as_posix()}:{node.name}"
                    )
    assert offenders == []


@pytest.fixture
def redirected(monkeypatch, tmp_path):
    """The one patch every consumer is supposed to honour."""
    monkeypatch.setattr(exports, "EXPORT_DIR", tmp_path)
    return tmp_path


def test_export_path_for_follows_the_owner(redirected):
    job = Job(id="abc", filename="talk.mp3", media_type="audio")
    assert exports.export_path_for(job, "uploads/abc.mp3").parent == redirected


def test_worker_renders_into_the_owner_directory(redirected):
    """The worker holds no copy: `ensure_export_dir` resolves it now."""
    assert worker.exports.ensure_export_dir() == redirected


def test_routes_read_the_owner_directory(redirected):
    assert audio_routes.exports.EXPORT_DIR == redirected
    assert admin_routes.exports.EXPORT_DIR == redirected


def test_retention_sweeps_the_owner_directory(redirected, tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (redirected / "job1_edited.mp3").write_bytes(b"x")

    found = list(retention.job_files("job1", upload_dir=uploads))

    assert found == [redirected / "job1_edited.mp3"]


def test_retention_still_takes_an_explicit_override(redirected, tmp_path):
    """The argument survives; only its *default* moved to the owner."""
    elsewhere = tmp_path / "other-exports"
    elsewhere.mkdir()
    (elsewhere / "job1_edited.mp3").write_bytes(b"x")
    (redirected / "job1_edited.mp3").write_bytes(b"x")

    removed = retention.delete_job_files("job1", tmp_path / "uploads", elsewhere)

    assert removed == 1
    assert not (elsewhere / "job1_edited.mp3").exists()
    assert (redirected / "job1_edited.mp3").exists()
