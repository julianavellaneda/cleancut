"""
Tests for an export being retired when the edits behind it change.

Regression: accepting, rejecting or re-cutting a suggestion left the rendered
file in `exports/` exactly where it was, still advertising `export_status =
"ready"`. The review screen offered "Download Master" for a file that answered
the edit list as it stood some edits ago, and nothing on the server or in the
API could tell the two apart.

The fix is a pair of counters. `jobs.edit_revision` is bumped whenever the
*accepted* edit set moves; `jobs.export_revision` records which revision the
file on disk came from. "Is this export current" is then a comparison, which
survives a reload, a second tab, and the poll replacing the job object - none of
which a flag in the review component could.

As elsewhere in the worker tests, the queue and its thread are not exercised:
`_process_export` is called directly and synchronously.
"""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

import app.routes.audio as audio_routes
import app.services.exports as exports
import app.services.worker as worker
from app.analysis.prompt_analyzer import AnalysisResult
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Job, Violation


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


class RecordingEditor:
    """Writes a stand-in export instead of invoking FFmpeg."""

    last = None

    def apply_edits(self, input_path, output_path, segments_to_cut=None,
                    segments_to_mute=None, media_type="audio"):
        RecordingEditor.last = {
            "cuts": sorted(segments_to_cut or []),
            "mutes": sorted(segments_to_mute or []),
        }
        open(output_path, "wb").write(b"rendered")


@pytest.fixture
def export_dir(monkeypatch, tmp_path):
    """Point the app at one tmp export directory.

    One setattr, because `services.exports` is the only module that knows where
    exports live - the routes and the worker read it through that module.
    """
    monkeypatch.setattr(exports, "MediaEditor", RecordingEditor)
    monkeypatch.setattr(exports, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(worker, "UPLOAD_DIR", tmp_path)
    RecordingEditor.last = None
    return tmp_path


@pytest.fixture
def client(export_dir, monkeypatch):
    monkeypatch.setattr(audio_routes, "enqueue_export", lambda job_id, edit_action=None: None)
    return TestClient(app)


@pytest.fixture
def make_job(monkeypatch, export_dir):
    """A completed job with media on disk and a violation per spec tuple."""

    def _make(violations=((1.0, 2.0, "cut", "accepted"),), transcript=None):
        job_id = str(uuid.uuid4())
        media = export_dir / f"{job_id}.mp3"
        media.write_bytes(b"not really audio")
        monkeypatch.setattr(audio_routes, "_get_audio_path", lambda jid: media)

        ids = []
        db = SessionLocal()
        try:
            db.add(Job(id=job_id, filename=f"{job_id}.mp3", status="completed",
                       transcript=transcript))
            for start, end, action, vstatus in violations:
                vid = str(uuid.uuid4())
                ids.append(vid)
                db.add(Violation(id=vid, job_id=job_id, text="x", label="Income Claim",
                                 start_time=start, end_time=end,
                                 action=action, status=vstatus))
            db.commit()
        finally:
            db.close()
        return job_id, ids

    return _make


def _job(job_id):
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == job_id).first()
    finally:
        db.close()


def _export_file(export_dir, job_id):
    return export_dir / f"{job_id}_edited.mp3"


def _render(job_id):
    """Take a job all the way to a ready export."""
    worker._process_export(job_id)


# --- a finished render records what it was rendered from --------------------

def test_a_finished_export_records_its_revision(client, make_job, export_dir):
    job_id, _ = make_job()

    _render(job_id)

    job = _job(job_id)
    assert job.export_status == "ready"
    assert job.export_revision == job.edit_revision == 0
    assert _export_file(export_dir, job_id).exists()


def test_the_poll_reports_both_revisions(client, make_job):
    job_id, _ = make_job()
    _render(job_id)

    body = client.get(f"/api/jobs/{job_id}").json()

    assert body["edit_revision"] == 0
    assert body["export_revision"] == 0


# --- a decision that changes the render retires it ---------------------------

def test_rejecting_an_accepted_edit_retires_the_export(client, make_job, export_dir):
    """The headline case: the file no longer contains the cut it advertises."""
    job_id, vids = make_job()
    _render(job_id)

    client.patch(f"/api/jobs/{job_id}/violations/{vids[0]}", json={"status": "rejected"})

    job = _job(job_id)
    assert job.edit_revision == 1
    assert job.export_status == "none"
    assert job.export_revision is None
    assert not _export_file(export_dir, job_id).exists(), "stale bytes must not survive"


