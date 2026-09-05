"""
Three inputs that used to be accepted and cost transcript.

They are grouped because they share a failure shape rather than a module: each
one turned a bad setting or a bad file into a *plausible* result - a partial
analysis that reads as complete, a cut where a mute was asked for, a clean
report on a file nobody could read. A compliance tool may return "nothing
found" only when something actually looked.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.routes.audio as audio_routes
import app.services.exports as exports
from app.analysis.prompt_analyzer import PromptAnalyzer, _validated_chunk_size
from app.analysis.transcriber import TranscriptFormatError, load_transcript
from app.database import SessionLocal, init_db
from app.main import app
from app.models import Job, Violation
from app.schemas import EDIT_ACTIONS, ExportRequest


@pytest.fixture(autouse=True)
def db_ready():
    init_db()
    yield


@pytest.fixture
def client(monkeypatch, tmp_path):
    """The API with the render queue stubbed out - nothing here should render."""
    monkeypatch.setattr(
        audio_routes, "enqueue_export", lambda job_id, edit_action=None, db=None: "task"
    )
    monkeypatch.setattr(audio_routes, "publish", lambda task: task)
    monkeypatch.setattr(exports, "EXPORT_DIR", tmp_path)
    return TestClient(app)


@pytest.fixture
def completed_job_with_accepted_edit(monkeypatch, tmp_path):
    """A job the export route would otherwise happily queue."""
    job_id = str(uuid.uuid4())
    media = tmp_path / f"{job_id}.mp3"
    media.write_bytes(b"not really audio")
    monkeypatch.setattr(audio_routes, "_get_audio_path", lambda jid: media)

    db = SessionLocal()
    try:
        db.add(Job(id=job_id, filename=media.name, status="completed"))
        db.add(
            Violation(
                id=str(uuid.uuid4()),
                job_id=job_id,
                text="x",
                start_time=1.0,
                end_time=2.0,
                action="cut",
                status="accepted",
            )
        )
        db.commit()
    finally:
        db.close()
    return job_id


# --- 1. chunk settings that skip transcript ---------------------------------


@pytest.fixture
def analyzer_factory(monkeypatch):
    """A PromptAnalyzer that never reaches a provider."""

    class _Provider:
        def complete(self, system_prompt, user_prompt):  # pragma: no cover
            raise AssertionError("no LLM call expected in these tests")

    def _make(**kwargs):
        return PromptAnalyzer(provider=_Provider(), **kwargs)

    return _make


@pytest.mark.parametrize("bad", [0, -1, -50])
def test_non_positive_chunk_size_is_rejected(analyzer_factory, bad):
    """
    A window of zero segments covers nothing: every chunk is empty and the
    whole transcript goes unanalyzed while the run still reports a result.
    """
    with pytest.raises(ValueError, match="chunk_size"):
        analyzer_factory(chunk_size=bad)


@pytest.mark.parametrize("bad", [-1, -10])
def test_negative_overlap_is_rejected(analyzer_factory, bad):
    """
    The chunker steps by ``chunk_size - overlap``. A negative overlap makes the
    step wider than the window, so segments in the gap are never sent anywhere.
    """
    with pytest.raises(ValueError, match="overlap"):
        analyzer_factory(overlap=bad)


@pytest.mark.parametrize("bad", [1.5, "50", True, None])
def test_chunk_size_must_be_a_whole_number(bad):
    if bad is None:
        # None is the one non-int that means something: "decide from the
        # transcript length".
        assert _validated_chunk_size(None) is None
        return
    with pytest.raises(ValueError):
        _validated_chunk_size(bad)


@pytest.mark.parametrize("good", [1, 25, 500])
def test_valid_chunk_settings_are_kept_verbatim(analyzer_factory, good):
    analyzer = analyzer_factory(chunk_size=good, overlap=0)
    assert analyzer.chunk_size == good
    assert analyzer.overlap == 0


def test_chunk_ranges_cover_every_segment_with_no_gap(analyzer_factory):
    """The invariant the validation exists to protect."""
    analyzer = analyzer_factory()
    ranges = analyzer._chunk_ranges(237, chunk_size=50, overlap=10)
    covered = {i for start, end in ranges for i in range(start, end)}
    assert covered == set(range(237))
    assert all(end > start for start, end in ranges)


def test_chunk_ranges_refuses_a_window_that_covers_nothing(analyzer_factory):
    analyzer = analyzer_factory()
    with pytest.raises(ValueError):
        analyzer._chunk_ranges(100, chunk_size=0, overlap=0)
    with pytest.raises(ValueError):
        analyzer._chunk_ranges(100, chunk_size=50, overlap=-5)


def test_empty_transcript_analyzes_to_nothing_without_tripping_the_window(
    analyzer_factory,
):
    """
    A transcript of no segments would derive a chunk size of 0. It is answered
    before the chunker, so the window invariant can stay unconditional.
    """
    from app.analysis.transcriber import TranscriptResult

    result = analyzer_factory().analyze(
        TranscriptResult(segments=[], language="en", duration=0.0)
    )
    assert result.violations == []
    assert result.total_segments == 0
    assert result.is_partial is False


# --- 2. an unknown export action used to become a cut -----------------------


@pytest.mark.parametrize("action", list(EDIT_ACTIONS) + [None])
def test_known_export_actions_are_accepted(action):
    assert ExportRequest(edit_action=action).edit_action == action


@pytest.mark.parametrize("action", ["mutee", "CUT", "delete", "", "silence"])
def test_unknown_export_action_is_rejected(action):
    """
    `partition_edits` reads anything that is not "mute" as a cut, so a typo used
    to render every accepted span *removed* - the destructive half of the pair,
    and the opposite of what someone typing "mutee" wanted.
    """
    with pytest.raises(ValidationError):
        ExportRequest(edit_action=action)


def test_export_route_rejects_an_unknown_action(
    client, completed_job_with_accepted_edit
):
    job_id = completed_job_with_accepted_edit
    response = client.post(f"/api/jobs/{job_id}/export", json={"edit_action": "mutee"})
    assert response.status_code == 422
    assert "edit_action" in response.text


def test_export_route_still_accepts_mute(client, completed_job_with_accepted_edit):
    job_id = completed_job_with_accepted_edit
    response = client.post(f"/api/jobs/{job_id}/export", json={"edit_action": "mute"})
    assert response.status_code == 202


def test_violation_actions_share_one_owner():
    """
    The PATCH, the bulk update and the export override all mean the same two
    words. A second spelling is how one of the three drifts.
    """
    from app.routes.violations import ACTIONS

    assert ACTIONS is EDIT_ACTIONS


# --- 3. a transcript file nobody could read -------------------------------


def _write(tmp_path, text):
    path = tmp_path / "transcript.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_transcript_with_no_timestamps_is_an_error(tmp_path):
    """
    Every line discarded used to give an empty transcript, which analyzes to
    "nothing found" and prints as a clean recording.
    """
    path = _write(
        tmp_path, "Speaker 1: we made forty thousand last month\nSpeaker 2: wow\n"
    )
    with pytest.raises(TranscriptFormatError) as excinfo:
        load_transcript(path)
    assert "Speaker 1" in str(excinfo.value)
    assert "[0.0s - 2.2s]" in str(excinfo.value)


def test_empty_transcript_file_is_an_error(tmp_path):
    path = _write(tmp_path, "\n   \n\n")
    with pytest.raises(TranscriptFormatError, match="empty"):
        load_transcript(path)


def test_partially_readable_transcript_loads_and_warns(tmp_path, capsys):
    path = _write(
        tmp_path,
        "# exported by some other tool\n"
        "[0.0s - 2.2s] we made forty thousand last month\n"
        "Speaker 2: wow\n"
        "[2.2s - 4.0s] results not typical\n",
    )
    result = load_transcript(path)

    assert [s.text for s in result.segments] == [
        "we made forty thousand last month",
        "results not typical",
    ]
    assert result.duration == pytest.approx(4.0)

    warning = capsys.readouterr().out
    assert "skipped 2 line(s)" in warning


def test_fully_readable_transcript_warns_about_nothing(tmp_path, capsys):
    path = _write(tmp_path, "[0.0s - 2.2s] one\n\n[2.2s - 4.0s] two\n")
    result = load_transcript(path)
    assert len(result.segments) == 2
    assert "skipped" not in capsys.readouterr().out
