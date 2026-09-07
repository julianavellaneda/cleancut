# Specification

The current contract, generated from the code — schema, routes, the export filter graph, and the
waveform marker encoding — as of 2026-09-07. Where this file and the code disagree, the code wins;
open an issue rather than trust this document over `backend/app/models.py`, `schemas.py` and
`routes/*.py`.

This file has no reasoning in it. For *why* the contract is shaped this way, see
[`AGENTS.md`](../AGENTS.md) and [`DESIGN_NOTES.md`](DESIGN_NOTES.md).

---

## 1. Database schema

Source: `backend/app/models.py`. SQLite, engine `sqlite:///` + `DATABASE_PATH`.

### `jobs`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | `String` | PK | UUID |
| `filename` | `String` | no | `{id}{ext}` |
| `original_filename` | `String` | yes | as uploaded |
| `media_type` | `String` | yes | `audio` \| `video`, default `"audio"` |
| `prompt` | `Text` | yes | free-form editing instruction |
| `status` | `String` | yes | default `"pending"`; see status values below |
| `auto_fix` | `Boolean` | yes | default `false` |
| `auto_scrub` | `Boolean` | yes | default `false` |
| `preset` | `String` | yes | rule preset id, or `NULL` for prompt mode |
| `duration_seconds` | `Float` | yes | |
| `language` | `String` | yes | |
| `created_at` | `DateTime` | yes | default UTC now |
| `error_message` | `Text` | yes | |
| `waveform_data` | `Text` | yes | JSON peaks, cached |
| `transcript` | `Text` | yes | JSON, schema versioned, words + segments |
| `export_status` | `String` | yes | default `"none"`; `none`\|`queued`\|`exporting`\|`ready`\|`failed` |
| `export_error` | `Text` | yes | |
| `edit_revision` | `Integer` | **no** | default `0`; bumped when the accepted set moves |
| `export_revision` | `Integer` | **yes** | revision the file on disk was rendered from; `NULL` = provenance unknown, not stale |

`status` values across the pipeline: `pending`, `converting`, `transcribing`, `analyzing`,
`exporting`, `completed`, `failed`.

### `violations`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | `String` | PK | UUID |
| `job_id` | `String` | no | FK → `jobs.id` |
| `text` | `Text` | no | quoted text |
| `start_time` | `Float` | no | seconds |
| `end_time` | `Float` | no | seconds |
| `label` | `String` | yes | e.g. `"Filler Word"`, prompt mode |
| `rule_violated` | `String` | yes | preset mode |
| `severity` | `String` | yes | `high`\|`medium`\|`low`, preset mode |
| `reasoning` | `Text` | yes | detector's own words only |
| `status` | `String` | yes | default `"pending"`; `pending`\|`accepted`\|`rejected` |
| `action` | `String` | yes | default `"cut"`; `cut`\|`mute` |
| `is_approximate` | `Boolean` | **no** | default `false`; span is a model estimate, not a measurement |
| `is_ambiguous` | `Boolean` | **no** | default `false`; word is only sometimes a filler |

### `tasks`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | `String` | PK | UUID |
| `kind` | `String` | no | `process`\|`export`\|`reanalyze` |
| `job_id` | `String` | no | FK → `jobs.id`, indexed |
| `file_path` | `Text` | yes | `process`: the uploaded media path |
| `edit_action` | `String` | yes | `export`: global cut/mute override |
| `prompt` | `Text` | yes | `reanalyze`: the new question |
| `preset` | `String` | yes | `reanalyze` |
| `state` | `String` | no | default `"pending"`; `pending`\|`running` |
| `attempts` | `Integer` | no | default `0`; abandoned past `MAX_ATTEMPTS = 3` |
| `created_at` | `DateTime` | yes | replay order |

Unique constraint `uq_tasks_job_kind (job_id, kind)`: one outstanding task per job per kind.

---

## 2. Route contract

Source: `backend/app/main.py`, `routes/jobs.py`, `routes/violations.py`, `routes/audio.py`,
`routes/admin.py`. `jobs.router`, `violations.router` and `audio.router` all mount at `/api/jobs`;
`admin.router` mounts at `/api/admin`.

### Health

| Method | Path | Response |
|---|---|---|
| GET | `/` | 200 `{"status": "ok", "message": "CleanCut API is running"}` |

### Jobs

| Method | Path | Status | Request | Response |
|---|---|---|---|---|
| POST | `/api/jobs` | **200**, 400, 413, 422, 500 | multipart: `file` (required), `prompt`, `media_type` (default `audio`), `auto_fix`, `auto_scrub`, `preset` — all `Form(...)` | `JobResponse` |
| GET | `/api/jobs` | 200 | query `limit` (default 50, max 200), `offset` (default 0) | `list[JobListResponse]`, newest first |
| GET | `/api/jobs/active` | 200 | — | `list[ActiveJobResponse]`: unfinished jobs only |
| GET | `/api/jobs/presets` | 200 | — | `list[PresetResponse]` |
| GET | `/api/jobs/{job_id}` | 200, 404 | — | `JobResponse` |
| POST | `/api/jobs/{job_id}/reanalyze` | **202**, 400, 404, 409 | `ReanalyzeRequest`: `prompt`, `preset` | `ReanalyzeResponse` |
| GET | `/api/jobs/{job_id}/transcript` | 200, 404 | — | `TranscriptResponse` |
| DELETE | `/api/jobs/{job_id}` | 200, 404, 409 | — | `{"message": "Job deleted"}` |

