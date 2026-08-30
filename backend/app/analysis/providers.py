"""
Which model answers the analysis, and how to reach it.

The analyzer used to construct `OpenAI()` and hardcode `gpt-4o` at the call
site, so trying a different vendor - or a different model from the same vendor -
meant editing the analyzer. This module is the seam: one env var names the
model, one function returns something that can be asked a question.

    CLEANCUT_MODEL=openai:gpt-4o            # the default; unchanged behaviour
    CLEANCUT_MODEL=anthropic:claude-opus-5

The `provider:model` spec is deliberately a single string rather than a pair of
variables: a provider and a model that do not go together is the failure mode
worth making impossible to configure, and one string cannot drift out of sync
with itself. Each provider names its own key variable, so a machine can hold
credentials for several and switch between them with one edit.

Providers return the model's raw text. Parsing, validation and the JSON contract
stay in `prompt_analyzer` - they are the same for every vendor, and a provider
that started interpreting answers would be a second place for that contract to
live.
"""

import os
from dataclasses import dataclass

# The provider a fresh checkout uses, so nothing about the default path changes
# when this module is introduced.
DEFAULT_MODEL_SPEC = "openai:gpt-4o"

# What each provider expects its credentials to be called. Preflight reads this
# to check the configured provider's key rather than assuming OpenAI's.
PROVIDER_API_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


class ProviderError(RuntimeError):
    """The configured model cannot be reached, or is not configured at all."""


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def api_key_name(self) -> str:
        return PROVIDER_API_KEYS[self.provider]


def parse_model_spec(spec: str) -> ModelSpec:
    """
    Read a ``provider:model`` string, or say precisely what is wrong with it.

    Model ids contain colons on some platforms, so only the first one splits.
    """
    provider, sep, model = (spec or "").partition(":")
    provider, model = provider.strip().lower(), model.strip()
    if not sep or not model or provider not in PROVIDER_API_KEYS:
        raise ProviderError(
            f"Invalid CLEANCUT_MODEL {spec!r}. Expected 'provider:model' with provider "
            f"one of {', '.join(sorted(PROVIDER_API_KEYS))} - for example "
            f"'{DEFAULT_MODEL_SPEC}' or 'anthropic:claude-opus-5'."
        )
    return ModelSpec(provider=provider, model=model)


def configured_model_spec() -> ModelSpec:
    """The model this deployment is set up to use. Read per call, not cached."""
    return parse_model_spec(os.getenv("CLEANCUT_MODEL") or DEFAULT_MODEL_SPEC)


class OpenAIProvider:
    """
    Chat completions with a JSON response format.

    `temperature=0.1` rather than 0: the same transcript should give the same
    answer twice, and this is as close to that as the endpoint offers.
    """

    def __init__(self, model: str):
        from openai import OpenAI

        self.model = model
        self._client = OpenAI()  # Reads OPENAI_API_KEY.

    def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        return response.choices[0].message.content


class AnthropicProvider:
    """
    The Messages API, with the system prompt in its own field.

    Two details that are not interchangeable with the OpenAI path:

    - There is no `response_format`. The system prompts already spell out the
      JSON contract in detail, and `_parse_llm_response` already copes with a
      fenced or chatty answer, so the contract is carried by the prompt rather
      than by a schema. A `json_schema` output format would have to be written
      twice anyway - prompt mode returns label/action, preset mode returns
      rule_violated/severity.
    - A refusal is an HTTP 200 with `stop_reason == "refusal"`, not an
      exception. Server-side fallbacks are enabled so a decline is re-run on
      another model inside the same call; a chain that refuses outright is
      raised as a `ProviderError`, which the analyzer already treats as a failed
      chunk - the job completes with a partial-analysis warning naming the
      spans nobody looked at. This matters more here than in most applications:
      the tool's whole job is to quote the objectionable parts of a recording,
      which is exactly the shape of request a safety classifier stops to think
      about.
    """

    # Enough room for a long list of findings on a dense chunk; the analyzer
    # sends ~50 transcript segments at a time.
    MAX_TOKENS = 16000

    def __init__(self, model: str):
        import anthropic

        self.model = model
        self._client = anthropic.Anthropic()  # Reads ANTHROPIC_API_KEY.

    def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        response = self._client.beta.messages.create(
            model=self.model,
            max_tokens=self.MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        if response.stop_reason == "refusal":
            detail = getattr(response.stop_details, "category", None) or "unspecified"
            raise ProviderError(
                f"{self.model} declined to analyze this section of the transcript "
                f"({detail}), and so did the fallback model."
            )

        # Thinking blocks can precede the answer, so the text blocks are picked
        # out rather than the first block being assumed to be one.
        return "".join(block.text for block in response.content if block.type == "text")


_PROVIDERS = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def get_provider(spec: ModelSpec | None = None):
    """
    Build the client for the configured model.

    The missing-key check is here rather than left to the SDK so the error names
    the variable this deployment actually needs - an OpenAI key is no help to a
    machine configured for Anthropic, and the SDK's own message would not say so.
    """
    spec = spec or configured_model_spec()
    if not os.getenv(spec.api_key_name):
        raise ProviderError(
            f"{spec.api_key_name} is not set, and CLEANCUT_MODEL is '{spec}'."
        )
    try:
        return _PROVIDERS[spec.provider](spec.model)
    except ImportError as e:
        raise ProviderError(
            f"The {spec.provider} client library is not installed: {e}"
        ) from e
