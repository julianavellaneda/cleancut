"""
Prompt-based semantic analysis module using GPT-4o.
Analyzes transcripts based on user-defined editing instructions.
"""

import json
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional

from openai import OpenAI

from .transcriber import TranscriptResult, Segment


# Built-in rule presets. A preset swaps the free-form user prompt for a curated
# rulebook plus a stricter, category-aware system prompt.
PRESETS_DIR = Path(__file__).parent / "presets"

PRESETS: dict[str, dict[str, str]] = {
    "income-claims": {
        "name": "Income & Lifestyle Claims",
        "description": "FTC-style earnings and lifestyle claim review for direct-selling material.",
        "rules_file": "income-claims.md",
        "default_action": "cut",
        "example_category": "Income Claims",
        "categories": (
            '"Income Claims", "Lifestyle Claims", "Political/Religious", '
            '"Medical/Health Claims", "Business Opportunity Misrepresentation", '
            '"Competitive Disparagement"'
        ),
    },
    "pii-redaction": {
        "name": "PII Redaction",
        "description": "Flags spoken personal, financial, and credential data for muting.",
        "rules_file": "pii-redaction.md",
        "default_action": "mute",
        "example_category": "Direct Identifiers",
        "categories": (
            '"Direct Identifiers", "Government/Financial Identifiers", '
            '"Credentials & Access", "Health & Protected Categories", '
            '"Confidential Business Information"'
        ),
    },
}


def is_valid_preset(preset: str | None) -> bool:
    """True when `preset` is None (prompt mode) or a known preset id."""
    return preset is None or preset in PRESETS


def load_preset_rules(preset: str) -> str:
    """Read the rulebook backing a preset id."""
    meta = PRESETS[preset]
    with open(PRESETS_DIR / meta["rules_file"]) as f:
        return f.read()


class AnalysisError(RuntimeError):
    """
    The model's answer could not be read as a list of suggestions.

    Distinct from "the model found nothing". Returning ``[]`` for an
    unparseable response made a broken analysis look exactly like a clean
    recording, which is the worst possible failure mode for a compliance tool -
    the user sees "0 violations" and ships the file.
    """


# Keys a well-formed object response may wrap its list in. The models drift
# between these depending on the prompt wording, so all three are accepted.
_LIST_KEYS = ("violations", "markers", "edits")

# How much of an unreadable response to quote back in the error. Enough to
# recognize a refusal or a truncation, short enough not to dump a transcript
# into the job's error_message column.
_ERROR_EXCERPT_CHARS = 300

# The two edits the pipeline knows how to render, and the three severities the
# preset prompts ask for. Anything else is a response we cannot act on.
_VALID_ACTIONS = ("cut", "mute")
_VALID_SEVERITIES = ("high", "medium", "low")

# Fields that must be strings when the model bothers to send them. `null` is
# treated as "not sent" - the models routinely pad objects with nulls.
_STRING_FIELDS = (
    "text", "label", "action", "reasoning",
    "rule_violated", "severity", "approximate_time",
)


def _excerpt(content: str | None) -> str:
    text = (content or "").strip()
    if not text:
        return "<empty response>"
    if len(text) > _ERROR_EXCERPT_CHARS:
        return text[:_ERROR_EXCERPT_CHARS] + "..."
    return text


def _validate_entries(entries: list, content: str | None) -> list[dict]:
    """
    Check that every entry is something the pipeline can safely act on.

    A list that parses is not the same as a list that means anything. An entry
    like ``{"summary": "none"}`` used to survive all the way to a Marker with
    empty text, whose timestamp lookup then fell back to the start of the
    transcript - and with ``auto_fix`` on, that segment was cut. Anything we
    cannot read as a suggestion fails the chunk instead, so the span is
    reported as unanalyzed rather than acted on.
    """
    for index, entry in enumerate(entries):
        position = f"entry {index + 1} of {len(entries)}"

        if not isinstance(entry, dict):
            raise AnalysisError(
                f"The model returned {position} as {type(entry).__name__}, expected an object. "
                f"Response began: {_excerpt(content)}"
            )

        for key in _STRING_FIELDS:
            value = entry.get(key)
            if value is not None and not isinstance(value, str):
                raise AnalysisError(
                    f"The model returned a non-string {key!r} in {position} "
                    f"(got {type(value).__name__}). Response began: {_excerpt(content)}"
                )

        if not (entry.get("text") or "").strip():
            raise AnalysisError(
                f"The model returned {position} with no quoted text, so it cannot be "
                f"mapped to a timestamp. Response began: {_excerpt(content)}"
            )

        action = entry.get("action")
        if action is not None and action.strip().lower() not in _VALID_ACTIONS:
            raise AnalysisError(
                f"The model returned an unknown action {action!r} in {position}; "
                f"expected one of {', '.join(_VALID_ACTIONS)}. "
                f"Response began: {_excerpt(content)}"
            )

        severity = entry.get("severity")
        if severity is not None and severity.strip().lower() not in _VALID_SEVERITIES:
            raise AnalysisError(
                f"The model returned an unknown severity {severity!r} in {position}; "
                f"expected one of {', '.join(_VALID_SEVERITIES)}. "
                f"Response began: {_excerpt(content)}"
            )

    return entries


