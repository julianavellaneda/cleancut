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
│   │   ├── network.py              # CLEANCUT_HOST: loopback-by-default binding
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
│   │   ├── eval/
│   │   │   ├── spec.py             # Ground truth: authored labels + measured offsets
│   │   │   ├── scoring.py          # Match suggestions to labels, precision/recall
│   │   │   └── run.py              # CLI: score a saved run, or --live
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
│   │       ├── transcripts.py      # Transcript JSON <-> the jobs.transcript column
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
│       │   ├── TranscriptPanel.tsx # Readable transcript, click-to-seek
│       │   └── ViolationCard.tsx   # Detail, accept/reject, cut/mute toggle
│       └── lib/api.ts              # API client
├── docs/                           # Architecture, spec, roadmap
└── tests/                          # Media fixtures (synthetic only) + the eval labels
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

# Frontend tests (vitest + Testing Library, jsdom - no browser)
npm test
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

**Eval** (how accurate the detectors are, as a number):

```bash
cd backend && source .venv/bin/activate
# Grade a recorded run. Free and deterministic - this checks the scorer, not the detectors.
python -m app.eval.run ../tests/fixtures/demo/seed_job.json

# Grade the deterministic detectors as they stand. Free: no model, no API key. What CI gates on.
python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3 --suite scrub

# Grade the whole pipeline. Transcribes and calls the LLM, so it stays opt-in.
python -m app.eval.run --live ../tests/fixtures/demo/demo_seminar.mp3

python -m app.eval.run ../tests/fixtures/demo/seed_job.json --json --min-recall 0.75

# Regenerate the committed word-level transcript the --detectors mode reads (local, free).
python ../scripts/dump_demo_transcript.py
```

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/jobs` | Upload media, enqueue processing (multipart) |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/presets` | List built-in rule presets |
| GET | `/api/jobs/{id}` | Job details + violation counts |
| DELETE | `/api/jobs/{id}` | Delete job and files |
| GET | `/api/jobs/{id}/transcript` | Stored transcript (404 when the job has none) |
| POST | `/api/jobs/{id}/reanalyze` | Re-run analysis on the stored transcript (202; poll `status`) |
| GET | `/api/jobs/{id}/violations` | List suggested edits |
| PATCH | `/api/jobs/{id}/violations/{vid}` | Update status or action |
| POST | `/api/jobs/{id}/violations/bulk-update` | Bulk update, filtered by label, id, or source status |
| GET | `/api/jobs/{id}/audio` | Stream original media |
| GET | `/api/jobs/{id}/audio/waveform` | Waveform peaks JSON |
| POST | `/api/jobs/{id}/export` | Queue an edited render (202; poll `export_status`) |
| GET | `/api/jobs/{id}/export/download` | Download edited file |
| GET | `/api/admin/stats` | System-wide statistics |
| POST | `/api/admin/reset-database` | Wipe all database records (requires `ADMIN_TOKEN`; 503 until one is set) |
| POST | `/api/admin/clear-storage` | Delete all media files (requires `ADMIN_TOKEN`; 503 until one is set) |
| POST | `/api/admin/reset-all` | Wipe database + storage (requires `ADMIN_TOKEN`; 503 until one is set) |

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
    transcript TEXT,                   -- JSON transcript segments, NULL on old rows
    export_status TEXT DEFAULT 'none', -- none, queued, exporting, ready, failed
    export_error TEXT,
    edit_revision INTEGER DEFAULT 0,   -- bumped whenever the accepted edit set moves
    export_revision INTEGER            -- the edit_revision the export was rendered from
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
CLEANCUT_MODEL=            # optional; "provider:model", default openai:gpt-4o
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=         # required instead when CLEANCUT_MODEL names anthropic
CLEANCUT_HOST=127.0.0.1   # optional; interface to listen on. Loopback default; 0.0.0.0 exposes it
CORS_ORIGINS=http://localhost:3000
DATABASE_PATH=            # optional; Docker sets this to a mounted volume
NEXT_PUBLIC_API_URL=      # optional; baked into the frontend build
MAX_UPLOAD_MB=500         # optional; upload size cap
MAX_DURATION_MINUTES=120  # optional; media length cap, probed with ffprobe (fails closed)
DEAD_AIR_FLOOR_DB=-50     # optional; dBFS below which audio counts as silence
DEAD_AIR_MIN_SECONDS=0.75 # optional; shortest dead-air span worth suggesting
ADMIN_TOKEN=              # destructive /api/admin/* needs it as X-Admin-Token; unset = those routes 503
ALLOW_UNAUTHENTICATED_ADMIN= # optional; 1 leaves them open with no token (local only)
RETENTION_HOURS=          # optional; delete jobs + media older than this. Unset = keep forever
RETENTION_SWEEP_MINUTES=15 # optional; sweeper interval
SKIP_PREFLIGHT=           # optional; 1 to boot past a failed startup check
```

System dependency: `brew install ffmpeg`.

## Key Implementation Details

- **Transcriber**: faster-whisper with int8 quantization for M-series Mac performance.
- **Model router** (`analysis/providers.py`): `CLEANCUT_MODEL="provider:model"` picks the vendor and
  the model - `openai:gpt-4o` (the default, unchanged behaviour) or `anthropic:claude-opus-5`. One
  string rather than two variables, because a provider and a model that do not go together is the
  misconfiguration worth making unrepresentable. A provider only has to answer
  `complete(system_prompt, user_prompt) -> str`; parsing and the JSON contract stay in
  `prompt_analyzer`, where they are the same for every vendor. `preflight` checks the key named by
  the *configured* provider, not `OPENAI_API_KEY` unconditionally. The Anthropic path has no
  `response_format`: the system prompts already spell the contract out and `_parse_llm_response`
  copes with a fenced answer. It does enable server-side refusal fallbacks, and turns a
  `stop_reason == "refusal"` into a `ProviderError` - which `analyze` catches per chunk alongside
  `AnalysisError`, so a declined section becomes a named gap rather than an empty answer that reads
  as a clean recording.
- **PromptAnalyzer**: two modes.
  - *Prompt mode* (`preset=None`): the user's instruction drives analysis; returns label + action.
  - *Preset mode*: a rulebook from `analysis/presets/` replaces the prompt; returns rule_violated +
    severity, and falls back to the preset's `default_action` (mute for `pii-redaction`).
  - Chunked sliding window for long transcripts: 50 segments per chunk, 10 overlap, deduplicated by
    label + timestamp proximity (5s).
  - LLM-quoted text is remapped onto word-level timestamps via `_find_text_timestamps`.
- **Adding a preset**: drop a markdown rulebook in `analysis/presets/` and add an entry to `PRESETS`
  in `prompt_analyzer.py`. It surfaces automatically via `GET /api/jobs/presets`.
- **Scrubber**: deterministic filler detection off word timestamps, no LLM. Matching is a
  longest-first pass per segment: `FILLER_PHRASES` holds the multi-word fillers ("you know",
  "I mean") because a space in `FILLER_WORDS` can never match a word-at-a-time scan, and
  `FILLER_WORDS` lists every spelling Whisper actually emits for a sound ("hm" *and* "hmm")
  rather than inferring them. Agreement noises ("mhm", "uh-huh") are deliberately excluded:
  cutting one deletes a spoken "yes". Dead air needs *two*
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
- **Export staleness** (`exports.invalidate_export`, `exports.export_is_stale`): an export is only
  current for the edit list it was rendered from, so the job carries two counters -
  `edit_revision`, bumped whenever the *accepted* set moves, and `export_revision`, the revision the
  file on disk came from. Every route that can move a suggestion goes through `invalidate_export`,
  which bumps, deletes the superseded file, and puts `export_status` back to `none`; the file is
  deleted rather than flagged because the counter is monotonic, so those bytes can never be current
  again. `affects_export` is what keeps this from churning: only accepted edits reach FFmpeg, so
  pending -> rejected, or re-cutting a rejected row, changes nothing and keeps the export. A render
  already in flight is left alone - `_process_export` captures the revision before it starts and
  re-checks after, discarding a file the edits overtook rather than publishing it `ready`. A
  **NULL** `export_revision` means "provenance unknown" (never exported, or a row from before these
  columns) and is deliberately *not* stale, which keeps an old row's download working. Both
  counters are on `JobResponse`, so the review page derives staleness from the server rather than
  from a flag that could not survive a reload or a second tab. `/export/download` and
  `/export/stream` answer **409** on a stale export - belt and braces, since invalidation normally
  deletes the file first.
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
- **Network binding** (`app/network.py`): every route but the admin wipes is unauthenticated, so the
  interface the port sits on *is* the access control. `CLEANCUT_HOST` defaults to **127.0.0.1** and
  names the interface CleanCut is *reachable* on, not the argument any one process hands a socket:
  `start.sh` passes it to uvicorn and to `next dev` (which binds every interface otherwise), while
  `docker-compose.yml` uses it as the published interface and the container still binds `0.0.0.0`
  internally - a container's network is not the host's. One variable rather than a bind/publish
  pair, because that is what lets the running app answer the only question it cares about: can
  anyone but this machine reach us. `is_loopback` treats anything unrecognised as exposed and never
  does a DNS lookup - a security decision that depends on a network round-trip fails in whichever
  direction the network does. A non-loopback host is warned about at startup, never refused.
- **Admin auth** (`app/auth.py`): `require_admin` fails **closed**. With `ADMIN_TOKEN` set it is the
  usual 401-unless-it-matches; with no token configured it is a **503**, not a pass — an unset
  variable is the state every deployment starts in and the one nobody notices, so it must not be the
  state that hands out the delete button. 503 rather than 401 because no header the caller could
  send would help: the fault is the server's configuration. `ALLOW_UNAUTHENTICATED_ADMIN=1` restores
  the old open behaviour for local dev, and is ignored when `ADMIN_TOKEN` is set — the flag opens the
  routes, so it must never weaken a gate an operator deliberately configured. It is also ignored
  once `CLEANCUT_HOST` is not loopback: the flag means "anything that can reach the port may wipe
  everything", which is not what was agreed to once a network can reach it, so the two settings in
  contradiction resolve to the closed reading with a 503 that names the conflict. `GET /admin/stats`
  stays ungated throughout: the dashboard has to load on an unconfigured server. The dependency is
  declared on all three destructive routes individually — `reset_all` calls the other two as plain
  Python functions, so a `Depends` on those never runs for it.
- **Transcript persistence** (`services/transcripts.py`): the worker stores the transcript on the
  job *before* analysis runs, so a partial or failed analysis still leaves the text behind - the
  LLM is the stage that fails, and re-running it is cheap next to re-transcribing. Stored **with
  word timing** (schema version 2): it is ~20x the bytes of segments alone and no reader wants it,
  but re-analysis needs it - a quote can only be placed as precisely as the timing behind it, and a
  re-run producing coarser markers than the first pass would put two kinds of precision on one
  screen. Words are stored and served to nobody; the route still returns lines. Version 1 rows have
  no words and read fine; a re-run over one falls back to segment spans, which is the analyzer's
  existing behaviour for an untimed segment. `GET /api/jobs/{id}/transcript` is a **404** for an unknown job, a job
  that never got that far, and a row from before the column existed - all three mean "nothing to
  read", where an empty segment list would claim the recording was silent. `from_json` is lenient
  by design: a truncated or hand-edited row reads as absent rather than raising.
- **Eval harness** (`app/eval/`): scores a run's suggestions against the labelled demo clip and
  reports precision, recall and per-category coverage. Ground truth is two files on purpose -
  `tests/fixtures/demo/expected_violations.json` is *generated* on every re-render and holds only
  timing, `eval_labels.json` is *authored* and holds the judgements, joined by line/pause index so
  the labels survive a re-render. Matching has to be loose in three specific ways: labels are
  free-form in prompt mode so a category is identified by declared substrings, coverage is measured
  against the *shorter* span so a model quoting one tight clause is not punished for cutting less,
  and a second suggestion on an already-matched label is a **duplicate** rather than a false
  positive. Fillers are matched by the word rather than the window, since word timestamps drift
  against the script's line offsets. Recall is per **suite** - a run told to find income claims is
  not marked down for missing an email address, so an out-of-scope hit is set aside and not graded
  either way - but only a label the clip *contains*: a suggestion landing on one marked
  `present: false` invented it, and counts as a false positive. The `controls` are the real
  assertion: an honest earnings disclaimer sitting between two income claims must never be flagged,
  and a control hit fails the run regardless of the aggregate numbers. Adding a label means editing
  `eval_labels.json`, not the scorer; a label whose span has no slot of its own (silence at a clip
  seam) names two line indices, and its boundary error is not reported since the window is a
  stand-in.
  Three input modes measure three different things: a saved run grades a **snapshot** (the scorer
  and the labels), `--detectors MEDIA` grades the **scrubber** against the real audio plus the
  committed `transcript_words.json` for free, and `--live MEDIA` grades the **whole pipeline** at
  the cost of a transcription and a completion. CI runs the first two. Exit codes are `0` pass,
  `1` a flagged control or a missed floor, and `2` the analysis was partial and `--allow-partial`
  was not given - a partial run's numbers can clear every floor, since the chunks that answered are
  graded as if they were the whole transcript.
- **Bulk update / undo** (`routes/violations.py`): `bulk-update` selects on three filters -
  `labels` and `from_status` as query params, `ids` in the body. `from_status` defaults to
  `pending`, which is what stops "Clean All" from overwriting an edit the reviewer already rejected
  by hand. Undo is the same call reversed: the review page captures the ids the sweep moved *before*
  it runs (afterwards they are indistinguishable from edits accepted by hand) and sends them back
  with `from_status=accepted`. An empty `ids` list means "these zero rows" and must never fall
  through to the whole job. Both `status` and `action` are validated here as they are on the PATCH;
  the bulk route used to write whatever it was given.

- **Re-analysis** (`POST /api/jobs/{id}/reanalyze` -> `worker._process_reanalysis`): the payoff for
  persisting the transcript. A new prompt used to mean a new Whisper pass; now it reads the stored
  words. The route validates and queues (202, poll `status`), refusing a job with no stored
  transcript or one still in the pipeline with a **409** - the job is real, so a 404 would send the
  caller hunting for it. What a re-run replaces is the design: the LLM's suggestions answer the old
  prompt so they all go, accepted and rejected included, since a decision about a suggestion that no
  longer exists cannot be carried forward honestly; the scrubber's are deterministic and
  prompt-independent, so they and their decisions stay. New suggestions are never pre-accepted even
  on an `auto_fix` job - that flag was a choice about the upload, and a re-run is a choice made in
  the review screen. A failed re-analysis leaves the job `completed` with a warning rather than
  `failed`, the same argument as a failed export, and the old suggestions survive because the delete
  only runs once the new analysis returns.

- **Keyboard review**: the review page binds `J`/`K`, `A`/`R` (decide and advance), `M`, `Space`,
  `P`, `T` (transcript panel) and `?` on `window`, guarded against modifier keys and text inputs.
  `Space` also defers to a focused `<button>`, since the transcript's lines are buttons and the
  browser's activate-on-space would otherwise fire alongside play/pause. `WaveformHandle` exposes
  `playClip`, `togglePlayPause` and `seekTo` (which the transcript panel drives); the auto-pause timer for `playClip` is held in a ref and
  cleared per call, since a keyboard-driven clip is easy to retrigger mid-playback.

## Conventions

- Backend: Pydantic for validation (`schemas.py`), logic in `services/`, routing in `routes/`.
- Frontend: functional components, Tailwind v4, strictly typed API interactions.
- Frontend tests live next to what they test (`Foo.test.tsx`), run under vitest in jsdom, and are
  included by `tsc --noEmit` but not by `next build`. `src/test/setup.ts` stubs `ResizeObserver`
  and `scrollIntoView`, which jsdom lacks and a plain render of the sidebar reaches.
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
