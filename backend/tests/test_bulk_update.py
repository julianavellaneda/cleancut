"""
Tests for POST /{job_id}/violations/bulk-update.

Two things this locks down.

"Clean All" was one-way. The endpoint only ever selected `status == "pending"`,
so once a sweep had accepted forty filler words there was no bulk move back -
the reviewer's only route out was forty clicks. `from_status` makes the same
call run in reverse, and defaults to pending so the sweep itself is unchanged:
an edit the reviewer already rejected by hand must not be accepted out from
under them by a later sweep.

And the endpoint wrote whatever it was given. The single-violation PATCH
validated `status` and `action` against their allowed values; the bulk route
did not, so one request could put every row in a job into a state nothing else
in the system knows how to read.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture
def make_job():
    def _make(violations):
        """violations: (label, status) pairs, laid out a second apart."""
        job_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(Job(id=job_id, filename=f"{job_id}.mp3", status="completed"))
            for i, (label, status) in enumerate(violations):
                db.add(Violation(
                    id=str(uuid.uuid4()), job_id=job_id, text="x",
                    start_time=float(i), end_time=float(i) + 0.5,
                    label=label, status=status, action="cut",
                ))
            db.commit()
        finally:
            db.close()
        return job_id
    return _make


def _statuses(job_id):
    db = SessionLocal()
    try:
        rows = (db.query(Violation)
                .filter(Violation.job_id == job_id)
                .order_by(Violation.start_time).all())
        return [(v.label, v.status) for v in rows]
    finally:
        db.close()


def _bulk(client, job_id, body, **params):
    return client.post(
        f"/api/jobs/{job_id}/violations/bulk-update", json=body, params=params
    )


# --- the sweep, unchanged ---------------------------------------------------

def test_clean_all_still_only_touches_pending(client, make_job):
    """
    The default has to stay pending-only. A reviewer who rejected an edit by
    hand has made a decision; a later "Clean All" must not overwrite it.
    """
    job_id = make_job([
        ("Filler Word", "pending"),
        ("Filler Word", "rejected"),
        ("Income Claims", "pending"),
    ])

    response = _bulk(client, job_id, {"status": "accepted"}, labels=["Filler Word"])

    assert response.status_code == 200
    assert response.json()["updated"] == 1
    assert _statuses(job_id) == [
        ("Filler Word", "accepted"),
        ("Filler Word", "rejected"),
        ("Income Claims", "pending"),
    ]


# --- undo -------------------------------------------------------------------

def test_an_accepted_sweep_can_be_put_back(client, make_job):
    """The headline fix: the same call, pointed the other way."""
    job_id = make_job([("Filler Word", "accepted")] * 3 + [("Income Claims", "accepted")])

    response = _bulk(client, job_id, {"status": "pending"},
                     labels=["Filler Word"], from_status=["accepted"])

    assert response.json()["updated"] == 3
    assert _statuses(job_id) == [
        ("Filler Word", "pending"),
        ("Filler Word", "pending"),
        ("Filler Word", "pending"),
        ("Income Claims", "accepted"),
    ]


def test_undo_leaves_a_hand_rejected_edit_where_it_is(client, make_job):
    """
    Undoing a sweep restores what the sweep did, not everything in the job. An
    edit rejected by hand was never part of the sweep and stays rejected.
    """
    job_id = make_job([("Filler Word", "accepted"), ("Filler Word", "rejected")])

    _bulk(client, job_id, {"status": "pending"},
          labels=["Filler Word"], from_status=["accepted"])

    assert _statuses(job_id) == [("Filler Word", "pending"), ("Filler Word", "rejected")]


def test_several_source_statuses_can_be_swept_at_once(client, make_job):
    """"Reject everything still undecided or accepted" is one call."""
    job_id = make_job([
        ("Filler Word", "pending"),
        ("Filler Word", "accepted"),
        ("Filler Word", "rejected"),
    ])

    response = _bulk(client, job_id, {"status": "rejected"},
                     from_status=["pending", "accepted"])

    assert response.json()["updated"] == 2
    assert {s for _, s in _statuses(job_id)} == {"rejected"}


# --- validation the bulk route never had ------------------------------------

@pytest.mark.parametrize("body", [{"status": "banana"}, {"action": "obliterate"}])
def test_an_unknown_value_is_refused(client, make_job, body):
    job_id = make_job([("Filler Word", "pending")])

    response = _bulk(client, job_id, body)

    assert response.status_code == 400
    assert _statuses(job_id) == [("Filler Word", "pending")]


def test_an_unknown_source_status_is_refused(client, make_job):
    """
    A typo here would silently match nothing and report "Updated 0", which
    reads as "there was nothing to do" rather than "you asked for nonsense".
    """
    job_id = make_job([("Filler Word", "accepted")])

    response = _bulk(client, job_id, {"status": "pending"}, from_status=["acceptd"])

    assert response.status_code == 400
    assert _statuses(job_id) == [("Filler Word", "accepted")]


def test_an_unknown_job_is_a_404(client):
    response = _bulk(client, str(uuid.uuid4()), {"status": "accepted"})

    assert response.status_code == 404


# --- naming the rows outright -----------------------------------------------

def _ids(job_id):
    db = SessionLocal()
    try:
        return [v.id for v in db.query(Violation)
                .filter(Violation.job_id == job_id)
                .order_by(Violation.start_time).all()]
    finally:
        db.close()


def test_ids_move_exactly_the_rows_named(client, make_job):
    """
    What undo actually needs. Reverting by label would also revert an edit the
    reviewer accepted by hand before the sweep ran; reverting by id puts back
    only what the sweep touched.
    """
    job_id = make_job([("Filler Word", "accepted")] * 3)
    swept = _ids(job_id)[:2]

    response = _bulk(client, job_id, {"status": "pending", "ids": swept},
                     from_status=["accepted"])

    assert response.json()["updated"] == 2
    assert _statuses(job_id) == [
        ("Filler Word", "pending"),
        ("Filler Word", "pending"),
        ("Filler Word", "accepted"),
    ]


def test_an_empty_id_list_moves_nothing(client, make_job):
    """
    "These zero rows" is a real answer. Falling through to the whole job here
    would turn an undo of nothing into an undo of everything.
    """
    job_id = make_job([("Filler Word", "accepted"), ("Dead Air", "accepted")])

    response = _bulk(client, job_id, {"status": "pending", "ids": []},
                     from_status=["accepted"])

    assert response.json()["updated"] == 0
    assert {s for _, s in _statuses(job_id)} == {"accepted"}


def test_an_id_from_another_job_is_ignored(client, make_job):
    job_id = make_job([("Filler Word", "accepted")])
    other = make_job([("Filler Word", "accepted")])

    response = _bulk(client, job_id, {"status": "pending", "ids": _ids(other)},
                     from_status=["accepted"])

    assert response.json()["updated"] == 0
    assert _statuses(other) == [("Filler Word", "accepted")]
