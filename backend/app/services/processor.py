"""
Audio processing service - wraps POC transcriber and compliance analyzer.
"""

import sys
from pathlib import Path

# Add POC directory to path for imports
POC_PATH = Path(__file__).parent.parent.parent.parent / "poc"
sys.path.insert(0, str(POC_PATH))

from dotenv import load_dotenv

# Load environment variables from poc/.env
load_dotenv(POC_PATH / ".env")

from transcriber import Transcriber, TranscriptResult
from compliance import ComplianceAnalyzer, AnalysisResult, Violation


class AudioProcessor:
    """
    Wraps POC transcription and compliance analysis for the backend.
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
    def analyzer(self) -> ComplianceAnalyzer:
        """Lazy-load compliance analyzer."""
        if self._analyzer is None:
            rules_path = POC_PATH / "bsm_rules.txt"
            self._analyzer = ComplianceAnalyzer(rules_path=str(rules_path))
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

    def analyze(self, transcript: TranscriptResult) -> AnalysisResult:
        """
        Analyze transcript for compliance violations.

        Args:
            transcript: TranscriptResult from transcription

        Returns:
            AnalysisResult with violations
        """
        return self.analyzer.analyze(transcript)

    def process_audio(
        self,
        audio_path: str,
        language: str | None = None
    ) -> tuple[TranscriptResult, AnalysisResult]:
        """
        Full pipeline: transcribe and analyze.

        Args:
            audio_path: Path to the audio file
            language: Language code or None for auto-detect

        Returns:
            Tuple of (TranscriptResult, AnalysisResult)
        """
        transcript = self.transcribe(audio_path, language)
        analysis = self.analyze(transcript)
        return transcript, analysis


# Global processor instance (reuse model across requests)
_processor: AudioProcessor | None = None


def get_processor(model_size: str = "medium") -> AudioProcessor:
    """Get or create the global processor instance."""
    global _processor
    if _processor is None or _processor.model_size != model_size:
        _processor = AudioProcessor(model_size=model_size)
    return _processor
