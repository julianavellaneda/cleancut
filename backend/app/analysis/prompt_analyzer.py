"""
Prompt-based semantic analysis module using GPT-4o.
Analyzes transcripts based on user-defined editing instructions.
"""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

from openai import OpenAI

from transcriber import TranscriptResult, Segment


@dataclass
class Violation:
    """Represents a detected marker/edit suggestion."""
    text: str
    start_time: float
    end_time: float
    label: str  # e.g., "Filler Word", "Income Claim", "Silence"
    action: str  # "cut" or "mute"
    reasoning: str


@dataclass
class AnalysisResult:
    """Complete analysis result."""
    violations: list[Violation]
    total_segments_analyzed: int
    transcript_language: str


class PromptAnalyzer:
    """
    Analyzes transcripts for suggested edits using GPT-4o based on a user prompt.
    """

    # Default chunk size in segments (~2-3 minutes of audio typically)
    DEFAULT_CHUNK_SIZE = 50

    # Overlap between chunks (in segments) to catch violations at boundaries
    DEFAULT_OVERLAP = 10

    def __init__(
        self,
        rules_path: str | None = None,
        chunk_size: int | None = None,
        overlap: int | None = None
    ):
        """
        Initialize the analyzer.

        Args:
            rules_path: Path to default rules file.
            chunk_size: Number of segments per chunk.
            overlap: Number of segments to overlap between chunks.
        """
        self.client = OpenAI()  # Uses OPENAI_API_KEY env var
        self.chunk_size = chunk_size
        self.overlap = overlap if overlap is not None else self.DEFAULT_OVERLAP

        # Load default rules as a baseline context
        if rules_path is None:
            rules_path = Path(__file__).parent / "bsm_rules.txt"
        
        try:
            with open(rules_path) as f:
                self.default_rules = f.read()
        except FileNotFoundError:
            self.default_rules = "No default rules provided."

    def analyze(self, transcript: TranscriptResult, prompt: Optional[str] = None) -> AnalysisResult:
        """
        Analyze a transcript for suggested edits based on a user prompt.

        Args:
            transcript: TranscriptResult from transcriber
            prompt: User-defined editing instructions

        Returns:
            AnalysisResult with list of suggested edits
        """
        total_segments = len(transcript.segments)

        # Determine if we should chunk
        chunk_size = self.chunk_size
        if chunk_size is None:
            chunk_size = self.DEFAULT_CHUNK_SIZE if total_segments > 100 else total_segments

        # Split into chunks with overlap
        overlap = self.overlap if total_segments > 100 else 0
        chunks = self._chunk_segments_with_overlap(transcript.segments, chunk_size, overlap)
        num_chunks = len(chunks)

        if num_chunks == 1:
            print(f"Analyzing transcript with prompt: '{prompt or 'Default'}'...")
        else:
            overlap_info = f", {overlap} segment overlap" if overlap > 0 else ""
            print(f"Analyzing transcript in {num_chunks} chunks ({chunk_size} segments each{overlap_info}) with prompt: '{prompt or 'Default'}'...")

        all_violations = []

        for i, chunk_segments in enumerate(chunks):
            if num_chunks > 1:
                chunk_start = chunk_segments[0].start
                chunk_end = chunk_segments[-1].end
                print(f"\n  Chunk {i+1}/{num_chunks} [{chunk_start:.0f}s - {chunk_end:.0f}s] ({len(chunk_segments)} segments)...")

            # Create a temporary TranscriptResult for this chunk
            chunk_transcript = TranscriptResult(
                segments=chunk_segments,
                language=transcript.language,
                duration=chunk_segments[-1].end - chunk_segments[0].start,
            )

            # Format and analyze this chunk
            transcript_text = self._format_transcript_for_analysis(chunk_transcript)
            chunk_violations = self._call_llm(transcript_text, prompt)

            if num_chunks > 1:
                print(f"    Found {len(chunk_violations)} suggested edit(s)")

            # Map violations back to precise timestamps
            mapped = self._map_to_timestamps(chunk_violations, chunk_transcript)
            all_violations.extend(mapped)

        # Deduplicate violations from overlapping chunks
        all_violations = self._deduplicate_violations(all_violations)

        # Sort all violations by time
        all_violations.sort(key=lambda v: v.start_time)

        return AnalysisResult(
            violations=all_violations,
            total_segments_analyzed=total_segments,
            transcript_language=transcript.language,
        )

    def _chunk_segments_with_overlap(
        self,
        segments: list[Segment],
        chunk_size: int,
        overlap: int = 0
    ) -> list[list[Segment]]:
        """Split segments into chunks with sliding window overlap."""
        if overlap >= chunk_size:
            overlap = chunk_size // 2

        chunks = []
        step = chunk_size - overlap

        i = 0
        while i < len(segments):
            end = min(i + chunk_size, len(segments))
            chunks.append(segments[i:end])
            if end >= len(segments):
                break
            i += step

        return chunks

    def _deduplicate_violations(self, violations: list[Violation]) -> list[Violation]:
        """Remove duplicate suggestions from overlapping chunks."""
        if not violations:
            return violations

        sorted_violations = sorted(violations, key=lambda v: (v.start_time, v.label))
        unique = []

        for v in sorted_violations:
            is_duplicate = False
            for existing in unique:
                # Check if same label and overlapping time (within 5 seconds)
                if (v.label == existing.label and
                    abs(v.start_time - existing.start_time) < 5.0):
                    if len(v.text) > len(existing.text):
                        unique.remove(existing)
                        unique.append(v)
                    is_duplicate = True
                    break

            if not is_duplicate:
                unique.append(v)

        return unique

    def _format_transcript_for_analysis(self, transcript: TranscriptResult) -> str:
        """Format transcript for LLM analysis."""
        lines = []
        for seg in transcript.segments:
            lines.append(f"[{seg.start:.1f}s - {seg.end:.1f}s] {seg.text}")
        return "\n".join(lines)

    def _call_llm(self, transcript_text: str, user_prompt: Optional[str]) -> list[dict]:
        """Call GPT-4o to analyze the transcript based on the user prompt."""
        
        instructions = user_prompt if user_prompt else "Identify all segments that should be removed or muted for clarity and compliance."
        
        system_prompt = f"""You are an expert audio/video editor and compliance officer.
        
## EDITING INSTRUCTIONS:
{instructions}

## BASELINE COMPLIANCE CONTEXT (If relevant):
{self.default_rules}

## YOUR TASK
Scan the transcript and extract EVERY segment that matches the editing instructions or violates the baseline compliance rules.

Return your response as a JSON array of objects with this structure:
```json
[
  {{
    "text": "exact quote from transcript",
    "approximate_time": "5.2s",
    "label": "Short descriptive label (e.g. Filler Word, Income Claim, Off-topic)",
    "action": "cut or mute",
    "reasoning": "brief explanation of why this segment was flagged"
  }}
]
```

If no segments match the criteria, return an empty array: []

IMPORTANT:
- Quote the EXACT text from the transcript.
- Include the approximate timestamp (e.g., "12.5s").
- Be EXHAUSTIVE - find all matching segments.
- Choose 'cut' if the segment should be physically removed (e.g. filler words, mistakes).
- Choose 'mute' if the segment should remain but be silenced (e.g. sensitive info, background noise).
"""

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"TRANSCRIPT TO ANALYZE:\n\n{transcript_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        content = response.choices[0].message.content
        try:
            result = json.loads(content)
            if isinstance(result, dict):
                if "violations" in result: return result["violations"]
                if "markers" in result: return result["markers"]
                if "edits" in result: return result["edits"]
                if "text" in result and "label" in result: return [result]
                return []
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            return []

    def _map_to_timestamps(
        self,
        raw_violations: list[dict],
        transcript: TranscriptResult
    ) -> list[Violation]:
        """Map violation text to precise timestamps using transcript data."""
        violations = []

        for v in raw_violations:
            text = v.get("text", "")
            approx_time = v.get("approximate_time", "0s")

            try:
                approx_seconds = float(approx_time.replace("s", ""))
            except ValueError:
                approx_seconds = 0

            start_time, end_time = self._find_text_timestamps(
                text, transcript, approx_seconds
            )

            violations.append(Violation(
                text=text,
                start_time=start_time,
                end_time=end_time,
                label=v.get("label", v.get("rule_violated", "Marker")),
                action=v.get("action", "cut"),
                reasoning=v.get("reasoning", ""),
            ))

        return violations

    def _find_text_timestamps(
        self,
        text: str,
        transcript: TranscriptResult,
        approx_time: float
    ) -> tuple[float, float]:
        """Find precise timestamps for a text segment."""
        text_lower = text.lower()
        candidates = []
        for seg in transcript.segments:
            if text_lower in seg.text.lower():
                distance = abs(seg.start - approx_time)
                candidates.append((distance, seg))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            best_seg = candidates[0][1]
            if best_seg.words:
                start, end = self._find_words_in_segment(text_lower, best_seg)
                if start is not None:
                    return start, end
            return best_seg.start, best_seg.end

        return max(0, approx_time - 2), approx_time + 2

    def _find_words_in_segment(
        self,
        text: str,
        segment: Segment
    ) -> tuple[float | None, float | None]:
        """Find word-level timestamps for text within a segment."""
        words = text.split()
        if not words or not segment.words:
            return None, None

        segment_words = [w.text.strip().lower() for w in segment.words]
        first_word = words[0].lower()

        for i, sw in enumerate(segment_words):
            if first_word in sw:
                start_time = segment.words[i].start
                end_idx = min(i + len(words) - 1, len(segment.words) - 1)
                end_time = segment.words[end_idx].end
                return start_time, end_time

        return None, None


def to_json(result: AnalysisResult, indent: int = 2) -> str:
    """Convert analysis result to JSON string."""
    data = {
        "violations": [asdict(v) for v in result.violations],
        "total_segments_analyzed": result.total_segments_analyzed,
        "transcript_language": result.transcript_language,
    }
    return json.dumps(data, indent=indent)
