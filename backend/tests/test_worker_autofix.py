"""
Tests for how the worker's auto-apply path routes suggestions to cut or mute.

Regression: auto-fix pushed every selected suggestion through `cut_segments`,
so a preset whose default action is mute (pii-redaction) had its findings
deleted from the timeline instead of silenced. The worker now partitions by
each suggestion's own action, the same way the export route does.

Transcription, the LLM and FFmpeg are all stubbed - what is under test is which
segments land in which bucket, and under which auto_fix/auto_scrub flags.
"""

import uuid

import numpy as np
import pytest

import app.services.exports as exports
import app.services.worker as worker
from app.analysis.prompt_analyzer import AnalysisResult, Violation
from app.analysis.transcriber import TranscriptResult
from app.database import SessionLocal, init_db
from app.models import Job, Violation as ViolationRow


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


class RecordingEditor:
    """Captures the cut/mute buckets instead of invoking FFmpeg."""

    last = None

    def apply_edits(self, input_path, output_path, segments_to_cut=None,
                    segments_to_mute=None, media_type="audio"):
        RecordingEditor.last = {
            "cuts": sorted(segments_to_cut or []),
            "mutes": sorted(segments_to_mute or []),
            "media_type": media_type,
        }

    def cut_segments(self, *args, **kwargs):
        raise AssertionError(
            "auto-apply must go through apply_edits so mute actions survive"
        )


def _violation(start, end, label, action):
    return Violation(
        text="x", start_time=start, end_time=end, label=label,
        action=action, reasoning="because",
    )


@pytest.fixture
def run_job(monkeypatch, tmp_path):
    """Run the worker's job body with stubbed analysis and a stubbed editor."""

    def _run(llm_violations=(), scrubber_violations=(), auto_fix=False,
             auto_scrub=False, media_type="audio"):
        RecordingEditor.last = None
        monkeypatch.setattr(exports, "MediaEditor", RecordingEditor)
        monkeypatch.setattr(worker, "EXPORT_DIR", tmp_path)

        transcript = TranscriptResult(segments=[], language="en", duration=60.0)

        class StubProcessor:
            def transcribe(self, path, language=None):
                return transcript

            def analyze(self, transcript, prompt=None, preset=None):
                return AnalysisResult(
                    violations=list(llm_violations),
                    total_segments_analyzed=0,
                    transcript_language="en",
                )

        monkeypatch.setattr(worker, "get_processor", lambda: StubProcessor())
        # The media here is a placeholder string of bytes; skip the real
        # level pass rather than spawn an ffmpeg that can only fail.
        monkeypatch.setattr(worker, "decode_pcm_mono",
                            lambda path, sr=8000: np.zeros(sr, dtype=np.float32))
        monkeypatch.setattr(
            worker.Scrubber, "detect_silence",
            staticmethod(lambda t, *a, **k: [v for v in scrubber_violations
                                             if v.label == "Dead Air"]),
        )
        monkeypatch.setattr(
            worker.Scrubber, "detect_filler_words",
            staticmethod(lambda t: [v for v in scrubber_violations
                                    if v.label == "Filler Word"]),
        )
        # Nothing was selected -> the worker transcodes the original instead.
        monkeypatch.setattr(worker, "ffmpeg", _StubFfmpeg())
        # The no-edits passthrough moved to `exports` along with the rest of
        # the render path; both modules reach for ffmpeg, so both are stubbed.
        monkeypatch.setattr(exports, "ffmpeg", _StubFfmpeg())

        job_id = str(uuid.uuid4())
        media = tmp_path / f"{job_id}.mp3"
        media.write_bytes(b"not really audio")

        db = SessionLocal()
        try:
            db.add(Job(id=job_id, filename=media.name, status="pending",
                       media_type=media_type, auto_fix=auto_fix,
                       auto_scrub=auto_scrub))
            db.commit()
        finally:
            db.close()

        worker._process_job_sequentially(job_id, str(media))
        return job_id

    return _run


class _StubFfmpeg:
    """Stands in for the `ffmpeg` module's no-edits passthrough."""

    def input(self, *a, **k):
        return self

    def output(self, *a, **k):
        return self

    def run(self, *a, **k):
        return None


def _job_status(job_id):
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == job_id).first().status
    finally:
        db.close()


def _export_status(job_id):
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == job_id).first().export_status
    finally:
        db.close()


def _rows(job_id):
    db = SessionLocal()
    try:
        return db.query(ViolationRow).filter(ViolationRow.job_id == job_id).all()
    finally:
        db.close()


def test_auto_fix_mute_suggestions_are_muted_not_cut(run_job):
    """The headline fix - a pii-redaction style mute must not delete audio."""
    job_id = run_job(
        llm_violations=[_violation(1.0, 2.0, "Direct Identifiers", "mute")],
        auto_fix=True,
    )

    assert _job_status(job_id) == "completed"
    assert RecordingEditor.last["mutes"] == [(1.0, 2.0)]
    assert RecordingEditor.last["cuts"] == []


def test_auto_fix_partitions_mixed_actions(run_job):
    run_job(
        llm_violations=[
            _violation(1.0, 2.0, "Income Claims", "cut"),
            _violation(5.0, 6.0, "Direct Identifiers", "mute"),
            _violation(8.0, 9.0, "Income Claims", "cut"),
        ],
        auto_fix=True,
    )

    assert RecordingEditor.last["cuts"] == [(1.0, 2.0), (8.0, 9.0)]
    assert RecordingEditor.last["mutes"] == [(5.0, 6.0)]


