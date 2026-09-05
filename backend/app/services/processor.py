"""
Audio processing service - wraps transcriber and prompt analyzer.
"""

from dotenv import load_dotenv

from ..config import root_env_path

# Load environment variables from the root .env file, when there is one.
# In Docker the container supplies them instead.
_ROOT_ENV = root_env_path(__file__)
if _ROOT_ENV:
    load_dotenv(_ROOT_ENV)

# PRESETS, Violation and is_valid_preset are re-exports, not leftovers: this
# module is the seam the rest of the backend reaches the analyzer through, and
# `routes/jobs.py` imports the first and third from here by name. The middle one
# is load-bearing in a stranger way - `tests/test_cli_entrypoint.py` imports
# `Violation` through both this path and the analyzer's own to assert they are
# the *same class*, which is the check that catches a sys.path hack quietly
# creating two of them. Deleting these as unused would break an import and a
# guard at once, so ruff is told once rather than argued with per line.
#
# Both import blocks also sit below load_dotenv on purpose, so E402 is silenced
# rather than obeyed: the analyzer resolves the configured provider's key at
# import time, and hoisting these would read an environment the .env had not
# been loaded into yet.
from ..analysis.prompt_analyzer import (  # noqa: E402, F401  (see above)
    PRESETS,
    AnalysisResult,
    PromptAnalyzer,
    Violation,
    is_valid_preset,
)
from ..analysis.transcriber import Transcriber, TranscriptResult  # noqa: E402


class AudioProcessor:
    """
    Wraps POC transcription and prompt analysis for the backend.
    """

    def __init__(self, model_size: str = "medium"):
        self.model_size = model_size
        self._transcriber = None
        self._analyzer = None

    @property
    def transcriber(self) -> Transcriber:
        """Lazy-load transcriber (model loading is slow)."""
        if self._transcriber is None:
            self._transcriber = Transcriber(model_size=self.model_size)
        return self._transcriber

    @property
    def analyzer(self) -> PromptAnalyzer:
        """Lazy-load prompt analyzer."""
        if self._analyzer is None:
            self._analyzer = PromptAnalyzer()
        return self._analyzer

    def transcribe(
        self, audio_path: str, language: str | None = None
    ) -> TranscriptResult:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to the audio file
            language: Language code or None for auto-detect

        Returns:
            TranscriptResult with segments and timing
        """
        return self.transcriber.transcribe(audio_path, language=language)

    def analyze(
        self,
        transcript: TranscriptResult,
        prompt: str | None = None,
        preset: str | None = None,
    ) -> AnalysisResult:
        """
        Analyze transcript against a free-form prompt or a built-in rule preset.

        Args:
            transcript: TranscriptResult from transcription
            prompt: User-defined editing instructions (ignored when a preset is set)
            preset: Preset id from PRESETS, or None for prompt mode

        Returns:
            AnalysisResult with suggested edits
        """
        return self.analyzer.analyze(transcript, prompt=prompt, preset=preset)

    def process_audio(
        self, audio_path: str, prompt: str | None = None, language: str | None = None
    ) -> tuple[TranscriptResult, AnalysisResult]:
        """
        Full pipeline: transcribe and analyze.

        Args:
            audio_path: Path to the audio file
            prompt: User-defined editing instructions
            language: Language code or None for auto-detect

        Returns:
            Tuple of (TranscriptResult, AnalysisResult)
        """
        transcript = self.transcribe(audio_path, language)
        analysis = self.analyze(transcript, prompt=prompt)
        return transcript, analysis


# Global processor instance (reuse model across requests)
_processor: AudioProcessor | None = None


def get_processor(model_size: str = "medium") -> AudioProcessor:
    """Get or create the global processor instance."""
    global _processor
    if _processor is None or _processor.model_size != model_size:
        _processor = AudioProcessor(model_size=model_size)
    return _processor
