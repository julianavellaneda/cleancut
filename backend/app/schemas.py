"""
Pydantic schemas for request/response validation.
"""

from datetime import datetime
from pydantic import BaseModel


class ViolationBase(BaseModel):
    text: str
    start_time: float
    end_time: float
    label: str | None = None
    rule_violated: str | None = None
    severity: str | None = None
    reasoning: str | None = None


class ViolationCreate(ViolationBase):
    pass


class ViolationResponse(ViolationBase):
    id: str
    job_id: str
    status: str
    action: str

    class Config:
        from_attributes = True


class ViolationUpdate(BaseModel):
    status: str | None = None  # pending, accepted, rejected
    action: str | None = None  # cut, mute


class JobBase(BaseModel):
    filename: str
    original_filename: str | None = None
    media_type: str = "audio"
    prompt: str | None = None


class JobCreate(JobBase):
    auto_fix: bool = False
    auto_scrub: bool = False
    preset: str | None = None


class JobResponse(JobBase):
    id: str
    status: str  # pending, transcribing, analyzing, completed, failed
    auto_fix: bool = False
    auto_scrub: bool = False
    preset: str | None = None
    duration_seconds: float | None = None
    language: str | None = None
    created_at: datetime
    error_message: str | None = None
    # Export runs on the worker queue; the frontend polls these two the same way
    # it polls `status` for the processing stages.
    export_status: str = "none"  # none, queued, exporting, ready, failed
    export_error: str | None = None
    violation_count: int = 0
    pending_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    id: str
    filename: str
    original_filename: str | None = None
    media_type: str = "audio"
    prompt: str | None = None
    status: str
    auto_fix: bool = False
    auto_scrub: bool = False
    preset: str | None = None
    duration_seconds: float | None = None
    created_at: datetime
    violation_count: int = 0

    class Config:
        from_attributes = True


class PresetResponse(BaseModel):
    """A selectable rule preset the analyzer can run instead of a free-form prompt."""
    id: str
    name: str
    description: str


class ExportRequest(BaseModel):
    # None = honor each violation's own action; set to force one action globally
    edit_action: str | None = None  # cut or mute


class ExportResponse(BaseModel):
    job_id: str
    export_filename: str
    message: str
    # Export is queued, not rendered inline, so the POST answers with the state
    # the caller should start polling rather than with a finished file.
    export_status: str = "queued"


class AdminStats(BaseModel):
    total_jobs: int
    total_violations: int
    jobs_by_status: dict[str, int]
    total_uploads_size_mb: float
    total_exports_size_mb: float
    files_count: int
