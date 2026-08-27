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


class BulkViolationUpdate(ViolationUpdate):
    # Exactly which rows to move. Undo needs this: a sweep is undone by putting
    # back the rows it actually changed, not every row that now happens to look
    # like them - an edit accepted by hand before the sweep is not the sweep's
    # to revert. None means "every row the filters select".
    ids: list[str] | None = None


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
    # Staleness, as data rather than as something the client has to remember: an
    # export is current only while `export_revision` still equals
    # `edit_revision`. NULL export_revision means "no export of known
    # provenance", which is not the same as stale.
    edit_revision: int = 0
    export_revision: int | None = None
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


class ReanalyzeRequest(BaseModel):
    """A second question about a transcript that has already been made."""

    prompt: str | None = None
    preset: str | None = None


class ReanalyzeResponse(BaseModel):
    job_id: str
    prompt: str | None = None
    preset: str | None = None
    # Queued on the same worker as everything else, so this is the state to
    # start polling rather than a result.
    status: str = "analyzing"


class TranscriptSegment(BaseModel):
    """One line of the transcript, with the timing the review UI seeks to."""
    start: float
    end: float
    text: str


class TranscriptResponse(BaseModel):
    job_id: str
    language: str | None = None
    duration: float | None = None
    segments: list[TranscriptSegment]


class AdminStats(BaseModel):
    total_jobs: int
    total_violations: int
    jobs_by_status: dict[str, int]
    total_uploads_size_mb: float
    total_exports_size_mb: float
    files_count: int
