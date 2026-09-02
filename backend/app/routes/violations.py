"""
Violation routes - list and update violation status.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Job, Violation
from ..schemas import (
    EDIT_ACTIONS,
    BulkViolationUpdate,
    ViolationResponse,
    ViolationUpdate,
)
from ..services import exports

router = APIRouter()

STATUSES = ("pending", "accepted", "rejected")
# Re-exported rather than re-spelled: `schemas.EDIT_ACTIONS` is the owner, and
# the export override validates against the same pair.
ACTIONS = EDIT_ACTIONS


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
            action=v.action,
            is_approximate=bool(v.is_approximate),
            is_ambiguous=bool(v.is_ambiguous),
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
    """
    Update violation status (accept/reject).

    A change that alters the accepted edit set also retires the job's export:
    the file in ``exports/`` was rendered from the previous list, and until
    Phase 4 it went on advertising itself as "ready" while describing edits the
    reviewer had since changed.
    """
    violation = (
        db.query(Violation)
        .filter(Violation.id == violation_id, Violation.job_id == job_id)
        .first()
    )

    if not violation:
        raise HTTPException(status_code=404, detail="Violation not found")

    if update.status is not None:
        _validate_status(update.status)
    if update.action is not None:
        _validate_action(update.action)

    changed_export = exports.affects_export(violation, update.status, update.action)

    # Update fields if provided
    if update.status is not None:
        violation.status = update.status

    if update.action is not None:
        violation.action = update.action

    # One transaction for the decision and everything that follows from it. This
    # used to be two commits - the violation, then the invalidation - and a
    # failure in between was unrecoverable by retrying: the second attempt found
    # the status already written, so `affects_export` answered "nothing changed"
    # and the stale export kept advertising itself as ready forever.
    superseded = []
    if changed_export:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            superseded = exports.mark_export_invalidated(job)

    db.commit()

    # After the commit, never before: the revision counters already refuse a
    # stale file on both download routes, so a failed unlink costs disk rather
    # than correctness - while deleting first and then rolling back would have
    # destroyed a file the job still considered current.
    exports.unlink_all(superseded)

    db.refresh(violation)

    return violation


@router.post("/{job_id}/violations/bulk-update")
def bulk_update_violations(
    job_id: str,
    update: BulkViolationUpdate,
    labels: List[str] | None = Query(None),
    from_status: List[str] | None = Query(
        None,
        description=(
            "Which statuses to move. Defaults to pending only, so 'Clean All' "
            "cannot silently revisit a decision the reviewer already made."
        ),
    ),
    db: Session = Depends(get_db)
):
    """
    Update several violations at once, optionally filtered by label.

    `ids` and `from_status` are what make a bulk action undoable. `ids` names
    the exact rows to move, which is what undo needs: a sweep is put back by
    restoring the rows it changed, not every row that now looks like them.

    `from_status` defaults to
    `pending`, which is the only safe default for "Clean All": a reviewer who
    has already rejected an edit by hand must not have it accepted out from
    under them by a later sweep. Undo is the same call pointed the other way -
    `from_status=accepted&status=pending` puts the sweep back.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if update.status is not None:
        _validate_status(update.status)
    if update.action is not None:
        _validate_action(update.action)

    sources = from_status or ["pending"]
    for status in sources:
        _validate_status(status)

    query = db.query(Violation).filter(
        Violation.job_id == job_id,
        Violation.status.in_(sources),
    )

    if labels:
        query = query.filter(Violation.label.in_(labels))

    if update.ids is not None:
        # An empty list is a real answer - "these zero rows" - and must not fall
        # through to selecting the whole job.
        query = query.filter(Violation.id.in_(update.ids))

    violations = query.all()

    updated_count = 0
    changed_export = False
    for v in violations:
        # Asked before the row is written, and only once for the whole sweep:
        # the export is retired if *any* accepted edit moved.
        changed_export = changed_export or exports.affects_export(v, update.status, update.action)
        if update.status is not None:
            v.status = update.status
        if update.action is not None:
            v.action = update.action
        updated_count += 1

    # As on the PATCH above: the sweep and its consequence commit together, and
    # the superseded file is unlinked only once that has landed.
    superseded = exports.mark_export_invalidated(job) if changed_export else []

    db.commit()

    exports.unlink_all(superseded)

    return {"message": f"Updated {updated_count} violations", "updated": updated_count}


def _validate_status(status: str) -> None:
    if status not in STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Status must be 'pending', 'accepted', or 'rejected'",
        )


def _validate_action(action: str) -> None:
    if action not in ACTIONS:
        raise HTTPException(status_code=400, detail="Action must be 'cut' or 'mute'")