def _parse_llm_response(content: str | None) -> list[dict]:
    """
    Coerce a raw model response into a list of validated suggestion dicts.

    Raises :class:`AnalysisError` for anything unreadable - invalid JSON, a
    refusal, an object whose shape carries no recognizable list, or a list
    holding entries that are not usable suggestions. Only a genuinely empty
    result returns ``[]``.
    """
    try:
        result = json.loads(content or "")
    except json.JSONDecodeError as e:
        raise AnalysisError(
            f"The model returned a response that is not valid JSON ({e.msg}). "
            f"Response began: {_excerpt(content)}"
        ) from e

    if isinstance(result, list):
        return _validate_entries(result, content)

    if isinstance(result, dict):
        for key in _LIST_KEYS:
            if isinstance(result.get(key), list):
                return _validate_entries(result[key], content)

        # A single suggestion returned bare, rather than wrapped in a list.
        if "text" in result and ("label" in result or "rule_violated" in result):
            return _validate_entries([result], content)

        # `{}` and `{"violations": null}` are the models' ways of saying
        # "nothing here" - not something to fail the job over.
        if not result or all(v is None for v in result.values()):
            return []

        # One unrecognized key holding a list: the model renamed the wrapper.
        # Accept it rather than throwing away real findings over a synonym.
        list_values = [v for v in result.values() if isinstance(v, list)]
        if len(result) == 1 and len(list_values) == 1:
            return _validate_entries(list_values[0], content)

        raise AnalysisError(
            "The model returned a JSON object with no recognizable list of suggestions "
            f"(keys: {', '.join(sorted(result)) or 'none'}). Response began: {_excerpt(content)}"
        )

    raise AnalysisError(
        f"The model returned JSON of type {type(result).__name__}, expected a list or object. "
        f"Response began: {_excerpt(content)}"
    )


@dataclass
class Violation:
    """Represents a detected marker/edit suggestion."""
    text: str
    start_time: float
    end_time: float
    label: str  # e.g., "Filler Word", "Income Claim", "Silence"
    action: str  # "cut" or "mute"
    reasoning: str
    rule_violated: str | None = None  # Populated in preset mode
    severity: str | None = None  # "high" | "medium" | "low", populated in preset mode


