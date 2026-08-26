"""
Persisting the transcript that the pipeline used to throw away.

Transcription is the slowest and most expensive stage of a job, and until now
its output lived only for the duration of the worker call: it was handed to the
analyzer, used to map quoted text onto timestamps, and dropped. Anything that
wanted to see what was said - a reader, a re-analysis under a different prompt,
an eval harness - had to re-transcribe.

**Segments, not words.** Word-level timing is what makes the timestamp mapping
precise, but it is also roughly twenty times the bytes, and every consumer of
the stored copy works at the line level. A two-hour recording is on the order of
100 KB stored this way and a couple of megabytes stored with words, in a TEXT
column in the same SQLite file the app queries on every poll. If a future
feature needs word timing it should re-open that decision deliberately rather
than inherit it.

This module is the single owner of the stored shape; the route and the worker
both go through it so the on-disk JSON has one definition.
"""

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Bumped when the stored shape changes incompatibly. Rows written by an older
# version are read leniently rather than migrated: a transcript is derived data,
# and the honest answer for one we cannot read is "not available", which the
# route already has to handle for jobs that predate the column.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StoredSegment:
    """One line of the transcript, as stored and as served."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class StoredTranscript:
    language: str | None
    duration: float | None
    segments: list[StoredSegment]


def to_json(transcript) -> str:
    """
    Serialize a ``TranscriptResult`` for the ``jobs.transcript`` column.

    Takes anything with ``segments``/``language``/``duration`` rather than
    importing ``TranscriptResult``, so tests and the CLI can hand it a stub
    without dragging faster-whisper into the import graph.
    """
    segments = [
        {
            "start": float(seg.start),
            "end": float(seg.end),
            "text": (seg.text or "").strip(),
        }
        for seg in getattr(transcript, "segments", []) or []
    ]
    return json.dumps(
        {
            "version": SCHEMA_VERSION,
            "language": getattr(transcript, "language", None),
            "duration": getattr(transcript, "duration", None),
            "segments": segments,
        },
        ensure_ascii=False,
    )


def from_json(raw: str | None) -> StoredTranscript | None:
    """
    Read a stored transcript back, or ``None`` when there isn't a usable one.

    Every failure mode collapses to ``None`` on purpose: a job from before the
    column existed, a job that failed before transcription, and a row that was
    truncated or hand-edited are all "no transcript to show", and none of them
    is worth a 500 on a read-only panel.
    """
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("Stored transcript is not readable JSON; treating it as absent.")
        return None
    if not isinstance(payload, dict):
        return None

    segments = []
    for item in payload.get("segments") or []:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        segments.append(StoredSegment(start=start, end=end, text=text))

    if not segments:
        return None

    duration = payload.get("duration")
    return StoredTranscript(
        language=payload.get("language") if isinstance(payload.get("language"), str) else None,
        duration=float(duration) if isinstance(duration, (int, float)) else None,
        segments=segments,
    )
