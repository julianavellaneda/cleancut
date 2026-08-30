"""
Locks in transcript persistence.

The regression this exists to prevent is the original behaviour: the transcript
was computed, handed to the analyzer, and dropped, so the slowest stage of the
job produced nothing anyone could read afterwards.

The specific things that must not drift:
  - the worker stores the transcript *before* analysis, so a job that ends up
    with a partial or failed analysis still keeps the text;
  - an unreadable or absent transcript is a 404, never an empty segment list -
    "nothing stored" and "this recording is silent" are different claims;
  - words are stored but not *served*: re-analysis needs the timing to place a
    quote as precisely as the first pass did, and the panel needs lines. A row
    written before words were stored still reads.

No FFmpeg, no Whisper, no LLM: the processor is stubbed, exactly as in
test_worker_autofix.
"""

import json
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.services.exports as exports
import app.services.worker as worker
from app.analysis.prompt_analyzer import AnalysisResult
from app.analysis.transcriber import Segment, TranscriptResult, Word
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Job
from app.services import transcripts


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _segment(start, end, text, with_words=True):
    words = (
        [Word(text=w, start=start, end=end, probability=0.9) for w in text.split()]
        if with_words
        else []
    )
    return Segment(text=text, start=start, end=end, words=words, language="en")


def _transcript(*segments, language="en", duration=60.0):
    return TranscriptResult(segments=list(segments), language=language, duration=duration)


def _stored(job_id):
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == job_id).first().transcript
    finally:
        db.close()


# --- serialization -----------------------------------------------------------


def test_round_trip_preserves_lines_and_timing():
    raw = transcripts.to_json(
        _transcript(_segment(0.0, 2.5, "Ninety percent of people quit."))
    )
    restored = transcripts.from_json(raw)

    assert restored is not None
    assert restored.language == "en"
    assert restored.duration == 60.0
    assert [(s.start, s.end, s.text) for s in restored.segments] == [
        (0.0, 2.5, "Ninety percent of people quit.")
    ]


def test_word_timing_is_stored():
    """
    It deliberately was not, on size grounds, until re-analysis needed it: an
    LLM quote can only be placed as precisely as the timing behind it, and a
    re-run that produced coarser markers than the first pass would put two
    kinds of precision on one review screen.
    """
    payload = json.loads(transcripts.to_json(_transcript(_segment(0.0, 1.0, "one two three"))))

    assert payload["version"] == 2
    assert [w["text"] for w in payload["segments"][0]["words"]] == ["one", "two", "three"]


def test_a_line_with_no_word_timing_stores_no_words_key():
    """
    Not `"words": []`. A line Whisper timed no words in has to read back exactly
    like a line from a version 1 row - one absence, not two.
    """
    payload = json.loads(
        transcripts.to_json(_transcript(_segment(0.0, 1.0, "one two", with_words=False)))
    )

    assert payload["segments"] == [{"start": 0.0, "end": 1.0, "text": "one two"}]


def test_a_version_1_row_still_reads():
    """The rows already in the database, which have no words at all."""
    raw = json.dumps({
        "version": 1, "language": "en", "duration": 12.0,
        "segments": [{"start": 0.0, "end": 2.0, "text": "no words here"}],
    })

    restored = transcripts.from_json(raw)

    assert restored is not None
    assert restored.segments[0].words == ()


def test_malformed_words_are_dropped_and_the_line_survives():
    """
    One unparseable word costs the precision of one quote. Refusing the whole
    transcript over it would cost the panel and every other line's timing.
    """
    raw = json.dumps({
        "version": 2, "language": "en", "duration": 12.0,
        "segments": [{"start": 0.0, "end": 2.0, "text": "a b", "words": [
            {"start": 0.0, "end": 0.5, "text": "a"},
            {"start": "nope", "end": 1.0, "text": "b"},
            {"start": 1.0, "end": 1.5},
            "not a word at all",
        ]}],
    })

    restored = transcripts.from_json(raw)

    assert [w.text for w in restored.segments[0].words] == ["a"]


def test_a_stored_transcript_rebuilds_into_something_the_analyzer_can_read():
    """What re-analysis runs on: the same shape transcription hands over."""
    stored = transcripts.from_json(
        transcripts.to_json(_transcript(_segment(0.0, 1.0, "one two three")))
    )

    rebuilt = transcripts.to_transcript_result(stored)

    assert rebuilt.language == "en"
    assert rebuilt.duration == 60.0
    assert [w.text for w in rebuilt.segments[0].words] == ["one", "two", "three"]


def test_segment_text_is_trimmed():
    """Whisper hands back leading spaces; they would show up in the panel."""
    payload = json.loads(transcripts.to_json(_transcript(_segment(0.0, 1.0, "  padded  "))))
    assert payload["segments"][0]["text"] == "padded"


