#!/usr/bin/env python3
"""
CleanCut analysis CLI.

Transcribes media and flags segments based on a user prompt, without the web app.
Run it as a module from the `backend/` directory so the `app` package resolves:

    python -m app.analysis.analyze audio.mp3 --prompt "Find all filler words"
    python -m app.analysis.analyze audio.mp3 --output results.json
    python -m app.analysis.analyze --transcript transcript.txt --prompt "..."

Exit codes: 0 on a complete analysis, 2 when one or more chunks failed and the
transcript was only partially analyzed, 1 on a usage or input error.
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from ..config import root_env_path
from .prompt_analyzer import PRESETS, AnalysisResult, PromptAnalyzer, to_json
from .transcriber import (
    Transcriber,
    TranscriptFormatError,
    load_transcript,
)

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
    """
    Print a formatted marker.

    The two "not without a human" flags are printed as their own line rather
    than read out of `reasoning`: they are fields on the finding, and the CLI
    renders them the way the review screen renders its badge.
    """
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

    yellow = "\033[93m"
    if getattr(v, "is_approximate", False):
        print(f"    {yellow}Check: this quote could not be matched to the transcript, "
              f"so the span is an estimate.{reset}")
    if getattr(v, "is_ambiguous", False):
        print(f"    {yellow}Check: this is also an ordinary word, and nothing around it "
              f"marks it as a hesitation.{reset}")


def print_partial_warning(result: AnalysisResult) -> None:
    """Warn that the analysis did not cover the whole transcript."""
    yellow, reset = "\033[93m", "\033[0m"
    covered = result.total_segments_analyzed
    total = result.total_segments

    print(f"\n{yellow}  WARNING: PARTIAL ANALYSIS{reset}")
    if total:
        print(f"  {covered} of {total} segment(s) were analyzed "
              f"({len(result.failed_chunks)} chunk(s) failed).")
    else:
        print(f"  {len(result.failed_chunks)} chunk(s) failed.")
    print("  These spans were NOT checked - findings below are incomplete:")
    for message in result.failed_chunks:
        print(f"    - {message}")


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
        try:
            transcript = load_transcript(str(transcript_path))
        except TranscriptFormatError as e:
            # A file in the wrong format must not analyze as a clean recording.
            print(f"Error: {e}")
            sys.exit(1)
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
    try:
        analyzer = PromptAnalyzer(
            rules_path=args.rules,
            chunk_size=args.chunk_size,
            overlap=overlap
        )
    except ValueError as e:
        # --chunk-size and --overlap come straight from the command line, so a
        # rejected window is a typo, not a bug. Say which one and stop, rather
        # than showing a traceback for something the user can fix in a word.
        print(f"Error: {e}")
        sys.exit(1)
    result = analyzer.analyze(transcript, prompt=args.prompt, preset=args.preset)

    print_header("RESULTS")

    # Say this before the findings, not after. "No segments found" reads as a
    # clean recording, and the reader has to know up front that part of the
    # transcript was never looked at.
    if result.is_partial:
        print_partial_warning(result)

    if not result.violations:
        if result.is_partial:
            print("\n  No segments matching the prompt were found in the analyzed portion.")
        else:
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

    if result.is_partial:
        # Exit non-zero so a script that pipes this cannot mistake an
        # incomplete review for a clean one.
        print("\nDone, but the analysis was PARTIAL - see the warning above.")
        sys.exit(2)

    print("\nDone!")
    sys.exit(0)


if __name__ == "__main__":
    main()
