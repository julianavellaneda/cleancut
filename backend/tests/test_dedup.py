"""
Tests for collapsing the same finding seen twice - and nothing else.

Chunks overlap so a claim in the seam is not cut in half by the window; the
price is that the model reports the seam twice. Deduplication exists to pay
that price and nothing more.

The old rule was "same label, starts within 5 seconds", applied to a flat list
with no idea which chunk anything came from. In a recording this tool exists to
review, two income claims three seconds apart is an ordinary sentence pair - and
the second one was deleted before the reviewer ever saw it. A compliance tool
that quietly drops findings is worse than one that shows a duplicate.
"""

import pytest

from app.analysis.prompt_analyzer import PromptAnalyzer, Violation


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")


@pytest.fixture
def analyzer():
    return PromptAnalyzer()


def _v(text, start, end, label="Income Claim"):
    return Violation(
        text=text,
        start_time=start,
        end_time=end,
        label=label,
        action="cut",
        reasoning="",
    )


# --- what must survive -------------------------------------------------------


def test_two_distinct_findings_seconds_apart_both_survive(analyzer):
    """The headline regression: 3s apart, same label, different sentences."""
    first = _v("you could quit your job by Christmas", 11.0, 13.5)
    second = _v("most people make six figures in year one", 14.5, 17.0)

    kept = analyzer._deduplicate_violations([[first, second]])

    assert [v.text for v in kept] == [first.text, second.text]


def test_two_findings_within_one_chunk_are_never_collapsed(analyzer):
    """
    A single chunk saw the audio once. If it reported two overlapping edits,
    that is the model's judgement, not an artifact of the sliding window - and
    the window is the only thing deduplication is entitled to undo.
    """
    kept = analyzer._deduplicate_violations(
        [
            [
                _v("quit your job by Christmas", 11.0, 14.0),
                _v("quit your job by Christmas", 11.0, 14.0),
            ]
        ]
    )

    assert len(kept) == 2


def test_overlapping_spans_with_unrelated_quotes_both_survive(analyzer):
    """Same label, overlapping time, different speech: two edits, not one."""
    kept = analyzer._deduplicate_violations(
        [
            [_v("you could quit your job", 11.0, 14.0)],
            [_v("send it to my personal address", 13.0, 16.0)],
        ]
    )

    assert len(kept) == 2


def test_a_different_label_at_the_same_time_survives(analyzer):
    kept = analyzer._deduplicate_violations(
        [
            [_v("quit your job by Christmas", 11.0, 14.0, label="Income Claim")],
            [_v("quit your job by Christmas", 11.0, 14.0, label="Guarantee")],
        ]
    )

    assert len(kept) == 2


def test_adjacent_edits_that_only_touch_are_two_edits(analyzer):
    """
    Abutting spans are the shape of two consecutive fillers, not one finding
    reported twice. "Starts within 5 seconds" swallowed the second of these.
    """
    kept = analyzer._deduplicate_violations(
        [
            [_v("um", 11.0, 12.0, label="Filler Word")],
            [_v("uh", 12.0, 13.0, label="Filler Word")],
        ]
    )

    assert len(kept) == 2


# --- what must collapse ------------------------------------------------------


def test_the_same_finding_from_two_chunks_collapses(analyzer):
    """The seam case deduplication exists for."""
    kept = analyzer._deduplicate_violations(
        [
            [_v("you could quit your job by Christmas", 11.0, 14.0)],
            [_v("You could quit your job by Christmas.", 11.0, 14.0)],
        ]
    )

    assert len(kept) == 1


def test_the_fuller_quote_wins(analyzer):
    """A chunk boundary can cut a sentence in half; the half is the worse quote."""
    kept = analyzer._deduplicate_violations(
        [
            [_v("quit your job", 11.0, 13.0)],
            [_v("you could quit your job by Christmas", 11.0, 14.0)],
        ]
    )

    assert [v.text for v in kept] == ["you could quit your job by Christmas"]


def test_a_clause_of_the_same_sentence_collapses_into_it(analyzer):
    """One chunk quoting a fragment of what the other quoted whole."""
    kept = analyzer._deduplicate_violations(
        [
            [
                _v(
                    "you could quit your job by Christmas if you follow the system",
                    11.0,
                    16.0,
                )
            ],
            [_v("quit your job by Christmas", 12.0, 14.0)],
        ]
    )

    assert len(kept) == 1


def test_a_lightly_reworded_repeat_collapses(analyzer):
    """Two chunks rarely quote a sentence identically."""
    kept = analyzer._deduplicate_violations(
        [
            [_v("you could quit your job by Christmas", 11.0, 14.0)],
            [_v("you could quit your job by Christmas easily", 11.2, 14.4)],
        ]
    )

    assert len(kept) == 1


def test_a_three_chunk_seam_leaves_one_copy(analyzer):
    quote = "you could quit your job by Christmas"
    kept = analyzer._deduplicate_violations(
        [
            [_v(quote, 11.0, 14.0)],
            [_v(quote, 11.0, 14.0)],
            [_v(quote, 11.0, 14.0)],
        ]
    )

    assert len(kept) == 1


def test_an_empty_analysis_is_handled(analyzer):
    assert analyzer._deduplicate_violations([]) == []
    assert analyzer._deduplicate_violations([[], []]) == []
