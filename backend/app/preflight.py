"""
Startup environment checks.

Both hard dependencies - a model API key and FFmpeg - are only reached deep in a
background worker thread, minutes after an upload. Without a preflight the
failure surfaces as a job that transcribes for two minutes and then dies with
``The api_key client option must be set``, which reads like a bug in the app
rather than a missing line in ``.env``. Check at startup instead, and refuse to
boot with a message that says exactly what to do.

Kept free of third-party imports so it can be loaded and tested without pulling
in FastAPI or any vendor SDK - `providers` is a sibling module with the same
rule, so importing it here does not break that.
"""

import os
import shutil
from collections.abc import Callable, Mapping

from .analysis.providers import DEFAULT_MODEL_SPEC, ProviderError, parse_model_spec

# Executables that must be on PATH. ffprobe ships with ffmpeg but is packaged
# separately by some distributions, and the upload duration cap needs it.
REQUIRED_EXECUTABLES = ("ffmpeg", "ffprobe")

INSTALL_HINTS = {
    "ffmpeg": "install it with `brew install ffmpeg` (macOS) or `apt install ffmpeg` (Debian/Ubuntu)",
    "ffprobe": "it ships with ffmpeg - `brew install ffmpeg` or `apt install ffmpeg`",
}


class PreflightError(RuntimeError):
    """Raised at startup when the environment cannot support a job run."""


def missing_requirements(
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """
    Return one human-readable problem string per unmet requirement.

    ``env`` and ``which`` are injectable so tests can describe an environment
    without mutating the real one.
    """
    env = os.environ if env is None else env
    problems = []

    # Which key matters depends on which model is configured: an OpenAI key is
    # no use to a deployment pointed at Anthropic, and reporting the wrong one
    # missing is worse than reporting nothing.
    spec_value = (env.get("CLEANCUT_MODEL") or "").strip() or DEFAULT_MODEL_SPEC
    try:
        spec = parse_model_spec(spec_value)
    except ProviderError as e:
        problems.append(str(e))
    else:
        if not (env.get(spec.api_key_name) or "").strip():
            problems.append(
                f"{spec.api_key_name} is not set, and CLEANCUT_MODEL is '{spec}'. "
                "Analysis cannot run without it. Copy .env.example to .env at the "
                "repo root and add your key."
            )

    for executable in REQUIRED_EXECUTABLES:
        if which(executable) is None:
            problems.append(f"`{executable}` was not found on PATH - {INSTALL_HINTS[executable]}.")

    return problems


def verify_environment(
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> None:
    """
    Raise :class:`PreflightError` listing *every* unmet requirement.

    All problems are reported at once rather than one per restart - a missing
    key and a missing ffmpeg are usually the same five minutes of setup.

    Set ``SKIP_PREFLIGHT=1`` to boot anyway. That is for inspecting a broken
    deployment through the API, not for normal use: jobs will still fail.
    """
    env = os.environ if env is None else env

    problems = missing_requirements(env, which)
    if not problems:
        return

    detail = "\n".join(f"  - {p}" for p in problems)

    if (env.get("SKIP_PREFLIGHT") or "").strip().lower() in {"1", "true", "yes"}:
        print(
            f"WARNING: starting with an incomplete environment (SKIP_PREFLIGHT set):\n{detail}\n"
            "Jobs that need these will fail."
        )
        return

    raise PreflightError(
        f"CleanCut cannot start - {len(problems)} unmet requirement(s):\n{detail}\n"
        "Set SKIP_PREFLIGHT=1 to start anyway (jobs will fail)."
    )