def test_accepting_a_pending_edit_retires_the_export(client, make_job, export_dir):
    job_id, vids = make_job(violations=(
        (1.0, 2.0, "cut", "accepted"),
        (3.0, 4.0, "cut", "pending"),
    ))
    _render(job_id)

    client.patch(f"/api/jobs/{job_id}/violations/{vids[1]}", json={"status": "accepted"})

    assert _job(job_id).export_status == "none"
    assert not _export_file(export_dir, job_id).exists()


def test_switching_an_accepted_edit_to_mute_retires_the_export(client, make_job):
    job_id, vids = make_job()
    _render(job_id)

    client.patch(f"/api/jobs/{job_id}/violations/{vids[0]}", json={"action": "mute"})

    assert _job(job_id).edit_revision == 1
    assert _job(job_id).export_status == "none"


def test_the_poll_shows_a_retired_export_as_such(client, make_job):
    job_id, vids = make_job()
    _render(job_id)

    client.patch(f"/api/jobs/{job_id}/violations/{vids[0]}", json={"status": "rejected"})

    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["export_status"] == "none"
    assert body["edit_revision"] == 1
    assert body["export_revision"] is None


# --- a decision that cannot change the render leaves it alone ----------------
#
# Only accepted edits reach FFmpeg. Throwing away a good export because the
# reviewer rejected a suggestion that was never in it would make the export
# button churn for no reason.

def test_rejecting_a_pending_edit_keeps_the_export(client, make_job, export_dir):
    job_id, vids = make_job(violations=(
        (1.0, 2.0, "cut", "accepted"),
        (3.0, 4.0, "cut", "pending"),
    ))
    _render(job_id)

    client.patch(f"/api/jobs/{job_id}/violations/{vids[1]}", json={"status": "rejected"})

    job = _job(job_id)
    assert job.edit_revision == 0
    assert job.export_status == "ready"
    assert _export_file(export_dir, job_id).exists()


def test_recutting_a_rejected_edit_keeps_the_export(client, make_job):
    """A rejected row's action is not in the render, so changing it changes nothing."""
    job_id, vids = make_job(violations=((1.0, 2.0, "cut", "rejected"),
                                        (3.0, 4.0, "cut", "accepted")))
    _render(job_id)

    client.patch(f"/api/jobs/{job_id}/violations/{vids[0]}", json={"action": "mute"})

    assert _job(job_id).export_status == "ready"


def test_writing_the_value_a_row_already_has_keeps_the_export(client, make_job):
    job_id, vids = make_job()
    _render(job_id)

    client.patch(f"/api/jobs/{job_id}/violations/{vids[0]}", json={"status": "accepted"})

    assert _job(job_id).edit_revision == 0
    assert _job(job_id).export_status == "ready"


def test_a_rejected_update_does_not_touch_the_export(client, make_job):
    """A 400 must leave both the row and the export exactly as they were."""
    job_id, vids = make_job()
    _render(job_id)

    response = client.patch(f"/api/jobs/{job_id}/violations/{vids[0]}",
                            json={"status": "banana"})

    assert response.status_code == 400
    assert _job(job_id).export_status == "ready"


# --- bulk moves --------------------------------------------------------------

def test_clean_all_retires_the_export_once(client, make_job, export_dir):
    job_id, _ = make_job(violations=(
        (1.0, 2.0, "cut", "accepted"),
        (3.0, 4.0, "cut", "pending"),
        (5.0, 6.0, "cut", "pending"),
    ))
    _render(job_id)

    client.post(f"/api/jobs/{job_id}/violations/bulk-update", json={"status": "accepted"})

    job = _job(job_id)
    assert job.edit_revision == 1, "one sweep is one revision, not one per row"
    assert job.export_status == "none"
    assert not _export_file(export_dir, job_id).exists()


def test_a_bulk_move_that_matches_nothing_keeps_the_export(client, make_job):
    job_id, _ = make_job()
    _render(job_id)

    response = client.post(f"/api/jobs/{job_id}/violations/bulk-update",
                           json={"status": "accepted", "ids": []})

    assert response.json()["updated"] == 0
    assert _job(job_id).export_status == "ready"


