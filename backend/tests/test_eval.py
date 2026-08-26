"""
Tests for the eval harness.

The gap these close: the demo fixture has carried ground truth since it was
generated - every line's measured offset, plus a written table of what was
planted where - and nothing ever read it back. "The analyzer looks accurate" was
an impression, and a regression in the detectors would have shown up as a
slightly worse demo rather than as a failing build.

So the recorded demo run is scored here against the labels on every test run.
No media, no model, no API key: `seed_job.json` is a snapshot of one real
completed pipeline run, and grading it is arithmetic. The live path
(`--live`, which transcribes and calls the LLM) is the one that measures the
detectors as they stand today, and it stays out of the suite because it costs
money and cannot be deterministic.

Two things are asserted beyond the aggregate numbers. The control lines - an
honest earnings disclaimer sitting between two income claims, and a neutral
follow-up question - must not be flagged; they are the fixture's test for
whether the analyzer is reading sentences or matching on the neighbourhood. And
the categories a free-form label maps to are checked directly, because a scorer
that silently classifies nothing reports a perfect precision on zero graded
suggestions.
"""

import json
from pathlib import Path

import pytest

from app.eval.run import as_dict, format_report, main
from app.eval.scoring import (
    MIN_COVERAGE,
    Prediction,
    load_predictions,
    score,
)
from app.eval.spec import (
    Control,
    EvalSpec,
    Expectation,
    SpecError,
    Suite,
    load_spec,
)

DEMO_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "demo"
SEED_JOB = DEMO_DIR / "seed_job.json"
LABELS = DEMO_DIR / "eval_labels.json"


# --------------------------------------------------------------------------
# The spec: authored labels joined onto generated offsets
# --------------------------------------------------------------------------

def _labels(**overrides) -> dict:
    base = {
        "timings_from": "timings.json",
        "categories": {"claim": {"label_patterns": ["claim"]}},
        "suites": {"only": {"description": "", "categories": ["claim"]}},
        "expectations": [{"id": "a", "category": "claim", "match": "span", "line": 0}],
        "controls": [],
    }
    base.update(overrides)
    return base


def _write_spec(tmp_path: Path, labels: dict) -> Path:
    (tmp_path / "timings.json").write_text(json.dumps({
        "lines": [{"start": 0.0, "end": 5.0}, {"start": 5.0, "end": 10.0}],
        "pauses": [{"start": 10.0, "end": 12.0}],
    }))
    path = tmp_path / "eval_labels.json"
    path.write_text(json.dumps(labels))
    return path


def test_labels_take_their_timing_from_the_generated_file(tmp_path):
    """
    The two files are separate so a re-render moves the offsets without
    touching the judgements. The join is what makes that work.
    """
    spec = load_spec(_write_spec(tmp_path, _labels()))
    assert (spec.expectations[0].start, spec.expectations[0].end) == (0.0, 5.0)


def test_a_pause_expectation_resolves_against_the_pause_list(tmp_path):
    spec = load_spec(_write_spec(tmp_path, _labels(
        expectations=[{"id": "gap", "category": "claim", "match": "span", "pause": 0}],
    )))
    assert (spec.expectations[0].start, spec.expectations[0].end) == (10.0, 12.0)


@pytest.mark.parametrize("broken, message", [
    ({"id": "a", "category": "nope", "match": "span", "line": 0}, "unknown category"),
    ({"id": "a", "category": "claim", "match": "vibes", "line": 0}, "unknown match mode"),
    ({"id": "a", "category": "claim", "match": "token", "line": 0}, "no text"),
    ({"id": "a", "category": "claim", "match": "span", "line": 99}, "does not have"),
    ({"id": "a", "category": "claim", "match": "span"}, "neither a line nor a pause"),
])
def test_an_unusable_label_is_an_error_not_a_skipped_row(tmp_path, broken, message):
    """
    A label the loader cannot resolve has to stop the run. Dropping it quietly
    would shrink the denominator, and a smaller denominator reads as better
    recall - the one failure mode an eval must never have.
    """
    with pytest.raises(SpecError, match=message):
        load_spec(_write_spec(tmp_path, _labels(expectations=[broken])))


