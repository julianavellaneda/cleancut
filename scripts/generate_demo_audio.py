"""
Render `tests/fixtures/demo/seminar_script.md` into a synthetic demo clip.

This produces the fixture the rest of the portfolio demo (and, eventually, an LLM-eval
test) builds on: a fully synthetic two-speaker "business opportunity seminar" with
planted compliance issues, generated with OpenAI TTS so the audio path is exercised
end to end rather than faked.

`expected_violations.json` is the more valuable half of the output. It records the
*measured* start/end offset of every spoken line and pause, derived from the exact
duration of each rendered TTS clip via `ffprobe` — never estimated or hand-typed. That
makes it usable as ground truth for an eval ("does the analyzer catch the planted
income claim within N ms of where it really is?"), which is worth far more than the
clip itself. Any change to the script or a re-render with a different voice
automatically re-measures these offsets; nothing here is hand-maintained.

Per-line audio is cached by content hash so edits to the script only re-render the
lines that actually changed, and repeated runs (including CI, if this is ever wired
into one) cost nothing once the cache is warm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

# `app.config` is a plain-stdlib module (see its own docstring), so importing it does
# not require the backend's virtualenv to be active. Everything past this point does.
sys.path.insert(0, str(BACKEND_DIR))
from app.config import root_env_path  # noqa: E402

DEFAULT_SCRIPT_PATH = REPO_ROOT / "tests" / "fixtures" / "demo" / "seminar_script.md"
DEFAULT_OUT_DIR = REPO_ROOT / "tests" / "fixtures" / "demo"

TTS_MODEL = "gpt-4o-mini-tts"
VOICES = {
    "HOST": "alloy",
    "GUEST": "ballad",
}

# OpenAI's published gpt-4o-mini-tts rate is per-character of input text, not per
# minute of audio, but the more legible way to communicate cost for a script like this
# is dollars-per-minute-of-speech. This constant is the commonly quoted approximation
# (as of when this script was written) and MUST be re-checked against
# https://openai.com/api/pricing/ before trusting the estimate for a real spend
# decision.
ESTIMATED_COST_PER_MINUTE_USD = 0.015

# Used only to turn a character count into an estimated minutes-of-audio figure for
# the --dry-run cost estimate. Real TTS pacing varies by voice/instructions; this is a
# rough midpoint for conversational English speech.
ASSUMED_WORDS_PER_MINUTE = 150.0
ASSUMED_CHARS_PER_WORD = 5.0  # includes the trailing space, a common English rule of thumb

SAMPLE_RATE = 24000  # gpt-4o-mini-tts wav output; anullsrc pauses must match to avoid a resample
CHANNELS = 1

CACHE_DIR_NAME = ".cache"

SPOKEN_LINE_RE = re.compile(r"^(HOST|GUEST)\s*\|(.*)\|(.*)$")
PAUSE_LINE_RE = re.compile(r"^\[PAUSE\s+([0-9]+(?:\.[0-9]+)?)\]$")


@dataclass
class SpokenLine:
    index: int  # 0-based index among spoken lines only
    speaker: str
    voice: str
    instructions: str
    text: str


@dataclass
class Pause:
    after_line: int  # index of the spoken line this pause follows, -1 if it opens the script
    duration: float


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """
    Run an external command (ffmpeg/ffprobe), raising with the stderr tail on failure.

    Centralized so every ffmpeg/ffprobe invocation in this file fails the same way,
    with enough of the tool's own error message to debug without re-running by hand.
    Never uses shell=True — every argument is passed as a literal list element.
    """
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-20:])
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}\n{tail}")
    return result


def parse_script(path: Path) -> list[SpokenLine | Pause]:
    """
    Extract the ordered list of spoken lines and pauses from the fenced code block
    under `## Script`. Everything outside that block (the surrounding prose, the
    "Planted items" table) is documentation for humans and is ignored here.
    """
    text = path.read_text(encoding="utf-8")

    # Find the '## Script' heading, then the first fenced block after it.
    script_heading = re.search(r"^##\s+Script\s*$", text, re.MULTILINE)
    if not script_heading:
        raise ValueError(f"{path}: no '## Script' heading found")

    after_heading = text[script_heading.end():]
    fence_match = re.search(r"```(?:\w*)\n(.*?)```", after_heading, re.DOTALL)
    if not fence_match:
        raise ValueError(f"{path}: no fenced code block found under '## Script'")

    block = fence_match.group(1)

    items: list[SpokenLine | Pause] = []
    spoken_index = 0
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        pause_match = PAUSE_LINE_RE.match(line)
        if pause_match:
            after_line = spoken_index - 1  # -1 if no spoken line has appeared yet
            items.append(Pause(after_line=after_line, duration=float(pause_match.group(1))))
            continue

        spoken_match = SPOKEN_LINE_RE.match(line)
        if not spoken_match:
            raise ValueError(f"{path}: unrecognized script line: {line!r}")

        speaker, instructions, spoken_text = spoken_match.groups()
        speaker = speaker.strip()
        instructions = instructions.strip()
        spoken_text = spoken_text.strip()
        if speaker not in VOICES:
            raise ValueError(f"{path}: unknown speaker {speaker!r}")
        if not instructions or not spoken_text:
            raise ValueError(f"{path}: line missing instruction or text: {line!r}")

        items.append(
            SpokenLine(
                index=spoken_index,
                speaker=speaker,
                voice=VOICES[speaker],
                instructions=instructions,
                text=spoken_text,
            )
        )
        spoken_index += 1

    return items


def cache_key(line: SpokenLine) -> str:
    """
    Hash everything that changes the rendered audio for a line, so editing the text,
    swapping a voice, or tweaking the tone instructions invalidates only that line's
    cache entry rather than the whole clip.
    """
    payload = "\x1f".join([TTS_MODEL, line.voice, line.instructions, line.text])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def estimate_minutes(char_count: int) -> float:
    words = char_count / ASSUMED_CHARS_PER_WORD
    return words / ASSUMED_WORDS_PER_MINUTE


def print_dry_run(items: list[SpokenLine | Pause], cache_dir: Path) -> None:
    lines = [item for item in items if isinstance(item, SpokenLine)]

    print(f"{'idx':>3}  {'speaker':<6} {'voice':<7} {'chars':>6}  cached  text")
    total_chars = 0
    cached_count = 0
    for line in lines:
        cached = (cache_dir / f"{cache_key(line)}.wav").is_file()
        cached_count += int(cached)
        total_chars += len(line.text)
        preview = line.text if len(line.text) <= 60 else line.text[:57] + "..."
        print(
            f"{line.index:>3}  {line.speaker:<6} {line.voice:<7} {len(line.text):>6}  "
            f"{'yes' if cached else 'no':<6}  {preview}"
        )

    billed_count = len(lines) - cached_count
    billed_chars = sum(len(line.text) for line in lines if not (cache_dir / f"{cache_key(line)}.wav").is_file())

    print()
    print(f"total lines:        {len(lines)}")
    print(f"total characters:   {total_chars}")
    print(f"already cached:     {cached_count}")
    print(f"would be billed:    {billed_count} lines, {billed_chars} characters")

    est_words = billed_chars / ASSUMED_CHARS_PER_WORD
    est_minutes = estimate_minutes(billed_chars)
    est_cost = est_minutes * ESTIMATED_COST_PER_MINUTE_USD

    print()
    print("cost estimate for the lines that would be billed:")
    print(f"  {billed_chars} chars / {ASSUMED_CHARS_PER_WORD} chars-per-word  ~= {est_words:.1f} estimated words")
    print(f"  {est_words:.1f} words / {ASSUMED_WORDS_PER_MINUTE:.0f} wpm            ~= {est_minutes:.2f} estimated minutes")
    print(f"  {est_minutes:.2f} minutes * ${ESTIMATED_COST_PER_MINUTE_USD}/min       ~= ${est_cost:.4f} estimated cost")
    print()
    print(
        "This is an ESTIMATE derived from an assumed speaking rate and a rate figure "
        "that must be re-checked against https://openai.com/api/pricing/ — not a quote."
    )


def synth_line(client, line: SpokenLine, cache_dir: Path, use_cache: bool) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{cache_key(line)}.wav"

    if use_cache and out_path.is_file():
        print(f"line {line.index:>3} [{line.speaker}]: cache hit, skipping API call")
        return out_path

    print(f"line {line.index:>3} [{line.speaker}]: rendering ({len(line.text)} chars)")
    response = client.audio.speech.create(
        model=TTS_MODEL,
        voice=line.voice,
        input=line.text,
        instructions=line.instructions,
        response_format="wav",
    )
    response.write_to_file(str(out_path))
    return out_path


def make_silence(duration: float, tmp_dir: Path, tag: str) -> Path:
    """Generate exact silence at the TTS output's sample rate/channel layout so the
    concat demuxer never has to resample across a pause boundary."""
    out_path = tmp_dir / f"silence_{tag}.wav"
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={SAMPLE_RATE}:cl=mono",
            "-t",
            f"{duration}",
            str(out_path),
        ]
    )
    return out_path


def probe_duration(path: Path) -> float:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    return float(result.stdout.strip())


def concat_parts(part_paths: list[Path], out_path: Path, tmp_dir: Path) -> None:
    list_file = tmp_dir / "concat_list.txt"
    with list_file.open("w", encoding="utf-8") as f:
        for part in part_paths:
            # ffmpeg's concat demuxer list format; escape single quotes per its own rules.
            escaped = str(part.resolve()).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-ac",
            "1",
            "-b:a",
            "64k",
            str(out_path),
        ]
    )


_FILTER_CACHE: set[str] | None = None


def _has_filter(name: str) -> bool:
    """Whether this ffmpeg build actually carries a filter, not just whether we want it."""
    global _FILTER_CACHE
    if _FILTER_CACHE is None:
        listing = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, check=False,
        ).stdout
        # Each listing row is "<flags> <name> <io> <description...>", so the filter
        # name is the second token of any row with at least four.
        _FILTER_CACHE = {
            tokens[1] for line in listing.splitlines()
            if len(tokens := line.split()) >= 4
        }
    return name in _FILTER_CACHE


def build_video(mp3_path: Path, mp4_path: Path) -> None:
    """
    Static title card + showwaves overlay driven by the finished mp3. This exercises
    the video path (HTML5 <video>, A/V-sync-preserving cuts) rather than only audio.
    """
    font_path = Path("/System/Library/Fonts/Supplemental/Arial.ttf")

    # showwaves alone is a black background; overlay it onto a solid color card.
    filter_complex = (
        "color=c=0x1a1a2e:s=1280x720:r=30[bg];"
        "[0:a]showwaves=s=1280x200:mode=cline:colors=0x4fd1c5[waves];"
        "[bg][waves]overlay=(W-w)/2:(H-h)/2-60:shortest=1[card]"
    )

    # drawtext needs an ffmpeg built with freetype, which a Homebrew build may not
    # have -- checking only for the font file is not enough. Without it, fall back
    # to a pair of drawbox rules, which every build has. The card is scaffolding for
    # the video code path, not something anyone watches, so plain is fine.
    if _has_filter("drawtext") and font_path.is_file():
        drawtext = (
            f"drawtext=fontfile={font_path}:text='CleanCut -- synthetic demo clip':"
            "fontcolor=white:fontsize=42:x=(w-text_w)/2:y=120"
        )
        filter_complex += f";[card]{drawtext}[v]"
    else:
        reason = "no drawtext filter in this ffmpeg" if not _has_filter("drawtext") \
            else "Arial.ttf not found"
        print(f"note: rendering the card without a title ({reason})")
        filter_complex += (
            ";[card]drawbox=x=440:y=150:w=400:h=3:color=0x4fd1c5@0.9:t=fill,"
            "drawbox=x=440:y=560:w=400:h=3:color=0x4fd1c5@0.35:t=fill[v]"
        )
    video_label = "[v]"

    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(mp3_path),
            "-filter_complex",
            filter_complex,
            "-map",
            video_label,
            "-map",
            "0:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            "-shortest",
            str(mp4_path),
        ]
    )


def round3(x: float) -> float:
    return round(x, 3)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render tests/fixtures/demo/seminar_script.md into a synthetic TTS demo clip "
            "(mp3 + mp4) plus a measured expected_violations.json eval fixture."
        )
    )
    parser.add_argument(
        "--script",
        type=Path,
        default=DEFAULT_SCRIPT_PATH,
        help=f"Path to the script markdown file (default: {DEFAULT_SCRIPT_PATH.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Directory to write demo_seminar.mp3/.mp4/expected_violations.json into (default: {DEFAULT_OUT_DIR.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force re-rendering every line via the API instead of reusing cached audio.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the script and print a cost estimate. Makes zero API calls and writes nothing.",
    )
    args = parser.parse_args()

    script_path: Path = args.script
    out_dir: Path = args.out_dir
    cache_dir = out_dir / CACHE_DIR_NAME

    if not script_path.is_file():
        print(f"error: script not found: {script_path}", file=sys.stderr)
        return 1

    items = parse_script(script_path)
    spoken_count = sum(1 for item in items if isinstance(item, SpokenLine))
    if spoken_count == 0:
        print(f"error: no spoken lines found in {script_path}", file=sys.stderr)
        return 1

    if args.dry_run:
        print_dry_run(items, cache_dir)
        return 0

    root_env = root_env_path(__file__)
    if root_env:
        from dotenv import load_dotenv

        load_dotenv(root_env)

    import os

    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "error: OPENAI_API_KEY is not set. Add it to the repo-root .env "
            "(see README) or export it in this shell.",
            file=sys.stderr,
        )
        return 1

    from openai import OpenAI

    client = OpenAI()

    out_dir.mkdir(parents=True, exist_ok=True)
    use_cache = not args.no_cache

    with tempfile.TemporaryDirectory(prefix="cleancut_demo_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        part_paths: list[Path] = []
        line_records: list[dict] = []
        pause_records: list[dict] = []
        offset = 0.0

        for item in items:
            if isinstance(item, SpokenLine):
                wav_path = synth_line(client, item, cache_dir, use_cache)
                part_paths.append(wav_path)
                duration = probe_duration(wav_path)
                line_records.append(
                    {
                        "index": item.index,
                        "speaker": item.speaker,
                        "voice": item.voice,
                        "text": item.text,
                        "start": round3(offset),
                        "end": round3(offset + duration),
                    }
                )
                offset += duration
            else:
                silence_path = make_silence(item.duration, tmp_dir, tag=f"after_{item.after_line}")
                part_paths.append(silence_path)
                duration = probe_duration(silence_path)
                pause_records.append(
                    {
                        "after_line": item.after_line,
                        "start": round3(offset),
                        "end": round3(offset + duration),
                        "duration": item.duration,
                    }
                )
                offset += duration

        mp3_path = out_dir / "demo_seminar.mp3"
        mp4_path = out_dir / "demo_seminar.mp4"
        concat_parts(part_paths, mp3_path, tmp_dir)

    total_duration = probe_duration(mp3_path)

    manifest = {
        "source": mp3_path.name,
        "generated_with": TTS_MODEL,
        "total_duration": round3(total_duration),
        "lines": line_records,
        "pauses": pause_records,
    }
    manifest_path = out_dir / "expected_violations.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"building {mp4_path.name} ...")
    build_video(mp3_path, mp4_path)

    print()
    print(f"wrote {mp3_path}")
    print(f"wrote {mp4_path}")
    print(f"wrote {manifest_path}")
    print(f"total duration: {total_duration:.3f}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())
