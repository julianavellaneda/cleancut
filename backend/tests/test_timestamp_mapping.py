"""
Tests for mapping an LLM's quoted text back onto word-level timestamps.

The mapper used to require the quote to sit inside a single Whisper segment.
Whisper splits on pauses, not on sentences, so a claim like "you could quit your
job by Christmas" routinely straddles a boundary - and every straddling quote
fell through to a guessed `approximate_time +/- 2s` window. On the waveform that
window lands on the wrong words, which reads to a reviewer as "the model never
flagged it" even though the model flagged it every time.

No LLM is involved; `_find_text_timestamps` is fed the text a model returned.
"""

import pytest

from app.analysis.prompt_analyzer import PromptAnalyzer
from app.analysis.transcriber import Segment, TranscriptResult, Word


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    """PromptAnalyzer builds an OpenAI client eagerly; no call is ever made."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")


@pytest.fixture
def analyzer():
    return PromptAnalyzer()


def _segment(text: str, start: float, end: float) -> Segment:
    """A segment whose words are evenly spaced across [start, end)."""
    tokens = text.split()
    step = (end - start) / max(len(tokens), 1)
    words = [
        Word(text=t, start=start + i * step, end=start + (i + 1) * step, probability=0.9)
        for i, t in enumerate(tokens)
    ]
    return Segment(text=text, start=start, end=end, words=words)


@pytest.fixture
def split_sentence():
    """The rehearsal transcript: one claim, split by Whisper at a pause."""
    return TranscriptResult(
        segments=[
            _segment("Some people earn nothing at all, and that's the honest truth.", 7.40, 11.01),
            _segment("You know, ah, honestly, you could quit your job", 11.01, 13.69),
            _segment("by Christmas if you just, like, follow the system.", 13.69, 17.01),
        ],
        language="en",
        duration=17.01,
    )


def test_quote_spanning_two_segments_maps_to_the_real_span(analyzer, split_sentence):
    """The defect: this used to return the guessed window (9.0, 13.0)."""
    start, end = analyzer._find_text_timestamps(
        "you could quit your job by Christmas", split_sentence, approx_time=11.0
    )

    assert 11.0 <= start < 13.7
    assert 13.7 <= end <= 17.02


def test_the_span_covers_the_words_that_were_quoted(analyzer, split_sentence):
    """A span that stops short of 'by Christmas' cuts the claim in half."""
    start, end = analyzer._find_text_timestamps(
        "you could quit your job by Christmas if you just, like, follow the system.",
        split_sentence,
        approx_time=11.0,
    )

    # "by Christmas" starts the third segment; the span has to reach past it.
    assert end > 14.0
    # ...without swallowing the preceding control line.
    assert start > 11.0


def test_the_span_does_not_reach_back_into_the_previous_sentence(analyzer, split_sentence):
    """
    The old fallback started at 9.0s, inside "some people earn nothing at all" -
    a deliberately compliant line. Cutting there removes the wrong content.
    """
    start, _ = analyzer._find_text_timestamps(
        "you could quit your job by Christmas", split_sentence, approx_time=11.0
    )

    assert start >= 11.01


def test_single_segment_quotes_still_use_the_exact_path(analyzer, split_sentence):
    start, end = analyzer._find_text_timestamps(
        "by Christmas", split_sentence, approx_time=13.7
    )

    assert 13.69 <= start < 15.0
    assert end <= 17.02


def test_a_quote_matching_nothing_falls_back_to_the_approximate_window(analyzer, split_sentence):
    start, end = analyzer._find_text_timestamps(
        "entirely different words about unrelated subject matter", split_sentence, approx_time=30.0
    )

    assert (start, end) == (28.0, 32.0)


def test_short_quotes_do_not_trigger_cross_segment_alignment(analyzer, split_sentence):
    """
    Two or three words match too much of a transcript to place safely. The
    approximate window is the honest answer.
    """
    start, end = analyzer._find_text_timestamps("job by", split_sentence, approx_time=40.0)

    assert (start, end) == (38.0, 42.0)


def test_alignment_survives_punctuation_and_casing_differences(analyzer, split_sentence):
    """Models re-punctuate their quotes; the transcript's commas are Whisper's."""
    start, end = analyzer._find_text_timestamps(
        "You could quit your job -- by Christmas!", split_sentence, approx_time=11.0
    )

    assert start >= 11.01
    assert end > 14.0


def test_transcripts_without_word_timings_fall_back_rather_than_guess(analyzer):
    """Cross-segment alignment needs word timings; segment bounds are not enough."""
    transcript = TranscriptResult(
        segments=[
            Segment(text="you could quit your job", start=11.0, end=13.7, words=[]),
            Segment(text="by Christmas if you follow the system", start=13.7, end=17.0, words=[]),
        ],
        language="en",
        duration=17.0,
    )

    start, end = analyzer._find_text_timestamps(
        "you could quit your job by Christmas", transcript, approx_time=11.0
    )

    assert (start, end) == (9.0, 13.0)


def test_the_nearest_occurrence_to_the_models_timestamp_wins(analyzer):
    """The same sentence twice; approximate_time disambiguates."""
    transcript = TranscriptResult(
        segments=[
            _segment("you could quit your job", 1.0, 3.0),
            _segment("by Christmas easily", 3.0, 5.0),
            _segment("filler in between here", 5.0, 40.0),
            _segment("you could quit your job", 40.0, 42.0),
            _segment("by Christmas easily", 42.0, 44.0),
        ],
        language="en",
        duration=44.0,
    )

    start, _ = analyzer._find_text_timestamps(
        "you could quit your job by Christmas", transcript, approx_time=40.0
    )

    assert start >= 40.0
