"""
A provider that needs no key, for running the app without an account anywhere.

    CLEANCUT_MODEL=mock:demo

The tests and the detector eval already run with no API key; the *app* did not,
because every analysis ended at a vendor's endpoint. This closes that gap for a
reviewer who wants to see upload -> review -> export work before deciding
whether to hand CleanCut a key. The model half of the spec is accepted and
ignored.

Three rules shape it, and each exists because the obvious version is worse:

- **It answers like a model, not around one.** `complete` returns raw JSON text
  and nothing else. Parsing, validation and timestamp mapping run exactly as
  they do for OpenAI or Anthropic; a mock whose output needed a side door past
  `_validate_entries` would demo a pipeline that does not exist.
- **Its findings come from the transcript it is given.** A canned list would put
  suggestions on a recording that does not contain them, which is worse than
  nothing in a demo. It scans the fenced transcript for a small, ordered set of
  patterns and quotes the matching sentence back verbatim, so the quote lands on
  word timings and the waveform marks the words that are actually there.
- **It cannot be mistaken for an analysis.** Every label is prefixed ``Mock:``
  and every ``reasoning`` opens with ``MOCK PROVIDER``. The target market is
  compliance review; a demo that quietly looks like a real pass is a liability.

It ignores the editing instruction entirely - it is a keyword matcher, and its
reasoning says so rather than pretending otherwise.
"""

import json
import re
from dataclasses import dataclass

from .providers import ProviderError

LABEL_PREFIX = "Mock: "
REASONING_PREFIX = "MOCK PROVIDER"

# One `[12.3s - 15.0s] text` line of `_format_transcript_for_analysis`.
_LINE_RE = re.compile(r"^\[(\d+(?:\.\d+)?)s - \d+(?:\.\d+)?s\] ?(.*)$")
_TRANSCRIPT_RE = re.compile(r"<transcript>\n?(.*?)\n?</transcript>", re.DOTALL)
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class _Rule:
    label: str
    pattern: re.Pattern[str]
    action: str


# Ordered: a sentence is reported once, under the first rule it matches.
#
# "earn" is deliberately absent. The demo clip's control line is an honest
# earnings disclaimer ("some people try this and earn nothing at all"), and the
# eval fails any run that flags it - a demo provider should not be the thing
# that teaches a reviewer the tool cannot tell a claim from a disclaimer.
_RULES = (
    _Rule(
        "Income Claim",
        re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\bbrought home\b", re.IGNORECASE),
        "cut",
    ),
    _Rule(
        "Lifestyle Claim",
        re.compile(
            r"\bquit (?:my|your|his|her|their) job\b|\bsports car\b"
            r"|\bpaid for in cash\b|\bretired? early\b|\bluxury\b",
            re.IGNORECASE,
        ),
        "cut",
    ),
    _Rule(
        "Health Claim",
        re.compile(
            r"\bcure[sd]?\b|\bdisappeared\b|\bcleared (?:it|them) up\b|\bheal(?:ed|s)?\b",
            re.IGNORECASE,
        ),
        "cut",
    ),
    _Rule(
        "Contact Details",
        re.compile(
            r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
            r"|\b[\w.-]+ at [\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io)\b"
            r"|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",
            re.IGNORECASE,
        ),
        # Contact details are redacted in place, not removed.
        "mute",
    ),
)


def _transcript_lines(user_prompt: str) -> list[tuple[float, str]]:
    """``(start_seconds, text)`` for every line of the fenced transcript."""
    fence = _TRANSCRIPT_RE.search(user_prompt)
    if fence is None:
        # Never `{"violations": []}`: an empty answer reads everywhere
        # downstream as a clean recording, so a prompt shape this module no
        # longer recognises has to fail the chunk loudly instead.
        raise ProviderError(
            "The mock provider found no <transcript> block in the request, so it "
            "has nothing to scan. The analyzer's request format has changed."
        )
    lines = []
    for raw in fence.group(1).splitlines():
        match = _LINE_RE.match(raw.strip())
        if match:
            lines.append((float(match.group(1)), match.group(2)))
    return lines


class MockProvider:
    """Keyword matches over the transcript, answered in the analyzer's JSON contract."""

    def __init__(self, model: str):
        self.model = model

    def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        # Which contract to answer in is read off the request, the way a model
        # reads it: the preset prompt asks for `rule_violated` and `severity`,
        # the prompt-mode one for `label` and `action`. Answering the wrong one
        # would still parse, and put a severity on a free-form suggestion.
        preset_contract = '"rule_violated"' in system_prompt

        findings: list[dict[str, str]] = []
        for start, text in _transcript_lines(user_prompt):
            for sentence in _SENTENCE_BREAK_RE.split(text.strip()):
                finding = self._match(sentence, start, preset_contract)
                if finding is not None:
                    findings.append(finding)

        return json.dumps({"violations": findings})

    @staticmethod
    def _match(
        sentence: str, start: float, preset_contract: bool
    ) -> dict[str, str] | None:
        for rule in _RULES:
            hit = rule.pattern.search(sentence)
            if hit is None:
                continue
            finding = {
                # The whole sentence, verbatim: a substring of the segment, so
                # the analyzer places it on word timings rather than guessing.
                "text": sentence,
                "approximate_time": f"{start:.1f}s",
                "reasoning": (
                    f"{REASONING_PREFIX} - matched the keyword pattern "
                    f"{hit.group(0)!r}. No model read this transcript and your "
                    "instruction was not consulted; set CLEANCUT_MODEL to a real "
                    "provider for an analysis."
                ),
            }
            if preset_contract:
                finding["rule_violated"] = LABEL_PREFIX + rule.label
                finding["severity"] = "medium"
            else:
                finding["label"] = LABEL_PREFIX + rule.label
                finding["action"] = rule.action
            return finding
        return None