`POST /api/jobs` status detail:
- 400 — unknown preset, or `file`'s extension is not one of
  `.mp3 .wav .m4a .flac .ogg .webm .aif .aiff .mp4 .mov`.
- 413 — over `MAX_UPLOAD_MB` (caught while streaming to disk), or over `MAX_DURATION_MINUTES`.
- 422 — duration unreadable by ffprobe. Fails closed: an unprobeable file is refused, not admitted.
- 500 — the file could not be saved.
- On 413/422 the `Job` row and the partial upload are both rolled back (`_discard_job`); the job
  never appears in the list.

`POST /api/jobs/{job_id}/reanalyze` status detail:
- 400 — unknown preset, or neither `prompt` nor `preset` given.
- 404 — unknown job.
- 409 — job not in `completed`/`failed` (still mid-pipeline), no stored transcript, or a
  re-analysis is already queued.

`DELETE /api/jobs/{job_id}` status detail:
- 409 — job is still in flight: `status` not terminal, or `export_status` in `queued`/`exporting`.

`GET /api/jobs/{job_id}/transcript` — 404 covers three cases identically: unknown job, job that has
not reached transcription yet, and a row from before the `transcript` column existed.

### Violations

| Method | Path | Status | Request | Response |
|---|---|---|---|---|
| GET | `/api/jobs/{job_id}/violations` | 200, 404 | — | `list[ViolationResponse]`, ordered by `start_time` |
| PATCH | `/api/jobs/{job_id}/violations/{violation_id}` | 200, 400, 404 | `ViolationUpdate`: `status`, `action` | `ViolationResponse` |
| POST | `/api/jobs/{job_id}/violations/bulk-update` | 200, 400, 404 | query `labels`, `from_status` (default `["pending"]`); body `BulkViolationUpdate`: `status`, `action`, `ids` | `{"message": str, "updated": int}` |

`status` values: `pending`, `accepted`, `rejected`. `action` values: `cut`, `mute` (`schemas.EDIT_ACTIONS`).
A PATCH or bulk-update that moves an *accepted* edit's status or action invalidates the job's export
in the same transaction (see §3).

### Audio and export

| Method | Path | Status | Request | Response |
|---|---|---|---|---|
| GET | `/api/jobs/{job_id}/audio` | 200, 404 | — | media file stream |
| GET | `/api/jobs/{job_id}/audio/waveform` | 200, 404, 500 | — | `{"peaks": list[float]}`, 800 peaks |
| POST | `/api/jobs/{job_id}/export` | **202**, 400, 404, 409 | body `ExportRequest`: `edit_action` (`null`, `"cut"` or `"mute"`) | `ExportResponse` |
| GET | `/api/jobs/{job_id}/export/download` | 200, 404, 409 | — | file, `Content-Disposition: attachment` |
| GET | `/api/jobs/{job_id}/export/stream` | 200, 404, 409 | — | file, `Content-Disposition: inline` |

`POST /api/jobs/{job_id}/export` status detail:
- 400 — job `status` is not `completed`, or no violations are `accepted`.
- 404 — unknown job, or the source media file is missing from `uploads/`.
- 409 — an export is already `queued`/`exporting` for this job.
- `edit_action` is validated against `schemas.EDIT_ACTIONS`; an invalid value is a 422 from Pydantic
  before the handler runs (`partition_edits` reads anything not `"mute"` as a cut, so an
  unvalidated override would turn a typo into a cut of every accepted span).

`GET .../export/download` and `.../export/stream` status detail:
- 404 — unknown job, or no export file has been generated yet.
- 409 — `export_revision` does not equal `edit_revision`: the export is stale. Normally unreachable
  because invalidation deletes the file first; this is the belt-and-braces check.

### Admin

| Method | Path | Status | Request | Response |
|---|---|---|---|---|
| GET | `/api/admin/stats` | 200 | — | `AdminStats` — **ungated** |
| POST | `/api/admin/reset-database` | 200, 401, 500, 503 | `X-Admin-Token` header | `{"message": str}` |
| POST | `/api/admin/clear-storage` | 200, 401, 500, 503 | `X-Admin-Token` header | `{"message": str}` |
| POST | `/api/admin/reset-all` | 200, 401, 500, 503 | `X-Admin-Token` header | `{"message", "database", "storage"}` |

