"""
Tests for the preset registry and the cut/mute action a preset assigns.

The action a preset defaults to is load-bearing: the export route and the
worker's auto-apply path both partition on `Violation.action`, so a preset that
means "silence this" (pii-redaction) has to say so here or the audio gets
deleted instead of muted.

No LLM is involved - `_map_to_timestamps` is fed the raw dicts a model would
have returned.
"""

import pytest

from app.analysis.prompt_analyzer import (
    PRESETS,
    PromptAnalyzer,
    is_valid_preset,
    load_preset_rules,
)
from app.analysis.transcriber import Segment, TranscriptResult, Word


@pytest.fixture
def transcript():
    words = [
        Word(text="my", start=1.0, end=1.2, probability=0.9),
        Word(text="number", start=1.2, end=1.6, probability=0.9),
        Word(text="is", start=1.6, end=1.8, probability=0.9),
    ]
    return TranscriptResult(
        segments=[Segment(text="my number is", start=1.0, end=1.8, words=words)],
        language="en",
        duration=10.0,
    )


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    """PromptAnalyzer builds an OpenAI client eagerly; no call is ever made."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")


@pytest.fixture
def analyzer():
    return PromptAnalyzer()


def _raw(**overrides):
    base = {"text": "my number", "approximate_time": "1s", "reasoning": "because"}
    return [{**base, **overrides}]


def test_pii_preset_defaults_to_mute(analyzer, transcript):
    """The reason the worker cannot blanket-cut auto-applied suggestions."""
    [v] = analyzer._map_to_timestamps(
        _raw(rule_violated="Direct Identifiers"), transcript, preset="pii-redaction"
    )

    assert v.action == "mute"


def test_income_claims_preset_defaults_to_cut(analyzer, transcript):
    [v] = analyzer._map_to_timestamps(
        _raw(rule_violated="Income Claims"), transcript, preset="income-claims"
    )

    assert v.action == "cut"


def test_model_supplied_action_wins_over_the_preset_default(analyzer, transcript):
    [v] = analyzer._map_to_timestamps(
        _raw(rule_violated="Direct Identifiers", action="cut"),
        transcript, preset="pii-redaction",
    )

    assert v.action == "cut"


def test_preset_mode_maps_rule_violated_onto_the_label(analyzer, transcript):
    [v] = analyzer._map_to_timestamps(
        _raw(rule_violated="Credentials & Access", severity="high"),
        transcript, preset="pii-redaction",
    )

    assert v.label == "Credentials & Access"
    assert v.rule_violated == "Credentials & Access"
    assert v.severity == "high"


def test_preset_label_falls_back_to_the_preset_name(analyzer, transcript):
    """A model that returns neither rule_violated nor label still renders."""
    [v] = analyzer._map_to_timestamps(_raw(), transcript, preset="pii-redaction")

    assert v.label == PRESETS["pii-redaction"]["name"]


def test_prompt_mode_defaults_to_cut(analyzer, transcript):
    [v] = analyzer._map_to_timestamps(_raw(label="Filler Word"), transcript)

    assert v.action == "cut"
    assert v.label == "Filler Word"


def test_prompt_mode_honors_a_model_supplied_mute(analyzer, transcript):
    [v] = analyzer._map_to_timestamps(
        _raw(label="Phone Number", action="mute"), transcript
    )

    assert v.action == "mute"


def test_timestamps_are_mapped_to_word_level(analyzer, transcript):
    [v] = analyzer._map_to_timestamps(_raw(), transcript, preset="pii-redaction")

    assert v.start_time == pytest.approx(1.0)
    assert v.end_time == pytest.approx(1.6)


@pytest.mark.parametrize("preset_id", sorted(PRESETS))
def test_every_preset_is_well_formed(preset_id):
    meta = PRESETS[preset_id]

    assert meta["default_action"] in {"cut", "mute"}
    assert meta["name"] and meta["description"]
    assert load_preset_rules(preset_id).strip(), "rulebook file is empty or missing"


@pytest.mark.parametrize("preset_id", sorted(PRESETS))
def test_preset_system_prompt_embeds_its_own_categories(preset_id):
    """
    The JSON exemplar used to hardcode an income-claims category for every
    preset, which told the PII model to emit a category it had no rule for.
    """
    prompt = PromptAnalyzer()._preset_system_prompt(preset_id)
    meta = PRESETS[preset_id]

    assert meta["example_category"] in prompt
    assert meta["example_category"] in meta["categories"]
    assert load_preset_rules(preset_id).strip()[:40] in prompt


def test_is_valid_preset():
    assert is_valid_preset(None)          # prompt mode
    assert is_valid_preset("income-claims")
    assert not is_valid_preset("nope")


def test_analyze_rejects_an_unknown_preset(analyzer, transcript):
    with pytest.raises(ValueError, match="Unknown preset"):
        analyzer.analyze(transcript, preset="nope")
