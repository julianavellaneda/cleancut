"""
Matching a run's suggestions against the labelled clip, and scoring the result.

Two things make this harder than comparing two lists of intervals.

*The labels are free-form.* In prompt mode the model names its own labels, so
"Income Claim", "Specific earnings figure" and "Income/Earnings" are the same
finding under three names. Categories are therefore matched on the substrings
declared in the labels file, not on an id the model was never given.

*A correct flag is rarely the same interval as the label.* An editor wants the
tightest span that still contains the claim, so a model quoting one clause of a
labelled line is doing the right thing, and a line split into two suggestions is
two correct flags rather than one correct and one spurious. Coverage is measured
against the *shorter* of the two spans for that reason - IoU would mark the
tighter, better span down - and a second suggestion landing on an
already-matched label is recorded as a duplicate instead of a false positive.

*Out of scope is not the same as absent.* A suggestion answering a real label
this suite did not ask about is set aside; a suggestion answering a label marked
``present: false`` is a hallucination about something the clip does not contain,
and costs precision like any other false positive.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from .spec import Control, EvalSpec, Expectation, Suite

# How much of the shorter span has to be shared before a suggestion counts as
# landing on a label. Half is deliberately loose: this asks "did it find the
# right moment", and how tightly it cut is reported separately as timing error.
MIN_COVERAGE = 0.5

# Filler words are matched by the word, not the window, so the window only has
# to be nearby. Whisper's word boundaries drift a few hundred milliseconds
# against the generator's line offsets; a second absorbs that without letting a
# filler from an adjacent line count.
TOKEN_TOLERANCE = 1.0


@dataclass(frozen=True)
class Prediction:
    """One suggestion from a run, whatever produced it."""

    text: str
    start: float
    end: float
    label: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class Hit:
    expectation_id: str
    category: str
    prediction_index: int
    coverage: float
    delta_start: float
    delta_end: float
    # False when the label's window is a stand-in for the real span - see
    # Expectation.timed. Such a hit is a hit; its boundary error is noise.
    timed: bool = True


@dataclass(frozen=True)
class Scorecard:
    suite: str
    predictions: tuple[Prediction, ...]
    hits: tuple[Hit, ...]
    misses: tuple[Expectation, ...]
    duplicates: tuple[tuple[int, str], ...]
    false_positives: tuple[int, ...]
    control_hits: tuple[tuple[int, Control], ...]
    out_of_scope: tuple[tuple[int, str], ...]
    scorable: tuple[Expectation, ...]

    @property
    def counted(self) -> int:
        """Suggestions the run is graded on - everything except the out-of-scope ones."""
        return len(self.predictions) - len(self.out_of_scope)

    @property
    def precision(self) -> float:
        if self.counted == 0:
            return 0.0
        matched = len({h.prediction_index for h in self.hits}) + len(self.duplicates)
        return matched / self.counted

    @property
    def recall(self) -> float:
        if not self.scorable:
            return 0.0
        return len({h.expectation_id for h in self.hits}) / len(self.scorable)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 0.0 if p + r == 0 else 2 * p * r / (p + r)

    @property
    def per_category(self) -> dict[str, tuple[int, int]]:
        """category -> (found, expected), in the suite's own order."""
        found: dict[str, int] = {}
        for h in self.hits:
            found[h.category] = found.get(h.category, 0) + 1
        totals: dict[str, int] = {}
        for e in self.scorable:
            totals[e.category] = totals.get(e.category, 0) + 1
        return {c: (found.get(c, 0), n) for c, n in totals.items()}

    @property
    def timing(self) -> dict[str, float]:
        """
        Mean absolute boundary error over the span matches, in seconds.

        Informational, not a pass/fail number. The labels are where the *script*
        put each line, and the acoustic edges sit a little outside that - a line
        trails off quietly, a pause starts before the last word decays. A
        detector measuring the audio is right to disagree with the script here.
        """
        spans = [h for h in self.hits if h.coverage > 0 and h.timed]
        if not spans:
            return {"start": 0.0, "end": 0.0, "n": 0}
        return {
            "start": sum(abs(h.delta_start) for h in spans) / len(spans),
            "end": sum(abs(h.delta_end) for h in spans) / len(spans),
            "n": len(spans),
        }


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _coverage(pred: Prediction, exp: Expectation) -> float:
    shorter = min(pred.duration, exp.duration)
    if shorter <= 0:
        # A zero-length suggestion (Whisper occasionally emits one for a word it
        # barely heard) has no span to share. Count it if it lands inside.
        return 1.0 if _overlap(pred.start, pred.end, exp.start - 0.01, exp.end + 0.01) >= 0 \
            and exp.start - 0.01 <= pred.start <= exp.end + 0.01 else 0.0
    return _overlap(pred.start, pred.end, exp.start, exp.end) / shorter


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9']+", (text or "").lower()) if t]


