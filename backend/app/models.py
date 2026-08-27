"""
SQLAlchemy models for Job and Violation.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship

from .database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Job(Base):
    """Represents an audio processing job."""
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=True)  # Track the extension (mp4, mov, mp3)
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
    export_status = Column(String, default="none")  # none, queued, exporting, ready, failed
    export_error = Column(Text, nullable=True)
    # Monotonic counter over the *accepted* edit set: bumped whenever a decision
    # or an action changes what a render would produce. `export_revision` records
    # which revision the file in exports/ was rendered from, so "is this export
    # still the edit list on screen" is a comparison rather than a guess. NULL
    # means no export whose provenance we know - a row migrated in from before
    # these columns, or a job that has never exported.
    edit_revision = Column(Integer, default=0, nullable=False)
    export_revision = Column(Integer, nullable=True)

    violations = relationship("Violation", back_populates="job", cascade="all, delete-orphan")


class Violation(Base):
    """Represents a detected compliance violation."""
    __tablename__ = "violations"

    id = Column(String, primary_key=True, default=generate_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    text = Column(Text, nullable=False)  # Quoted text
    start_time = Column(Float, nullable=False)  # Seconds
    end_time = Column(Float, nullable=False)  # Seconds
    label = Column(String, nullable=True)  # Generic label (e.g., "Filler Word", "Off-topic")
    rule_violated = Column(String, nullable=True)  # Deprecated in favor of label, but keeping for compatibility
    severity = Column(String, nullable=True)  # high, medium, low
    reasoning = Column(Text, nullable=True)  # AI explanation
    status = Column(String, default="pending")  # pending, accepted, rejected
    action = Column(String, default="cut")  # cut, mute

    job = relationship("Job", back_populates="violations")
