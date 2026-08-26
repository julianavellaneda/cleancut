# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**CleanCut** — describe what to find in a recording in plain English, review the AI's suggestions on a
waveform, export a surgically edited file. It transcribes audio or video with word-level timestamps,
sends the transcript plus your instruction to an LLM, maps the LLM's quoted text back to precise
timestamps, and renders the accepted edits with FFmpeg.

**Philosophy**: "Copilot, not Autopilot" — the AI suggests edits for human review; nothing is removed
without a human accepting it.

## Architecture

```
ai-audio-editing/
├── backend/                        # FastAPI backend
│   ├── app/
│   │   ├── main.py                 # FastAPI entry, CORS, lifespan startup
│   │   ├── config.py               # Root .env discovery
│   │   ├── auth.py                 # ADMIN_TOKEN gate for the destructive admin routes
│   │   ├── preflight.py            # Startup checks: OPENAI_API_KEY, ffmpeg/ffprobe
│   │   ├── limits.py               # Upload size + duration caps
│   │   ├── database.py             # SQLite setup + hand-rolled column migrations
│   │   ├── models.py               # SQLAlchemy: Job, Violation
│   │   ├── schemas.py              # Pydantic request/response
│   │   ├── analysis/
│   │   │   ├── transcriber.py      # faster-whisper, word-level timestamps
│   │   │   ├── prompt_analyzer.py  # Chunked LLM analysis + preset registry
│   │   │   ├── analyze.py          # Standalone CLI
│   │   │   └── presets/            # Rule preset markdown (income-claims, pii-redaction)
│   │   ├── routes/
│   │   │   ├── jobs.py             # Upload, list, presets, status, delete
│   │   │   ├── violations.py       # List, update, bulk-update
│   │   │   ├── audio.py            # Stream, waveform, export, download
│   │   │   └── admin.py            # Reset, storage, stats
│   │   └── services/
│   │       ├── worker.py           # Threaded job queue, per-stage status
│   │       ├── processor.py        # Wraps transcriber + analyzer
│   │       ├── exports.py          # Export naming, cut/mute partition, render
│   │       ├── retention.py        # RETENTION_HOURS sweeper: expired jobs + orphan media
│   │       ├── scrubber.py         # Deterministic silence + filler detection
│   │       └── media_editor.py     # FFmpeg trim/atrim + concat filter graphs
│   ├── tests/                      # pytest suite
│   ├── uploads/                    # Uploaded media
│   └── exports/                    # Edited output
├── frontend/                       # Next.js 15 frontend
│   └── src/
│       ├── app/
│       │   ├── page.tsx            # Upload + prompt/preset selection
│       │   ├── admin/page.tsx      # Admin dashboard
│       │   └── jobs/[id]/page.tsx  # Review interface
│       ├── components/
│       │   ├── Waveform.tsx        # wavesurfer + region markers
│       │   ├── KeyboardLegend.tsx  # Review shortcut reference
│       │   ├── ViolationList.tsx   # Sidebar list + Clean All
│       │   └── ViolationCard.tsx   # Detail, accept/reject, cut/mute toggle
│       └── lib/api.ts              # API client
├── docs/                           # Architecture, spec, roadmap
└── tests/                          # Media fixtures (synthetic only)
```

**Data flow:**
1. Upload media → FastAPI saves to `uploads/`, creates a Job, enqueues it
2. Worker converts if needed → transcribes (faster-whisper) → analyzes (LLM) → scrubs (deterministic)
3. Suggestions stored as `Violation` rows; frontend polls job status
4. User reviews on a waveform, accepts/rejects, picks cut or mute per edit
5. Export builds one FFmpeg filter graph from the accepted edits

## Commands

```bash
# Backend (port 8000)
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Backend tests
pip install -r requirements-dev.txt
pytest

# Frontend (port 3000)
cd frontend
npm install
npm run dev
```

Both at once: `./start.sh`. Or `docker compose up --build`.

**CLI** (analysis pipeline without the web app):
Run as a module from `backend/` — `analysis/` uses package-relative imports, so invoking
`analyze.py` as a script fails with `attempted relative import with no known parent package`.

