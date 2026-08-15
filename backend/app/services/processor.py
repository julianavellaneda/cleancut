"""
Audio processing service - wraps transcriber and prompt analyzer.
"""

import sys
from pathlib import Path

# Add the analysis directory to the Python path for imports
ANALYSIS_PATH = Path(__file__).parent.parent / "analysis"
sys.path.insert(0, str(ANALYSIS_PATH))

from dotenv import load_dotenv

from ..config import root_env_path

# Load environment variables from the root .env file, when there is one.
# In Docker the container supplies them instead.
_ROOT_ENV = root_env_path(__file__)
if _ROOT_ENV:
    load_dotenv(_ROOT_ENV)

from transcriber import Transcriber, TranscriptResult
from prompt_analyzer import PromptAnalyzer, AnalysisResult, Violation


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
            rules_path = ANALYSIS_PATH / "bsm_rules.txt"
            self._analyzer = PromptAnalyzer(rules_path=str(rules_path))
        return self._analyzer

    def transcribe(self, audio_path: str, language: str | None = None) -> TranscriptResult:
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
        bsm_mode: bool = False,
    ) -> AnalysisResult:
        """
        Analyze transcript based on a prompt, or strict compliance.

        Args:
            transcript: TranscriptResult from transcription
            prompt: User-defined editing instructions (ignored when bsm_mode=True)
            bsm_mode: If True, use the strict rulebook compliance system prompt

        Returns:
            AnalysisResult with suggested edits
        """
        return self.analyzer.analyze(transcript, prompt=prompt, bsm_mode=bsm_mode)

    def process_audio(
        self,
        audio_path: str,
        prompt: str | None = None,
        language: str | None = None
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
