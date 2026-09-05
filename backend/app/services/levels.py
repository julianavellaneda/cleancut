"""
Audio level analysis - where is this recording actually quiet?

Dead air used to be inferred from gaps between Whisper transcript segments. That
answers "is anyone speaking?", which is not the same question. Room tone,
applause, a music bed or ambience all leave a transcript gap, and with
``auto_scrub`` on those gaps were cut with no human in the loop. Voice activity
detection does not help: it answers the same question. (Silero VAD is already
running inside faster-whisper via ``vad_filter=True``, and measured on the demo
fixture it still flagged 3.7s of pink noise as dead air.)

What settles it is amplitude. This module turns decoded PCM into the spans that
are genuinely below a level floor; :class:`~app.services.scrubber.Scrubber` then
uses those to confirm and trim the speech-derived candidates.

Kept free of FFmpeg and FastAPI imports so the maths can be exercised on plain
numpy arrays in tests, with no media file anywhere.
"""

import math
import os
from collections.abc import Mapping, Sequence

import numpy as np

from .media_editor import DECODE_SAMPLE_RATE

# 50 ms analysis frames - 400 samples at 8 kHz. Short enough that a boundary
# lands within a frame of where an ear would put it (measured against
# `ffmpeg -af silencedetect` on the demo fixture: agreement inside ~15 ms), long
# enough that a single zero-crossing in the middle of speech is not "silence".
FRAME_SECONDS = 0.05

# -50 dBFS. Validated on tests/fixtures/demo/demo_seminar.mp3, where it isolated
# all three planted pauses and correctly rejected a pink-noise room tone at the
# same offsets. It is a default, not a constant of nature - a noisy field
# recording may need it raised, a studio capture lowered.
DEFAULT_FLOOR_DB = -50.0

# The shortest span worth offering as a cut. The old detector used 2.0s purely
# because Whisper's segment boundaries jitter by tens of milliseconds between
# runs; amplitude boundaries do not, so this can come down far enough to be
# useful for ordinary podcast tightening rather than only for 3-second holes.
DEFAULT_MIN_QUIET_SECONDS = 0.75

# log10(0) is -inf and numpy warns about it, so clamp RMS to a floor well below
# anything DEFAULT_FLOOR_DB could plausibly be set to (-200 dBFS).
_RMS_EPSILON = 1e-10


def _finite_float(env: Mapping[str, str], key: str, default: float) -> float:
    """
    Read a finite float from the environment, falling back to ``default``.

    ``limits._positive_float`` cannot be reused for the dB floor: it rejects
    non-positive values and every sane floor is negative. A malformed entry
    falls back rather than crashing, for the same reason it does there - a typo
    in `.env` should not take the API down.
    """
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def floor_db(env: Mapping[str, str] | None = None) -> float:
    """Level below which audio counts as silence, from ``DEAD_AIR_FLOOR_DB``."""
    env = os.environ if env is None else env
    return _finite_float(env, "DEAD_AIR_FLOOR_DB", DEFAULT_FLOOR_DB)


def min_quiet_seconds(env: Mapping[str, str] | None = None) -> float:
    """
    Shortest dead-air span worth flagging, from ``DEAD_AIR_MIN_SECONDS``.

    Non-positive values fall back to the default: "0" would flag every gap
    between two words, which is not a setting anyone means to choose.
    """
    env = os.environ if env is None else env
    value = _finite_float(env, "DEAD_AIR_MIN_SECONDS", DEFAULT_MIN_QUIET_SECONDS)
    return value if value > 0 else DEFAULT_MIN_QUIET_SECONDS


def find_quiet_regions(
    samples: Sequence[float] | np.ndarray,
    sample_rate: int = DECODE_SAMPLE_RATE,
    floor: float | None = None,
) -> list[tuple[float, float]]:
    """
    Contiguous spans of ``samples`` whose frame RMS sits below ``floor`` dBFS.

    Returns ``(start_seconds, end_seconds)`` tuples on the media's own timeline.

    Deliberately unfiltered by length. A four-second transcript gap that turns
    out to contain only 0.3s of real quiet is exactly the case the scrubber has
    to catch, and it can only see that after intersecting - so the length rule
    lives there, not here.
    """
    floor = floor_db() if floor is None else floor
    x = np.asarray(samples, dtype=np.float32)

    hop = max(1, int(round(sample_rate * FRAME_SECONDS)))
    frame_count = len(x) // hop
    if frame_count == 0:
        return []

    # Drop the trailing partial frame rather than zero-padding it: a padded tail
    # reads as quiet whether or not it is, which would invent a dead-air region
    # at the very end of every file whose length is not a whole number of frames.
    frames = x[: frame_count * hop].reshape(frame_count, hop)

    # float64 for the mean - squaring float32 samples near the floor loses
    # precision exactly where the comparison is being made.
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    db = 20 * np.log10(np.maximum(rms, _RMS_EPSILON))
    quiet = db < floor

    # Contiguous runs of True, found from the transitions in the padded diff.
    padded = np.concatenate(([False], quiet, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    starts, ends = edges[0::2], edges[1::2]

    # strict=True asserts what the padding above guarantees: a run that opens
    # must close, so `edges` has an even length and these two are the same size.
    # Were that ever untrue, a plain zip would silently drop the last region -
    # a stretch of dead air that simply never gets suggested.
    return [
        (float(s * hop / sample_rate), float(e * hop / sample_rate))
        for s, e in zip(starts, ends, strict=True)
    ]
