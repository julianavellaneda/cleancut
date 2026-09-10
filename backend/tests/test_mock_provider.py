"""
Tests for the mock provider: CleanCut's app runnable with no API key.

What is pinned here is not "the mock returns something". It is the four
properties that make a demo provider safe to ship in a compliance tool:

- it needs no key, at the router and at preflight;
- its answer goes through the real parser and timestamp mapping untouched;
- its findings come from the transcript it was sent, land on the words that are
  actually there, and leave the demo clip's honest-disclaimer control alone;
- nobody can read one of its suggestions as a real analysis.

The demo clip's committed word-level transcript is the fixture, so these run
with no model, no media decode and no network.
"""

import json
from pathlib import Path

import pytest

from app.analysis.mock_provider import LABEL_PREFIX, REASONING_PREFIX, MockProvider
from app.analysis.prompt_analyzer import (
    PromptAnalyzer,
    _parse_llm_response,
    _wrap_transcript,
)
from app.analysis.providers import ProviderError, get_provider, parse_model_spec
from app.eval.run import load_word_transcript
from app.preflight import missing_requirements, model_notice

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_TRANSCRIPT = REPO_ROOT / "tests" / "fixtures" / "demo" / "transcript_words.json"

KEY_VARIABLES = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")


@pytest.fixture
def demo_transcript():
    return load_word_transcript(DEMO_TRANSCRIPT)


@pytest.fixture
def analyzer():
    return PromptAnalyzer(provider=MockProvider("demo"))


def _request(analyzer, transcript):
    return _wrap_transcript(analyzer._format_transcript_for_analysis(transcript))


# --- no key, anywhere -------------------------------------------------------


def test_the_router_builds_the_mock_with_no_key_set(monkeypatch):
    monkeypatch.setenv("CLEANCUT_MODEL", "mock:demo")
    for name in KEY_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    assert isinstance(get_provider(), MockProvider)


def test_the_mock_spec_names_no_key_variable():
    """None, not "": a keyless provider and a blank key name must differ."""
    assert parse_model_spec("mock:demo").api_key_name is None


def test_preflight_does_not_demand_a_key_for_the_mock():
    def everything_on_path(name):
        return f"/usr/bin/{name}"

    assert (
        missing_requirements({"CLEANCUT_MODEL": "mock:demo"}, everything_on_path) == []
    )


def test_startup_says_loudly_that_the_mock_is_answering():
    notice = model_notice({"CLEANCUT_MODEL": "mock:demo"})

    assert notice is not None
    assert "WARNING" in notice
    assert "MOCK" in notice


# --- the real parser accepts it ---------------------------------------------


def test_the_answer_survives_the_real_parser(analyzer, demo_transcript):
    """If this needed a side door past _validate_entries, the mock would be wrong."""
    content = analyzer.provider.complete(
        analyzer._prompt_system_prompt("flag every claim"),
        _request(analyzer, demo_transcript),
    )

    entries = _parse_llm_response(content)

    assert entries, "the demo clip contains claims; the mock found none"


def test_the_same_request_gets_the_same_answer(analyzer, demo_transcript):
    system = analyzer._prompt_system_prompt("flag every claim")
    request = _request(analyzer, demo_transcript)

    assert analyzer.provider.complete(system, request) == analyzer.provider.complete(
        system, request
    )


def test_a_request_with_no_transcript_fence_fails_rather_than_passing():
    """
    An empty list would read everywhere downstream as a clean recording, so a
    request shape the mock no longer recognises has to fail the chunk.
    """
    with pytest.raises(ProviderError):
        MockProvider("demo").complete("system", "TRANSCRIPT TO ANALYZE: hello")


def test_a_transcript_with_nothing_to_find_is_an_empty_list(analyzer):
    content = MockProvider("demo").complete(
        "system", _wrap_transcript("[0.0s - 2.0s] Thanks for listening.")
    )

    assert json.loads(content) == {"violations": []}


# --- both contracts, read off the real system prompts -----------------------


def test_prompt_mode_is_answered_with_label_and_action(analyzer, demo_transcript):
    content = analyzer.provider.complete(
        analyzer._prompt_system_prompt("flag every claim"),
        _request(analyzer, demo_transcript),
    )

    for entry in _parse_llm_response(content):
        assert {"label", "action"} <= entry.keys()
        assert "severity" not in entry


@pytest.mark.parametrize("preset", ["income-claims", "pii-redaction"])
def test_preset_mode_is_answered_with_rule_and_severity(
    analyzer, demo_transcript, preset
):
    """
    Built from the analyzer's own preset prompt, so a change to that prompt's
    wording breaks this test rather than silently flipping the demo's contract.
    """
    content = analyzer.provider.complete(
        analyzer._preset_system_prompt(preset), _request(analyzer, demo_transcript)
    )

    for entry in _parse_llm_response(content):
        assert {"rule_violated", "severity"} <= entry.keys()
        assert "label" not in entry


# --- transcript-derived, placed, and unmistakable ---------------------------


def test_every_suggestion_lands_on_the_words_it_quotes(analyzer, demo_transcript):
    """
    Quoting whole sentences verbatim is what lets the analyzer place them on
    word timings. An approximate span would be the mock's guess, not a mark on
    the waveform where the words are.
    """
    result = analyzer.analyze(demo_transcript, prompt="flag every claim")

    assert result.violations
    assert not result.is_partial
    for violation in result.violations:
        assert not violation.is_approximate, violation.text


def test_it_finds_what_the_demo_clip_plants(analyzer, demo_transcript):
    result = analyzer.analyze(demo_transcript, prompt="flag every claim")
    labels = {v.label for v in result.violations}

    assert labels == {
        LABEL_PREFIX + "Income Claim",
        LABEL_PREFIX + "Lifestyle Claim",
        LABEL_PREFIX + "Health Claim",
        LABEL_PREFIX + "Contact Details",
    }


def test_the_honest_disclaimer_is_never_flagged(analyzer, demo_transcript):
    """The eval fails any run that flags this control; the demo must not either."""
    result = analyzer.analyze(demo_transcript, prompt="flag every claim")

    assert not any("earn nothing" in v.text for v in result.violations)


def test_contact_details_are_muted_not_cut(analyzer, demo_transcript):
    result = analyzer.analyze(demo_transcript, prompt="flag every claim")
    contact = [v for v in result.violations if v.label.endswith("Contact Details")]

    assert contact
    assert {v.action for v in contact} == {"mute"}


@pytest.mark.parametrize("preset", [None, "income-claims", "pii-redaction"])
def test_no_suggestion_can_be_read_as_a_real_analysis(
    analyzer, demo_transcript, preset
):
    """
    The label is what the list, the waveform and the card all show, so the
    prefix is on it - not only in the reasoning, which is one panel deep.
    """
    result = analyzer.analyze(
        demo_transcript, prompt=None if preset else "flag every claim", preset=preset
    )

    assert result.violations
    for violation in result.violations:
        assert violation.label.startswith(LABEL_PREFIX)
        assert violation.reasoning.startswith(REASONING_PREFIX)
