"""
The two "not without a human" flags, as far as the review screen can see them.

`worker._is_pre_accepted` has always known that an unplaced quote or an
unevidenced filler is not safe to apply unattended, and has always left those
rows pending. What it could not do was say so: the flags lived on the
detectors' dataclasses, and the only trace they left on the row was a sentence
prepended to `reasoning` - unfilterable, unsortable, and indistinguishable from
the model's own words. These tests pin the round trip from the column to the
JSON the frontend reads.

The list route builds its `ViolationResponse` field by field, so a new column
reaches it only if someone adds it there; that is exactly the omission worth a
test.
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
    def _make(flags):
        """flags: (is_approximate, is_ambiguous) pairs, laid out a second apart."""
        job_id = str(uuid.uuid4())
        db = SessionLocal()
        try:
            db.add(Job(id=job_id, filename=f"{job_id}.mp3", status="completed"))
            for i, (approximate, ambiguous) in enumerate(flags):
                db.add(Violation(
                    id=f"{job_id}-{i}", job_id=job_id, text="like",
                    start_time=float(i), end_time=float(i) + 0.5,
                    label="Filler Word", status="pending", action="cut",
                    is_approximate=approximate, is_ambiguous=ambiguous,
                ))
            db.commit()
        finally:
            db.close()
        return job_id
    return _make


def test_the_list_route_carries_both_flags(client, make_job):
    job_id = make_job([(False, False), (True, False), (False, True)])

    body = client.get(f"/api/jobs/{job_id}/violations").json()

    assert [(v["is_approximate"], v["is_ambiguous"]) for v in body] == [
        (False, False), (True, False), (False, True),
    ]


def test_the_patch_response_carries_them_too(client, make_job):
    """
    The review page re-renders from the PATCH's response, so a badge that
    disappeared the moment the reviewer pressed Accept would be worse than no
    badge at all.
    """
    job_id = make_job([(True, False)])

    body = client.patch(
        f"/api/jobs/{job_id}/violations/{job_id}-0", json={"status": "accepted"},
    ).json()

    assert body["status"] == "accepted"
    assert body["is_approximate"] is True
    assert body["is_ambiguous"] is False


def test_a_row_written_without_the_flags_reads_as_false(client):
    """
    Every writer sets them, but a migrated row predates all of them. The API
    contract is a boolean either way - `null` would render as a missing badge
    in one place and a crash in another.
    """
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Job(id=job_id, filename=f"{job_id}.mp3", status="completed"))
        db.add(Violation(
            id=f"{job_id}-0", job_id=job_id, text="um",
            start_time=0.0, end_time=0.5, label="Filler Word",
            status="pending", action="cut",
        ))
        db.commit()
    finally:
        db.close()

    body = client.get(f"/api/jobs/{job_id}/violations").json()

    assert body[0]["is_approximate"] is False
    assert body[0]["is_ambiguous"] is False


def test_the_flags_are_not_writable_through_the_patch(client, make_job):
    """
    Whether a suggestion may be applied unreviewed is the server's judgement,
    made once in `_is_pre_accepted` from the detector's own output. A client
    that could clear the flag could talk the next `Clean All` into a cut the
    detector never stood behind, so `ViolationUpdate` does not carry them.
    """
    job_id = make_job([(False, True)])

    client.patch(
        f"/api/jobs/{job_id}/violations/{job_id}-0",
        json={"status": "accepted", "is_ambiguous": False},
    )

    body = client.get(f"/api/jobs/{job_id}/violations").json()
    assert body[0]["is_ambiguous"] is True
