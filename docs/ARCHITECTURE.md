# Architecture: CleanCut

How CleanCut is built **today**, on this commit. Where this file and the code disagree, the code is
right and this file is a bug — an earlier version of it described a Celery worker, Zustand state and
VAD-based silence detection, none of which were ever true.

[`AGENTS.md`](../AGENTS.md) at the repo root is the deeper reference and carries the reasoning
behind each decision; this is the map. An architectural change is a two-file change — that file and
this one — and they may differ in depth but never in fact.

---

## System overview

```
browser ──relative /api──▶ Next.js server ──BACKEND_ORIGIN──▶ FastAPI ──▶ worker thread
   │                    (route handler proxy)                    │            │
   └── wavesurfer.js waveform, keyboard review                   │            ├─ FFmpeg
                                                                 │            ├─ faster-whisper
                                                          SQLite ┘            └─ LLM provider
```

Three processes at most, and on a default install they all sit on loopback.

- **Frontend** — Next.js 16 / React 19 / Tailwind v4. The browser only ever calls a **relative**
  `/api`; nothing about the backend's address is compiled into the page.
- **The proxy** (`frontend/src/app/api/[...path]/route.ts`) — a **route handler**, deliberately not a
  `next.config.ts` `rewrites()` entry. Next resolves rewrites at *build* time and writes the
  destination into `routes-manifest.json`, which baked `http://localhost:8000` into the Compose
  image and pointed the frontend container at itself. A route handler is evaluated per request, so
  it reads the running container's environment. The body streams both ways, because this path
  carries 500 MB uploads and ranged audio.
- **Backend** — FastAPI, SQLAlchemy over SQLite, and a threaded worker in the same process.
- **State** — SQLite (`jobs`, `violations`, `tasks`). No Redis, no external broker.

---

## Data flow

1. **Upload** — `POST /api/jobs` validates the preset and extension, then commits the `Job` row
   first: it owns the id the uploaded file is named after. The file streams to `uploads/` next, with
   the size cap (`app/limits.py`) enforced as it writes; the duration cap is checked after that,
   against the file now on disk. A rejection at either point rolls the row back through
   `_discard_job`. Returns **200** with the job, not 202 — the upload itself is synchronous, only the
   processing behind it is queued. A sync `def` on purpose, so FastAPI runs it in the thread pool
   rather than blocking the event loop.
2. **Convert** — video gets its audio track extracted; anything else is normalised
   (`services/media_editor.py`).
3. **Transcribe** — `analysis/transcriber.py`, faster-whisper with int8 quantization, **word-level**
   timestamps. The transcript is stored on the job *before* analysis runs, so a failed analysis
   still leaves the expensive half behind.
4. **Analyze (LLM)** — `analysis/prompt_analyzer.py`. Transcripts of more than 100 segments are split
   into a chunked sliding window (50 segments, 10 overlap); shorter ones run as a single chunk.
   Results are deduplicated across chunk boundaries, not by timestamp proximity: a suggestion is
   collapsed into an earlier one only when it comes from a **different chunk**, the labels agree, the
   spans genuinely overlap (abutting is two edits, not one), and `_is_same_finding` confirms text
   agreement (equal, one quoting a token-run of the other, or a `difflib` ratio above
   `_DUPLICATE_TEXT_RATIO`). The fuller quote wins. The model's quoted text is mapped back onto word
   timestamps by `_find_text_timestamps`. `analysis/providers.py` routes
   `CLEANCUT_MODEL="provider:model"` to OpenAI, Anthropic, or a keyless keyword-matching `mock`
   (`mock:demo`, for running the app with no API key) behind a one-method interface:
   `complete(system_prompt, user_prompt) -> str`.
5. **Scrub (deterministic)** — `services/scrubber.py`. Filler words and dead air, measured off word
   timestamps and audio levels with no model in the loop.
6. **Review** — the waveform, the suggestion list and the transcript panel. Nothing is applied
   without a human accepting it.
7. **Export** — `services/exports.py` partitions the accepted edits into cuts and mutes and hands
   them to `services/media_editor.py`, which builds **one** FFmpeg `trim`/`atrim` + `concat` filter
   graph. Mutes are applied before cuts, since cutting shifts the timeline under the mute
   timestamps. A single pass, so A/V stays in sync.

---

## Durable queue