```bash
cd backend && source .venv/bin/activate
python -m app.analysis.analyze audio.mp3 --prompt "flag every income claim"
python -m app.analysis.analyze audio.mp3 --preset income-claims
python -m app.analysis.analyze --transcript path/to/transcript.txt --prompt "find filler words"
```

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/jobs` | Upload media, enqueue processing (multipart) |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/presets` | List built-in rule presets |
| GET | `/api/jobs/{id}` | Job details + violation counts |
| DELETE | `/api/jobs/{id}` | Delete job and files |
| GET | `/api/jobs/{id}/violations` | List suggested edits |
| PATCH | `/api/jobs/{id}/violations/{vid}` | Update status or action |
| POST | `/api/jobs/{id}/violations/bulk-update` | Bulk update, optionally filtered by label |
| GET | `/api/jobs/{id}/audio` | Stream original media |
| GET | `/api/jobs/{id}/audio/waveform` | Waveform peaks JSON |
| POST | `/api/jobs/{id}/export` | Queue an edited render (202; poll `export_status`) |
| GET | `/api/jobs/{id}/export/download` | Download edited file |
| GET | `/api/admin/stats` | System-wide statistics |
| POST | `/api/admin/reset-database` | Wipe all database records (gated by `ADMIN_TOKEN`) |
| POST | `/api/admin/clear-storage` | Delete all media files (gated by `ADMIN_TOKEN`) |
| POST | `/api/admin/reset-all` | Wipe database + storage (gated by `ADMIN_TOKEN`) |

**Note:** `/api/jobs/presets` must stay declared before `/api/jobs/{job_id}` in `routes/jobs.py`,
or the path-param route shadows it.

## Database Schema (SQLite)

```sql
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    original_filename TEXT,
    media_type TEXT DEFAULT 'audio',   -- audio, video
    prompt TEXT,                       -- free-form editing instruction
    status TEXT DEFAULT 'pending',     -- pending, converting, transcribing,
                                       -- analyzing, exporting, completed, failed
    auto_fix BOOLEAN DEFAULT 0,        -- pre-accept LLM suggestions
    auto_scrub BOOLEAN DEFAULT 0,      -- pre-accept scrubber suggestions
    preset TEXT,                       -- rule preset id, NULL = prompt mode
    duration_seconds REAL,
    language TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT,
    waveform_data TEXT,                -- JSON cached peaks
    export_status TEXT DEFAULT 'none', -- none, queued, exporting, ready, failed
    export_error TEXT
);

CREATE TABLE violations (
    id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES jobs(id),
    text TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    label TEXT,                        -- "Filler Word", "Income Claims", ...
    rule_violated TEXT,                -- set in preset mode
    severity TEXT,                     -- high, medium, low
    reasoning TEXT,
    status TEXT DEFAULT 'pending',     -- pending, accepted, rejected
    action TEXT DEFAULT 'cut'          -- cut, mute
);
```

Schema changes to `jobs` go in `database._apply_migrations()` — a hand-rolled additive migration run
on every startup. Add a column there and cover it in `backend/tests/test_migrations.py`.

## Environment

A `.env` at the **repo root** (not in a subdirectory), discovered by `app/config.py`:

```
OPENAI_API_KEY=your_key_here
CORS_ORIGINS=http://localhost:3000
DATABASE_PATH=            # optional; Docker sets this to a mounted volume
NEXT_PUBLIC_API_URL=      # optional; baked into the frontend build
MAX_UPLOAD_MB=500         # optional; upload size cap
MAX_DURATION_MINUTES=120  # optional; media length cap, probed with ffprobe (fails closed)
DEAD_AIR_FLOOR_DB=-50     # optional; dBFS below which audio counts as silence
DEAD_AIR_MIN_SECONDS=0.75 # optional; shortest dead-air span worth suggesting
ADMIN_TOKEN=              # optional; when set, destructive /api/admin/* needs X-Admin-Token
RETENTION_HOURS=          # optional; delete jobs + media older than this. Unset = keep forever
RETENTION_SWEEP_MINUTES=15 # optional; sweeper interval
SKIP_PREFLIGHT=           # optional; 1 to boot past a failed startup check
```

System dependency: `brew install ffmpeg`.

## Key Implementation Details

- **Transcriber**: faster-whisper with int8 quantization for M-series Mac performance.
- **PromptAnalyzer**: two modes.
  - *Prompt mode* (`preset=None`): the user's instruction drives analysis; returns label + action.
  - *Preset mode*: a rulebook from `analysis/presets/` replaces the prompt; returns rule_violated +
    severity, and falls back to the preset's `default_action` (mute for `pii-redaction`).
  - Chunked sliding window for long transcripts: 50 segments per chunk, 10 overlap, deduplicated by
    label + timestamp proximity (5s).
  - LLM-quoted text is remapped onto word-level timestamps via `_find_text_timestamps`.
- **Adding a preset**: drop a markdown rulebook in `analysis/presets/` and add an entry to `PRESETS`
  in `prompt_analyzer.py`. It surfaces automatically via `GET /api/jobs/presets`.
- **Scrubber**: deterministic filler detection off word timestamps, no LLM. Dead air needs *two*
  signals to agree: the transcript proposes a span nobody speaks over, and an RMS pass
  (`services/levels.py`) has to confirm it is below `DEAD_AIR_FLOOR_DB`. The confirmed sub-interval
  is what gets emitted, which also trims Whisper's loose boundaries off the next line's onset.
  Gap-detection alone flagged room tone, applause and music beds as Dead Air, and `auto_scrub` cut
  them unreviewed; VAD makes the same mistake, since it answers the same question. If the level pass
  cannot run, silence detection is **skipped** and the job carries a warning - never downgraded back
  to gaps.