def test_undoing_a_sweep_retires_the_export_again(client, make_job):
    job_id, vids = make_job(violations=((1.0, 2.0, "cut", "pending"),))
    client.post(f"/api/jobs/{job_id}/violations/bulk-update", json={"status": "accepted"})
    _render(job_id)

    client.post(
        f"/api/jobs/{job_id}/violations/bulk-update?from_status=accepted",
        json={"status": "pending", "ids": vids},
    )

    assert _job(job_id).export_status == "none"


# --- an edit landing while the render runs -----------------------------------

def test_an_in_flight_export_is_not_deleted_out_from_under_the_worker(
    client, make_job, export_dir
):
    """
    A queued or running render owns the file it is writing. Invalidation leaves
    it alone and lets the worker settle it, rather than unlinking a file FFmpeg
    still has open.
    """
    job_id, vids = make_job()
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.export_status = "exporting"
        db.commit()
    finally:
        db.close()

    client.patch(f"/api/jobs/{job_id}/violations/{vids[0]}", json={"status": "rejected"})

    job = _job(job_id)
    assert job.edit_revision == 1
    assert job.export_status == "exporting", "the worker still owns this render"


def test_a_render_overtaken_by_an_edit_is_discarded(client, make_job, export_dir, monkeypatch):
    """
    The reviewer changes their mind mid-encode. The file that lands answers the
    old edit list, so it is thrown away rather than published as ready - which
    is what a plain "set ready when done" would have done.
    """
    job_id, vids = make_job()

    class EditingEditor(RecordingEditor):
        def apply_edits(self, *args, **kwargs):
            super().apply_edits(*args, **kwargs)
            client.patch(f"/api/jobs/{job_id}/violations/{vids[0]}",
                         json={"status": "rejected"})

    monkeypatch.setattr(exports, "MediaEditor", EditingEditor)

    worker._process_export(job_id)

    job = _job(job_id)
    assert job.export_status == "none"
    assert job.export_revision is None
    assert not _export_file(export_dir, job_id).exists()


# --- re-analysis -------------------------------------------------------------

def test_a_re_analysis_retires_the_export(client, make_job, export_dir, monkeypatch):
    """
    A re-run deletes every LLM suggestion, decisions included. Whatever is in
    exports/ was rendered from a list that no longer exists.
    """
    transcript = json.dumps({
        "version": 2, "language": "en", "duration": 5.0,
        "segments": [{"start": 0.0, "end": 3.0, "text": "hello there", "words": []}],
    })
    job_id, _ = make_job(transcript=transcript)
    _render(job_id)

    class StubProcessor:
        def analyze(self, transcript, prompt=None, preset=None):
            return AnalysisResult(violations=[], total_segments_analyzed=1,
                                  transcript_language="en", failed_chunks=[])

    monkeypatch.setattr(worker, "get_processor", lambda: StubProcessor())

    worker._process_reanalysis(job_id)

    job = _job(job_id)
    assert job.status == "completed"
    assert job.export_status == "none"
    assert not _export_file(export_dir, job_id).exists()


# --- the download route is the last line of defence --------------------------

def test_a_stale_export_cannot_be_downloaded(client, make_job, export_dir):
    """
    Invalidation normally deletes the file, so this only fires when one survives
    - an unlink that failed, or a render that landed late. It must not be served
    as the user's finished master either way.
    """
    job_id, _ = make_job()
    _render(job_id)
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.edit_revision = 7  # the file stays; only the bookkeeping moves
        db.commit()
    finally:
        db.close()

    for route in ("download", "stream"):
        response = client.get(f"/api/jobs/{job_id}/export/{route}")
        assert response.status_code == 409
        assert "out of date" in response.json()["detail"]


def test_a_current_export_still_downloads(client, make_job):
    job_id, _ = make_job()
    _render(job_id)

    assert client.get(f"/api/jobs/{job_id}/export/download").status_code == 200


def test_an_export_of_unknown_provenance_still_downloads(client, make_job, export_dir):
    """
    A row from before these columns has NULL export_revision and a file on disk
    the filesystem probe finds. That download works today and must keep working:
    nothing recorded which edits it came from, and "unknown" is not "stale".
    """
    job_id, _ = make_job()
    _export_file(export_dir, job_id).write_bytes(b"rendered long ago")
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.export_revision = None
        job.edit_revision = 4
        db.commit()
    finally:
        db.close()

    assert client.get(f"/api/jobs/{job_id}/export/download").status_code == 200
