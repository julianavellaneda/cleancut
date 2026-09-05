"""
Score a run against the labelled clip.

    # Grade the recorded demo run - no API key, no model, no media.
    python -m app.eval.run --suite claims-and-scrub ../tests/fixtures/demo/seed_job.json

    # Grade the deterministic detectors against the real audio. Free, no LLM.
    python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3 --suite scrub

    # Grade the whole pipeline as it stands today. Transcribes and calls the LLM.
    python -m app.eval.run --suite claims-and-scrub --live ../tests/fixtures/demo/demo_seminar.mp3

Three modes, and they measure three different things. The saved-run mode grades
a snapshot: it is deterministic and free, and it fails the moment someone
changes the matching rules or the labels in a way the recorded run no longer
satisfies - it says nothing about the detectors as they stand today. The
detector mode does measure them, for the half of the pipeline that has no model
in it: the scrubber runs against the real audio and a stored word-level
transcript, so CI can gate on it on every push. The live mode measures the other
half, and it costs a transcription and a completion, so it stays opt-in.

Exit codes:

    0  the run cleared every floor it was given
    1  a control was flagged, or a threshold was missed
    2  the run itself was incomplete (chunks failed) and --allow-partial was not
       given. A partial run's recall is a floor, not a measurement, and the part
       that did succeed can still clear a threshold - so it must not be able to
       exit 0 by accident.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .scoring import Prediction, RunResult, Scorecard, load_run, score
from .spec import EvalSpec, Suite, load_spec


def _bar(found: int, total: int, width: int = 12) -> str:
    filled = 0 if total == 0 else round(width * found / total)
    return "#" * filled + "." * (width - filled)


def format_report(
    spec: EvalSpec,
    suite: Suite,
    card: Scorecard,
    run: RunResult | None = None,
) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"Suite: {suite.id} - {suite.description}")
    if suite.prompt:
        add(f"Prompt: {suite.prompt}")
    if suite.preset:
        add(f"Preset: {suite.preset}")
    add("")
    add(f"  precision  {card.precision:6.1%}   ({card.counted} suggestions graded)")
    add(f"  recall     {card.recall:6.1%}   ({len(card.scorable)} labels in scope)")
    add(f"  F1         {card.f1:6.1%}")
    add("")

    add("By category:")
    for category, (found, total) in card.per_category.items():
        add(f"  {category:<16} {_bar(found, total)}  {found}/{total}")
    add("")

    if card.misses:
        add("Missed:")
        for exp in card.misses:
            what = exp.text or exp.quote or f"{exp.start:.2f}-{exp.end:.2f}"
            add(f"  - {exp.id:<22} {exp.start:7.2f}s  {what}")
        add("")

    if card.false_positives:
        add("Flagged with no label behind it:")
        for i in card.false_positives:
            p = card.predictions[i]
            add(f"  - {p.start:7.2f}-{p.end:7.2f}s  [{p.label}] {p.text[:60]}")
        add("")

    if card.control_hits:
        add("CONTROL FLAGGED - these spans are supposed to survive review:")
        for i, control in card.control_hits:
            p = card.predictions[i]
            add(f"  ! {control.id}: {p.text[:60]}")
            add(f"    {control.reason}")
        add("")

    if card.duplicates:
        add(
            f"Duplicates (a second suggestion on an already-found label): {len(card.duplicates)}"
        )
    if card.out_of_scope:
        add(f"Out of scope for this suite, not graded: {len(card.out_of_scope)}")

    timing = card.timing
    if timing["n"]:
        add(
            f"Boundary error vs the script, mean: start {timing['start'] * 1000:.0f} ms, "
            f"end {timing['end'] * 1000:.0f} ms, over {timing['n']:.0f} spans"
        )

    if run is not None and run.is_partial:
        add("")
        add(
            f"INCOMPLETE RUN - {len(run.failed_chunks)} chunk(s) failed. Every number "
            "above is a floor, not a measurement:"
        )
        for chunk in run.failed_chunks:
            add(f"  ! {chunk}")

    excluded = [
        e for e in spec.expectations if not e.present and e.category in suite.categories
    ]
    if excluded:
        add("")
        add("Excluded from scoring (the clip does not contain these):")
        for exp in excluded:
            add(f"  ~ {exp.id}: {exp.note or 'no reason recorded'}")

    return "\n".join(lines)


def as_dict(card: Scorecard, run: RunResult | None = None) -> dict:
    return {
        "suite": card.suite,
        "precision": card.precision,
        "recall": card.recall,
        "f1": card.f1,
        "graded": card.counted,
        "labels": len(card.scorable),
        "per_category": {
            c: {"found": f, "expected": t} for c, (f, t) in card.per_category.items()
        },
        "misses": [e.id for e in card.misses],
        "false_positives": len(card.false_positives),
        "control_hits": [c.id for _, c in card.control_hits],
        "duplicates": len(card.duplicates),
        "out_of_scope": len(card.out_of_scope),
        "timing": card.timing,
        "is_partial": bool(run and run.is_partial),
        "failed_chunks": list(run.failed_chunks) if run else [],
    }


DEMO_TRANSCRIPT = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "demo"
    / "transcript_words.json"
)


def _as_predictions(violations) -> list[Prediction]:
    return [
        Prediction(text=v.text, start=v.start_time, end=v.end_time, label=v.label)
        for v in violations
    ]


def load_word_transcript(path: Path):
    """
    Rebuild a :class:`TranscriptResult` with word timing from a saved JSON file.

    ``services/transcripts.py`` cannot be reused here: it stores segments only,
    on purpose, and word timing is exactly what the filler detector reads.
    """
    from ..analysis.transcriber import Segment, TranscriptResult, Word

    data = json.loads(Path(path).read_text())
    segments = [
        Segment(
            text=seg.get("text", ""),
            start=float(seg["start"]),
            end=float(seg["end"]),
            words=[
                Word(
                    text=w["text"],
                    start=float(w["start"]),
                    end=float(w["end"]),
                    probability=float(w.get("probability", 1.0)),
                )
                for w in seg.get("words", [])
            ],
            language=seg.get("language"),
        )
        for seg in data.get("segments", [])
    ]
    return TranscriptResult(
        segments=segments,
        language=data.get("language", "en"),
        duration=float(data.get("duration", segments[-1].end if segments else 0.0)),
    )


def run_detectors(media: Path, transcript_path: Path) -> RunResult:
    """
    Run the deterministic half of the pipeline and return what it suggests.

    No Whisper and no LLM: the level pass reads the real audio, and the
    transcript comes from a committed fixture. That is what makes this cheap
    enough to gate every push on - grading `seed_job.json` proves the scorer
    still works, this proves the detectors still do.
    """
    from ..services.levels import find_quiet_regions
    from ..services.media_editor import DECODE_SAMPLE_RATE, decode_pcm_mono
    from ..services.scrubber import Scrubber

    transcript = load_word_transcript(transcript_path)
    quiet_regions = find_quiet_regions(
        decode_pcm_mono(str(media), DECODE_SAMPLE_RATE), DECODE_SAMPLE_RATE
    )
    found = list(Scrubber.detect_silence(transcript, quiet_regions))
    found.extend(Scrubber.detect_filler_words(transcript))
    return RunResult(predictions=tuple(_as_predictions(found)))


def run_live(media: Path, suite: Suite, model_size: str) -> RunResult:
    """
    Drive the real pipeline and return what it suggests.

    Deliberately the same three calls the worker makes, in the same order, so
    what is graded here is what a user would get. Imported lazily: the saved-run
    path must not need faster-whisper or an API key on the import.
    """
    from ..services.levels import find_quiet_regions
    from ..services.media_editor import DECODE_SAMPLE_RATE, decode_pcm_mono
    from ..services.processor import AudioProcessor
    from ..services.scrubber import Scrubber

    processor = AudioProcessor(model_size=model_size)
    print(f"Transcribing {media.name} with the {model_size} model...", file=sys.stderr)
    transcript = processor.transcribe(str(media))

    print("Analyzing...", file=sys.stderr)
    result = processor.analyze(transcript, prompt=suite.prompt, preset=suite.preset)
    if result.is_partial:
        print(
            f"WARNING: {len(result.failed_chunks)} chunk(s) failed; recall below is a floor, "
            "not a measurement.",
            file=sys.stderr,
        )

    found = list(result.violations)
    quiet_regions = find_quiet_regions(
        decode_pcm_mono(str(media), DECODE_SAMPLE_RATE), DECODE_SAMPLE_RATE
    )
    found.extend(Scrubber.detect_silence(transcript, quiet_regions))
    found.extend(Scrubber.detect_filler_words(transcript))

    return RunResult(
        predictions=tuple(_as_predictions(found)),
        is_partial=result.is_partial,
        failed_chunks=tuple(result.failed_chunks),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.eval.run",
        description="Score a run's suggestions against the labelled demo clip.",
    )
    parser.add_argument(
        "run",
        nargs="?",
        type=Path,
        help="A saved run: seed_job.json, an analysis JSON, or an API violation list.",
    )
    parser.add_argument(
        "--suite", default="claims-and-scrub", help="Which suite to grade against."
    )
    parser.add_argument(
        "--live",
        type=Path,
        metavar="MEDIA",
        help="Transcribe and analyze this file instead of reading a saved run.",
    )
    parser.add_argument(
        "--detectors",
        type=Path,
        metavar="MEDIA",
        help="Run only the deterministic detectors against this file. "
        "No model, no API key.",
    )
    parser.add_argument(
        "--transcript",
        type=Path,
        default=DEMO_TRANSCRIPT,
        help="Word-level transcript JSON for --detectors "
        f"(default: {DEMO_TRANSCRIPT.name}).",
    )
    parser.add_argument(
        "--model", default="medium", help="Whisper model size for --live."
    )
    parser.add_argument("--labels", type=Path, help="Override the labels file.")
    parser.add_argument(
        "--json", action="store_true", help="Print the scorecard as JSON."
    )
    parser.add_argument("--min-precision", type=float, default=None)
    parser.add_argument("--min-recall", type=float, default=None)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Score a run whose analysis was incomplete instead of exiting 2.",
    )
    args = parser.parse_args(argv)

    modes = [bool(args.run), bool(args.live), bool(args.detectors)]
    if sum(modes) != 1:
        parser.error(
            "Give exactly one of: a saved run file, --live MEDIA, or --detectors MEDIA."
        )

    spec = load_spec(args.labels)
    suite = spec.suite(args.suite)

    if args.live:
        run = run_live(args.live, suite, args.model)
    elif args.detectors:
        run = run_detectors(args.detectors, args.transcript)
    else:
        run = load_run(args.run)
    card = score(spec, suite, list(run.predictions))

    if args.json:
        print(json.dumps(as_dict(card, run), indent=2))
    else:
        print(format_report(spec, suite, card, run))

    # A flagged control is a failure on its own terms. The whole point of that
    # line is that a keyword matcher trips on it and a reader does not, so it
    # fails the run no matter how good the aggregate numbers look.
    failed = bool(card.control_hits)
    if args.min_precision is not None and card.precision < args.min_precision:
        failed = True
    if args.min_recall is not None and card.recall < args.min_recall:
        failed = True
    if failed:
        return 1
    # An incomplete run is reported separately from a bad one: the numbers above
    # may well clear every floor, because the chunks that did answer are graded
    # as if they were the whole transcript.
    if run.is_partial and not args.allow_partial:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
