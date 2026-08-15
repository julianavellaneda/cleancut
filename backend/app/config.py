"""
Filesystem layout helpers.

Kept free of third-party imports so it can be loaded (and tested) without
pulling in FastAPI, faster-whisper, or the OpenAI client.
"""

from pathlib import Path


def root_env_path(module_file: str | Path) -> Path | None:
    """
    Find the ``.env`` that applies to a module, by walking up from it.

    Returns ``None`` when there is no ``.env`` above the module. That is the
    normal case inside the Docker image, where this package lives at
    ``/app/app/`` and configuration arrives as container environment variables.

    The search walks up rather than indexing a fixed number of parents, so it
    stays correct for modules at different depths (``app/main.py`` and
    ``app/services/processor.py`` both find the repo root) and cannot raise
    ``IndexError`` on a shallow layout. A fixed ``parents[3]`` walk previously
    killed the container during import, before FastAPI ever initialized.

    The walk stops at the repository root so a stray ``.env`` in a parent
    directory or the user's home cannot be picked up by accident.
    """
    for parent in Path(module_file).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
        if (parent / ".git").exists():
            break
    return None
