#!/usr/bin/env python3
"""
CleanCut analysis CLI.

Transcribes media and flags segments based on a user prompt, without the web app.
Run it as a module from the `backend/` directory so the `app` package resolves:

    python -m app.analysis.analyze audio.mp3 --prompt "Find all filler words"
    python -m app.analysis.analyze audio.mp3 --output results.json
    python -m app.analysis.analyze --transcript transcript.txt --prompt "..."
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from ..config import root_env_path
from .transcriber import Transcriber, TranscriptResult, load_transcript
from .prompt_analyzer import PromptAnalyzer, AnalysisResult, PRESETS, to_json

# Load environment variables from the .env at the repo root, when there is one.
_ROOT_ENV = root_env_path(__file__)
if _ROOT_ENV:
    load_dotenv(_ROOT_ENV)


def print_header(text: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def print_marker(v, index: int) -> None:
    """Print a formatted marker."""
    action_colors = {
        "cut": "\033[91m",    # Red
        "mute": "\033[93m",  # Yellow
    }
    reset = "\033[0m"

    color = action_colors.get(v.action.lower(), "")

    print(f"\n{color}[{index}] {v.label.upper()} ({v.action.upper()}){reset}")
    print(f"    Time: {v.start_time:.1f}s - {v.end_time:.1f}s")
    print(f"    Text: \"{v.text}\"")
    print(f"    Reason: {v.reasoning}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze audio based on a prompt."
    )
    parser.add_argument(
        "audio_file",
        nargs="?",
        help="Path to the audio file to analyze"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file path (default: <audio_name>_analysis.json)"
    )
    parser.add_argument(
        "--prompt", "-p",
        help="The editing instruction or question for the analyzer."
    )
    parser.add_argument(
        "--model", "-m",
        default="medium",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size (default: medium)"
    )
    parser.add_argument(
        "--language", "-l",
        help="Audio language (e.g., 'en', 'es'). Auto-detect if not specified."
    )
    parser.add_argument(
        "--rules", "-r",
        help="Path to a custom rules file (used as baseline context in prompt mode)"
    )
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        help="Run a built-in rule preset instead of a free-form prompt"
    )
    parser.add_argument(
        "--transcript-only", "-t",
        action="store_true",
        help="Only transcribe, skip analysis"
    )
    parser.add_argument(
        "--transcript", "-T",
        help="Path to existing transcript file (skip transcription, run analysis only)"
    )
    parser.add_argument(
        "--chunk-size", "-c",
        type=int,
        help="Segments per chunk for analysis (default: 50)"
    )
    parser.add_argument(
        "--overlap",
        type=int,
        help="Segments to overlap between chunks (default: 10)"
    )
    parser.add_argument(
        "--no-overlap",
        action="store_true",
        help="Disable chunk overlap"
    )

    args = parser.parse_args()

    if not args.audio_file and not args.transcript:
        parser.error("Either audio_file or --transcript is required")

    if not args.preset and not args.prompt and not args.transcript_only:
        parser.error("Either --prompt or --preset is required")

    if args.transcript:
        transcript_path = Path(args.transcript)
        if not transcript_path.exists():
            print(f"Error: Transcript file not found: {transcript_path}")
            sys.exit(1)

        if args.output:
            output_path = Path(args.output)
        else:
            output_path = transcript_path.parent / f"{transcript_path.stem.replace('_transcript', '')}_analysis.json"

        print_header("LOADING EXISTING TRANSCRIPT")
        transcript = load_transcript(str(transcript_path))
        print(f"Loaded {len(transcript.segments)} segments from {transcript_path.name}")
    
    else:
        audio_path = Path(args.audio_file)
        if not audio_path.exists():
            print(f"Error: File not found: {audio_path}")
            sys.exit(1)

        if args.output:
            output_path = Path(args.output)
        else:
            output_path = audio_path.parent / f"{audio_path.stem}_analysis.json"

        print_header("STEP 1: TRANSCRIPTION")
        transcriber = Transcriber(model_size=args.model)
        transcript = transcriber.transcribe(str(audio_path), language=args.language)
        print(f"\nTranscribed {len(transcript.segments)} segments, language: {transcript.language}")

    if args.transcript_only:
        transcript_output = audio_path.parent / f"{audio_path.stem}_transcript.txt"
        with open(transcript_output, "w") as f:
            f.write(transcriber.to_timestamped_text(transcript))
        print(f"\nTranscript saved to: {transcript_output}")
        sys.exit(0)

    if args.preset:
        print_header(f"STEP 2: PRESET ANALYSIS ({args.preset})")
    else:
        print_header("STEP 2: PROMPT-BASED ANALYSIS")
    overlap = 0 if args.no_overlap else args.overlap
    analyzer = PromptAnalyzer(
        rules_path=args.rules,
        chunk_size=args.chunk_size,
        overlap=overlap
    )
    result = analyzer.analyze(transcript, prompt=args.prompt, preset=args.preset)

    print_header("RESULTS")

    if not result.violations:
        print("\n  No segments matching the prompt were found.")
    else:
        print(f"\n  Found {len(result.violations)} matching segment(s):")
        for i, v in enumerate(result.violations, 1):
            print_marker(v, i)

    print_header("OUTPUT")
    with open(output_path, "w") as f:
        f.write(to_json(result))
    print(f"  Analysis saved to: {output_path}")

    if not args.transcript:
        transcript_output = audio_path.parent / f"{audio_path.stem}_transcript.txt"
        with open(transcript_output, "w") as f:
            f.write(transcriber.to_timestamped_text(transcript))
        print(f"  Transcript saved to: {transcript_output}")

    print("\nDone!")
    sys.exit(0)


if __name__ == "__main__":
    main()
