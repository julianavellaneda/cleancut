"""
Pins for the devcontainer: CleanCut runnable from a checkout with nothing on
the host.

None of this can be exercised by the suite - building the image needs Docker -
so what is pinned is the handful of decisions that fail silently when undone:
a base image that floats, a host's macOS binaries leaking into a Linux
container, a digest nobody is told to move, and a setup script that could
overwrite a real key.
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEVCONTAINER = REPO_ROOT / ".devcontainer"


def _json_without_comments(path: Path) -> str:
    """devcontainer.json is JSONC; its comments are whole lines."""
    return "\n".join(
        line
        for line in path.read_text().splitlines()
        if not line.lstrip().startswith("//")
    )


def test_every_base_image_is_pinned_by_digest():
    """
    A tag moves under you. Phase A pinned the backend's dependencies for that
    reason, and an image that floats is the same failure one layer down.
    """
    from_lines = [
        line
        for line in (DEVCONTAINER / "Dockerfile").read_text().splitlines()
        if line.startswith("FROM ")
    ]

    assert len(from_lines) >= 2
    for line in from_lines:
        assert re.search(r"@sha256:[0-9a-f]{64}\b", line), line


def test_dependency_directories_are_volumes_not_the_host_checkout():
    """
    A local "Reopen in Container" bind-mounts a checkout that may already hold
    a macOS .venv and node_modules. Without a volume over each, the container
    runs - and fails on - the host's native binaries.
    """
    import json

    config = json.loads(_json_without_comments(DEVCONTAINER / "devcontainer.json"))
    volume_targets = [mount for mount in config["mounts"] if "type=volume" in mount]

    for directory in ("/backend/.venv", "/frontend/node_modules"):
        assert any(
            f"target=${{containerWorkspaceFolder}}{directory}," in m
            for m in volume_targets
        ), f"{directory} is not a volume mount"


def test_post_create_script_is_what_runs():
    import json

    config = json.loads(_json_without_comments(DEVCONTAINER / "devcontainer.json"))

    assert config["postCreateCommand"] == "bash .devcontainer/post-create.sh"
    assert (DEVCONTAINER / "post-create.sh").is_file()


def test_post_create_never_overwrites_an_existing_env():
    """An existing .env is where someone's real key lives."""
    script = (DEVCONTAINER / "post-create.sh").read_text()
    writes = [line for line in script.splitlines() if "> .env" in line]

    assert writes, "post-create.sh no longer writes a .env at all"
    assert "if [ ! -f .env ]; then" in script


def test_the_env_template_still_has_the_line_post_create_rewrites():
    """
    post-create.sh turns a bare `CLEANCUT_MODEL=` into `mock:demo`. Lose that
    line from .env.example and the new container boots into a preflight failure
    for a key nobody was asked for.
    """
    lines = (REPO_ROOT / ".env.example").read_text().splitlines()

    assert "CLEANCUT_MODEL=" in lines


def test_dependabot_moves_the_digests():
    """A pin nothing moves goes stale quietly."""
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text())

    assert any(
        update["package-ecosystem"] == "docker"
        and update["directory"] == "/.devcontainer"
        for update in config["updates"]
    )
