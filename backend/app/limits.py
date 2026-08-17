"""
Upload guardrails - size and duration caps.

Transcription cost is linear in media length and the whole pipeline is a single
sequential worker, so one three-hour upload blocks every other job behind it.
Both caps are configurable because the right ceiling for a laptop and for a
public demo are not the same number.

Kept free of FastAPI imports so the limits can be exercised directly in tests.
"""

import os
import subprocess
from pathlib import Path
from typing import BinaryIO, Mapping

# Read in 1 MB blocks: big enough that the syscall overhead is irrelevant, small
# enough that an oversized upload is caught long before it is fully buffered.
CHUNK_BYTES = 1024 * 1024

DEFAULT_MAX_UPLOAD_MB = 500.0
DEFAULT_MAX_DURATION_MINUTES = 120.0


class UploadTooLarge(Exception):
    """The upload exceeded the byte cap. Carries the cap for the error message."""

    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        super().__init__(f"Upload exceeds the {max_bytes / 1_000_000:.0f} MB limit.")


class MediaTooLong(Exception):
    """The media ran longer than the duration cap."""

    def __init__(self, duration_seconds: float, max_seconds: float):
        self.duration_seconds = duration_seconds
        self.max_seconds = max_seconds
        super().__init__(
            f"Media is {duration_seconds / 60:.1f} minutes long, "
            f"over the {max_seconds / 60:.0f} minute limit."
        )


class MediaDurationUnknown(Exception):
    """
    ``ffprobe`` could not report a duration, so the cap cannot be enforced.

    Treated as a rejection rather than a pass. An unprobeable file is either
    corrupt - in which case the worker was going to fail on it anyway - or a
    container whose length we cannot bound, and letting that through is exactly
    how an unbounded stream gets past ``MAX_DURATION_MINUTES`` and monopolizes
    the sequential worker.
    """

    def __init__(self) -> None:
        super().__init__(
            "Could not determine the media duration. The file may be corrupt, "
            "truncated, or in a container without duration metadata. "
            "Re-encode it (for example to MP3 or MP4) and upload again."
        )


def _positive_float(env: Mapping[str, str], key: str, default: float) -> float:
    """
    Read a positive float from the environment, falling back to ``default``.

    A malformed or non-positive value falls back rather than crashing: a typo in
    `.env` should not take the API down, and "0" is far more likely to mean
    "I meant to disable this" than "reject every upload".
    """
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def max_upload_bytes(env: Mapping[str, str] | None = None) -> int:
    """Byte ceiling for an upload, from ``MAX_UPLOAD_MB``."""
    env = os.environ if env is None else env
    return int(_positive_float(env, "MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB) * 1_000_000)


def max_duration_seconds(env: Mapping[str, str] | None = None) -> float:
    """Duration ceiling for media, from ``MAX_DURATION_MINUTES``."""
    env = os.environ if env is None else env
    return _positive_float(env, "MAX_DURATION_MINUTES", DEFAULT_MAX_DURATION_MINUTES) * 60


def save_within_limit(source: BinaryIO, destination: Path, max_bytes: int) -> int:
    """
    Stream ``source`` to ``destination``, aborting past ``max_bytes``.

    Returns the number of bytes written. Raises :class:`UploadTooLarge` after
    deleting the partial file - the cap exists to bound disk use, so leaving the
    truncated upload behind would defeat it.

    The check is on bytes actually read, not on the ``Content-Length`` header,
    which a client controls and can lie about.
    """
    written = 0
    try:
        with open(destination, "wb") as out:
            while True:
                chunk = source.read(CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise UploadTooLarge(max_bytes)
                out.write(chunk)
    except UploadTooLarge:
        destination.unlink(missing_ok=True)
        raise
    return written


def probe_duration_seconds(path: Path | str) -> float | None:
    """
    Duration of a media file in seconds via ``ffprobe``, or ``None``.

    ``None`` means "could not tell" - ffprobe missing, the file unreadable, or a
    container with no duration in its header. Callers must treat that as
    unknown rather than as zero, and unknown is a rejection: see
    :func:`enforce_duration_limit`.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    try:
        duration = float(result.stdout.strip())
    except ValueError:
        return None

    return duration if duration > 0 else None


def enforce_duration_limit(path: Path | str, max_seconds: float) -> float:
    """
    Probe ``path`` and return its duration, rejecting anything over the cap.

    Fails closed: a duration we cannot read raises
    :class:`MediaDurationUnknown` rather than being waved through. The cap is
    there to bound how long one job can hold the sequential worker, and a limit
    that any unprobeable file can skip is not a limit.
    """
    duration = probe_duration_seconds(path)
    if duration is None:
        raise MediaDurationUnknown()
    if duration > max_seconds:
        raise MediaTooLong(duration, max_seconds)
    return duration