def _contains_token(pred: Prediction, exp: Expectation) -> bool:
    """Does the suggestion's text contain the expected filler, as whole words?"""
    wanted = _tokens(exp.text or "")
    if not wanted:
        return False
    got = _tokens(pred.text)
    n = len(wanted)
    return any(got[i:i + n] == wanted for i in range(len(got) - n + 1))


def _near(pred: Prediction, exp: Expectation) -> bool:
    return _overlap(
        pred.start, pred.end,
        exp.start - TOKEN_TOLERANCE, exp.end + TOKEN_TOLERANCE,
    ) > 0 or exp.start - TOKEN_TOLERANCE <= pred.start <= exp.end + TOKEN_TOLERANCE


def _matches(pred: Prediction, exp: Expectation) -> float | None:
    """The coverage at which this suggestion lands on this label, or None."""
    if exp.match == "token":
        return 1.0 if _contains_token(pred, exp) and _near(pred, exp) else None
    coverage = _coverage(pred, exp)
    return coverage if coverage >= MIN_COVERAGE else None


def score(spec: EvalSpec, suite: Suite, predictions: list[Prediction]) -> Scorecard:
    """
    Grade one run against one suite.

    Assignment is greedy rather than optimal: labels are far enough apart in the
    clip that no suggestion is a plausible match for two of them, and a greedy
    pass is the one a reader can follow when they disagree with a verdict.
    """
    scorable = spec.scorable(suite)
    hits: list[Hit] = []
    duplicates: list[tuple[int, str]] = []
    out_of_scope: list[tuple[int, str]] = []
    control_hits: list[tuple[int, Control]] = []
    false_positives: list[int] = []
    claimed: set[str] = set()
    matched_predictions: set[int] = set()

    def candidates(pred: Prediction, pool) -> list[Expectation]:
        cats = spec.categories_for_label(pred.label)
        return [e for e in pool if e.category in cats]

    # Filler words first. They are matched by the word rather than the window,
    # and one merged suggestion ("um, you know") legitimately answers two labels,
    # so they cannot go through the one-prediction-one-label pass below.
    for i, pred in enumerate(predictions):
        for exp in candidates(pred, scorable):
            if exp.match != "token" or exp.id in claimed:
                continue
            if _matches(pred, exp) is not None:
                claimed.add(exp.id)
                matched_predictions.add(i)
                hits.append(Hit(exp.id, exp.category, i, 0.0, 0.0, 0.0))

    for i, pred in enumerate(predictions):
        if i in matched_predictions:
            continue
        best: tuple[float, Expectation] | None = None
        for exp in candidates(pred, scorable):
            if exp.match != "span":
                continue
            coverage = _matches(pred, exp)
            if coverage is not None and (best is None or coverage > best[0]):
                best = (coverage, exp)
        if best is None:
            continue
        coverage, exp = best
        matched_predictions.add(i)
        if exp.id in claimed:
            duplicates.append((i, exp.id))
            continue
        claimed.add(exp.id)
        hits.append(Hit(
            exp.id, exp.category, i, coverage,
            pred.start - exp.start, pred.end - exp.end, exp.timed,
        ))

    # Whatever is left either answers a label this suite did not ask about, or
    # is a false positive - and a false positive on a control is the one the
    # fixture was built to catch.
    #
    # Only *present* labels from other categories are set aside. An expectation
    # marked present: false is not in the clip at all, so a suggestion landing on
    # it invented something; excluding that from the denominator would let a
    # hallucinated phone number on a silent line score a flawless run.
    rest = [
        e for e in spec.expectations
        if e.present and e.category not in suite.categories
    ]
    for i, pred in enumerate(predictions):
        if i in matched_predictions:
            continue
        elsewhere = next(
            (e for e in candidates(pred, rest) if _matches(pred, e) is not None), None
        )
        if elsewhere is not None:
            out_of_scope.append((i, elsewhere.id))
            continue
        hit_control = next(
            (c for c in spec.controls
             if _overlap(pred.start, pred.end, c.start, c.end) / max(pred.duration, 1e-9) >= MIN_COVERAGE),
            None,
        )
        if hit_control is not None:
            control_hits.append((i, hit_control))
        false_positives.append(i)

    return Scorecard(
        suite=suite.id,
        predictions=tuple(predictions),
        hits=tuple(hits),
        misses=tuple(e for e in scorable if e.id not in claimed),
        duplicates=tuple(duplicates),
        false_positives=tuple(false_positives),
        control_hits=tuple(control_hits),
        out_of_scope=tuple(out_of_scope),
        scorable=scorable,
    )