@pytest.mark.parametrize("raw", [None, "", "not json", "[]", "{}", '{"segments": []}'])
def test_unusable_rows_read_as_absent(raw):
    assert transcripts.from_json(raw) is None


def test_malformed_segments_are_dropped_not_fatal():
    """A hand-edited or truncated row must not 500 a read-only panel."""
    raw = json.dumps(
        {
            "version": 1,
            "segments": [
                {"start": "x", "end": 1.0, "text": "bad timing"},
                {"start": 0.0, "end": 1.0},
                {"start": 2.0, "end": 3.0, "text": "good"},
            ],
        }
    )
    restored = transcripts.from_json(raw)

    assert [s.text for s in restored.segments] == ["good"]


# --- the worker --------------------------------------------------------------


@pytest.fixture
def run_job(monkeypatch, tmp_path):
    """Run the worker's job body against a stubbed transcriber and analyzer."""

    def _run(transcript, analyze=None):
        class StubProcessor:
            def transcribe(self, path, language=None):
                return transcript

            def analyze(self, transcript, prompt=None, preset=None):
                if analyze is not None:
                    return analyze(transcript)
                return AnalysisResult(
                    violations=[], total_segments_analyzed=0, transcript_language="en"
                )

        monkeypatch.setattr(worker, "get_processor", lambda: StubProcessor())
        monkeypatch.setattr(exports, "EXPORT_DIR", tmp_path)
        monkeypatch.setattr(
            worker, "decode_pcm_mono", lambda path, sr=8000: np.zeros(sr, dtype=np.float32)
        )
        monkeypatch.setattr(
            worker.Scrubber, "detect_silence", staticmethod(lambda t, *a, **k: [])
        )
        monkeypatch.setattr(
            worker.Scrubber, "detect_filler_words", staticmethod(lambda t: [])
        )

        job_id = str(uuid.uuid4())
        media = tmp_path / f"{job_id}.mp3"
        media.write_bytes(b"not really audio")

        db = SessionLocal()
        try:
            db.add(Job(id=job_id, filename=media.name, status="pending"))
            db.commit()
        finally:
            db.close()

        worker._process_job_sequentially(job_id, str(media))
        return job_id

    return _run


def test_worker_persists_the_transcript(run_job):
    job_id = run_job(_transcript(_segment(0.0, 2.0, "Results are not typical.")))

    restored = transcripts.from_json(_stored(job_id))
    assert [s.text for s in restored.segments] == ["Results are not typical."]


def test_transcript_survives_a_failed_analysis(run_job):
    """
    Stored before the analyzer runs, on purpose: the LLM is the stage that
    fails, and re-running it is cheap next to re-transcribing an hour of audio.
    """

    def blow_up(_transcript):
        raise RuntimeError("the model returned something unreadable")

    job_id = run_job(_transcript(_segment(0.0, 2.0, "kept anyway")), analyze=blow_up)

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        assert job.status == "failed"
    finally:
        db.close()

    restored = transcripts.from_json(_stored(job_id))
    assert [s.text for s in restored.segments] == ["kept anyway"]


# --- the endpoint ------------------------------------------------------------


def _make_job(**kwargs):
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        db.add(Job(id=job_id, filename=f"{job_id}.mp3", status="completed", **kwargs))
        db.commit()
    finally:
        db.close()
    return job_id


def test_endpoint_serves_the_stored_lines(client):
    job_id = _make_job(
        language="en",
        duration_seconds=12.0,
        transcript=transcripts.to_json(
            _transcript(
                _segment(0.0, 2.0, "First line."),
                _segment(2.0, 4.0, "Second line."),
                duration=12.0,
            )
        ),
    )

    response = client.get(f"/api/jobs/{job_id}/transcript")

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert body["language"] == "en"
    assert body["duration"] == 12.0
    assert [s["text"] for s in body["segments"]] == ["First line.", "Second line."]


def test_endpoint_404s_for_a_job_with_no_transcript(client):
    """A job from before the column existed, or one that never got that far."""
    job_id = _make_job(transcript=None)

    assert client.get(f"/api/jobs/{job_id}/transcript").status_code == 404


def test_endpoint_404s_for_an_unreadable_transcript(client):
    job_id = _make_job(transcript="{ truncated")

    assert client.get(f"/api/jobs/{job_id}/transcript").status_code == 404


def test_endpoint_404s_for_an_unknown_job(client):
    assert client.get(f"/api/jobs/{uuid.uuid4()}/transcript").status_code == 404


def test_transcript_route_is_not_shadowed_by_the_job_route(client):
    """
    /{job_id} is declared first; a path with an extra segment must still reach
    the transcript handler rather than being swallowed as a job id.
    """
    job_id = _make_job(transcript=transcripts.to_json(_transcript(_segment(0.0, 1.0, "hi"))))

    body = client.get(f"/api/jobs/{job_id}/transcript").json()
    assert "segments" in body
