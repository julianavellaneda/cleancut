"""
Tests for the model router.

`OpenAI()` and `model="gpt-4o"` used to be written into the analyzer at the
call site, so pointing the tool at a different vendor - or a different model
from the same vendor - meant editing analysis code. `CLEANCUT_MODEL` moves that
to one line of `.env`.

Two things here are worth more than the plumbing they test. A `provider:model`
spec is one string on purpose: a provider and a model that do not go together
is the misconfiguration worth making impossible, and one string cannot drift
out of sync with itself. And a refusal from the Anthropic path arrives as a
successful response with `stop_reason == "refusal"`, not an exception - a
provider that missed that would hand the analyzer an empty string, which reads
as "this section of the recording is clean".

No network: both SDK clients are stubbed.
"""

import pytest

from app.analysis.providers import (
    DEFAULT_MODEL_SPEC,
    AnthropicProvider,
    ProviderError,
    configured_model_spec,
    get_provider,
    parse_model_spec,
)

# --- the spec ---------------------------------------------------------------


def test_the_default_is_the_provider_the_tool_shipped_with():
    """Introducing the router must not change what an unconfigured checkout does."""
    assert DEFAULT_MODEL_SPEC == "openai:gpt-4o"


@pytest.mark.parametrize(
    "raw,provider,model",
    [
        ("openai:gpt-4o", "openai", "gpt-4o"),
        ("anthropic:claude-opus-5", "anthropic", "claude-opus-5"),
        ("  OpenAI : gpt-4o-mini  ", "openai", "gpt-4o-mini"),
    ],
)
def test_a_well_formed_spec_parses(raw, provider, model):
    spec = parse_model_spec(raw)

    assert (spec.provider, spec.model) == (provider, model)


def test_only_the_first_colon_splits():
    """Some model ids carry colons of their own; the provider is the prefix."""
    assert parse_model_spec("openai:ft:gpt-4o:acme").model == "ft:gpt-4o:acme"


@pytest.mark.parametrize(
    "raw", ["", "gpt-4o", "openai:", ":gpt-4o", "mistral:large", None]
)
def test_a_malformed_spec_names_what_was_expected(raw):
    """
    The error has to be readable by whoever edited `.env`, since that is the
    only place this value comes from.
    """
    with pytest.raises(ProviderError) as excinfo:
        parse_model_spec(raw)

    assert "provider:model" in str(excinfo.value)
    assert "anthropic" in str(excinfo.value)


def test_an_unset_variable_falls_back_to_the_default(monkeypatch):
    monkeypatch.delenv("CLEANCUT_MODEL", raising=False)

    assert str(configured_model_spec()) == DEFAULT_MODEL_SPEC


def test_the_variable_is_read_per_call_not_at_import(monkeypatch):
    """Otherwise a test - or a reload - could never change it."""
    monkeypatch.setenv("CLEANCUT_MODEL", "anthropic:claude-opus-5")
    assert configured_model_spec().provider == "anthropic"

    monkeypatch.setenv("CLEANCUT_MODEL", "openai:gpt-4o")
    assert configured_model_spec().provider == "openai"


# --- building the client ----------------------------------------------------


def test_the_missing_key_named_is_the_one_this_deployment_needs(monkeypatch):
    """
    An OpenAI key is no help to a machine configured for Anthropic, and the
    SDK's own "api_key must be set" would not say which one is meant.
    """
    monkeypatch.setenv("CLEANCUT_MODEL", "anthropic:claude-opus-5")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    with pytest.raises(ProviderError) as excinfo:
        get_provider()

    assert "ANTHROPIC_API_KEY" in str(excinfo.value)
    assert "OPENAI_API_KEY" not in str(excinfo.value)


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("openai:gpt-4o", "OpenAIProvider"),
        ("anthropic:claude-opus-5", "AnthropicProvider"),
        ("mock:demo", "MockProvider"),
    ],
)
def test_the_spec_picks_the_client(monkeypatch, spec, expected):
    monkeypatch.setenv("CLEANCUT_MODEL", spec)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    assert type(get_provider()).__name__ == expected


def test_a_real_provider_still_demands_its_key_beside_the_keyless_one(monkeypatch):
    """Adding a provider with no key must not open a path around the check."""
    monkeypatch.setenv("CLEANCUT_MODEL", "openai:gpt-4o")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ProviderError):
        get_provider()


def test_the_error_for_a_bad_spec_offers_the_keyless_option():
    """Whoever is stuck without a key is the reader most likely to see this."""
    with pytest.raises(ProviderError) as excinfo:
        parse_model_spec("gpt-4o")

    assert "mock:demo" in str(excinfo.value)


# --- the Anthropic path -----------------------------------------------------


class _Block:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _Response:
    def __init__(self, content, stop_reason="end_turn", category=None):
        self.content = content
        self.stop_reason = stop_reason
        self.stop_details = type("Details", (), {"category": category})()


@pytest.fixture
def anthropic_provider(monkeypatch):
    """An AnthropicProvider whose client returns a canned response."""

    def _build(response):
        calls = {}

        class StubMessages:
            def create(self, **kwargs):
                calls.update(kwargs)
                return response

        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.model = "claude-opus-5"
        provider._client = type(
            "C", (), {"beta": type("B", (), {"messages": StubMessages()})()}
        )()
        return provider, calls

    return _build


def test_the_answer_is_the_text_blocks(anthropic_provider):
    """
    Thinking blocks can precede the answer, so the first block is not assumed
    to be the one carrying the JSON.
    """
    provider, _ = anthropic_provider(
        _Response(
            [
                _Block("thinking", "reasoning that is not the answer"),
                _Block("text", '{"violations": '),
                _Block("text", "[]}"),
            ]
        )
    )

    assert provider.complete("system", "transcript") == '{"violations": []}'


def test_the_system_prompt_goes_in_its_own_field(anthropic_provider):
    """Not prepended to the transcript, where the model reads it as content."""
    provider, calls = anthropic_provider(_Response([_Block("text", "{}")]))

    provider.complete("you are a reviewer", "TRANSCRIPT")

    assert calls["system"] == "you are a reviewer"
    assert calls["messages"] == [{"role": "user", "content": "TRANSCRIPT"}]


def test_a_refusal_is_raised_rather_than_returned_empty(anthropic_provider):
    """
    The failure this guards. A refusal is an HTTP 200 with no text blocks, so
    returning the joined text would hand the analyzer "" - which parses as
    nothing found, and reads on the review screen as a clean recording.
    """
    provider, _ = anthropic_provider(
        _Response([], stop_reason="refusal", category="cyber")
    )

    with pytest.raises(ProviderError) as excinfo:
        provider.complete("system", "transcript")

    assert "declined" in str(excinfo.value)
    assert "cyber" in str(excinfo.value)


def test_fallbacks_are_asked_for(anthropic_provider):
    """
    A tool whose job is to quote the objectionable parts of a recording is
    exactly the shape of request a classifier stops on, so a decline is re-run
    on another model inside the same call rather than losing the chunk.
    """
    provider, calls = anthropic_provider(_Response([_Block("text", "{}")]))

    provider.complete("system", "transcript")

    assert calls["fallbacks"] == "default"
    assert calls["betas"] == ["server-side-fallback-2026-07-01"]
