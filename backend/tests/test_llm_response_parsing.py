"""
Tests for reading the model's response.

Regression: `_call_llm` caught `JSONDecodeError` and returned `[]`, making a
broken analysis indistinguishable from a clean recording. For a compliance
tool that is the worst possible failure mode - the reviewer sees "0 violations"
and ships the file.
"""

import json

import pytest

from app.analysis.prompt_analyzer import AnalysisError, _parse_llm_response


# --- genuinely empty results must stay empty, not raise -------------------

@pytest.mark.parametrize("content", [
    "[]",
    '{"violations": []}',
    '{"markers": []}',
    '{"edits": []}',
    "{}",
    '{"violations": null}',
])
def test_empty_results_parse_as_empty(content):
    assert _parse_llm_response(content) == []


# --- well-formed results ---------------------------------------------------

def test_bare_list():
    content = json.dumps([{"text": "a", "label": "Filler Word"}])

    assert _parse_llm_response(content) == [{"text": "a", "label": "Filler Word"}]


@pytest.mark.parametrize("key", ["violations", "markers", "edits"])
def test_recognized_wrapper_keys(key):
    """The model drifts between these three depending on prompt wording."""
    content = json.dumps({key: [{"text": "a"}, {"text": "b"}]})

    assert len(_parse_llm_response(content)) == 2


def test_single_suggestion_returned_unwrapped():
    content = json.dumps({"text": "I made $10,000", "label": "Income Claim"})

    assert _parse_llm_response(content) == [{"text": "I made $10,000", "label": "Income Claim"}]


def test_single_preset_suggestion_returned_unwrapped():
    content = json.dumps({"text": "I made $10,000", "rule_violated": "Income Claims"})

    assert len(_parse_llm_response(content)) == 1


def test_renamed_wrapper_key_is_still_accepted():
    """One unknown key holding a list is a synonym, not a reason to lose findings."""
    content = json.dumps({"results": [{"text": "a"}]})

    assert _parse_llm_response(content) == [{"text": "a"}]


# --- unreadable responses must raise, not return [] ------------------------

def test_invalid_json_raises():
    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response("I'm sorry, I can't help with that.")

    assert "not valid JSON" in str(excinfo.value)


def test_empty_response_raises():
    with pytest.raises(AnalysisError):
        _parse_llm_response("")


def test_none_response_raises():
    """A refusal comes back with `content=None`, not an empty string."""
    with pytest.raises(AnalysisError):
        _parse_llm_response(None)


def test_unrecognizable_object_raises():
    content = json.dumps({"summary": "no problems", "confidence": 0.9})

    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response(content)

    assert "no recognizable list" in str(excinfo.value)


def test_wrong_json_type_raises():
    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response('"just a string"')

    assert "expected a list" in str(excinfo.value)


def test_error_quotes_the_raw_response():
    """The point of failing loudly is being able to see what came back."""
    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response("<html>502 Bad Gateway</html>")

    assert "502 Bad Gateway" in str(excinfo.value)


def test_error_excerpt_is_truncated():
    """An error_message column is not a place to dump a whole transcript."""
    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response("x" * 5000)

    assert len(str(excinfo.value)) < 600
    assert "..." in str(excinfo.value)


# --- entries must be usable suggestions, not just valid JSON ---------------
#
# A list that parses is not a list that means anything. `{"summary": "none"}`
# inside a `violations` array used to become an empty-text Marker with action
# "cut", mapped onto the first segment of the transcript - and with auto_fix on,
# that segment was deleted. Anything unusable fails the chunk instead.

@pytest.mark.parametrize("item", ["a string", 42, None, True, ["nested"]])
def test_non_object_entry_raises(item):
    content = json.dumps({"violations": [item]})

    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response(content)

    assert "expected an object" in str(excinfo.value)


def test_entry_without_text_raises():
    """The exact case that became a destructive edit."""
    content = json.dumps({"violations": [{"summary": "none"}]})

    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response(content)

    assert "no quoted text" in str(excinfo.value)


@pytest.mark.parametrize("text", ["", "   ", None])
def test_entry_with_empty_text_raises(text):
    content = json.dumps({"violations": [{"text": text, "label": "Filler Word"}]})

    with pytest.raises(AnalysisError):
        _parse_llm_response(content)


def test_bare_list_entries_are_validated_too():
    with pytest.raises(AnalysisError):
        _parse_llm_response(json.dumps([{"label": "Filler Word"}]))


def test_renamed_wrapper_entries_are_validated_too():
    with pytest.raises(AnalysisError):
        _parse_llm_response(json.dumps({"results": [{"label": "Filler Word"}]}))


def test_unknown_action_raises():
    content = json.dumps([{"text": "a", "action": "delete_everything"}])

    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response(content)

    assert "unknown action" in str(excinfo.value)


def test_unknown_severity_raises():
    content = json.dumps([{"text": "a", "severity": "catastrophic"}])

    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response(content)

    assert "unknown severity" in str(excinfo.value)


@pytest.mark.parametrize("field,value", [
    ("text", 42),
    ("label", ["Filler Word"]),
    ("reasoning", {"why": "because"}),
    ("rule_violated", 7),
    ("approximate_time", 5.2),
])
def test_non_string_field_raises(field, value):
    content = json.dumps([{"text": "a", field: value}])

    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response(content)

    assert "non-string" in str(excinfo.value)


@pytest.mark.parametrize("action", ["cut", "mute", "CUT", " Mute "])
def test_valid_actions_are_accepted(action):
    content = json.dumps([{"text": "a", "action": action}])

    assert len(_parse_llm_response(content)) == 1


@pytest.mark.parametrize("severity", ["high", "medium", "low", "HIGH"])
def test_valid_severities_are_accepted(severity):
    content = json.dumps([{"text": "a", "severity": severity}])

    assert len(_parse_llm_response(content)) == 1


def test_null_optional_fields_are_accepted():
    """The models pad objects with nulls; that is not a malformed entry."""
    content = json.dumps([{
        "text": "a", "label": None, "action": None,
        "severity": None, "rule_violated": None, "reasoning": None,
    }])

    assert len(_parse_llm_response(content)) == 1


def test_error_names_the_offending_entry():
    content = json.dumps({"violations": [{"text": "a"}, {"text": "b"}, {"summary": "x"}]})

    with pytest.raises(AnalysisError) as excinfo:
        _parse_llm_response(content)

    assert "entry 3 of 3" in str(excinfo.value)
