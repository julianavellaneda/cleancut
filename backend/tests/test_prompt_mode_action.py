"""
Tests for the cut/mute default in prompt mode.

Preset mode inherits a default_action from its rulebook (see
test_preset_actions.py). Prompt mode had no equivalent, so the model picked per
suggestion and the same sentence came back "cut" on one run and "mute" on the
next. The instruction is the only stated intent prompt mode has, so it decides.

No LLM is involved - `_map_to_timestamps` is fed the raw dicts a model would
have returned.
"""

import pytest

from app.analysis.prompt_analyzer import PromptAnalyzer, _prompt_default_action
from app.analysis.transcriber import Segment, TranscriptResult, Word


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")


@pytest.fixture
def analyzer():
    return PromptAnalyzer()


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


def _raw(**overrides):
    base = {"text": "my number", "approximate_time": "1s", "reasoning": "because"}
    return [{**base, **overrides}]


# --- the derivation itself -------------------------------------------------


@pytest.mark.parametrize(
    "instruction",
    [
        None,
        "",
        "flag every income claim",
        "find the filler words",
        "remove anything off-topic",
    ],
)
def test_ordinary_instructions_default_to_cut(instruction):
    assert _prompt_default_action(instruction) == "cut"


@pytest.mark.parametrize(
    "instruction",
    [
        "redact any personal information",
        "bleep the profanity",
        "silence anything sensitive",
        "censor the account numbers",
        "anonymize every name you hear",
        "Mute any PII",
    ],
)
def test_redaction_instructions_default_to_mute(instruction):
    assert _prompt_default_action(instruction) == "mute"


def test_a_mixed_instruction_defaults_to_cut():
    """
    "cut the filler and bleep the phone numbers" names both edits. The default
    covers the common case; the system prompt asks the model to mark the
    individual redactions, and a model-supplied action always wins.
    """
    assert (
        _prompt_default_action("cut the filler words and bleep the phone numbers")
        == "cut"
    )


def test_the_derivation_is_case_insensitive():
    assert _prompt_default_action("REDACT THE CARD NUMBERS") == "mute"


# --- how it reaches a Violation --------------------------------------------


def test_prompt_mode_falls_back_to_the_instruction_derived_default(
    analyzer, transcript
):
    [v] = analyzer._map_to_timestamps(
        _raw(label="Phone Number"), transcript, prompt="redact any personal information"
    )

    assert v.action == "mute"


def test_prompt_mode_defaults_to_cut_for_a_non_redaction_instruction(
    analyzer, transcript
):
    [v] = analyzer._map_to_timestamps(
        _raw(label="Income Claim"), transcript, prompt="flag every income claim"
    )

    assert v.action == "cut"


def test_a_model_supplied_action_still_wins(analyzer, transcript):
    """Per-item nuance survives; the default only fills a gap."""
    [v] = analyzer._map_to_timestamps(
        _raw(label="Phone Number", action="mute"),
        transcript,
        prompt="cut every mistake and mute the phone numbers",
    )

    assert v.action == "mute"


def test_no_instruction_at_all_still_yields_cut(analyzer, transcript):
    [v] = analyzer._map_to_timestamps(_raw(label="Marker"), transcript)

    assert v.action == "cut"


def test_the_instruction_does_not_override_a_presets_default(analyzer, transcript):
    """Preset mode has its own rulebook default and must ignore the prompt."""
    [v] = analyzer._map_to_timestamps(
        _raw(rule_violated="Direct Identifiers"),
        transcript,
        preset="pii-redaction",
        prompt="cut everything you find",
    )

    assert v.action == "mute"


def test_the_prompt_mode_system_prompt_states_the_rule(analyzer):
    """
    The default is only half the fix - the model has to be told the basis for
    its own choice, or it keeps picking freely and the default never applies.
    """
    system_prompt = analyzer._prompt_system_prompt("flag every income claim")

    assert 'The default is "cut"' in system_prompt
    assert 'Use "mute" ONLY when' in system_prompt