def test_duplicate_expectation_ids_are_rejected(tmp_path):
    row = {"id": "a", "category": "claim", "match": "span", "line": 0}
    with pytest.raises(SpecError, match="Duplicate"):
        load_spec(_write_spec(tmp_path, _labels(expectations=[row, dict(row)])))


def test_a_suite_naming_an_unknown_category_is_rejected(tmp_path):
    with pytest.raises(SpecError, match="unknown categories"):
        load_spec(_write_spec(tmp_path, _labels(
            suites={"only": {"description": "", "categories": ["ghost"]}},
        )))


def test_unknown_suite_lists_the_ones_that_exist(tmp_path):
    spec = load_spec(_write_spec(tmp_path, _labels()))
    with pytest.raises(SpecError, match="Available: only"):
        spec.suite("missing")


# --------------------------------------------------------------------------
# Matching: free-form labels, loose spans
# --------------------------------------------------------------------------

def _spec(**kwargs) -> EvalSpec:
    return EvalSpec(
        expectations=tuple(kwargs.get("expectations", ())),
        controls=tuple(kwargs.get("controls", ())),
        suites={},
        label_patterns=kwargs.get("label_patterns", {"claim": ("income", "claim")}),
    )


def _suite(*categories: str) -> Suite:
    return Suite(id="t", description="", categories=categories)


CLAIM = Expectation(id="claim-1", category="claim", match="span", start=10.0, end=20.0)


def test_a_label_is_matched_on_substrings_not_on_an_id():
    """
    Prompt mode lets the model name its own labels. "Income Claim" and
    "Specific income figure" are the same finding, and neither is an id anyone
    handed the model.
    """
    spec = _spec()
    assert spec.categories_for_label("Specific income figure") == ("claim",)
    assert spec.categories_for_label("Filler Word") == ()
    assert spec.categories_for_label(None) == ()


def test_a_tighter_span_inside_the_label_still_counts():
    """
    Quoting one clause of a labelled line is the *better* answer for an editor -
    it cuts less. Measuring coverage against the shorter span is what stops the
    scorer punishing it; IoU would score this at 0.2.
    """
    card = score(_spec(expectations=[CLAIM]), _suite("claim"),
                 [Prediction("...", 14.0, 16.0, "Income Claim")])
    assert len(card.hits) == 1
    assert card.recall == 1.0


def test_a_span_that_barely_grazes_the_label_does_not_count():
    card = score(_spec(expectations=[CLAIM]), _suite("claim"),
                 [Prediction("...", 19.0, 30.0, "Income Claim")])
    assert card.hits == ()
    assert card.false_positives == (0,)
    assert MIN_COVERAGE == 0.5


def test_a_second_suggestion_on_the_same_label_is_a_duplicate_not_a_false_positive():
    """
    A model splitting one claim across two sentences found the claim twice. It
    should not cost precision, and it should not earn recall either.
    """
    card = score(_spec(expectations=[CLAIM]), _suite("claim"), [
        Prediction("first half", 10.0, 15.0, "Income Claim"),
        Prediction("second half", 15.0, 20.0, "Income Claim"),
    ])
    assert len(card.hits) == 1
    assert card.duplicates == ((1, "claim-1"),)
    assert card.precision == 1.0
    assert card.recall == 1.0


def test_a_filler_is_matched_by_the_word_not_by_the_window():
    """
    Word timestamps drift against the generator's line offsets, so a filler
    cannot be graded on overlap. It is graded on being the right word, near
    enough to the right line.
    """
    um = Expectation(id="um", category="filler", match="token", start=0.0, end=5.0, text="um")
    spec = _spec(expectations=[um], label_patterns={"filler": ("filler",)})
    card = score(spec, _suite("filler"), [Prediction("um,", 4.6, 4.9, "Filler Word")])
    assert len(card.hits) == 1


def test_a_filler_from_the_next_line_over_does_not_count():
    um = Expectation(id="um", category="filler", match="token", start=0.0, end=5.0, text="um")
    spec = _spec(expectations=[um], label_patterns={"filler": ("filler",)})
    card = score(spec, _suite("filler"), [Prediction("um,", 30.0, 30.4, "Filler Word")])
    assert card.hits == ()
    assert [e.id for e in card.misses] == ["um"]


