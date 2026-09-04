"""
The one place that knows where exports live, how one is named, and how edits
are partitioned.

Before this module the ``{job_id}_edited{ext}`` convention and the cut/mute
partition lived in three copies - the sync export route, the worker's auto-fix
branch, and the "does an export exist" probe - which is exactly the kind of
duplication that lets two of them drift while the third keeps working.

``EXPORT_DIR`` joined them here for the same reason: six modules each derived
``Path(__file__).parent.parent.parent / "exports"`` for themselves, so the
directory's location depended on how deep the file deriving it happened to sit.
Every caller now reads ``exports.EXPORT_DIR`` **at call time** rather than
importing the value - that is what lets a test point the whole app at a
``tmp_path`` by patching one name instead of remembering which five modules
kept a copy.
"""

import logging
from pathlib import Path
from typing import Iterable, Sequence

import ffmpeg

from ..models import Job
from .media_editor import MediaEditor

logger = logging.getLogger(__name__)

# The single owner. Read it through this module (``exports.EXPORT_DIR``), never
# by importing the name or binding it as a default argument - both snapshot the
# value at import time and put the patch back out of reach.
EXPORT_DIR = Path(__file__).parent.parent.parent / "exports"

Segment = tuple[float, float]


def export_dir(explicit: Path | None = None) -> Path:
    """
    The export directory a caller should use: its own, or the configured one.

    Callers that take an ``export_dir`` argument resolve it through here so the
    override stays available to tests while the default is looked up now rather
    than at import.
    """
    return EXPORT_DIR if explicit is None else explicit


def ensure_export_dir(explicit: Path | None = None) -> Path:
    """:func:`export_dir`, created if it is not there yet."""
    path = export_dir(explicit)
    path.mkdir(parents=True, exist_ok=True)
    return path

# An export the worker has not finished with. The file on disk is mid-write, so
# invalidation must not delete it - the render itself checks the revision when
# it lands.
IN_FLIGHT_EXPORT_STATUSES = ("queued", "exporting")

# Scrubber-authored labels. The worker uses these to decide whether a suggestion
# is governed by auto_scrub or by auto_fix.
SCRUBBER_LABELS = ("Dead Air", "Filler Word")


def export_suffix(job: Job, source_path: str | Path) -> str:
    """Video keeps its container; audio is normalized to mp3."""
    return Path(source_path).suffix if job.media_type == "video" else ".mp3"


def export_path_for(job: Job, source_path: str | Path, directory: Path | None = None) -> Path:
    """Where the edited file for ``job`` is written."""
    return export_dir(directory) / f"{job.id}_edited{export_suffix(job, source_path)}"


def export_filename_for(job: Job, suffix: str) -> str:
    """The human-facing download name, derived from the job's stored filename."""
    return f"{Path(job.filename).stem}_edited{suffix}"


def affects_export(violation, new_status: str | None, new_action: str | None) -> bool:
    """
    Whether moving one suggestion changes what a render would produce.

    Only accepted edits reach FFmpeg, so pending -> rejected changes nothing on
    disk and must not throw away a perfectly good export. What counts is a row
    entering or leaving `accepted`, or an accepted row switching between cut and
    mute. A write that sets a field to the value it already holds is not a
    change at all.

    Read before the update is applied: it compares against the row's current
    values.
    """
    status = violation.status or "pending"
    action = violation.action or "cut"

    if new_status is not None and new_status != status and "accepted" in (status, new_status):
        return True

    effective_status = new_status if new_status is not None else status
    return (
        new_action is not None
        and new_action != action
        and effective_status == "accepted"
    )


def export_files(job_id: str, directory: Path | None = None) -> list[Path]:
    """
    Whatever export a job has on disk, listed rather than removed.

    Globbed rather than rebuilt from the naming rule, so an export written under
    a container the current code no longer derives is still found.

    ``EXPORT_DIR`` is read at call time rather than bound as a default, so a
    test pointing this module at a tmp_path is honoured.

    Split from :func:`delete_export_files` so a caller inside a transaction can
    decide *what* is superseded now and unlink it after committing.
    """
    directory = export_dir(directory)
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"{job_id}_edited.*"))


def delete_export_files(job_id: str, directory: Path | None = None) -> int:
    """Remove whatever export a job has on disk. Returns the count unlinked."""
    return unlink_all(export_files(job_id, directory))


def export_is_stale(job: Job) -> bool:
    """
    Whether the export on disk predates the current edit set.

    ``export_revision is None`` is *not* stale: it means nothing recorded which
    edits produced the file - a job that has never exported, or a row from
    before the column existed whose file the filesystem probe still finds.
    Calling those stale would break a download that works today on no evidence
    at all.
    """
    if job.export_revision is None:
        # An export that was *retired* also clears this, so a file that survived
        # a failed unlink is still served. That is deliberate and pinned by
        # `test_an_export_of_unknown_provenance_still_downloads`: NULL means
        # "nothing recorded which edits this came from", and rows predating
        # these columns are indistinguishable from retired ones. Refusing both
        # would break a download that works today to close a window that only
        # opens when `unlink` itself fails.
        return False
    return job.export_revision != (job.edit_revision or 0)