@dataclass
class AnalysisResult:
    """Complete analysis result."""
    violations: list[Violation]
    # Segments that a chunk actually returned an answer for - NOT the size of
    # the transcript. On a partial run this is smaller than `total_segments`,
    # and the gap is exactly the audio nobody checked.
    total_segments_analyzed: int
    transcript_language: str
    # Segments in the transcript, analyzed or not. The denominator for coverage.
    total_segments: int = 0
    # One message per chunk the model gave an unusable answer for. Empty on a
    # clean run. A partially analyzed transcript is still worth reviewing, but
    # the user has to be told which parts were not covered.
    failed_chunks: list[str] = field(default_factory=list)

    @property
    def is_partial(self) -> bool:
        return bool(self.failed_chunks)


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
            rules_path: Optional path to a rules file used as baseline context in
                prompt mode. Preset mode loads its own rulebook instead.
            chunk_size: Number of segments per chunk.
            overlap: Number of segments to overlap between chunks.
        """
        self.client = OpenAI()  # Uses OPENAI_API_KEY env var
        self.chunk_size = chunk_size
        self.overlap = overlap if overlap is not None else self.DEFAULT_OVERLAP

        self.default_rules = ""
        if rules_path:
            try:
                with open(rules_path) as f:
                    self.default_rules = f.read()
            except FileNotFoundError:
                self.default_rules = ""

    def analyze(
        self,
        transcript: TranscriptResult,
        prompt: Optional[str] = None,
        preset: str | None = None,
    ) -> AnalysisResult:
        """
        Analyze a transcript for suggested edits, driven either by a free-form
        user prompt or by a built-in rule preset.

        Args:
            transcript: TranscriptResult from transcriber
            prompt: User-defined editing instructions (ignored when a preset is set)
            preset: Preset id from PRESETS, or None for prompt mode. Preset mode
                uses the preset's rulebook and extracts rule_violated + severity.

        Returns:
            AnalysisResult with list of suggested edits
        """
        if not is_valid_preset(preset):
            raise ValueError(f"Unknown preset: {preset!r}")
        total_segments = len(transcript.segments)

        # Determine if we should chunk
        chunk_size = self.chunk_size
        if chunk_size is None:
            chunk_size = self.DEFAULT_CHUNK_SIZE if total_segments > 100 else total_segments

        # Split into chunks with overlap
        overlap = self.overlap if total_segments > 100 else 0
        chunk_ranges = self._chunk_ranges(total_segments, chunk_size, overlap)
        chunks = [transcript.segments[s:e] for s, e in chunk_ranges]
        num_chunks = len(chunks)

        mode_label = (
            f"preset: '{PRESETS[preset]['name']}'"
            if preset
            else f"prompt: '{prompt or 'Default'}'"
        )
        if num_chunks == 1:
            print(f"Analyzing transcript with {mode_label}...")
        else:
            overlap_info = f", {overlap} segment overlap" if overlap > 0 else ""
            print(f"Analyzing transcript in {num_chunks} chunks ({chunk_size} segments each{overlap_info}) with {mode_label}...")

        all_violations = []
        failed_chunks: list[str] = []
        # Segment indices a chunk actually came back with an answer for. With
        # overlap one segment can sit in two chunks, so this is a set rather
        # than a running count - a segment covered by a surviving chunk counts
        # as analyzed even if its other chunk failed.
        analyzed_indices: set[int] = set()

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
            try:
                chunk_violations = self._call_llm(transcript_text, prompt, preset=preset)
            except AnalysisError as e:
                # Keep going: the other chunks still produce reviewable
                # suggestions, and the caller is told exactly which span of
                # audio went unanalyzed.
                span = f"{chunk_segments[0].start:.0f}s-{chunk_segments[-1].end:.0f}s"
                failed_chunks.append(f"chunk {i + 1}/{num_chunks} [{span}]: {e}")
                print(f"    Analysis failed for this chunk: {e}")
                continue

            analyzed_indices.update(range(*chunk_ranges[i]))

            if num_chunks > 1:
                print(f"    Found {len(chunk_violations)} suggested edit(s)")

            # Map violations back to precise timestamps
            mapped = self._map_to_timestamps(chunk_violations, chunk_transcript, preset=preset)
            all_violations.extend(mapped)

        # Every chunk failed: there is no analysis at all, so fail loudly
        # rather than hand back an empty result that reads as "nothing found".
        if failed_chunks and len(failed_chunks) == num_chunks:
            raise AnalysisError(
                f"Analysis failed for all {num_chunks} chunk(s). First failure: {failed_chunks[0]}"
            )

        # Deduplicate violations from overlapping chunks
        all_violations = self._deduplicate_violations(all_violations)

        # Sort all violations by time
        all_violations.sort(key=lambda v: v.start_time)

        return AnalysisResult(
            violations=all_violations,
            total_segments_analyzed=len(analyzed_indices),
            transcript_language=transcript.language,
            total_segments=total_segments,
            failed_chunks=failed_chunks,
        )

    def _chunk_ranges(
        self,
        total: int,
        chunk_size: int,
        overlap: int = 0
    ) -> list[tuple[int, int]]:
        """
        Half-open ``[start, end)`` index ranges for the sliding window.

        Ranges rather than slices so a chunk's outcome can be attributed back to
        the segments it covered - overlap means a segment may belong to two
        chunks, and it counts as analyzed if either of them succeeded.
        """
        if overlap >= chunk_size:
            overlap = chunk_size // 2

        ranges = []
        step = max(1, chunk_size - overlap)

        i = 0
        while i < total:
            end = min(i + chunk_size, total)
            ranges.append((i, end))
            if end >= total:
                break
            i += step

        return ranges

    def _chunk_segments_with_overlap(
        self,
        segments: list[Segment],
        chunk_size: int,
        overlap: int = 0
    ) -> list[list[Segment]]:
        """Split segments into chunks with sliding window overlap."""
        return [
            segments[start:end]
            for start, end in self._chunk_ranges(len(segments), chunk_size, overlap)
        ]

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

    def _prompt_system_prompt(self, user_prompt: Optional[str]) -> str:
        """Generic prompt-driven system prompt (default mode)."""
        instructions = user_prompt if user_prompt else "Identify all segments that should be removed or muted for clarity and compliance."
        baseline = (
            f"\n## BASELINE COMPLIANCE CONTEXT (If relevant):\n{self.default_rules}\n"
            if self.default_rules
            else ""
        )
        return f"""You are an expert audio/video editor and compliance officer.

