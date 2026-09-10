"""
Pins for the root Makefile.

It is shorthand, and it must stay shorthand: CI's behaviour is defined in
ci.yml and pyproject.toml, and a Makefile that started carrying its own copy
of a threshold would be right until the first time one of them moved.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"

DOCUMENTED_TARGETS = (
    "help",
    "install",
    "dev",
    "test",
    "lint",
    "eval",
    "eval-live",
    "lock",
    "docker",
)


def _recipe_lines() -> list[str]:
    return [
        line.strip()
        for line in MAKEFILE.read_text().splitlines()
        if line.startswith("\t")
    ]


def test_every_documented_target_exists():
    text = MAKEFILE.read_text()

    for target in DOCUMENTED_TARGETS:
        assert re.search(rf"^{re.escape(target)}:", text, re.MULTILINE), target


def test_lock_uses_the_uv_version_ci_pins():
    """
    A different uv formats the lock header differently, so `make lock` on the
    wrong version fails CI's drift check on an otherwise correct commit.
    """
    ci_version = re.search(
        r'setup-uv@[^\n]*\n\s*with:\s*\n\s*version:\s*"([^"]+)"', CI.read_text()
    )
    make_version = re.search(
        r"^UV_VERSION := (\S+)$", MAKEFILE.read_text(), re.MULTILINE
    )

    assert ci_version and make_version
    assert make_version.group(1) == ci_version.group(1)


def test_no_eval_floor_is_defined_here():
    """The floors live in ci.yml. A second copy is right until one of them moves."""
    assert not any("--min-" in line for line in _recipe_lines())


def test_recipes_are_tab_indented():
    """make 3.81 reads a space-indented recipe as a syntax error."""
    body = MAKEFILE.read_text().splitlines()
    for index, line in enumerate(body):
        if re.match(r"^[a-z-]+:", line):
            following = body[index + 1] if index + 1 < len(body) else ""
            if following.strip():
                assert following.startswith("\t"), f"recipe after {line!r}"
