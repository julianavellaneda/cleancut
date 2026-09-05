"""
Transcription module using faster-whisper for local audio transcription.
Optimized for Apple Silicon (M4).
"""

from dataclasses import dataclass

from faster_whisper import WhisperModel


@dataclass
class Word:
    """Represents a single transcribed word with timing."""
    text: str
    start: float
    end: float
    probability: float


@dataclass
class Segment:
    """Represents a transcribed segment (sentence/phrase) with timing."""
    text: str
    start: float
    end: float
    words: list[Word]
    language: str | None = None


@dataclass
class TranscriptResult:
    """Complete transcription result."""
    segments: list[Segment]
    language: str
    duration: float


class Transcriber:
    """
    Audio transcriber using faster-whisper.
    Runs locally on Apple Silicon for fast, private transcription.
    """

    def __init__(self, model_size: str = "medium", device: str = "auto"):
        """
        Initialize the transcriber.

        Args:
            model_size: Whisper model size. Options:
                - "tiny", "base", "small", "medium", "large-v3"
                - "medium" is the default (good balance of speed and accuracy)
            device: "auto", "cpu", or "cuda". Auto will use Metal on Mac.
        """
        print(f"Loading Whisper model '{model_size}'...")

        # On Apple Silicon, use CPU with int8 for good speed
        # faster-whisper doesn't directly support Metal, but CPU is fast on M4
        compute_type = "int8"  # Good balance of speed and accuracy

        self.model = WhisperModel(
            model_size,
            device="cpu",  # CPU is actually fast on M4 with int8
            compute_type=compute_type,
        )
        print("Model loaded successfully.")

    def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
        word_timestamps: bool = True,
    ) -> TranscriptResult:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to the audio file (mp3, wav, etc.)
            language: Language code (e.g., "en", "es") or None for auto-detect
            word_timestamps: Whether to include word-level timestamps

        Returns:
            TranscriptResult with segments and word-level timing
        """
        print(f"Transcribing: {audio_path}")

        segments_gen, info = self.model.transcribe(
            audio_path,
            language=language,
            word_timestamps=word_timestamps,
            vad_filter=True,  # Voice activity detection to skip silence
        )

        print(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
        print(f"Audio duration: {info.duration:.1f} seconds")

        segments = []
        for seg in segments_gen:
            words = []
            if seg.words:
                for w in seg.words:
                    words.append(Word(
                        text=w.word,
                        start=w.start,
                        end=w.end,
                        probability=w.probability,
                    ))

            segments.append(Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                words=words,
                language=info.language,
            ))

            # Print progress
            print(f"  [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text.strip()[:50]}...")

        return TranscriptResult(
            segments=segments,
            language=info.language,
            duration=info.duration,
        )

    def to_text(self, result: TranscriptResult) -> str:
        """Convert transcript result to plain text."""
        return " ".join(seg.text for seg in result.segments)

    def to_timestamped_text(self, result: TranscriptResult) -> str:
        """Convert transcript result to text with timestamps."""
        lines = []
        for seg in result.segments:
            timestamp = f"[{seg.start:.1f}s - {seg.end:.1f}s]"
            lines.append(f"{timestamp} {seg.text}")
        return "\n".join(lines)


class TranscriptFormatError(ValueError):
    """Raised when a transcript file yields no readable segments."""


def load_transcript(file_path: str) -> TranscriptResult:
    """
    Load a transcript from a timestamped text file.

    Expected format per line:
        [0.0s - 2.2s] Text content here

    Lines that do not carry a timestamp are skipped - a header or a note in the
    margin should not stop a run - but they are **counted and reported**, and a
    file that yields no segments at all is an error rather than an empty
    transcript. That distinction is the whole point: an empty transcript flows
    into the analyzer, comes back with nothing found, and is printed as a clean
    recording. A file in the wrong format would then be indistinguishable from
    a compliant one, which is the worst answer this tool can give.

    Args:
        file_path: Path to the transcript text file

    Returns:
        TranscriptResult with segments (no word-level data)

    Raises:
        TranscriptFormatError: the file has no timestamped lines, whether
            because it is empty or because every line is in another format.
    """
    import re

    pattern = re.compile(r'\[(\d+\.?\d*)s\s*-\s*(\d+\.?\d*)s\]\s*(.+)')
    segments = []
    max_end = 0.0
    skipped: list[str] = []

    with open(file_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            match = pattern.match(line)
            if match:
                start = float(match.group(1))
                end = float(match.group(2))
                text = match.group(3)

                segments.append(Segment(
                    text=text,
                    start=start,
                    end=end,
                    words=[],  # No word-level data from text file
                ))
                max_end = max(max_end, end)
            else:
                skipped.append(line)

    if not segments:
        detail = (
            f"the first of its {len(skipped)} line(s) reads: {skipped[0][:80]!r}"
            if skipped
            else "the file is empty"
        )
        raise TranscriptFormatError(
            f"No timestamped lines found in {file_path} - {detail}. "
            "Each line must look like: [0.0s - 2.2s] Text content here"
        )

    if skipped:
        # Not fatal - the segments that did parse are still worth analyzing -
        # but silence here means a mangled file is analyzed in part and
        # reported in full.
        print(
            f"  Warning: skipped {len(skipped)} line(s) with no timestamp, "
            f"beginning: {skipped[0][:80]!r}"
        )

    # Detect language from first segment or default to unknown
    language = "unknown"

    return TranscriptResult(
        segments=segments,
        language=language,
        duration=max_end,
    )


if __name__ == "__main__":
    # Quick test
    import sys

    if len(sys.argv) < 2:
        print("Usage: python transcriber.py <audio_file>")
        sys.exit(1)

    transcriber = Transcriber(model_size="medium")
    result = transcriber.transcribe(sys.argv[1])

    print("\n" + "="*50)
    print("TRANSCRIPT:")
    print("="*50)
    print(transcriber.to_timestamped_text(result))
