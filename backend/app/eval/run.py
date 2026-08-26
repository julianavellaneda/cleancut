"""
Score a run against the labelled clip.

    # Grade the recorded demo run - no API key, no model, no media.
    python -m app.eval.run --suite claims-and-scrub ../tests/fixtures/demo/seed_job.json

    # Grade the pipeline as it stands today. Transcribes and calls the LLM.
    python -m app.eval.run --suite claims-and-scrub --live ../tests/fixtures/demo/demo_seminar.mp3

The saved-run mode is what CI uses: it is deterministic and free, and it fails
the moment someone changes the matching rules or the labels in a way the
recorded run no longer satisfies. The live mode is what actually answers "is the
analyzer still as good as it was", and it costs a transcription and a
completion, so it stays opt-in.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .scoring import Prediction, Scorecard, load_predictions, score
from .spec import EvalSpec, Suite, load_spec


def _bar(found: int, total: int, width: int = 12) -> str:
    filled = 0 if total == 0 else round(width * found / total)
    return "#" * filled + "." * (width - filled)


def format_report(spec: EvalSpec, suite: Suite, card: Scorecard) -> str:
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
        add(f"Duplicates (a second suggestion on an already-found label): {len(card.duplicates)}")
    if card.out_of_scope:
        add(f"Out of scope for this suite, not graded: {len(card.out_of_scope)}")

    timing = card.timing
    if timing["n"]:
        add(
            f"Boundary error vs the script, mean: start {timing['start'] * 1000:.0f} ms, "
            f"end {timing['end'] * 1000:.0f} ms, over {timing['n']:.0f} spans"
        )

    excluded = [e for e in spec.expectations if not e.present and e.category in suite.categories]
    if excluded:
        add("")
        add("Excluded from scoring (the clip does not contain these):")
        for exp in excluded:
            add(f"  ~ {exp.id}: {exp.note or 'no reason recorded'}")

    return "\n".join(lines)


def as_dict(card: Scorecard) -> dict:
    return {
        "suite": card.suite,
        "precision": card.precision,
        "recall": card.recall,
        "f1": card.f1,
        "graded": card.counted,
        "labels": len(card.scorable),
        "per_category": {c: {"found": f, "expected": t} for c, (f, t) in card.per_category.items()},
        "misses": [e.id for e in card.misses],
        "false_positives": len(card.false_positives),
        "control_hits": [c.id for _, c in card.control_hits],
        "duplicates": len(card.duplicates),
        "out_of_scope": len(card.out_of_scope),
        "timing": card.timing,
    }


def run_live(media: Path, suite: Suite, model_size: str) -> list[Prediction]:
    """
    Drive the real pipeline and return what it suggests.

    Deliberately the same three calls the worker makes, in the same order, so
    what is graded here is what a user would get. Imported lazily: the saved-run
    path must not need faster-whisper or an API key on the import.
    """
    from ..analysis.prompt_analyzer import Violation
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

    found: list[Violation] = list(result.violations)
    quiet_regions = find_quiet_regions(
        decode_pcm_mono(str(media), DECODE_SAMPLE_RATE), DECODE_SAMPLE_RATE
    )
    found.extend(Scrubber.detect_silence(transcript, quiet_regions))
    found.extend(Scrubber.detect_filler_words(transcript))

    return [
        Prediction(text=v.text, start=v.start_time, end=v.end_time, label=v.label)
        for v in found
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.eval.run",
        description="Score a run's suggestions against the labelled demo clip.",
    )
    parser.add_argument(
        "run", nargs="?", type=Path,
        help="A saved run: seed_job.json, an analysis JSON, or an API violation list.",
    )
    parser.add_argument("--suite", default="claims-and-scrub", help="Which suite to grade against.")
    parser.add_argument("--live", type=Path, metavar="MEDIA",
                        help="Transcribe and analyze this file instead of reading a saved run.")
    parser.add_argument("--model", default="medium", help="Whisper model size for --live.")
    parser.add_argument("--labels", type=Path, help="Override the labels file.")
    parser.add_argument("--json", action="store_true", help="Print the scorecard as JSON.")
    parser.add_argument("--min-precision", type=float, default=None)
    parser.add_argument("--min-recall", type=float, default=None)
    args = parser.parse_args(argv)

    if bool(args.run) == bool(args.live):
        parser.error("Give either a saved run file or --live MEDIA, not both and not neither.")

    spec = load_spec(args.labels)
    suite = spec.suite(args.suite)

    predictions = (
        run_live(args.live, suite, args.model) if args.live else load_predictions(args.run)
    )
    card = score(spec, suite, predictions)

    if args.json:
        print(json.dumps(as_dict(card), indent=2))
    else:
        print(format_report(spec, suite, card))

    # A flagged control is a failure on its own terms. The whole point of that
    # line is that a keyword matcher trips on it and a reader does not, so it
    # fails the run no matter how good the aggregate numbers look.
    failed = bool(card.control_hits)
    if args.min_precision is not None and card.precision < args.min_precision:
        failed = True
    if args.min_recall is not None and card.recall < args.min_recall:
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