All three destructive routes: 503 when `ADMIN_TOKEN` is unset (or `ALLOW_UNAUTHENTICATED_ADMIN=1` is
set but `CLEANCUT_HOST` is not loopback); 401 when a token is configured and the supplied
`X-Admin-Token` is missing or wrong.

### Ordering constraint

`/api/jobs/presets` and `/api/jobs/active` must be declared before `/api/jobs/{job_id}` in
`routes/jobs.py`, or the path-param route shadows them.

---

## 3. Export filter graph

Source: `backend/app/services/media_editor.py`, `MediaEditor.apply_edits`.

One FFmpeg invocation per export. Steps, in order:

1. **Mute first.** If any spans are muted, a `volume` filter is applied to the whole audio stream:
   `volume='if(between(t,t1,t2)+between(t,t3,t4)+...,0,1)'` with `eval=frame` — required, because the
   default `eval=once` evaluates `t` a single time at startup and silently disables the expression.
   This runs on the untrimmed timeline, before any cut shifts it.
2. **Compute keep segments.** Cuts are merged (sorted, overlapping spans combined), then inverted
   against the file's full duration (from `ffmpeg.probe`) to get the spans to keep.
3. **Split the audio.** A filter output feeds only one consumer, so when there is more than one keep
   segment the (possibly muted) audio is fanned out with `asplit`. Raw input pads split themselves;
   the `volume` filter's output does not.
4. **Trim each keep segment.** Audio: `atrim=start=..:end=..` → `asetpts=PTS-STARTPTS`. Video (video
   jobs only): `trim=start=..:end=..` → `setpts=PTS-STARTPTS`, off the original (unmuted) video
   stream.
5. **Concat.** Video jobs concat interleaved `[v0][a0][v1][a1]...` pairs with `strict=True` — a
   video segment with no paired audio segment does not raise, it silently shifts audio against
   picture, so the pairing is enforced. Audio-only jobs concat the audio stream alone.
6. **Output.** `-map` the concatenated video and audio (or audio alone) to the output path.

If there is nothing to cut and nothing to mute, the file is copied/transcoded through unchanged. If
there are mutes but no cuts, the muted stream is output directly (video copies its `vcodec` untouched)
with no trim/concat step.

Worked example — cutting `[10, 15]` and `[40, 44]` from an audio file with one earlier mute at
`[5, 7]`:

```
[0:a] volume=if(between(t,5,7),0,1):eval=frame [muted]
[muted] asplit=3 [a0][a1][a2]
[a0] atrim=start=0:end=10,   asetpts=PTS-STARTPTS [k0]
[a1] atrim=start=15:end=40,  asetpts=PTS-STARTPTS [k1]
[a2] atrim=start=44:end=<duration>, asetpts=PTS-STARTPTS [k2]
[k0][k1][k2] concat=n=3:v=0:a=1 [out]
```

`-map "[out]"` to the output path. A video job carries the matching `trim`/`setpts` chain on
`[0:v]` alongside each `[k*]` and concats the interleaved pairs with `v=1:a=1`.

### Output naming

Source: `services/exports.py`.

- On-disk path: `{EXPORT_DIR}/{job.id}_edited{suffix}`.
- `suffix`: the source file's extension for a video job (container preserved); `.mp3` for an audio
  job (normalized).
- Download filename (`Content-Disposition`): `{stem of job.filename}_edited{suffix}`.

---

## 4. Waveform marker encoding

Source: `frontend/src/components/Waveform.tsx`, `regionFill` / `regionOpacity`.

Each suggestion renders as one region. Two independent visual channels:

**Hue and fill pattern — encodes `action`:**

| `action` | Fill token | Pattern |
|---|---|---|
| `cut` (or unset) | `--acc` (solid) / `--acc-200` (tint) | none |
| `mute` | `--acc2` (solid) / `--acc2-200` (tint) | `repeating-linear-gradient(135deg, transparent 0 3px, var(--surface) 3px 5px)` hatch |

**Fill color and border — encodes `status`:**

| `status` | Fill | Border-left |
|---|---|---|
| `rejected` | `--faint` | transparent |
| `accepted` | solid accent (`--acc` or `--acc2`) | solid accent |
| `pending` | tint (`--acc-200` or `--acc2-200`) | solid accent |

**Opacity — encodes selection, independent of status/action:**

| Condition | Opacity |
|---|---|
| `status === "rejected"` | 0.35 |
| selected (any other status) | 1 |
| not selected (any other status) | 0.8 |

A region has a 3px minimum width so a short edit stays visible. There is no severity-based color
scheme and no "Keepers" concept; `severity` (preset mode only) renders as text in the suggestion
list and detail panel, not as a waveform color.

---

## 5. Model router

Source: `backend/app/analysis/providers.py`.

`CLEANCUT_MODEL="provider:model"` (default `openai:gpt-4o`) selects both vendor and model as one
string. Supported providers: `openai`, `anthropic`. Each implements
`complete(system_prompt, user_prompt) -> str`; parsing and the JSON contract are the same for every
vendor and live in `prompt_analyzer.py`.
