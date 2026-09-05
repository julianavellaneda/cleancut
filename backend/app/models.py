"""
SQLAlchemy models for Job and Violation.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Job(Base):
    """Represents an audio processing job."""

    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    filename = Column(String, nullable=False)
    original_filename = Column(
        String, nullable=True
    )  # Track the extension (mp4, mov, mp3)
    media_type = Column(String, default="audio")  # 'audio' or 'video'
    prompt = Column(Text, nullable=True)  # User instructions for editing
    status = Column(String, default="pending")  # pending, processing, completed, failed
    auto_fix = Column(Boolean, default=False)
    auto_scrub = Column(Boolean, default=False)  # Apply silence/filler detection
    preset = Column(String, nullable=True)  # Rule preset id, or NULL for prompt mode
    duration_seconds = Column(Float, nullable=True)
    language = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)
    waveform_data = Column(Text, nullable=True)  # JSON string of waveform peaks
    # The transcript the analysis ran on, as JSON (see services/transcripts.py).
    # Kept because transcription is the slowest stage of the job and every
    # reader of it - the review panel, a future re-analysis - would otherwise
    # have to pay for it again. Segments only, no word timing.
    transcript = Column(Text, nullable=True)
    # Export state is tracked separately from `status`. Folding it in would mean a
    # failed re-encode marks the whole job "failed" and throws away the review the
    # user just finished, and there would be no way to tell "never exported" from
    # "export ready".
    export_status = Column(
        String, default="none"
    )  # none, queued, exporting, ready, failed
    export_error = Column(Text, nullable=True)
    # Monotonic counter over the *accepted* edit set: bumped whenever a decision
    # or an action changes what a render would produce. `export_revision` records
    # which revision the file in exports/ was rendered from, so "is this export
    # still the edit list on screen" is a comparison rather than a guess. NULL
    # means no export whose provenance we know - a row migrated in from before
    # these columns, or a job that has never exported.
    edit_revision = Column(Integer, default=0, nullable=False)
    export_revision = Column(Integer, nullable=True)

    violations = relationship(
        "Violation", back_populates="job", cascade="all, delete-orphan"
    )
    # Background work outstanding for this job. Cascaded so deleting a job -
    # by hand or by the retention sweeper - cannot leave a task behind that a
    # restart would then try to replay against a row that is gone.
    tasks = relationship("Task", back_populates="job", cascade="all, delete-orphan")


class Violation(Base):
    """Represents a detected compliance violation."""

    __tablename__ = "violations"

    id = Column(String, primary_key=True, default=generate_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    text = Column(Text, nullable=False)  # Quoted text
    start_time = Column(Float, nullable=False)  # Seconds
    end_time = Column(Float, nullable=False)  # Seconds
    label = Column(
        String, nullable=True
    )  # Generic label (e.g., "Filler Word", "Off-topic")
    rule_violated = Column(
        String, nullable=True
    )  # Deprecated in favor of label, but keeping for compatibility
    severity = Column(String, nullable=True)  # high, medium, low
    reasoning = Column(Text, nullable=True)  # AI explanation
    status = Column(String, default="pending")  # pending, accepted, rejected
    action = Column(String, default="cut")  # cut, mute
    # Why this suggestion was left pending on a job that asked for everything to
    # be applied. `_is_pre_accepted` reads the same two flags off the detector's
    # dataclass before the row is written; keeping them here is what lets the
    # reviewer see the answer, rather than being handed a queue of pending rows
    # on an `auto_fix` job with no way to tell which ones the system itself was
    # unsure about. Not the analyzer's confidence in the *finding* - both mean
    # "not safe to apply with nobody in the room".
    #
    #  - is_approximate: the quote could not be placed against the transcript,
    #    so the span is the model's estimate rather than a measurement.
    #  - is_ambiguous: the word is only sometimes what the detector took it for
    #    ("like" as a comparison, "you know" as a real question).
    is_approximate = Column(Boolean, default=False, nullable=False)
    is_ambiguous = Column(Boolean, default=False, nullable=False)

    job = relationship("Job", back_populates="violations")


class Task(Base):
    """
    One unit of background work, on disk rather than only in memory.

    The worker's queue is a `queue.Queue` in a single process, so before this
    table existed a restart - a deploy, a crash, a laptop lid - silently threw
    away every job that had been accepted but not yet run. The upload had
    returned 202, the row said `pending`, and nothing was ever going to move it
    again. The row here is written *before* the in-memory put, so the durable
    record is never behind the queue; the worker deletes it when the task is
    done, which makes "what is outstanding" a query rather than a guess.

    `attempts` is what keeps a task that kills the process from killing it
    again on every boot: the worker increments it as it picks the task up, and
    a task that has burned through `MAX_ATTEMPTS` is abandoned with the reason
    recorded on the job instead of being replayed forever.
    """

    __tablename__ = "tasks"

    # One outstanding task of each kind per job. A row is deleted the moment its
    # task retires, so this constrains *work in flight*, not history: one
    # analysis, one export and one re-analysis at a time.
    #
    # It exists because the routes' own `has_outstanding()` check is a read
    # followed by a write, with no lock between them. Two export requests
    # arriving together both read "nothing outstanding", both insert, and both
    # render - two FFmpeg passes over the length of the media, writing the same
    # output path. The check stays, because it gives the common case a specific
    # 409 without touching the constraint; this is what makes the answer correct
    # when the two overlap.
    __table_args__ = (UniqueConstraint("job_id", "kind", name="uq_tasks_job_kind"),)

    id = Column(String, primary_key=True, default=generate_uuid)
    kind = Column(String, nullable=False)  # process, export, reanalyze
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False, index=True)
    # The arguments each kind of task needs. Carried here rather than re-derived
    # at replay time: an export's `edit_action` override and a re-analysis's
    # prompt exist nowhere else, and guessing them would run a different job
    # from the one that was asked for.
    file_path = Column(Text, nullable=True)
    edit_action = Column(String, nullable=True)
    prompt = Column(Text, nullable=True)
    preset = Column(String, nullable=True)
    state = Column(String, nullable=False, default="pending")  # pending, running
    attempts = Column(Integer, nullable=False, default=0)
    # Replay order. FIFO is the only ordering the queue ever had, and a restart
    # should not reshuffle work that was already waiting in a particular order.
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="tasks")