@dataclass(frozen=True)
class RunResult:
    """
    A run's suggestions, plus whether the run actually finished.

    ``is_partial`` is the reason this is not just a list. A chunk that failed
    leaves findings behind for the rest of the transcript, and those findings
    score perfectly well - the recall they produce is a floor, not a
    measurement, and nothing downstream can tell the difference once the flag is
    dropped.
    """

    predictions: tuple[Prediction, ...]
    is_partial: bool = False
    failed_chunks: tuple[str, ...] = ()


def _timestamp(row: dict, key: str) -> float:
    try:
        value = float(row[key])
    except KeyError:
        raise ValueError(f"Suggestion has no '{key}': {row!r}") from None
    except (TypeError, ValueError):
        raise ValueError(f"Suggestion has a non-numeric '{key}': {row!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"Suggestion has a non-finite '{key}': {row!r}")
    return value


def load_run(source: Path | str | dict | list) -> RunResult:
    """
    Read a run's suggestions and its completeness.

    Accepts the three shapes this repo already writes: the seeded demo job, the
    CLI's ``analysis.to_json`` output, and the API's violation list. All three
    carry the same four fields under the same names; only the wrapper differs,
    and only ``to_json`` records whether the analysis was partial.

    An object without a ``violations`` key is an error rather than an empty run.
    A schema change at the producer, or simply the wrong file, would otherwise
    read as a legitimate zero-finding run - which scores as a detector that
    found nothing, the single most alarming result the harness can report, and
    the one it must not report by accident.
    """
    if isinstance(source, (str, Path)):
        data = json.loads(Path(source).read_text())
    else:
        data = source

    if isinstance(data, dict):
        if "violations" not in data:
            raise ValueError(
                "Object has no 'violations' list. Give a saved run "
                f"(seed_job.json, analysis JSON, or an API violation list); got keys: "
                f"{sorted(data)}"
            )
        rows = data["violations"]
        failed_chunks = tuple(str(c) for c in data.get("failed_chunks", ()) or ())
        is_partial = bool(data.get("is_partial", False)) or bool(failed_chunks)
    else:
        rows = data
        failed_chunks = ()
        is_partial = False
    if not isinstance(rows, list):
        raise ValueError("Expected a list of suggestions, or an object with a 'violations' list.")

    predictions = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"Suggestion is not an object: {row!r}")
        start = _timestamp(row, "start_time")
        end = _timestamp(row, "end_time")
        # Zero-length is legal - see _coverage - but an interval that ends
        # before it starts is not a tight cut, it is a corrupt row.
        if end < start:
            raise ValueError(f"Suggestion ends before it starts: {row!r}")
        predictions.append(Prediction(
            text=str(row.get("text", "")),
            start=start,
            end=end,
            label=row.get("label"),
        ))
    return RunResult(
        predictions=tuple(predictions),
        is_partial=is_partial,
        failed_chunks=failed_chunks,
    )


def load_predictions(source: Path | str | dict | list) -> list[Prediction]:
    """The suggestions alone, for callers that do not care about completeness."""
    return list(load_run(source).predictions)
