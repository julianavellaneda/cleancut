"""
Tests for the query and decode work behind the two endpoints that get polled.

Three findings share one shape here: the *correct answer* was being computed the
expensive way, over and over, because the page asking for it is on a timer.

1. `GET /api/jobs` ran one SELECT per job to length-check `job.violations`, and
   each of those SELECTs dragged every suggestion's quoted text and reasoning
   across just to produce a count. Now one grouped COUNT answers the page.
2. `GET /api/jobs/{id}` did the same per poll for its four status counts.
3. `GET /api/jobs/{id}/audio/waveform` let every concurrent request for the same
   job run its own FFmpeg decode, each holding the full PCM buffer.

The query tests count *emitted SQL*, not wall-clock: the bug was O(n) statements
and that is the thing that must not come back. A timing assertion would pass on
a fast laptop with the N+1 still in place.
"""

import json
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine

import app.routes.audio as audio_routes
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Job, Violation


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


@pytest.fixture
def client():
    return TestClient(app)


class StatementCounter:
    """
    Count SELECTs against a table while a block of code runs.

    Listens on the ``Engine`` *class* rather than on ``database.engine``: other
    modules in this suite point the app at a temp-file database, which builds a
    different Engine, and a listener bound to the import-time instance then
    counts zero statements and passes vacuously.
    """

    def __init__(self, table: str):
        self.table = table
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(Engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        event.remove(Engine, "before_cursor_execute", self._record)
        return False

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.split()).lower()
        if normalized.startswith("select") and self.table in normalized:
            self.statements.append(normalized)

    @property
    def count(self) -> int:
        return len(self.statements)


def _seed(job_count: int, violations_each: int) -> list[str]:
    """Create jobs with suggestions on them, returning the job ids."""
    db = SessionLocal()
    ids = []
    try:
        for _ in range(job_count):
            job_id = str(uuid.uuid4())
            ids.append(job_id)
            db.add(Job(id=job_id, filename=f"{job_id}.mp3", status="completed"))
            for i in range(violations_each):
                db.add(
                    Violation(
                        id=str(uuid.uuid4()),
                        job_id=job_id,
                        text=f"quote {i}",
                        start_time=float(i),
                        end_time=float(i) + 1.0,
                        label="Filler Word",
                        status=["pending", "accepted", "rejected"][i % 3],
                    )
                )
        db.commit()
    finally:
        db.close()
    return ids


def test_job_list_does_not_scale_queries_with_job_count(client):
    """
    The regression: `len(job.violations)` per job in the list comprehension.

    Six jobs used to mean six extra SELECTs against `violations`. The count is
    pinned as a constant rather than a ratio, so adding a job to the fixture
    cannot quietly make an N+1 look linear-and-fine.
    """
    _seed(job_count=6, violations_each=4)

    with StatementCounter("violations") as counter:
        response = client.get("/api/jobs")

    assert response.status_code == 200
    assert counter.count == 1, (
        f"expected one grouped count over violations, got {counter.count}:\n"
        + "\n".join(counter.statements)
    )


def test_job_list_counts_are_still_right(client):
    """The cheap query has to produce the same numbers as the expensive one."""
    ids = _seed(job_count=2, violations_each=5)
    empty_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Job(id=empty_id, filename=f"{empty_id}.mp3", status="completed"))
        db.commit()
    finally:
        db.close()

    body = client.get("/api/jobs").json()
    by_id = {row["id"]: row for row in body}

    for job_id in ids:
        assert by_id[job_id]["violation_count"] == 5
    # A job with no suggestions has no row in the aggregate at all - it must
    # read as 0, not fall off the response or raise a KeyError.
    assert by_id[empty_id]["violation_count"] == 0


