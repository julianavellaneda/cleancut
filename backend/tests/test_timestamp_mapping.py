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

import math

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
    start, end, aligned = analyzer._find_text_timestamps(
        "you could quit your job by Christmas", split_sentence, approx_time=11.0
    )

    assert 11.0 <= start < 13.7
    assert 13.7 <= end <= 17.02


def test_the_span_covers_the_words_that_were_quoted(analyzer, split_sentence):
    """A span that stops short of 'by Christmas' cuts the claim in half."""
    start, end, aligned = analyzer._find_text_timestamps(
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
    start, _, aligned = analyzer._find_text_timestamps(
        "you could quit your job by Christmas", split_sentence, approx_time=11.0
    )

    assert start >= 11.01


def test_single_segment_quotes_still_use_the_exact_path(analyzer, split_sentence):
    start, end, aligned = analyzer._find_text_timestamps(
        "by Christmas", split_sentence, approx_time=13.7
    )

    assert 13.69 <= start < 15.0
    assert end <= 17.02


def test_a_quote_matching_nothing_is_reported_as_unaligned(analyzer, split_sentence):
    """
    The window is still returned so the finding stays reviewable, but it is
    flagged as an estimate. Handing this back as an ordinary span is what let a
    quote nobody could place be auto-applied to whatever sat at that time.
    """
    start, end, aligned = analyzer._find_text_timestamps(
        "entirely different words about unrelated subject matter", split_sentence, approx_time=30.0
    )

    assert (start, end) == (28.0, 32.0)
    assert aligned is False


def test_short_quotes_do_not_trigger_cross_segment_alignment(analyzer, split_sentence):
    """
    Two or three words match too much of a transcript to place safely. The
    approximate window is the honest answer.
    """
    start, end, aligned = analyzer._find_text_timestamps("job by", split_sentence, approx_time=40.0)

    assert (start, end) == (38.0, 42.0)
    assert aligned is False


def test_alignment_survives_punctuation_and_casing_differences(analyzer, split_sentence):
    """Models re-punctuate their quotes; the transcript's commas are Whisper's."""
    start, end, aligned = analyzer._find_text_timestamps(
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

    start, end, aligned = analyzer._find_text_timestamps(
        "you could quit your job by Christmas", transcript, approx_time=11.0
    )

    assert (start, end) == (9.0, 13.0)
    assert aligned is False


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

    start, _, aligned = analyzer._find_text_timestamps(
        "you could quit your job by Christmas", transcript, approx_time=40.0
    )

    assert start >= 40.0


# --- matching whole words, not the first one as a substring ------------------
#
# `_find_words_in_segment` used to scan for the quote's *first* word as a
# substring of any word in the segment, then take a span as many words long as
# the quote from wherever that hit. So "so" matched inside "also", "I" matched
# inside "like", and the end was a word count measured from a start nobody had
# verified. The span landed on speech that was never quoted - and under
# `auto_fix`, that is the speech that got cut.

def test_a_first_word_hiding_inside_another_word_does_not_anchor_the_span(analyzer):
    """
    "so" appears inside "also" three words before it appears as itself. The old
    scan anchored on "also" and cut from there.
    """
    transcript = TranscriptResult(
        segments=[_segment("we also tried it and so we quit our jobs", 10.0, 20.0)],
        language="en",
        duration=20.0,
    )

    start, end, aligned = analyzer._find_text_timestamps(
        "so we quit our jobs", transcript, approx_time=10.0
    )

    assert aligned is True
    # "so" is the 6th of 10 evenly spaced words across [10, 20).
    assert start == pytest.approx(15.0)
    assert end == pytest.approx(20.0)


def test_the_span_ends_on_the_last_quoted_word(analyzer):
    """
    The end used to be `start_index + len(quote_words)`, counted through the
    segment's words - which drifts the moment the quote's tokenization and the
    transcript's disagree.
    """
    transcript = TranscriptResult(
        segments=[_segment("I earn six figures a month, honestly I do", 0.0, 10.0)],
        language="en",
        duration=10.0,
    )

    start, end, aligned = analyzer._find_text_timestamps(
        "six figures a month", transcript, approx_time=0.0
    )

    assert aligned is True
    # Nine words evenly spaced across [0, 10): the quote is words 3 through 6,
    # and the span has to stop at the end of "month" rather than counting on.
    step = 10.0 / 9
    assert start == pytest.approx(2 * step)
    assert end == pytest.approx(6 * step)


def test_an_unmatchable_quote_inside_a_segment_uses_the_segment_bounds(analyzer):
    """
    Not every failure to place a quote is a guess. If the quote is known to sit
    in this segment, the segment's own bounds are measured - so this stays
    aligned, unlike a quote the transcript cannot account for at all.
    """
    transcript = TranscriptResult(
        segments=[_segment("we all know the drill by now", 4.0, 8.0)],
        language="en",
        duration=8.0,
    )
    # Substring of the segment text, but not a whole-token run of its words.
    start, end, aligned = analyzer._find_text_timestamps(
        "now the dril", transcript, approx_time=4.0
    )

    assert (start, end) == (4.0, 8.0)
    assert aligned is True


# --- timestamps the model made up -------------------------------------------

@pytest.mark.parametrize("approximate_time", ["nan", "inf", "-inf", "-12s", "later", None])
def test_an_unusable_model_timestamp_does_not_reach_the_span(analyzer, approximate_time):
    """
    float() accepts "nan" and "inf" as readily as "12.5", and both used to flow
    straight into a span the exporter hands to FFmpeg. A negative time is as
    unusable. None of them may produce a non-finite or negative marker.
    """
    transcript = TranscriptResult(
        segments=[_segment("you could quit your job by Christmas", 11.0, 14.0)],
        language="en",
        duration=14.0,
    )

    mapped = analyzer._map_to_timestamps(
        [{"text": "words that appear nowhere in this transcript at all",
          "approximate_time": approximate_time, "label": "Income Claim"}],
        transcript,
        prompt="find income claims",
    )

    span = mapped[0]
    assert math.isfinite(span.start_time) and math.isfinite(span.end_time)
    assert 0 <= span.start_time <= span.end_time


def test_a_usable_model_timestamp_is_still_honoured(analyzer):
    transcript = TranscriptResult(
        segments=[_segment("you could quit your job by Christmas", 11.0, 14.0)],
        language="en",
        duration=14.0,
    )

    mapped = analyzer._map_to_timestamps(
        [{"text": "nothing here matches", "approximate_time": "30s", "label": "Income Claim"}],
        transcript,
        prompt="find income claims",
    )

    assert (mapped[0].start_time, mapped[0].end_time) == (28.0, 32.0)


# --- an unplaced quote says so ----------------------------------------------

def test_an_unplaced_quote_is_marked_approximate_and_says_why(analyzer):
    transcript = TranscriptResult(
        segments=[_segment("you could quit your job by Christmas", 11.0, 14.0)],
        language="en",
        duration=14.0,
    )

    mapped = analyzer._map_to_timestamps(
        [{"text": "a sentence nobody in this recording said",
          "approximate_time": "12s", "label": "Income Claim",
          "reasoning": "Promises a specific outcome."}],
        transcript,
        prompt="find income claims",
    )

    assert mapped[0].is_approximate is True
    assert "Approximate placement" in mapped[0].reasoning
    # The model's own reasoning is kept, not replaced.
    assert "Promises a specific outcome." in mapped[0].reasoning


def test_a_placed_quote_is_not_marked_approximate(analyzer):
    transcript = TranscriptResult(
        segments=[_segment("you could quit your job by Christmas", 11.0, 14.0)],
        language="en",
        duration=14.0,
    )

    mapped = analyzer._map_to_timestamps(
        [{"text": "quit your job by Christmas", "approximate_time": "11s",
          "label": "Income Claim", "reasoning": "Promises a specific outcome."}],
        transcript,
        prompt="find income claims",
    )

    assert mapped[0].is_approximate is False
    assert mapped[0].reasoning == "Promises a specific outcome."
