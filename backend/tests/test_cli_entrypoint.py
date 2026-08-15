"""
Tests that the documented CLI invocation actually starts.

Regression: `analysis/` mixed package-relative imports (`from .transcriber`)
with top-level ones (`from transcriber`), which only worked because
`processor.py` pushed `app/analysis` onto sys.path first. That made
`python -m app.analysis.analyze` - the command in the README - die on import
before argparse ever ran. Imports are now uniformly package-relative.

These run in a subprocess from `backend/` because that is exactly how the docs
tell a reader to run it; importing in-process would not catch a sys.path
dependency that pytest's rootdir handling papers over.
"""

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "app.analysis.analyze", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_documented_module_invocation_starts():
    result = _run_cli("--help")

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_no_module_uses_a_syspath_hack():
    """
    `analysis` and `services` must import each other as packages. A stray
    sys.path insert makes the same module importable under two names, which
    silently creates two distinct `Violation` classes.
    """
    for name in ("analyze.py", "prompt_analyzer.py", "transcriber.py"):
        source = (BACKEND_DIR / "app" / "analysis" / name).read_text()
        assert "sys.path.insert" not in source, f"{name} still patches sys.path"

    processor = (BACKEND_DIR / "app" / "services" / "processor.py").read_text()
    assert "sys.path.insert" not in processor


def test_analysis_modules_are_importable_as_a_package():
    result = subprocess.run(
        [sys.executable, "-c",
         "from app.analysis.prompt_analyzer import Violation as A;"
         "from app.services.processor import Violation as B;"
         "print(A is B)"],
        cwd=BACKEND_DIR, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_preset_choices_are_advertised():
    result = _run_cli("--help")

    assert "income-claims" in result.stdout
    assert "pii-redaction" in result.stdout


def test_unknown_preset_is_rejected():
    result = _run_cli("audio.mp3", "--preset", "nope")

    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_missing_input_is_rejected():
    result = _run_cli("--prompt", "find filler words")

    assert result.returncode != 0
    assert "audio_file or --transcript" in result.stderr


def test_missing_instruction_is_rejected():
    """Neither a prompt nor a preset means there is nothing to analyze for."""
    result = _run_cli("audio.mp3")

    assert result.returncode != 0
    assert "--prompt or --preset" in result.stderr


def test_missing_transcript_file_exits_cleanly(tmp_path):
    result = _run_cli("--transcript", str(tmp_path / "nope.txt"), "--prompt", "x")

    assert result.returncode == 1
    assert "not found" in result.stdout
