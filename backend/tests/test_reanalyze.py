"""
Tests for re-analyzing a job's stored transcript under a new prompt.

The gap this closes: a new question about the same recording used to mean a
full Whisper pass, the slowest and most expensive stage of the job and the one
stage the change has nothing to do with. The transcript has been persisted for
a while; this is what finally reads it back.

The design worth locking down is what a re-run replaces. The LLM's suggestions
answer the old prompt, so they go - accepted and rejected ones included, since a
decision about a suggestion that no longer exists cannot be carried forward
honestly. The scrubber's are deterministic, have nothing to do with the prompt,
and would come back byte-identical, so they and every decision on them stay put.

No Whisper and no LLM: the processor is stubbed, as in test_worker_autofix.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

import app.services.worker as worker
from app.analysis.prompt_analyzer import AnalysisResult, Violation
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Job
from app.models import Violation as ViolationRow
from app.services import transcripts


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


@pytest.fixture
def client(monkeypatch):
    """A client whose re-analysis requests queue rather than run."""
    monkeypatch.setattr("app.routes.jobs.enqueue_reanalysis", lambda job_id, **kwargs: "task")
    monkeypatch.setattr("app.routes.jobs.publish", lambda task: task)
    return TestClient(app)


TRANSCRIPT = json.dumps({
    "version": 2, "language": "en", "duration": 12.0,
    "segments": [{
        "start": 0.0, "end": 3.0, "text": "I made eleven thousand dollars",
        "words": [
            {"start": 0.0, "end": 0.4, "text": "I"},
            {"start": 0.4, "end": 0.9, "text": "made"},
            {"start": 0.9, "end": 1.6, "text": "eleven"},
            {"start": 1.6, "end": 2.3, "text": "thousand"},
            {"start": 2.3, "end": 3.0, "text": "dollars"},
        ],
    }],
})


@pytest.fixture
def make_job():
    def _make(transcript=TRANSCRIPT, status="completed", violations=(), **kwargs):
        job_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(Job(id=job_id, filename=f"{job_id}.mp3", status=status,
                       transcript=transcript, prompt="find income claims", **kwargs))
            for label, vstatus in violations:
                db.add(ViolationRow(
                    id=str(uuid.uuid4()), job_id=job_id, text=label,
                    start_time=1.0, end_time=2.0, label=label,
                    status=vstatus, action="cut",
                ))
            db.commit()
        finally:
            db.close()
        return job_id
    return _make


def _job(job_id):
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == job_id).first()
    finally:
        db.close()


def _violations(job_id):
    db = SessionLocal()
    try:
        rows = db.query(ViolationRow).filter(ViolationRow.job_id == job_id).all()
        return sorted((v.label, v.status) for v in rows)
    finally:
        db.close()


@pytest.fixture
def stub_analysis(monkeypatch):
    """Answer the next analysis with these suggestions, and record the call."""
    calls = []

    def _stub(violations=(), failed_chunks=(), raises=None):
        class StubProcessor:
            def analyze(self, transcript, prompt=None, preset=None):
                calls.append({"transcript": transcript, "prompt": prompt, "preset": preset})
                if raises:
                    raise raises
                return AnalysisResult(
                    violations=list(violations),
                    total_segments_analyzed=1,
                    transcript_language="en",
                    failed_chunks=list(failed_chunks),
                )

        monkeypatch.setattr(worker, "get_processor", lambda: StubProcessor())
        return calls

    return _stub


def _violation(label, start=0.9, end=3.0):
    return Violation(text="eleven thousand dollars", start_time=start, end_time=end,
                     label=label, action="cut", reasoning="because")


# --- the route validates, queues, and answers 202 ---------------------------

def test_a_re_analysis_is_queued_not_run(client, make_job):
    job_id = make_job()

    response = client.post(f"/api/jobs/{job_id}/reanalyze",
                           json={"prompt": "find every filler"})

    assert response.status_code == 202
    assert response.json()["prompt"] == "find every filler"
    # Set before the worker sees it, so the frontend's existing status poll
    # picks the re-run up immediately.
    assert _job(job_id).status == "analyzing"
    # The prompt is not. It labels the suggestion list, and the list on screen
    # is still the answer to the old question until the worker replaces it.
    assert _job(job_id).prompt == "find income claims"


def test_a_job_with_no_stored_transcript_is_refused(client, make_job):
    """
    409, not 404. The job is real - it predates the transcript column or never
    reached transcription - and saying "not found" would send the caller
    looking for a job that is right there in their list.
    """
    job_id = make_job(transcript=None)

    response = client.post(f"/api/jobs/{job_id}/reanalyze", json={"prompt": "x"})

    assert response.status_code == 409
    assert _job(job_id).status == "completed"


def test_a_job_still_in_the_pipeline_is_refused(client, make_job):
    """The run in flight would overwrite whatever this one wrote."""
    job_id = make_job(status="transcribing")

    response = client.post(f"/api/jobs/{job_id}/reanalyze", json={"prompt": "x"})

    assert response.status_code == 409


def test_a_request_with_neither_prompt_nor_preset_is_refused(client, make_job):
    job_id = make_job()

    response = client.post(f"/api/jobs/{job_id}/reanalyze", json={})

    assert response.status_code == 400
    assert _job(job_id).status == "completed"


def test_a_blank_prompt_is_not_a_prompt(client, make_job):
    job_id = make_job()

    response = client.post(f"/api/jobs/{job_id}/reanalyze", json={"prompt": "   "})

    assert response.status_code == 400


def test_an_unknown_preset_is_refused(client, make_job):
    job_id = make_job()

    response = client.post(f"/api/jobs/{job_id}/reanalyze", json={"preset": "nonsense"})

    assert response.status_code == 400


def test_switching_to_a_preset_clears_the_prompt(make_job, stub_analysis):
    """
    The analyzer runs in one mode or the other; the job has to say which. The
    swap lands with the suggestions, in the worker.
    """
    stub_analysis(violations=[_violation("PII")])
    job_id = make_job()

    worker._process_reanalysis(job_id, preset="pii-redaction")

    assert _job(job_id).preset == "pii-redaction"
    assert _job(job_id).prompt is None


def test_an_unknown_job_is_a_404(client):
    response = client.post(f"/api/jobs/{uuid.uuid4()}/reanalyze", json={"prompt": "x"})

    assert response.status_code == 404


# --- the worker re-runs the analysis off the stored words -------------------

def test_the_stored_words_are_what_the_analyzer_sees(make_job, stub_analysis):
    """The headline: no audio is touched, and the timing is not degraded."""
    calls = stub_analysis(violations=[_violation("Filler Word Hunt")])
    job_id = make_job()

    worker._process_reanalysis(job_id)

    transcript = calls[0]["transcript"]
    assert [w.text for w in transcript.segments[0].words] == [
        "I", "made", "eleven", "thousand", "dollars",
    ]


def test_the_old_suggestions_are_replaced(make_job, stub_analysis):
    stub_analysis(violations=[_violation("Health Claims")])
    job_id = make_job(violations=[("Income Claims", "accepted"),
                                  ("Income Claims", "rejected")])

    worker._process_reanalysis(job_id)

    assert _violations(job_id) == [("Health Claims", "pending")]


def test_the_scrubbers_work_and_its_decisions_survive(make_job, stub_analysis):
    """
    Deterministic and prompt-independent: a re-run would produce these
    byte-identical, so throwing away the reviewer's decisions on them would be
    pure loss.
    """
    stub_analysis(violations=[_violation("Health Claims")])
    job_id = make_job(violations=[("Filler Word", "accepted"),
                                  ("Dead Air", "rejected"),
                                  ("Income Claims", "accepted")])

    worker._process_reanalysis(job_id)

    assert _violations(job_id) == [
        ("Dead Air", "rejected"),
        ("Filler Word", "accepted"),
        ("Health Claims", "pending"),
    ]


def test_nothing_is_pre_accepted_even_on_an_auto_fix_job(make_job, stub_analysis):
    """
    `auto_fix` was a choice about the upload. A re-analysis is a choice made in
    the review screen, where the whole point is to look at what came back.
    """
    stub_analysis(violations=[_violation("Health Claims")])
    job_id = make_job(auto_fix=True)

    worker._process_reanalysis(job_id)

    assert _violations(job_id) == [("Health Claims", "pending")]


def test_a_stale_partial_warning_is_cleared(make_job, stub_analysis):
    stub_analysis(violations=[_violation("Health Claims")])
    job_id = make_job()
    db = SessionLocal()
    try:
        db.query(Job).filter(Job.id == job_id).first().error_message = "Partial analysis: 2 ..."
        db.commit()
    finally:
        db.close()

    worker._process_reanalysis(job_id)

    assert _job(job_id).error_message is None
    assert _job(job_id).status == "completed"


def test_a_partial_re_analysis_still_completes_with_a_warning(make_job, stub_analysis):
    stub_analysis(violations=[_violation("Health Claims")],
                  failed_chunks=["segments 10-60"])
    job_id = make_job()

    worker._process_reanalysis(job_id)

    assert _job(job_id).status == "completed"
    assert "Partial analysis" in _job(job_id).error_message


def test_a_failed_re_analysis_leaves_the_review_intact(make_job, stub_analysis):
    """
    The same argument as a failed export: this is a completed job with a
    reviewed edit list, and a bad response to a second prompt must not strand
    that behind an error screen. The old suggestions are still there, because
    the delete only runs once the new analysis has come back.
    """
    stub_analysis(raises=RuntimeError("the model returned nonsense"))
    job_id = make_job(violations=[("Income Claims", "accepted")])

    worker._process_reanalysis(job_id)

    job = _job(job_id)
    assert job.status == "completed"
    assert "Re-analysis failed" in job.error_message
    assert _violations(job_id) == [("Income Claims", "accepted")]


def test_the_new_question_is_what_the_analyzer_is_asked(make_job, stub_analysis):
    """
    It travels on the task rather than being read back off the job, precisely so
    the job's own prompt can stay behind until there is something to label.
    """
    calls = stub_analysis(violations=[_violation("Health Claims")])
    job_id = make_job()

    worker._process_reanalysis(job_id, prompt="find health claims")

    assert calls[0]["prompt"] == "find health claims"
    assert calls[0]["preset"] is None


def test_the_prompt_and_the_suggestions_land_together(make_job, stub_analysis):
    stub_analysis(violations=[_violation("Health Claims")])
    job_id = make_job(violations=[("Income Claims", "accepted")])

    worker._process_reanalysis(job_id, prompt="find health claims")

    assert _job(job_id).prompt == "find health claims"
    assert _violations(job_id) == [("Health Claims", "pending")]


def test_a_failed_re_run_leaves_the_old_prompt_over_the_old_suggestions(
    make_job, stub_analysis,
):
    """
    The mismatch this closes: the suggestions on screen answer the *old*
    question, and writing the new prompt at request time relabelled them as
    answers to a question that was never put to the model. There is nothing to
    restore here - the row was never moved.
    """
    stub_analysis(raises=RuntimeError("the model returned nonsense"))
    job_id = make_job(violations=[("Income Claims", "accepted")])

    worker._process_reanalysis(job_id, prompt="find health claims")

    job = _job(job_id)
    assert job.prompt == "find income claims"
    assert job.preset is None
    assert _violations(job_id) == [("Income Claims", "accepted")]


def test_a_re_run_with_no_stored_transcript_does_not_move_the_prompt(
    make_job, stub_analysis,
):
    """The other early return out of the worker, which never reaches the swap."""
    stub_analysis()
    job_id = make_job(transcript=None)

    worker._process_reanalysis(job_id, prompt="find health claims")

    assert _job(job_id).prompt == "find income claims"


def test_the_route_hands_the_question_to_the_queue(client, make_job, monkeypatch):
    queued = []
    def record(job_id, db=None, **kwargs):
        # `db` is admission plumbing, not part of the question being asked, so
        # it is taken off before the call is recorded: this test is about the
        # prompt and preset reaching the queue.
        queued.append((job_id, kwargs))
        return "task"

    monkeypatch.setattr("app.routes.jobs.enqueue_reanalysis", record)
    monkeypatch.setattr("app.routes.jobs.publish", lambda task: task)
    job_id = make_job()

    client.post(f"/api/jobs/{job_id}/reanalyze", json={"prompt": "find every filler"})

    assert queued == [(job_id, {"prompt": "find every filler", "preset": None})]


def test_a_version_1_row_re_analyzes_at_segment_precision(make_job, stub_analysis):
    """
    The rows already in the database have no words. That degrades the timing of
    a quote to its line, which is the analyzer's existing fallback - it is not a
    reason to refuse the re-run.
    """
    calls = stub_analysis(violations=[_violation("Health Claims")])
    job_id = make_job(transcript=json.dumps({
        "version": 1, "language": "en", "duration": 12.0,
        "segments": [{"start": 0.0, "end": 3.0, "text": "I made eleven thousand dollars"}],
    }))

    worker._process_reanalysis(job_id)

    assert calls[0]["transcript"].segments[0].words == []
    assert _violations(job_id) == [("Health Claims", "pending")]


def test_an_unreadable_transcript_does_not_fail_the_job(make_job, stub_analysis):
    stub_analysis()
    job_id = make_job(transcript="{ truncated")

    worker._process_reanalysis(job_id)

    assert _job(job_id).status == "completed"
    assert "needs a stored transcript" in _job(job_id).error_message


def test_the_transcript_row_itself_is_untouched(make_job, stub_analysis):
    """A re-run answers a new question about the same words; it is not a re-read."""
    stub_analysis(violations=[_violation("Health Claims")])
    job_id = make_job()

    worker._process_reanalysis(job_id)

    assert transcripts.from_json(_job(job_id).transcript) is not None
    assert _job(job_id).transcript == TRANSCRIPT
