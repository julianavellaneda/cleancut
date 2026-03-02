"""
Violation routes - list and update violation status.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Job, Violation
from ..schemas import ViolationResponse, ViolationUpdate

router = APIRouter()


@router.get("/{job_id}/violations", response_model=List[ViolationResponse])
def list_violations(job_id: str, db: Session = Depends(get_db)):
    """List all violations for a job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    violations = (
        db.query(Violation)
        .filter(Violation.job_id == job_id)
        .order_by(Violation.start_time)
        .all()
    )

    return [
        ViolationResponse(
            id=v.id,
            job_id=v.job_id,
            text=v.text,
            start_time=v.start_time,
            end_time=v.end_time,
            label=v.label,
            rule_violated=v.rule_violated,
            severity=v.severity,
            reasoning=v.reasoning,
            status=v.status,
            action=v.action
        )
        for v in violations
    ]


@router.patch("/{job_id}/violations/{violation_id}", response_model=ViolationResponse)
def update_violation(
    job_id: str,
    violation_id: str,
    update: ViolationUpdate,
    db: Session = Depends(get_db)
):
    """Update violation status (accept/reject)."""
    violation = (
        db.query(Violation)
        .filter(Violation.id == violation_id, Violation.job_id == job_id)
        .first()
    )

    if not violation:
        raise HTTPException(status_code=404, detail="Violation not found")

    # Update fields if provided
    if update.status is not None:
        if update.status not in ["pending", "accepted", "rejected"]:
            raise HTTPException(
                status_code=400,
                detail="Status must be 'pending', 'accepted', or 'rejected'"
            )
        violation.status = update.status

    if update.action is not None:
        if update.action not in ["cut", "mute"]:
            raise HTTPException(
                status_code=400,
                detail="Action must be 'cut' or 'mute'"
            )
        violation.action = update.action

    db.commit()
    db.refresh(violation)

    return violation


@router.post("/{job_id}/violations/bulk-update")
def bulk_update_violations(
    job_id: str,
    update: ViolationUpdate,
    labels: List[str] | None = Query(None),
    db: Session = Depends(get_db)
):
    """Update multiple pending violations for a job, optionally filtered by label."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    query = db.query(Violation).filter(
        Violation.job_id == job_id, 
        Violation.status == "pending"
    )

    if labels:
        query = query.filter(Violation.label.in_(labels))

    violations = query.all()

    updated_count = 0
    for v in violations:
        if update.status is not None:
            v.status = update.status
        if update.action is not None:
            v.action = update.action
        updated_count += 1

    db.commit()

    return {"message": f"Updated {updated_count} violations"}
