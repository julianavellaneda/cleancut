"""
Pydantic schemas for request/response validation.
"""

from datetime import datetime
from pydantic import BaseModel


class ViolationBase(BaseModel):
    text: str
    start_time: float
    end_time: float
    rule_violated: str | None = None
    severity: str | None = None
    reasoning: str | None = None


class ViolationCreate(ViolationBase):
    pass


class ViolationResponse(ViolationBase):
    id: str
    job_id: str
    status: str
    edit_action: str

    class Config:
        from_attributes = True


class ViolationUpdate(BaseModel):
    status: str | None = None  # pending, accepted, rejected
    edit_action: str | None = None  # cut, mute


class JobBase(BaseModel):
    filename: str


class JobCreate(JobBase):
    pass


class JobResponse(JobBase):
    id: str
    status: str
    duration_seconds: float | None = None
    language: str | None = None
    created_at: datetime
    error_message: str | None = None
    violation_count: int = 0
    pending_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    id: str
    filename: str
    status: str
    duration_seconds: float | None = None
    created_at: datetime
    violation_count: int = 0

    class Config:
        from_attributes = True


class ExportRequest(BaseModel):
    edit_action: str = "cut"  # cut or mute


class ExportResponse(BaseModel):
    job_id: str
    export_filename: str
    message: str