def mark_export_invalidated(job: Job, directory: Path | None = None) -> list[Path]:
    """
    Retire a job's export *in the caller's session*, without committing.

    The database half of :func:`invalidate_export`, split out so a route can put
    the reviewer's decision and the invalidation it causes in **one**
    transaction. They used to be two: the violation was committed, then this
    function committed again. A failure in between left the decision durable
    while the file in ``exports/`` went on advertising itself as ready - and the
    obvious fix, retrying the same request, was a no-op, because
    ``affects_export`` compares against a status that had already been written.

    Returns the files the caller should unlink once its commit has landed.
    Deleting after the commit is deliberate: the revision is monotonic, so a
    file that survives a failed unlink is already refused by ``export_is_stale``
    on both download routes. Deleting *before* would be the unrecoverable order
    - bytes gone, transaction rolled back.

    A render already in flight is left alone: its file is being written right
    now, and ``_process_export`` re-checks the revision when it finishes.
    """
    job.edit_revision = (job.edit_revision or 0) + 1
    if (job.export_status or "none") in IN_FLIGHT_EXPORT_STATUSES:
        return []

    superseded = export_files(job.id, directory)
    job.export_status = "none"
    job.export_error = None
    job.export_revision = None
    return superseded


def invalidate_export(db, job: Job, directory: Path | None = None) -> None:
    """
    Record that the edit set changed, retire the export, and commit.

    The whole operation for a caller that owns its transaction outright and has
    nothing else to commit alongside - the worker's re-analysis path. A route
    handling a reviewer's decision should use :func:`mark_export_invalidated`
    instead and commit once, so the decision and its consequence cannot come
    apart.

    Every caller that can move a suggestion goes through one of the two, so "the
    file in exports/ matches the review screen" is a property of this module
    rather than of every route remembering to clear a flag.
    """
    superseded = mark_export_invalidated(job, directory)
    db.commit()
    unlink_all(superseded)


def unlink_all(paths: Iterable[Path]) -> int:
    """
    Remove files that are no longer current. Returns how many actually went.

    A failure is logged, not raised: by the time this runs the transaction that
    made these files stale has committed, and the revision counters already stop
    them being served. A leftover file is a wasted block, not a wrong answer.
    """
    removed = 0
    for path in paths:
        try:
            path.unlink()
            removed += 1
        except OSError:
            logger.exception(f"Could not delete superseded export {path}")
    return removed


def partition_edits(
    violations: Iterable,
    edit_action: str | None = None,
) -> tuple[list[Segment], list[Segment]]:
    """
    Split suggestions into (cuts, mutes) by each one's own action.

    ``edit_action``, when supplied, overrides every violation's action - that is
    the "force one action globally" escape hatch on ``ExportRequest``. Anything
    that is not explicitly "mute" is treated as a cut, matching the column
    default.
    """
    cuts: list[Segment] = []
    mutes: list[Segment] = []
    for v in violations:
        action = edit_action or getattr(v, "action", None) or "cut"
        target = mutes if action == "mute" else cuts
        target.append((v.start_time, v.end_time))
    return cuts, mutes


def render_export(
    source_path: str,
    export_path: str | Path,
    cuts: Sequence[Segment],
    mutes: Sequence[Segment],
    media_type: str = "audio",
) -> None:
    """
    Render the edited file.

    ``MediaEditor`` is looked up off this module at call time on purpose: the
    test suite swaps in a recording double via ``exports.MediaEditor`` rather
    than shelling out to FFmpeg.
    """
    if cuts or mutes:
        editor = MediaEditor()
        editor.apply_edits(
            source_path,
            str(export_path),
            segments_to_cut=list(cuts),
            segments_to_mute=list(mutes),
            media_type=media_type,
        )
    else:
        # Nothing to remove - still produce an export, so "download the master"
        # means the same thing whether or not any edit survived review.
        ffmpeg.input(source_path).output(str(export_path)).run(overwrite_output=True, quiet=True)


def describe_edits(cuts: Sequence[Segment], mutes: Sequence[Segment]) -> str:
    """Human-readable summary of what an export applied."""
    parts = []
    if cuts:
        parts.append(f"{len(cuts)} cut")
    if mutes:
        parts.append(f"{len(mutes)} muted")
    if not parts:
        return "Exported with no edits applied"
    return f"Exported with {' and '.join(parts)} edit(s)"
