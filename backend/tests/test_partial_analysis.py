"""
Tests for how a chunk-level analysis failure is handled.

A long transcript is analyzed in overlapping chunks. One unreadable model
response should not throw away the other nineteen chunks of real findings - but
it must not vanish either, or the reviewer believes a span was checked and found
clean when it was never checked at all.
"""

import json

import pytest

from app.analysis.prompt_analyzer import AnalysisError, PromptAnalyzer, to_json
from app.analysis.transcriber import Segment, TranscriptResult, Word


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    """PromptAnalyzer builds an OpenAI client eagerly; no call is ever made."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")


def _segment(index: int) -> Segment:
    start = float(index)
    text = f"word{index}"
    return Segment(
        text=text,
        start=start,
        end=start + 1.0,
        words=[Word(text=text, start=start, end=start + 1.0, probability=0.9)],
    )


@pytest.fixture
def transcript():
    """Long enough to force chunking: >100 segments triggers the sliding window."""
    segments = [_segment(i) for i in range(120)]
    return TranscriptResult(segments=segments, language="en", duration=120.0)


@pytest.fixture
def short_transcript():
    return TranscriptResult(segments=[_segment(0)], language="en", duration=1.0)


def _analyzer_with(monkeypatch, responses):
    """
    An analyzer whose `_call_llm` replays `responses`, one per chunk.

    Each entry is either a list of raw suggestion dicts or an exception to raise.
    """
    analyzer = PromptAnalyzer()
    calls = iter(responses)

    def fake_call(transcript_text, user_prompt, preset=None):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(analyzer, "_call_llm", fake_call)
    return analyzer


def _suggestion(index: int) -> dict:
    return {
        "text": f"word{index}",
        "approximate_time": f"{index}s",
        "label": "Income Claim",
        "action": "cut",
        "reasoning": "planted",
    }


def test_transcript_is_actually_chunked(monkeypatch, transcript):
    """Guards the premise of every test below."""
    chunks = transcript.segments
    analyzer = PromptAnalyzer()
    assert len(analyzer._chunk_segments_with_overlap(chunks, 50, 10)) > 1


def test_one_failed_chunk_keeps_the_other_findings(monkeypatch, transcript):
    analyzer = _analyzer_with(monkeypatch, [
        [_suggestion(1)],
        AnalysisError("garbled response"),
        [_suggestion(101)],
    ])

    result = analyzer.analyze(transcript, prompt="find claims")

    assert len(result.violations) == 2


def test_one_failed_chunk_is_reported(monkeypatch, transcript):
    analyzer = _analyzer_with(monkeypatch, [
        [_suggestion(1)],
        AnalysisError("garbled response"),
        [_suggestion(101)],
    ])

    result = analyzer.analyze(transcript, prompt="find claims")

    assert result.is_partial
    assert len(result.failed_chunks) == 1
    assert "garbled response" in result.failed_chunks[0]


def test_failure_names_the_unanalyzed_timespan(monkeypatch, transcript):
    """"Which part of my audio was skipped?" has to be answerable."""
    analyzer = _analyzer_with(monkeypatch, [
        [], AnalysisError("garbled"), [],
    ])

    result = analyzer.analyze(transcript, prompt="find claims")

    assert "s-" in result.failed_chunks[0]


def test_clean_run_is_not_partial(monkeypatch, transcript):
    analyzer = _analyzer_with(monkeypatch, [[], [], []])

    result = analyzer.analyze(transcript, prompt="find claims")

    assert result.failed_chunks == []
    assert result.is_partial is False


def test_all_chunks_failing_raises(monkeypatch, transcript):
    """
    No chunk analyzed means no analysis. Returning an empty result here would
    render as a clean recording.
    """
    analyzer = _analyzer_with(monkeypatch, [
        AnalysisError("garbled 1"),
        AnalysisError("garbled 2"),
        AnalysisError("garbled 3"),
    ])

    with pytest.raises(AnalysisError) as excinfo:
        analyzer.analyze(transcript, prompt="find claims")

    assert "garbled 1" in str(excinfo.value)


def test_single_chunk_failure_raises(monkeypatch, short_transcript):
    """A short transcript is one chunk, so its failure is a total failure."""
    analyzer = _analyzer_with(monkeypatch, [AnalysisError("garbled")])

    with pytest.raises(AnalysisError):
        analyzer.analyze(short_transcript, prompt="find claims")


def test_non_analysis_errors_still_propagate(monkeypatch, transcript):
    """A network or auth error is not a per-chunk problem to shrug off."""
    analyzer = _analyzer_with(monkeypatch, [ConnectionError("no route to host")])

    with pytest.raises(ConnectionError):
        analyzer.analyze(transcript, prompt="find claims")


# --- coverage accounting ---------------------------------------------------
#
# `total_segments_analyzed` used to be the length of the transcript regardless
# of what failed, so a partial run reported full coverage.

def test_clean_run_covers_every_segment(monkeypatch, transcript):
    analyzer = _analyzer_with(monkeypatch, [[], [], []])

    result = analyzer.analyze(transcript, prompt="find claims")

    assert result.total_segments == 120
    assert result.total_segments_analyzed == 120


def test_failed_chunk_shrinks_the_analyzed_count(monkeypatch, transcript):
    analyzer = _analyzer_with(monkeypatch, [[], AnalysisError("garbled"), []])

    result = analyzer.analyze(transcript, prompt="find claims")

    assert result.total_segments == 120
    assert result.total_segments_analyzed < 120


def test_overlap_still_counts_a_segment_once(monkeypatch, transcript):
    """Chunks overlap, so a naive sum would exceed the transcript length."""
    analyzer = _analyzer_with(monkeypatch, [[], [], []])

    result = analyzer.analyze(transcript, prompt="find claims")

    assert result.total_segments_analyzed == result.total_segments


# --- serialization ---------------------------------------------------------
#
# The JSON file is often all a downstream reader ever sees. Dropping
# `failed_chunks` from it recreated the false-clean result the chunk handling
# exists to prevent.

def test_json_carries_the_partial_status(monkeypatch, transcript):
    analyzer = _analyzer_with(monkeypatch, [[], AnalysisError("garbled"), []])

    result = analyzer.analyze(transcript, prompt="find claims")
    data = json.loads(to_json(result))

    assert data["is_partial"] is True
    assert len(data["failed_chunks"]) == 1
    assert "garbled" in data["failed_chunks"][0]
    assert data["total_segments_analyzed"] < data["total_segments"]


def test_json_of_a_clean_run_is_not_partial(monkeypatch, transcript):
    analyzer = _analyzer_with(monkeypatch, [[], [], []])

    data = json.loads(to_json(analyzer.analyze(transcript, prompt="find claims")))

    assert data["is_partial"] is False
    assert data["failed_chunks"] == []
    assert data["total_segments_analyzed"] == data["total_segments"]