def test_job_detail_uses_one_count_query(client):
    """
    The review page polls this for as long as a job is open. Loading the
    relationship pulled every row's text and reasoning to compute four counts
    that only read `status`.
    """
    job_id = _seed(job_count=1, violations_each=9)[0]

    with StatementCounter("violations") as counter:
        response = client.get(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    assert counter.count == 1, (
        f"expected one grouped count, got {counter.count}:\n"
        + "\n".join(counter.statements)
    )


def test_job_detail_counts_are_still_right(client):
    """9 suggestions cycling through the three statuses: 3 of each."""
    job_id = _seed(job_count=1, violations_each=9)[0]

    body = client.get(f"/api/jobs/{job_id}").json()

    assert body["violation_count"] == 9
    assert body["pending_count"] == 3
    assert body["accepted_count"] == 3
    assert body["rejected_count"] == 3


def test_job_detail_counts_zero_for_a_job_with_no_suggestions(client):
    """The grouped query returns no rows here; every count must read 0."""
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Job(id=job_id, filename=f"{job_id}.mp3", status="completed"))
        db.commit()
    finally:
        db.close()

    body = client.get(f"/api/jobs/{job_id}").json()

    assert body["violation_count"] == 0
    assert body["pending_count"] == 0
    assert body["accepted_count"] == 0
    assert body["rejected_count"] == 0


# --- waveform single-flight -------------------------------------------------


@pytest.fixture
def waveform_job(tmp_path, monkeypatch):
    """A completed job with a file on disk and no cached peaks."""
    job_id = str(uuid.uuid4())
    monkeypatch.setattr(audio_routes, "UPLOAD_DIR", tmp_path)
    (tmp_path / f"{job_id}.mp3").write_bytes(b"not really an mp3")

    db = SessionLocal()
    try:
        db.add(Job(id=job_id, filename=f"{job_id}.mp3", status="completed"))
        db.commit()
    finally:
        db.close()

    # Locks are keyed by job id and live for the process; a fresh uuid per test
    # already isolates them, but clear the dict so a long suite does not carry
    # every job it ever touched.
    audio_routes._waveform_locks.clear()
    return job_id


def test_concurrent_waveform_requests_decode_once(client, waveform_job, monkeypatch):
    """
    Two requests arriving before the first decode finishes must produce one
    decode, not two. Both still get the peaks.

    The generator blocks on a barrier-ish gate so the second request is
    guaranteed to arrive mid-decode - the race the lock exists for, rather than
    whichever interleaving the scheduler happened to pick.
    """
    calls = []
    first_call_started = threading.Event()
    release = threading.Event()

    def slow_peaks(path, num_peaks=800):
        calls.append(path)
        first_call_started.set()
        # Wait until the test says the second request is definitely queued.
        release.wait(timeout=5)
        return [0.5] * num_peaks

    monkeypatch.setattr(audio_routes, "generate_waveform_peaks", slow_peaks)

    results: dict[str, object] = {}

    def fetch(key):
        results[key] = client.get(f"/api/jobs/{waveform_job}/audio/waveform")

    first = threading.Thread(target=fetch, args=("first",))
    first.start()
    assert first_call_started.wait(timeout=5), "first decode never started"

    second = threading.Thread(target=fetch, args=("second",))
    second.start()
    # Give the second thread time to reach the lock and block on it.
    second.join(timeout=0.5)
    assert second.is_alive(), "second request did not wait on the first"

    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert len(calls) == 1, f"waveform was decoded {len(calls)} times"
    for key in ("first", "second"):
        assert results[key].status_code == 200
        assert results[key].json()["peaks"] == [0.5] * 800


def test_waveform_serves_the_cache_on_the_second_request(
    client, waveform_job, monkeypatch
):
    """Sequentially, too: once cached, no further decode happens."""
    calls = []

    def counting_peaks(path, num_peaks=800):
        calls.append(path)
        return [0.25] * num_peaks

    monkeypatch.setattr(audio_routes, "generate_waveform_peaks", counting_peaks)

    first = client.get(f"/api/jobs/{waveform_job}/audio/waveform")
    second = client.get(f"/api/jobs/{waveform_job}/audio/waveform")

    assert first.json()["peaks"] == second.json()["peaks"]
    assert len(calls) == 1

    db = SessionLocal()
    try:
        stored = db.query(Job).filter(Job.id == waveform_job).first().waveform_data
    finally:
        db.close()
    assert json.loads(stored) == [0.25] * 800


