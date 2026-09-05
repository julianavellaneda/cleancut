"""
Persisting the transcript that the pipeline used to throw away.

Transcription is the slowest and most expensive stage of a job, and until now
its output lived only for the duration of the worker call: it was handed to the
analyzer, used to map quoted text onto timestamps, and dropped. Anything that
wanted to see what was said - a reader, a re-analysis under a different prompt,
an eval harness - had to re-transcribe.

**Segments and words.** This was segments-only at first, on the grounds that
nothing read the word timing back and it is roughly twenty times the bytes -
a two-hour recording is on the order of 100 KB stored as lines and a couple of
megabytes stored with words, in a TEXT column in the same SQLite file the app
queries on every poll. Re-analysis is the feature that re-opened that decision:
mapping an LLM's quote onto a timestamp is only as precise as the timing it is
given, and a re-run that produced visibly coarser markers than the first pass
would be two kinds of precision in one review screen.

Words are therefore stored (version 2) and served to nobody: the transcript
route still returns lines, because the panel reads lines. Version 1 rows are
still readable and simply have no words; a re-analysis over one falls back to
segment-level spans, which is the analyzer's existing behaviour for a segment
Whisper gave no word timing for.

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
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class StoredWord:
    """One word and its timing. Stored for re-analysis; never served."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class StoredSegment:
    """One line of the transcript, as stored and as served."""

    start: float
    end: float
    text: str
    # Empty for a version 1 row, and for a segment Whisper timed no words in.
    words: tuple[StoredWord, ...] = ()


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
    segments = []
    for seg in getattr(transcript, "segments", []) or []:
        stored = {
            "start": float(seg.start),
            "end": float(seg.end),
            "text": (seg.text or "").strip(),
        }
        words = [
            {"start": float(w.start), "end": float(w.end), "text": w.text}
            for w in getattr(seg, "words", None) or []
            if w.start is not None and w.end is not None
        ]
        # Omitted rather than written as [], so a line Whisper timed no words in
        # reads back the same as a line from a version 1 row.
        if words:
            stored["words"] = words
        segments.append(stored)
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
        segments.append(
            StoredSegment(
                start=start,
                end=end,
                text=text,
                words=_words_from(item.get("words")),
            )
        )

    if not segments:
        return None

    duration = payload.get("duration")
    return StoredTranscript(
        language=payload.get("language")
        if isinstance(payload.get("language"), str)
        else None,
        duration=float(duration) if isinstance(duration, (int, float)) else None,
        segments=segments,
    )


def _words_from(raw) -> tuple[StoredWord, ...]:
    """
    Read a segment's word timings, dropping anything malformed.

    Lenient for the same reason `from_json` is: a word that will not parse costs
    the precision of one quote, and refusing the whole transcript over it would
    cost the panel, the re-analysis and the timing of every other line.
    """
    if not isinstance(raw, list):
        return ()
    words = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        try:
            words.append(
                StoredWord(
                    start=float(item["start"]),
                    end=float(item["end"]),
                    text=item["text"],
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(words)


def to_transcript_result(stored: StoredTranscript):
    """
    Rebuild a ``TranscriptResult`` from a stored transcript, for re-analysis.

    Imported lazily: `transcriber` pulls in faster-whisper, and the route that
    validates a re-analysis request has no business loading a speech model to do
    it.
    """
    from ..analysis.transcriber import Segment, TranscriptResult, Word

    return TranscriptResult(
        segments=[
            Segment(
                text=seg.text,
                start=seg.start,
                end=seg.end,
                words=[
                    # `probability` is not stored - it is the model's confidence
                    # in its own transcription, which nothing downstream reads.
                    Word(text=w.text, start=w.start, end=w.end, probability=1.0)
                    for w in seg.words
                ],
            )
            for seg in stored.segments
        ],
        language=stored.language or "unknown",
        duration=stored.duration
        or (stored.segments[-1].end if stored.segments else 0.0),
    )