- **decode_pcm_mono** (`services/media_editor.py`): one shared FFmpeg decode to 8 kHz mono f32le,
  used by both the waveform peaks and the level pass. Do not add a second decode.
- **MediaEditor**: FFmpeg `trim`/`atrim` + `concat`, single pass, A/V sync preserved. Mutes are
  applied before cuts, since cutting shifts the timeline under the mute timestamps.
- **exports.py**: the single owner of the `{job_id}_edited{ext}` naming rule, the cut/mute
  partition, and the render call. Both the queued export and the worker's auto-fix branch go
  through it; do not re-derive an export path anywhere else. Tests swap `exports.MediaEditor`.
- **Retention** (`services/retention.py`): off unless `RETENTION_HOURS` is set - an unparseable
  value also leaves it off, because a typo in `.env` must not start deleting media on a schedule
  nobody chose (the opposite of `limits.py`, which fails closed). The sweeper is a daemon thread
  started in the lifespan; it deletes expired jobs whose status is terminal, their media, and any
  file on disk with no live job behind it. Jobs still in the pipeline are skipped however old they
  are - the queue is sequential, so age alone does not mean abandoned. `delete_job_files` is the
  single owner of "remove a job's media"; `DELETE /api/jobs/{id}` calls it too, which is what fixed
  that route leaving the export behind.
- **Worker**: threaded queue, sequential processing, per-stage job status polled by the frontend.
  Queue items are `QueuedTask(kind, job_id, ...)` with `kind` either `"process"` or `"export"`.
- **Export is asynchronous**: `POST /export` validates synchronously (404 unknown job, 400 not
  completed, 404 missing source, 400 nothing accepted), sets `export_status="queued"`, enqueues and
  returns **202**. `export_status`/`export_error` are deliberately separate from `job.status`: a
  failed render must not mark a reviewed job `failed` and strand the user's work.
- **Admin auth** (`app/auth.py`): `require_admin` is a no-op when `ADMIN_TOKEN` is unset and a 401
  otherwise. It is declared on all three destructive routes individually — `reset_all` calls the
  other two as plain Python functions, so a `Depends` on those never runs for it.
- **Keyboard review**: the review page binds `J`/`K`, `A`/`R` (decide and advance), `M`, `Space`,
  `P` and `?` on `window`, guarded against modifier keys and text inputs. `WaveformHandle` exposes
  `playClip` and `togglePlayPause`; the auto-pause timer for `playClip` is held in a ref and
  cleared per call, since a keyboard-driven clip is easy to retrigger mid-playback.

## Conventions

- Backend: Pydantic for validation (`schemas.py`), logic in `services/`, routing in `routes/`.
- Frontend: functional components, Tailwind v4, strictly typed API interactions.
- Fixtures in `tests/` must be synthetic. Never commit a real customer recording or transcript.

## Common Issues

**Unreadable LLM response**: `_parse_llm_response` raises `AnalysisError` with an excerpt of the raw
response instead of returning `[]`. `_validate_entries` then checks each item: non-object entries,
missing/empty `text`, non-string fields, and unknown `action`/`severity` values all raise too — an
unusable entry used to become an empty-text `cut` on the first segment, which `auto_fix` applied.
A single bad chunk leaves the job `completed` with a partial-analysis warning in `error_message`;
if every chunk fails, the job fails with the reason. `AnalysisResult.total_segments_analyzed`
counts only segments a chunk answered for (`total_segments` is the denominator), and `to_json`
serializes `is_partial` + `failed_chunks`; the CLI prints the warning and exits 2.

**Upload rejections**: `POST /api/jobs` is a sync `def` on purpose — it streams to disk and runs
ffprobe, so FastAPI must schedule it in the thread pool rather than on the event loop. Over the
size cap is a 413, over the duration cap is a 413, and an unprobeable duration is a **422**:
`enforce_duration_limit` fails closed rather than letting an unbounded stream past the cap.

**Server won't start**: `preflight.verify_environment()` runs first in the lifespan and lists every
unmet requirement (`OPENAI_API_KEY`, `ffmpeg`, `ffprobe`). `SKIP_PREFLIGHT=1` boots anyway.

**Slow transcription**: use `--model medium` or `--model small` on the CLI for faster, less accurate
transcription.

**CORS errors**: backend on 8000, frontend on 3000, or set `CORS_ORIGINS`.

**Database issues**: use the admin dashboard at `/admin` to reset, or delete
`backend/audio_compliance.db`.