def test_one_merged_suggestion_can_answer_two_filler_labels():
    """
    The scrubber merges fillers less than 0.5s apart into a single suggestion.
    That is one edit covering two planted words, and it found both.
    """
    spec = _spec(
        expectations=[
            Expectation("um", "filler", "token", 0.0, 5.0, text="um"),
            Expectation("you-know", "filler", "token", 0.0, 5.0, text="you know"),
        ],
        label_patterns={"filler": ("filler",)},
    )
    card = score(spec, _suite("filler"), [Prediction("um, you know", 1.0, 2.2, "Filler Word")])
    assert {h.expectation_id for h in card.hits} == {"um", "you-know"}
    assert card.recall == 1.0


def test_a_finding_the_suite_did_not_ask_for_is_set_aside_not_penalized():
    """
    A run told to find income claims should not lose precision for also
    noticing an email address. It is a real finding against a real label; it is
    just not what this suite is measuring.
    """
    spec = _spec(
        expectations=[
            CLAIM,
            Expectation("email-1", "email", "span", 60.0, 70.0),
        ],
        label_patterns={"claim": ("claim",), "email": ("email",)},
    )
    card = score(spec, _suite("claim"), [
        Prediction("...", 10.0, 20.0, "Income Claim"),
        Prediction("...", 60.0, 70.0, "Email Address"),
    ])
    assert card.out_of_scope == ((1, "email-1"),)
    assert card.counted == 1
    assert card.precision == 1.0
    assert card.false_positives == ()


def test_flagging_a_control_is_a_false_positive_and_is_named():
    """
    The controls are the fixture's real assertion. An honest disclaimer sitting
    next to two income claims is exactly what a keyword matcher trips on, so
    flagging it does not just cost precision - it says the analyzer stopped
    reading.
    """
    control = Control(id="disclaimer", start=54.0, end=60.0, reason="honest disclaimer")
    card = score(_spec(expectations=[CLAIM], controls=[control]), _suite("claim"),
                 [Prediction("some people earn nothing", 54.5, 59.5, "Income Claim")])
    assert [c.id for _, c in card.control_hits] == ["disclaimer"]
    assert card.false_positives == (0,)


def test_a_run_that_finds_nothing_scores_zero_rather_than_dividing_by_zero():
    card = score(_spec(expectations=[CLAIM]), _suite("claim"), [])
    assert (card.precision, card.recall, card.f1) == (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------
# Reading a run
# --------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {"violations": [{"text": "x", "start_time": 1.0, "end_time": 2.0, "label": "L"}]},
    [{"text": "x", "start_time": 1.0, "end_time": 2.0, "label": "L"}],
])
def test_both_saved_shapes_read_the_same(payload):
    """The seeded job wraps its list; the API returns a bare one. Same fields."""
    assert load_predictions(payload) == [Prediction("x", 1.0, 2.0, "L")]


def test_a_malformed_run_is_an_error():
    with pytest.raises(ValueError):
        load_predictions({"violations": ["not an object"]})


# --------------------------------------------------------------------------
# The recorded demo run, scored against the fixture
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def demo_card():
    spec = load_spec(LABELS)
    suite = spec.suite("claims-and-scrub")
    return spec, suite, score(spec, suite, load_predictions(SEED_JOB))


def test_every_suggestion_in_the_recorded_run_is_classifiable(demo_card):
    """
    Guards the scorer's own blind spot: if no label matched any category, every
    suggestion would fall through to "out of scope", the denominator would be
    zero, and the run would report a flawless 100% precision on nothing.
    """
    spec, _, card = demo_card
    unclassified = [
        p.label for p in card.predictions if not spec.categories_for_label(p.label)
    ]
    assert unclassified == []
    assert card.counted == len(card.predictions)


def test_the_recorded_run_clears_the_floors(demo_card):
    """
    Floors, not exact numbers. The point is to catch a real regression in the
    detectors or in the matching rules, not to freeze one snapshot to three
    decimal places. The recorded run scores 1.00 / 0.80.
    """
    _, _, card = demo_card
    assert card.precision >= 0.95
    assert card.recall >= 0.75


def test_the_controls_survive_the_recorded_run(demo_card):
    _, _, card = demo_card
    assert card.control_hits == ()
    assert card.false_positives == ()


