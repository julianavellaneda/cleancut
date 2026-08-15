"""
Tests for .env resolution across deployment layouts.

Regression: the original `parents[3]` walk raised IndexError inside the Docker
image (where the module sits at /app/app/main.py, which has only 3 parents),
crashing the container during import. Locally it also pointed one directory
above the repo root, so the .env was never found.
"""

import pytest

from app.config import root_env_path


@pytest.fixture
def repo(tmp_path):
    """A repo-shaped tree: .git and .env at the root, app package underneath."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test\n")
    (tmp_path / "backend" / "app" / "services").mkdir(parents=True)
    return tmp_path


def test_finds_env_from_main_module(repo):
    main = repo / "backend" / "app" / "main.py"
    assert root_env_path(main) == repo / ".env"


def test_finds_same_env_from_deeper_module(repo):
    """Modules at different depths must resolve to the same repo-root .env."""
    processor = repo / "backend" / "app" / "services" / "processor.py"
    assert root_env_path(processor) == repo / ".env"


def test_docker_container_path_returns_none():
    """
    The exact path the Dockerfile produces. /app/app/main.py has only three
    parents, so the original parents[3] raised IndexError here and killed the
    container during import.

    This uses the literal path rather than a tmp_path copy on purpose: the
    failure depends on absolute depth, and anything under tmp_path is deep
    enough to mask it.
    """
    assert root_env_path("/app/app/main.py") is None


@pytest.mark.parametrize("shallow", [
    "/app/app/main.py",                    # the Docker layout
    "/app/app/services/processor.py",      # deeper module, same image
    "/app/main.py",
    "/main.py",
])
def test_shallow_layouts_do_not_raise(shallow):
    """Any layout too shallow to hold a repo root must degrade, not raise."""
    assert root_env_path(shallow) is None


def test_stops_at_repo_root(tmp_path):
    """An .env outside the repo must not be picked up."""
    (tmp_path / "outside.env").write_text("x=1")
    (tmp_path / ".env").write_text("LEAKED=yes\n")
    repo = tmp_path / "myrepo"
    (repo / "backend" / "app").mkdir(parents=True)
    (repo / ".git").mkdir()
    # No .env inside the repo, and the one above it is out of bounds.
    assert root_env_path(repo / "backend" / "app" / "main.py") is None


def test_real_checkout_resolves_next_to_env_example():
    """
    In the actual checked-out tree the resolved .env - if the developer has
    created one - sits at the repo root beside .env.example.
    """
    import app.main as main_module

    resolved = root_env_path(main_module.__file__)
    if resolved is None:
        pytest.skip("no .env in this checkout")
    assert (resolved.parent / ".env.example").exists(), (
        f"expected repo root, got {resolved.parent}"
    )