`services/task_store.py` plus the `tasks` table. The in-memory `queue.Queue` is still what the
worker blocks on, but **every enqueue writes the row first and puts second**, so a restart cannot
silently drop work a route has already answered for — a 200 upload or a 202 re-analyze/export.

- The worker claims a row (`state="running"`, `attempts += 1`) before the handler and deletes it
  after, in a `finally` — a handler that raises retires its task instead of being replayed into the
  same failure forever.
- `worker.recover_interrupted_work()` runs in the lifespan **before** the worker starts. Outstanding
  rows replay oldest-first; a task past `MAX_ATTEMPTS = 3` is abandoned with the reason written onto
  the job. That cutoff is the stop on a poison task that kills the process on every boot.
- A second pass catches jobs whose *status* claims they are mid-flight with no task to explain it.
  Those re-queue only when re-running is safe — no stored transcript, media still on disk. A job
  carrying a transcript could be an interrupted **re-analysis**, and re-running it as a fresh job
  would re-transcribe over somebody's review, so it fails with an actionable message instead.

Kinds are `process`, `export` and `reanalyze`, one outstanding per job per kind.

---

## Dead-air detection

The transcript proposes a span nobody speaks over, and an RMS pass (`services/levels.py`) must
**confirm** it sits below `DEAD_AIR_FLOOR_DB`. The confirmed sub-interval is what gets emitted,
which also trims Whisper's loose boundaries off the next line's onset. If the level pass cannot run,
silence detection is **skipped** and the job carries a warning — never downgraded back to gaps.

**VAD was specified and rejected for this job specifically.** Gap-detection alone flagged room tone,
applause and music beds as dead air, and `auto_scrub` cut them unreviewed. VAD answers the same
question — "is anyone speaking" — so it makes the same mistake. Requiring the level pass to agree is
what fixed it. Transcription itself still uses VAD (`vad_filter` on the faster-whisper call, to skip
silent stretches before decoding); the rejection is scoped to dead-air *detection*, not to voice
activity detection generally. See `docs/ROADMAP.md`.

---

## Export currency

Two counters on the job: `edit_revision`, bumped whenever the **accepted** set moves, and
`export_revision`, the revision the file on disk came from. `services/exports.py` is the single
owner of `EXPORT_DIR`, the `{job_id}_edited{ext}` naming rule, the cut/mute partition and the render
call — read through the module at call time, never imported as a constant, which is pinned by an AST
test (`tests/test_export_dir_owner.py`).

`mark_export_invalidated` bumps the counter and returns the superseded files **without committing**,
so a route can put the reviewer's decision and the invalidation it causes in one transaction and
unlink after the commit. As two commits, a failure in between left the decision durable while the
export went on advertising itself as `ready`. `affects_export` keeps this from churning: only
accepted edits reach FFmpeg, so `pending → rejected` changes nothing and keeps the file.

Export runs on the same queue and reports through `export_status` / `export_error`, deliberately
separate from `job.status` — a failed render must not mark a reviewed job `failed` and strand the
work.

---

## Trust boundaries

- **The transcript is data, not instructions.** A speaker cannot talk the analyzer into reporting a
  clean recording; the request is built to make that fail loud rather than fail silent.
- **Admin auth fails closed.** With no `ADMIN_TOKEN` configured the destructive routes answer 503,
  not a pass.
- **Loopback by default.** Every route but the admin wipes is unauthenticated, so the interface the
  port sits on *is* the access control.

See [`../SECURITY.md`](../SECURITY.md) for the threat model, the deployment posture and what is by
design.

---

## Accuracy is measured

`app/eval/` scores suggestions against a labelled synthetic clip and reports precision, recall and
per-category coverage. Ground truth is deliberately two files: generated timing
(`expected_violations.json`) and authored judgements (`eval_labels.json`), joined by index so the
labels survive a re-render. The `controls` are the real assertion — an honest earnings disclaimer
between two income claims must never be flagged, and a control hit fails the run regardless of the
aggregate numbers. See `CONTRIBUTING.md` for the eval commands and the thresholds CI gates on.

---

## What this is not

No Celery. No Redis or external broker — the queue is a SQLite table and a thread. No Zustand or
Redux — review state is React state in `jobs/[id]/page.tsx`. No VAD in dead-air detection
specifically (see above; transcription does use it). No `next/font/google`; the fonts are
self-hosted so `next build` never needs the network. No authentication on the media routes, by
design and documented.