def test_every_claim_and_every_planted_pause_was_found(demo_card):
    """
    The categories the tool is actually sold on. Filler recall is allowed to be
    partial below; a missed income claim is not.
    """
    _, _, card = demo_card
    per_category = card.per_category
    for category in ("income-claim", "lifestyle-claim", "health-claim", "dead-air"):
        found, expected = per_category[category]
        assert found == expected, f"{category}: {found}/{expected}"


def test_the_recorded_run_misses_exactly_the_three_known_fillers(demo_card):
    """
    Not a target - a record of what the harness found the moment it existed,
    and all three are the scrubber's doing rather than bad luck:

    - "you know" is two words. `detect_filler_words` matches word by word
      against `FILLER_WORDS`, so a multi-word entry in that set can never fire.
    - "hm" is in the set; Whisper transcribes the sound as "Hmm", which is not.
    - "Er," was dropped from the transcript altogether.

    If someone fixes the first two, this assertion is what tells them to
    re-record `seed_job.json` rather than leaving a stale snapshot behind.
    """
    _, _, card = demo_card
    assert sorted(e.id for e in card.misses) == [
        "filler-er-1", "filler-hm-1", "filler-you-know-1",
    ]


def test_the_silent_line_is_excluded_rather_than_counted_as_a_miss(demo_card):
    """
    Line 9's text-to-speech call came back with 0.3s of silence and the
    generator recorded that as the line's duration, so the spoken phone number
    is not in the clip. Scoring it would report a miss no detector could have
    avoided, which is worse than no measurement at all.
    """
    spec, suite, card = demo_card
    absent = {e.id for e in spec.expectations if not e.present}
    assert "phone-number-1" in absent
    assert absent.isdisjoint({e.id for e in card.scorable})
    assert absent.isdisjoint({e.id for e in card.misses})
    assert all(spec.expectations[i].note for i in range(len(spec.expectations))
               if not spec.expectations[i].present)


def test_the_pii_suite_grades_a_different_set_of_labels():
    """
    Recall is only meaningful per suite: the demo prompt never asked for contact
    details, so the email address belongs to the preset's suite and not to it.
    """
    spec = load_spec(LABELS)
    claims = spec.scorable(spec.suite("claims-and-scrub"))
    pii = spec.scorable(spec.suite("pii-redaction"))
    assert {e.id for e in pii} == {"email-address-1"}
    assert {e.id for e in claims}.isdisjoint({e.id for e in pii})


# --------------------------------------------------------------------------
# The CLI
# --------------------------------------------------------------------------

def test_the_report_names_what_was_missed_and_what_was_excluded(demo_card):
    spec, suite, card = demo_card
    report = format_report(spec, suite, card)
    assert "filler-er-1" in report
    assert "Excluded from scoring" in report
    # The excluded fillers are listed; the phone number belongs to the other
    # suite, so it is named only as the reason they are gone.
    assert "~ filler-uh-2" in report
    assert "~ phone-number-1" not in report


def test_the_cli_scores_a_saved_run(capsys):
    assert main(["--suite", "claims-and-scrub", str(SEED_JOB), "--labels", str(LABELS)]) == 0
    assert "precision" in capsys.readouterr().out


def test_the_cli_fails_the_run_when_a_floor_is_not_met(capsys):
    """The hook CI hangs a regression on: a threshold miss is a non-zero exit."""
    code = main([
        "--suite", "claims-and-scrub", str(SEED_JOB), "--labels", str(LABELS),
        "--min-recall", "0.99",
    ])
    capsys.readouterr()
    assert code == 1


def test_the_cli_emits_json_for_a_machine(capsys):
    main(["--suite", "claims-and-scrub", str(SEED_JOB), "--labels", str(LABELS), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["suite"] == "claims-and-scrub"
    assert payload["per_category"]["dead-air"] == {"found": 3, "expected": 3}


def test_the_cli_refuses_a_saved_run_and_a_live_one_at_once():
    with pytest.raises(SystemExit):
        main([str(SEED_JOB), "--live", str(DEMO_DIR / "demo_seminar.mp3")])


def test_as_dict_round_trips_through_json(demo_card):
    _, _, card = demo_card
    assert json.loads(json.dumps(as_dict(card)))["recall"] == card.recall
