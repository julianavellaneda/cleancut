"""
The labelled ground truth for an eval clip.

Two files make one spec, and they are separate on purpose:

- ``expected_violations.json`` is *generated*. ``scripts/generate_demo_audio.py``
  writes it with the offsets it measured while rendering, and overwrites it on
  every re-render. Nothing hand-written survives in there.
- ``eval_labels.json`` is *authored*. It says what each line is and whether a
  detector should flag it, and refers to lines and pauses by index.

Joining them here keeps the judgement stable across a re-render while the timing
follows whatever the clip actually turned out to be.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Repo root -> tests/fixtures/demo. Two parents up from app/eval/ is `backend/`.
DEMO_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "demo"


class SpecError(ValueError):
    """The labels and the measured offsets do not line up."""


@dataclass(frozen=True)
class Expectation:
    """One thing a detector is supposed to find."""

    id: str
    category: str
    # "span"  - judged by how much of the prediction lands inside this window.
    # "token" - judged by the word itself; the window only has to contain it.
    match: str
    start: float
    end: float
    text: str | None = None
    quote: str | None = None
    # False when the clip does not actually contain this, despite the script
    # calling for it. Excluded from scoring rather than deleted: the reason it
    # is missing is worth keeping next to the label.
    present: bool = True
    note: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class Control:
    """A span that must *not* be flagged. A hit here is a false positive that matters."""

    id: str
    start: float
    end: float
    reason: str


@dataclass(frozen=True)
class Suite:
    """
    One way of running the tool, and the categories it is fair to grade it on.

    Recall is meaningless without this. A run driven by "find income claims"
    should not be marked down for missing an email address nobody asked it for,
    so a prediction landing on an out-of-scope expectation is set aside rather
    than counted either way.
    """

    id: str
    description: str
    categories: tuple[str, ...]
    prompt: str | None = None
    preset: str | None = None


@dataclass(frozen=True)
class EvalSpec:
    expectations: tuple[Expectation, ...]
    controls: tuple[Control, ...]
    suites: dict[str, Suite]
    # category id -> lowercase substrings that identify it in a prediction's label.
    label_patterns: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def suite(self, suite_id: str) -> Suite:
        try:
            return self.suites[suite_id]
        except KeyError:
            known = ", ".join(sorted(self.suites)) or "none"
            raise SpecError(f"Unknown suite '{suite_id}'. Available: {known}") from None

    def scorable(self, suite: Suite) -> tuple[Expectation, ...]:
        """In-scope expectations the clip actually contains."""
        return tuple(
            e for e in self.expectations
            if e.present and e.category in suite.categories
        )

    def categories_for_label(self, label: str | None) -> tuple[str, ...]:
        """
        Which categories a free-form label could plausibly be.

        Prompt mode lets the model name its own labels, so there is no id to key
        on - "Income Claim", "Income/Earnings claim" and "Specific income figure"
        are all the same finding. Matching on declared substrings keeps that
        judgement in the labels file, where it can be argued with, instead of
        hard-coded in the scorer.
        """
        text = (label or "").strip().lower()
        if not text:
            return ()
        return tuple(
            category
            for category, patterns in self.label_patterns.items()
            if any(p in text for p in patterns)
        )


def _window(entry: dict, lines: list[dict], pauses: list[dict], where: str) -> tuple[float, float]:
    if "line" in entry:
        index, source, kind = entry["line"], lines, "line"
    elif "pause" in entry:
        index, source, kind = entry["pause"], pauses, "pause"
    else:
        raise SpecError(f"{where} names neither a line nor a pause.")
    if not isinstance(index, int) or not 0 <= index < len(source):
        raise SpecError(f"{where} points at {kind} {index}, which the clip does not have.")
    item = source[index]
    return float(item["start"]), float(item["end"])


def load_spec(
    labels_path: Path | str | None = None,
    timings_path: Path | str | None = None,
) -> EvalSpec:
    """Load the authored labels and join them onto the generated offsets."""
    labels_path = Path(labels_path or DEMO_FIXTURE_DIR / "eval_labels.json")
    labels = json.loads(labels_path.read_text())

    timings_path = Path(
        timings_path or labels_path.parent / labels.get("timings_from", "expected_violations.json")
    )
    timings = json.loads(timings_path.read_text())
    lines = list(timings.get("lines", []))
    pauses = list(timings.get("pauses", []))

    categories = labels.get("categories", {})
    label_patterns = {
        cid: tuple(p.lower() for p in meta.get("label_patterns", []))
        for cid, meta in categories.items()
    }

    expectations = []
    for entry in labels.get("expectations", []):
        eid = entry.get("id") or "<unnamed expectation>"
        category = entry.get("category")
        if category not in categories:
            raise SpecError(f"Expectation '{eid}' has unknown category '{category}'.")
        match = entry.get("match", "span")
        if match not in {"span", "token"}:
            raise SpecError(f"Expectation '{eid}' has unknown match mode '{match}'.")
        if match == "token" and not entry.get("text"):
            raise SpecError(f"Token expectation '{eid}' has no text to match on.")
        start, end = _window(entry, lines, pauses, f"Expectation '{eid}'")
        expectations.append(Expectation(
            id=eid,
            category=category,
            match=match,
            start=start,
            end=end,
            text=entry.get("text"),
            quote=entry.get("quote"),
            present=bool(entry.get("present", True)),
            note=entry.get("note"),
        ))

    seen: set[str] = set()
    for e in expectations:
        if e.id in seen:
            raise SpecError(f"Duplicate expectation id '{e.id}'.")
        seen.add(e.id)

    controls = []
    for entry in labels.get("controls", []):
        cid = entry.get("id") or "<unnamed control>"
        start, end = _window(entry, lines, pauses, f"Control '{cid}'")
        controls.append(Control(
            id=cid, start=start, end=end, reason=entry.get("reason", ""),
        ))

    suites = {}
    for sid, entry in labels.get("suites", {}).items():
        unknown = [c for c in entry.get("categories", []) if c not in categories]
        if unknown:
            raise SpecError(f"Suite '{sid}' names unknown categories: {', '.join(unknown)}.")
        suites[sid] = Suite(
            id=sid,
            description=entry.get("description", ""),
            categories=tuple(entry.get("categories", [])),
            prompt=entry.get("prompt"),
            preset=entry.get("preset"),
        )

    return EvalSpec(
        expectations=tuple(expectations),
        controls=tuple(controls),
        suites=suites,
        label_patterns=label_patterns,
    )
