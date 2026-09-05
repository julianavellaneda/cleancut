"""
Admin routes for system management and maintenance.
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..database import get_db
from ..models import Job, Task, Violation
from ..schemas import AdminStats
from ..services import exports

router = APIRouter()

# Directories. `services.exports` owns the export directory; it is read through
# that module at call time so a test only has to patch one name.
UPLOAD_DIR = Path(__file__).parent.parent.parent / "uploads"


def _get_dir_size_mb(directory: Path) -> float:
    """Calculate total size of files in a directory in MB."""
    total_size = 0
    if not directory.exists():
        return 0.0
    for f in directory.glob("**/*"):
        if f.is_file() and f.name != ".gitkeep":
            total_size += f.stat().st_size
    return round(total_size / (1024 * 1024), 2)


def _get_file_count(directory: Path) -> int:
    """Count files in a directory excluding .gitkeep."""
    if not directory.exists():
        return 0
    return sum(1 for f in directory.glob("**/*") if f.is_file() and f.name != ".gitkeep")


@router.get("/stats", response_model=AdminStats)
def get_admin_stats(db: Session = Depends(get_db)):
    """Get system-wide statistics."""
    total_jobs = db.query(Job).count()
    total_violations = db.query(Violation).count()
    
    # Jobs by status
    status_counts = db.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
    jobs_by_status = {status: count for status, count in status_counts}
    
    # Storage stats
    uploads_size = _get_dir_size_mb(UPLOAD_DIR)
    exports_size = _get_dir_size_mb(exports.EXPORT_DIR)
    files_count = _get_file_count(UPLOAD_DIR) + _get_file_count(exports.EXPORT_DIR)
    
    return AdminStats(
        total_jobs=total_jobs,
        total_violations=total_violations,
        jobs_by_status=jobs_by_status,
        total_uploads_size_mb=uploads_size,
        total_exports_size_mb=exports_size,
        files_count=files_count
    )


@router.post("/reset-database", dependencies=[Depends(require_admin)])
def reset_database(db: Session = Depends(get_db)):
    """Wipe all data from the database."""
    try:
        # Delete all violations first (though cascade should handle it).
        # Queued work goes too: this is a bulk delete, so the ORM cascade that
        # normally clears a job's tasks never runs, and a task pointing at a
        # wiped job would sit on the books until the next restart replayed it
        # against nothing.
        db.query(Violation).delete()
        db.query(Task).delete()
        db.query(Job).delete()
        db.commit()
        return {"message": "Database wiped successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to reset database: {str(e)}")


@router.post("/clear-storage", dependencies=[Depends(require_admin)])
def clear_storage():
    """Delete all files from uploads and exports directories."""
    deleted_count = 0
    try:
        for directory in [UPLOAD_DIR, exports.EXPORT_DIR]:
            if not directory.exists():
                continue
            for f in directory.glob("**/*"):
                if f.is_file() and f.name != ".gitkeep":
                    f.unlink()
                    deleted_count += 1
        return {"message": f"Storage cleared successfully. Deleted {deleted_count} files."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear storage: {str(e)}")


# `reset_all` calls reset_database/clear_storage as plain Python functions, not
# over HTTP, so a dependency declared on *those* never runs for this route. The
# gate has to be declared here too - it is the one that actually protects it.
@router.post("/reset-all", dependencies=[Depends(require_admin)])
def reset_all(db: Session = Depends(get_db)):
    """Wipe both database and storage."""
    db_res = reset_database(db)
    storage_res = clear_storage()
    return {
        "message": "System reset successfully",
        "database": db_res["message"],
        "storage": storage_res["message"]
    }