def test_auto_scrub_only_selects_scrubber_suggestions(run_job):
    run_job(
        llm_violations=[_violation(1.0, 2.0, "Income Claims", "cut")],
        scrubber_violations=[_violation(5.0, 6.0, "Filler Word", "cut")],
        auto_fix=False,
        auto_scrub=True,
    )

    assert RecordingEditor.last["cuts"] == [(5.0, 6.0)]
    assert RecordingEditor.last["mutes"] == []


def test_auto_fix_only_selects_llm_suggestions(run_job):
    run_job(
        llm_violations=[_violation(1.0, 2.0, "Income Claims", "cut")],
        scrubber_violations=[_violation(5.0, 6.0, "Dead Air", "cut")],
        auto_fix=True,
        auto_scrub=False,
    )

    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]


def test_no_auto_flags_means_no_export(run_job):
    job_id = run_job(
        llm_violations=[_violation(1.0, 2.0, "Income Claims", "cut")],
    )

    assert _job_status(job_id) == "completed"
    assert _export_status(job_id) == "none"
    assert RecordingEditor.last is None


def test_auto_applied_job_lands_with_its_export_ready(run_job):
    """The download must be live the moment an auto-applied job appears."""
    job_id = run_job(
        llm_violations=[_violation(1.0, 2.0, "Income Claims", "cut")],
        auto_fix=True,
    )

    assert _job_status(job_id) == "completed"
    assert _export_status(job_id) == "ready"


def test_auto_fix_with_nothing_found_still_completes(run_job):
    """No suggestions - falls through to the passthrough transcode."""
    job_id = run_job(auto_fix=True)

    assert _job_status(job_id) == "completed"
    assert RecordingEditor.last is None


def test_suggestions_are_persisted_with_their_action_and_status(run_job):
    job_id = run_job(
        llm_violations=[_violation(1.0, 2.0, "Direct Identifiers", "mute")],
        scrubber_violations=[_violation(5.0, 6.0, "Filler Word", "cut")],
        auto_fix=True,
        auto_scrub=False,
    )

    by_label = {v.label: v for v in _rows(job_id)}
    assert by_label["Direct Identifiers"].action == "mute"
    assert by_label["Direct Identifiers"].status == "accepted"
    # auto_scrub was off, so the scrubber's finding stays for human review
    assert by_label["Filler Word"].status == "pending"


def test_media_type_is_passed_through(run_job):
    run_job(
        llm_violations=[_violation(1.0, 2.0, "Income Claims", "cut")],
        auto_fix=True,
        media_type="video",
    )

    assert RecordingEditor.last["media_type"] == "video"


# --- a suggestion nobody could place is never applied unattended -------------
#
# When the analyzer cannot find a quote in the transcript, the span it returns
# is the model's own estimate. `auto_fix` used to apply those exactly like a
# measured one, so a quote that matched nothing cut whatever happened to be at
# the guessed time - the one case where an unreviewed cut is guaranteed wrong.

def _approximate(start, end, label, action):
    v = _violation(start, end, label, action)
    v.is_approximate = True
    return v


def test_auto_fix_leaves_an_unplaced_suggestion_pending(run_job):
    job_id = run_job(
        llm_violations=[_approximate(1.0, 2.0, "Income Claims", "cut")],
        auto_fix=True,
    )

    assert [row.status for row in _rows(job_id)] == ["pending"]


def test_an_unplaced_suggestion_is_not_rendered_into_the_export(run_job):
    """The review screen and the exported file have to agree about it."""
    run_job(
        llm_violations=[
            _violation(1.0, 2.0, "Income Claims", "cut"),
            _approximate(5.0, 6.0, "Income Claims", "cut"),
        ],
        auto_fix=True,
    )

    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]


# The same argument one level down, for the deterministic side. The scrubber
# matches fillers on spelling, and a few of those spellings are ordinary words -
# an unevidenced "like" cut unattended turns "I like this" into "I this".

def _ambiguous(start, end, label, action):
    v = _violation(start, end, label, action)
    v.is_ambiguous = True
    return v


def test_auto_scrub_leaves_an_ambiguous_filler_pending(run_job):
    job_id = run_job(
        scrubber_violations=[_ambiguous(1.0, 2.0, "Filler Word", "cut")],
        auto_scrub=True,
    )

    assert [row.status for row in _rows(job_id)] == ["pending"]


def test_an_ambiguous_filler_is_not_rendered_into_the_export(run_job):
    run_job(
        scrubber_violations=[
            _violation(1.0, 2.0, "Filler Word", "cut"),
            _ambiguous(5.0, 6.0, "Filler Word", "cut"),
        ],
        auto_scrub=True,
    )

    assert RecordingEditor.last["cuts"] == [(1.0, 2.0)]


def test_an_evidenced_filler_is_still_auto_accepted(run_job):
    job_id = run_job(
        scrubber_violations=[_violation(1.0, 2.0, "Filler Word", "cut")],
        auto_scrub=True,
    )

    assert [row.status for row in _rows(job_id)] == ["accepted"]


def test_placed_suggestions_are_still_auto_accepted(run_job):
    job_id = run_job(
        llm_violations=[_violation(1.0, 2.0, "Income Claims", "cut")],
        auto_fix=True,
    )

    assert [row.status for row in _rows(job_id)] == ["accepted"]
