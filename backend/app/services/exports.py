"""
The one place that knows how an export is named and how edits are partitioned.

Before this module the ``{job_id}_edited{ext}`` convention and the cut/mute
partition lived in three copies - the sync export route, the worker's auto-fix
branch, and the "does an export exist" probe - which is exactly the kind of
duplication that lets two of them drift while the third keeps working.
"""

import logging
from pathlib import Path
from typing import Iterable, Sequence

import ffmpeg

from ..models import Job
from .media_editor import MediaEditor

logger = logging.getLogger(__name__)

Segment = tuple[float, float]

# Scrubber-authored labels. The worker uses these to decide whether a suggestion
# is governed by auto_scrub or by auto_fix.
SCRUBBER_LABELS = ("Dead Air", "Filler Word")


def export_suffix(job: Job, source_path: str | Path) -> str:
    """Video keeps its container; audio is normalized to mp3."""
    return Path(source_path).suffix if job.media_type == "video" else ".mp3"


def export_path_for(job: Job, source_path: str | Path, export_dir: Path) -> Path:
    """Where the edited file for ``job`` is written."""
    return export_dir / f"{job.id}_edited{export_suffix(job, source_path)}"


def export_filename_for(job: Job, suffix: str) -> str:
    """The human-facing download name, derived from the job's stored filename."""
    return f"{Path(job.filename).stem}_edited{suffix}"


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
