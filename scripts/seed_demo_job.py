#!/usr/bin/env python3
"""
Seed a fully processed demo job from committed JSON.

Transcription costs ~30s per run on the demo fixture, which is fine once and
intolerable when you are re-shooting a screen capture for the tenth time. This
script snapshots one real completed job to JSON, then replays it into the
database in well under a second, media file and cached waveform included.

The snapshot is taken from a genuine pipeline run rather than hand-authored, so
what the capture shows is what the app actually produced.

    # once, after a real prompt-mode run of the fixture:
    python scripts/seed_demo_job.py --capture-from <job_id>

    # before every take:
    python scripts/seed_demo_job.py --state fresh
    python scripts/seed_demo_job.py --state cleaned

`--state cleaned` pre-accepts the scrubber edits and one LLM edit, because the
"Export Edited" button stays disabled until at least one violation is accepted.

Run from the repo root with the backend venv active.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Job, Violation  # noqa: E402

SEED_JSON = REPO_ROOT / "tests" / "fixtures" / "demo" / "seed_job.json"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "demo"
UPLOAD_DIR = BACKEND / "uploads"

# Fixed so re-seeding replaces the previous seed instead of piling up jobs, and
# so the capture scripts can hardcode the review URL.
DEMO_JOB_ID = "demo-0000-0000-0000-cleancut"

SCRUB_LABELS = {"Filler Word", "Dead Air"}

JOB_FIELDS = (
    "filename", "original_filename", "media_type", "prompt", "auto_fix",
    "auto_scrub", "preset", "duration_seconds", "language", "error_message",
    "waveform_data",
)
VIOLATION_FIELDS = (
    "text", "start_time", "end_time", "label", "rule_violated", "severity",
    "reasoning", "status", "action",
)


def capture(job_id: str) -> None:
    """Snapshot a real completed job into SEED_JSON."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            sys.exit(f"No job {job_id} in {BACKEND / 'audio_compliance.db'}")
        if job.status != "completed":
            sys.exit(f"Job {job_id} is '{job.status}', not 'completed' - capture a finished run")

        violations = (
            db.query(Violation)
            .filter(Violation.job_id == job_id)
            .order_by(Violation.start_time)
            .all()
        )
        if not violations:
            sys.exit(f"Job {job_id} has no violations - nothing worth capturing")

        if not job.waveform_data:
            print(
                "  ! waveform_data is empty. Open the review page for this job once so the\n"
                "    backend caches the peaks, then re-run --capture-from.",
                file=sys.stderr,
            )

        payload = {
            "job": {f: getattr(job, f) for f in JOB_FIELDS},
            "violations": [
                {f: getattr(v, f) for f in VIOLATION_FIELDS} for v in violations
            ],
        }
    finally:
        db.close()

    SEED_JSON.parent.mkdir(parents=True, exist_ok=True)
    SEED_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    peaks = payload["job"]["waveform_data"]
    print(f"Captured job {job_id} -> {SEED_JSON.relative_to(REPO_ROOT)}")
    print(f"  {len(payload['violations'])} violations, "
          f"{len(json.loads(peaks)) if peaks else 0} waveform peaks")


def _source_media(filename: str) -> Path:
    """Locate the fixture media the snapshot was produced from."""
    candidate = FIXTURE_DIR / filename
    if candidate.exists():
        return candidate
    # The captured job's filename is the uploaded name; fall back on extension.
    for path in sorted(FIXTURE_DIR.glob(f"demo_seminar{Path(filename).suffix}")):
        return path
    sys.exit(
        f"Cannot find fixture media for '{filename}' in {FIXTURE_DIR.relative_to(REPO_ROOT)}.\n"
        f"Generate it first with scripts/generate_demo_audio.py."
    )


def seed(state: str) -> None:
    if not SEED_JSON.exists():
        sys.exit(
            f"{SEED_JSON.relative_to(REPO_ROOT)} does not exist.\n"
            f"Run a real pipeline job on the fixture, then "
            f"`python scripts/seed_demo_job.py --capture-from <job_id>`."
        )

    payload = json.loads(SEED_JSON.read_text())
    job_fields = payload["job"]
    violations = payload["violations"]

    source = _source_media(job_fields["filename"])
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for stale in UPLOAD_DIR.glob(f"{DEMO_JOB_ID}.*"):
        stale.unlink()
    shutil.copy2(source, UPLOAD_DIR / f"{DEMO_JOB_ID}{source.suffix}")

    init_db()
    db = SessionLocal()
    try:
        existing = db.query(Job).filter(Job.id == DEMO_JOB_ID).first()
        if existing is not None:
            db.delete(existing)  # cascades to violations
            db.commit()

        db.add(Job(id=DEMO_JOB_ID, status="completed", **job_fields))
        for index, entry in enumerate(violations):
            fields = dict(entry)
            fields["status"] = _status_for(fields, index, violations, state)
            db.add(Violation(id=f"{DEMO_JOB_ID}-v{index:03d}", job_id=DEMO_JOB_ID, **fields))
        db.commit()
    finally:
        db.close()

    accepted = sum(
        1 for i, v in enumerate(violations) if _status_for(dict(v), i, violations, state) == "accepted"
    )
    print(f"Seeded job {DEMO_JOB_ID} (state={state})")
    print(f"  media:      {(UPLOAD_DIR / f'{DEMO_JOB_ID}{source.suffix}').relative_to(REPO_ROOT)}")
    print(f"  violations: {len(violations)} ({accepted} accepted)")
    print(f"  review at:  http://localhost:3000/jobs/{DEMO_JOB_ID}")


def _status_for(entry: dict, index: int, violations: list[dict], state: str) -> str:
    """Everything is pending in 'fresh'; 'cleaned' mirrors a Clean All plus one accept."""
    if state == "fresh":
        return "pending"
    if entry.get("label") in SCRUB_LABELS:
        return "accepted"
    first_llm = next(
        (i for i, v in enumerate(violations) if v.get("label") not in SCRUB_LABELS), None
    )
    return "accepted" if index == first_llm else "pending"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--capture-from", metavar="JOB_ID",
                        help="snapshot this completed job into seed_job.json and exit")
    parser.add_argument("--state", choices=("fresh", "cleaned"), default="fresh",
                        help="'fresh' leaves every edit pending; 'cleaned' pre-accepts the "
                             "scrubber edits and one LLM edit so Export is enabled")
    args = parser.parse_args()

    if args.capture_from:
        capture(args.capture_from)
    else:
        seed(args.state)


if __name__ == "__main__":
    main()
