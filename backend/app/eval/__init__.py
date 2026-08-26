"""
Measuring the detectors against a labelled clip.

The demo fixture has always carried ground truth - every line's measured offset
and a written table of what was planted where - but nothing read it back, so
"the analyzer seems accurate" stayed an impression. This package turns it into
a number: load the labels, score a run against them, and print precision and
recall per category.

Three pieces:

- ``spec``    - the ground truth, joined from the generated offsets and the
                hand-written labels.
- ``scoring`` - matching predictions to expectations, and the scorecard.
- ``run``     - the CLI, which can score a saved run or drive a live one.
"""

from .spec import EvalSpec, Expectation, Control, Suite, load_spec
from .scoring import Prediction, Scorecard, load_predictions, score

__all__ = [
    "EvalSpec",
    "Expectation",
    "Control",
    "Suite",
    "load_spec",
    "Prediction",
    "Scorecard",
    "load_predictions",
    "score",
]
