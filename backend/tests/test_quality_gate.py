"""
The backend gate is configured *and* invoked.

`pyproject.toml` can hold a flawless ruff and mypy configuration and mean
nothing at all, because configuration does not run itself. This is the same
argument `test_dependency_locks.py` makes about `--generate-hashes`: hashes
that nothing installs with are decoration, and a lint config that no workflow
step calls is decoration too. The difference is that a missing CI step leaves
no trace - the build is green, the file looks maintained, and the gate has
simply never run.

There is deliberately no assertion here on what ruff or mypy *find*. That is
what running them does. What is pinned is that they are wired up, and that the
three places naming a Python version agree.
"""

import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = BACKEND_DIR / "pyproject.toml"

# The command each gate runs in ci.yml. Matched loosely on the tool and its
# mode, not on the exact flag list - the flags are the workflow's business, and
# duplicating them here would make this test a second place every flag change
# has to land.
GATE_COMMANDS = (
    "ruff format --check",
    "ruff check",
    "run: mypy",
)

# 3.10 is the floor: it is what the README promises, what the locks compile
# for, and therefore what the linter must target. CI runs 3.12, which is a
# different question and deliberately not this one.
TARGET_PYTHON = "3.10"


@pytest.mark.parametrize("command", GATE_COMMANDS)
def test_ci_actually_runs_the_gate(command):
    assert command in CI.read_text(), (
        f"`{command}` is configured in backend/pyproject.toml but no step in "
        "ci.yml runs it. A gate nothing invokes is decoration."
    )


def test_the_backend_job_name_still_describes_what_it_does():
    """
    The job was called "Backend (pytest)" when pytest was all it ran. A stale
    name is how a reader concludes the backend is untyped and unlinted while
    looking straight at the job that lints it.
    """
    ci = CI.read_text()
    assert "name: Backend (pytest)" not in ci, (
        "the backend job runs more than pytest now; its name should say so"
    )
    assert re.search(r"name: Backend \(.*lint.*\)", ci), (
        "expected the backend job name to mention linting"
    )


def test_the_python_floor_is_stated_consistently():
    """
    Three files name 3.10 for three different reasons: the locks compile at
    that lower bound, ruff targets it when rewriting syntax, and the README
    promises it. Two of them drifting is invisible - the build stays green and
    the repo quietly starts accepting syntax the version it advertises cannot
    run.
    """
    assert f"--python-version {TARGET_PYTHON}" in CI.read_text(), (
        "ci.yml's lock compile no longer names the Python floor this test knows"
    )

    pyproject = PYPROJECT.read_text()
    target = re.search(r'target-version\s*=\s*"py(\d)(\d+)"', pyproject)
    assert target, "backend/pyproject.toml sets no ruff target-version"
    assert f"{target.group(1)}.{target.group(2)}" == TARGET_PYTHON, (
        f"ruff targets {target.group(0)} but the locks compile for "
        f"{TARGET_PYTHON}. Ruff's UP rules rewrite syntax against this, so a "
        "higher target lets code merge that the advertised Python cannot run."
    )


def test_every_package_under_app_is_a_real_package():
    """
    `app/analysis/` had no `__init__.py` while `routes/`, `services/` and
    `eval/` all did, making it an implicit namespace package nested inside a
    regular one. The visible symptom is a type checker refusing to start -
    the same file reachable as both `analyze` and `app.analysis.analyze` is a
    hard error. The invisible one is worse and already has a test of its own:
    a module importable under two names is two distinct classes, which is what
    `test_cli_entrypoint.py` exists to catch for `Violation`.
    """
    app_dir = BACKEND_DIR / "app"
    missing = sorted(
        str(directory.relative_to(BACKEND_DIR))
        for directory in app_dir.rglob("*")
        if directory.is_dir()
        and directory.name != "__pycache__"
        and any(directory.glob("*.py"))
        and not (directory / "__init__.py").is_file()
    )
    assert not missing, (
        f"these directories hold Python modules but are not packages: {missing}. "
        "Add an __init__.py - see this test's docstring for what goes wrong."
    )