## EDITING INSTRUCTIONS:
{instructions}
{baseline}
## YOUR TASK
Scan the transcript and extract EVERY segment that matches the editing instructions.

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

    def _preset_system_prompt(self, preset: str) -> str:
        """Strict rulebook-driven system prompt used when a preset is selected."""
        meta = PRESETS[preset]
        return f"""{load_preset_rules(preset)}

## YOUR TASK
You are a forensic compliance auditor. Your job is to meticulously scan the ENTIRE transcript and extract EVERY SINGLE instance of content that violates the guidelines above.

CRITICAL INSTRUCTIONS:
1. You MUST read the ENTIRE transcript from start to finish
2. You MUST identify ALL violations, not just the first one you find
3. A single transcript may contain ZERO violations, or it may contain TEN or more - list them ALL
4. Do NOT stop after finding one or two violations - continue scanning until the end
5. Each violation must be reported separately, even if they are similar

Return your response as a JSON array with this exact structure:
```json
[
  {{
    "text": "exact quote from transcript",
    "approximate_time": "57.1s",
    "rule_violated": "{meta['example_category']}",
    "severity": "high",
    "reasoning": "brief explanation"
  }}
]
```

If no violations are found, return an empty array: []

IMPORTANT:
- Quote the EXACT text that violates guidelines
- Include the approximate timestamp (e.g. "57.1s")
- severity must be "high", "medium", or "low"
- rule_violated must be one of the categories in the guidelines above (e.g. {meta['categories']})
- Be EXHAUSTIVE - scan every sentence for potential violations
- Flag actual violations, not borderline cases
- Do NOT summarize or combine multiple violations into one entry
"""

    def _call_llm(
        self,
        transcript_text: str,
        user_prompt: Optional[str],
        preset: str | None = None,
    ) -> list[dict]:
        """Call GPT-4o to analyze the transcript using the preset rulebook or the user prompt."""

        if preset:
            system_prompt = self._preset_system_prompt(preset)
        else:
            system_prompt = self._prompt_system_prompt(user_prompt)

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"TRANSCRIPT TO ANALYZE:\n\n{transcript_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        return _parse_llm_response(response.choices[0].message.content)

    def _map_to_timestamps(
        self,
        raw_violations: list[dict],
        transcript: TranscriptResult,
        preset: str | None = None,
    ) -> list[Violation]:
        """Map violation text to precise timestamps using transcript data."""
        violations = []

        for v in raw_violations:
            text = v.get("text", "")
            approx_time = v.get("approximate_time", "0s")

            try:
                approx_seconds = float(str(approx_time).replace("s", ""))
            except ValueError:
                approx_seconds = 0

            start_time, end_time = self._find_text_timestamps(
                text, transcript, approx_seconds
            )

            rule_violated = v.get("rule_violated")
            severity = v.get("severity")

            # In preset mode the model returns rule_violated/severity and no label/action.
            # Map rule_violated onto the label field so the existing review UI renders,
            # and fall back to the preset's own default action (mute for redaction).
            if preset:
                label = rule_violated or v.get("label") or PRESETS[preset]["name"]
                action = v.get("action") or PRESETS[preset]["default_action"]
            else:
                label = v.get("label") or rule_violated or "Marker"
                action = v.get("action") or "cut"
            action = action.strip().lower()

            violations.append(Violation(
                text=text,
                start_time=start_time,
                end_time=end_time,
                label=label,
                action=action,
                reasoning=v.get("reasoning", ""),
                rule_violated=rule_violated,
                severity=severity,
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
    """
    Convert analysis result to JSON string.

    ``is_partial`` and ``failed_chunks`` ride along with the findings: a saved
    result claiming zero violations means one thing when the whole transcript
    was analyzed and something very different when a chunk was skipped, and the
    file is often all a downstream reader ever sees.
    """
    data = {
        "violations": [asdict(v) for v in result.violations],
        "total_segments_analyzed": result.total_segments_analyzed,
        "total_segments": result.total_segments,
        "transcript_language": result.transcript_language,
        "is_partial": result.is_partial,
        "failed_chunks": result.failed_chunks,
    }
    return json.dumps(data, indent=indent)