# --- the list is bounded, and the poll is small -----------------------------
#
# The other half of the same problem. The N+1 was fixed, but the remaining two
# queries were still unbounded: `SELECT *` over every job ever created, plus a
# GROUP BY over the whole violations table - fetched every three seconds by the
# home page's timer, for the life of the install. Retention is off unless
# RETENTION_HOURS is set, so nothing was ever going to make that table smaller.


def test_the_job_list_is_bounded_by_default(client):
    _seed(job_count=8, violations_each=1)

    body = client.get("/api/jobs").json()

    assert len(body) <= 50


def test_the_page_size_can_be_asked_for_and_is_capped(client):
    _seed(job_count=5, violations_each=1)

    assert len(client.get("/api/jobs?limit=2").json()) == 2
    # Above the cap is refused rather than quietly served in full: a client
    # must not get to choose the size of a query this endpoint answers on a
    # timer.
    assert client.get("/api/jobs?limit=5000").status_code == 422
    assert client.get("/api/jobs?limit=0").status_code == 422
    assert client.get("/api/jobs?offset=-1").status_code == 422


def test_paging_walks_the_list_without_repeating_or_skipping(client):
    _seed(job_count=6, violations_each=1)

    first = client.get("/api/jobs?limit=3&offset=0").json()
    second = client.get("/api/jobs?limit=3&offset=3").json()

    assert len(first) == 3 and len(second) == 3
    assert {j["id"] for j in first}.isdisjoint({j["id"] for j in second})


def test_the_count_aggregate_is_scoped_to_the_page(client):
    """
    The grouped COUNT has to be filtered by the ids on this page, not run over
    the whole table. Otherwise the query the cap was added to bound is still
    proportional to the history behind it.
    """
    _seed(job_count=6, violations_each=3)

    with StatementCounter("violations") as counter:
        response = client.get("/api/jobs?limit=2")

    assert response.status_code == 200
    assert counter.count == 1
    statement = counter.statements[0].lower()
    assert " in (" in statement, (
        "the aggregate is not scoped to the page's job ids:\n" + counter.statements[0]
    )


def test_the_active_endpoint_returns_only_unfinished_jobs(client):
    done = _seed(job_count=2, violations_each=1)
    busy = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Job(id=busy, filename=f"{busy}.mp3", status="transcribing"))
        db.commit()
    finally:
        db.close()

    body = client.get("/api/jobs/active").json()

    ids = {job["id"] for job in body}
    assert busy in ids
    assert ids.isdisjoint(set(done))


def test_the_active_endpoint_includes_a_job_whose_export_is_running(client):
    """
    `status` returns to `completed` the moment analysis finishes and says
    nothing about a render queued behind it. Polling on `status` alone would
    stop the timer while FFmpeg was still going.
    """
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(
            Job(
                id=job_id,
                filename=f"{job_id}.mp3",
                status="completed",
                export_status="exporting",
            )
        )
        db.commit()
    finally:
        db.close()

    body = client.get("/api/jobs/active").json()

    row = next(job for job in body if job["id"] == job_id)
    assert row["export_status"] == "exporting"


def test_the_active_endpoint_is_not_shadowed_by_the_job_route(client):
    """
    Same trap `/presets` sits above: declared after `/{job_id}`, this path is
    read as a job id and answers 404.
    """
    response = client.get("/api/jobs/active")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_the_active_endpoint_carries_no_row_bodies(client):
    """
    It exists to be small. The fields that do not change while a job runs -
    filename, prompt, preset, timestamps - have no business on a response
    fetched every three seconds.
    """
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(
            Job(
                id=job_id,
                filename=f"{job_id}.mp3",
                status="analyzing",
                prompt="flag income claims",
                original_filename="seminar.mp3",
            )
        )
        db.commit()
    finally:
        db.close()

    row = next(j for j in client.get("/api/jobs/active").json() if j["id"] == job_id)

    assert set(row) == {"id", "status", "export_status", "violation_count"}
