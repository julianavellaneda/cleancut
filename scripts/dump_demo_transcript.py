#!/usr/bin/env python3
"""
Write a word-level transcript of the demo clip to tests/fixtures/demo/.

The eval harness's ``--detectors`` mode grades the scrubber - filler words and
dead air - against the real audio. Dead air comes from an RMS pass on the media
itself, but filler detection needs word timing, and transcribing in CI would
mean a Whisper model download on every run. So the transcript is committed once
and the detectors are graded against it.

Local, free, and offline once the model is cached: no API key is involved. Run
it again after re-rendering the clip, since every offset moves.

    python scripts/dump_demo_transcript.py [--model medium]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEMO_DIR = REPO_ROOT / "tests" / "fixtures" / "demo"
DEFAULT_MEDIA = DEMO_DIR / "demo_seminar.mp3"
DEFAULT_OUT = DEMO_DIR / "transcript_words.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", type=Path, default=DEFAULT_MEDIA)
    parser.add_argument("--model", default="medium", help="Whisper model size.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    from app.services.processor import AudioProcessor

    print(f"Transcribing {args.media.name} with the {args.model} model...", file=sys.stderr)
    transcript = AudioProcessor(model_size=args.model).transcribe(str(args.media))

    payload = {
        "source": args.media.name,
        "model": args.model,
        "language": transcript.language,
        "duration": transcript.duration,
        "segments": [asdict(segment) for segment in transcript.segments],
    }
    args.out.write_text(json.dumps(payload, indent=1) + "\n")
    words = sum(len(s.words) for s in transcript.segments)
    print(f"Wrote {args.out.relative_to(REPO_ROOT)} - "
          f"{len(transcript.segments)} segments, {words} words.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
