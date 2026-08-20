"""
The system prompts must ask for the shape `response_format` actually permits.

Both prompts once asked for a top-level JSON *array* while the API call pinned
`response_format={"type": "json_object"}`, which only permits an object. The
model resolved the contradiction by returning a single bare violation object,
and `_parse_llm_response` accepted that as one suggestion - so a transcript with
six blatant violations analyzed to exactly one, silently, every time.

That is the failure mode this module exists to prevent: a partial analysis that
is indistinguishable from a clean recording.
"""

import json
import re

import pytest

from app.analysis.prompt_analyzer import PRESETS, PromptAnalyzer


@pytest.fixture
def analyzer(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    return PromptAnalyzer()


def _prompts(analyzer):
    yield "prompt mode", analyzer._prompt_system_prompt("flag every income claim")
    for preset in PRESETS:
        yield f"preset {preset}", analyzer._preset_system_prompt(preset)


@pytest.mark.parametrize("mode", ["prompt", *PRESETS])
def test_prompt_asks_for_an_object_wrapping_a_list(analyzer, mode):
    """The documented response shape must be an object keyed by "violations"."""
    text = (
        analyzer._prompt_system_prompt("flag every income claim")
        if mode == "prompt"
        else analyzer._preset_system_prompt(mode)
    )

    blocks = re.findall(r"```json\s*(.+?)```", text, re.DOTALL)
    assert blocks, f"{mode}: no JSON example in the system prompt"

    for block in blocks:
        parsed = json.loads(block)
        assert isinstance(parsed, dict), (
            f"{mode}: the example response is a top-level {type(parsed).__name__}, but the "
            "API call pins response_format=json_object. The model cannot satisfy both."
        )
        assert isinstance(parsed.get("violations"), list), (
            f"{mode}: the example response has no \"violations\" array; "
            f"keys were {sorted(parsed)}"
        )


@pytest.mark.parametrize("mode", ["prompt", *PRESETS])
def test_prompt_does_not_ask_for_a_bare_array(analyzer, mode):
    """No leftover instruction telling the model to return an array or `[]`."""
    text = (
        analyzer._prompt_system_prompt("flag every income claim")
        if mode == "prompt"
        else analyzer._preset_system_prompt(mode)
    )
    lowered = text.lower()

    assert "json array" not in lowered, (
        f"{mode}: still asks for a 'JSON array' while response_format is json_object"
    )
    assert "return an empty array: []" not in lowered, (
        f"{mode}: still tells the model to return a bare [] for the empty case"
    )


@pytest.mark.parametrize("mode", ["prompt", *PRESETS])
def test_prompt_forbids_the_bare_single_object(analyzer, mode):
    """
    The one-violation case is where this broke, so it must be called out.

    `_parse_llm_response` still accepts a bare object defensively, but that path
    silently discards every violation after the first, so the prompt has to
    close it rather than relying on the parser to catch it.
    """
    text = (
        analyzer._prompt_system_prompt("flag every income claim")
        if mode == "prompt"
        else analyzer._preset_system_prompt(mode)
    )
    assert "bare object" in text.lower(), (
        f"{mode}: nothing tells the model that a lone finding is still an array of one"
    )
