"""
SQLAlchemy models for Job and Violation.
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Text, ForeignKey, DateTime, Boolean
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
    duration_seconds = Column(Float, nullable=True)
    language = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)
    waveform_data = Column(Text, nullable=True)  # JSON string of waveform peaks

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
