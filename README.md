# CleanCut

Describe what to find in plain English. Review it on a waveform. Export a surgically edited file.

CleanCut transcribes audio or video with word-level timestamps, sends the transcript to an LLM
along with your instruction ("cut every filler word", "flag any specific dollar figure", "mute
anything that sounds like a phone number"), and turns the answers back into precise timestamps.
You review each suggestion on a waveform, accept or reject it, choose cut or mute per edit, and
export a single re-encoded file.

**Copilot, not autopilot.** Nothing is removed without a human accepting it.

## Key features

- **Word-level transcription** via `faster-whisper`, with int8 quantization for local CPU use.
- **Prompt-driven analysis** — a free-form instruction, not a fixed rulebook.
- **Rule presets** for recurring review jobs (income and lifestyle claims, PII redaction), selectable
  in place of a prompt.
- **Deterministic scrubber** — silence and filler-word detection straight off the word timestamps,
  no LLM involved, plus a one-click "Clean All" for those.
- **Interactive review** — a waveform with a marker per suggestion, and keyboard-driven
  accept/reject (`J`/`K` to move, `A`/`R` to decide and advance, `M` to flip cut/mute,
  `Space` to play, `P` to replay the selected clip, `T` for the transcript, `?` for the full list).
- **Searchable transcript panel** — the transcript the analysis actually ran on, kept with the job.
  Click a line to seek there, watch it follow playback, and see which lines carry a suggested edit.
- **Per-edit cut or mute**, honored independently on export.
- **A/V-sync-preserving export** — a single FFmpeg `trim`/`atrim` + `concat` filter graph, so video
  stays in sync with its audio across every cut.
- **Background job queue** with per-stage status (`converting` → `transcribing` → `analyzing` →
  `exporting` → `completed`), polled by the frontend. Export is queued the same way, so a long
  re-encode never holds an HTTP request open.
- **Multi-language**, including code-switching between English and Spanish mid-sentence.

## Architecture

| Layer | Stack |
|---|---|
| Backend | FastAPI, SQLAlchemy (SQLite), FFmpeg, OpenAI API |
| Frontend | Next.js 15, Tailwind CSS v4, Wavesurfer.js |
| Analysis | `faster-whisper` transcription, chunked sliding-window LLM analysis |

```
upload → queue → Whisper (word timestamps) → LLM analysis → review UI → FFmpeg export
```

## Quickstart (Docker)

```bash
cp .env.example .env      # then add your OPENAI_API_KEY
docker compose up --build
```

Open http://localhost:3000.

## Quickstart (local)

Requires Python 3.10+, Node 18+, and FFmpeg (`brew install ffmpeg`).

```bash
# 1. Environment — a .env at the repo root, read by the backend
cp .env.example .env      # then add your OPENAI_API_KEY

# 2. Backend (port 8000)
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 3. Frontend (port 3000), in a second terminal
cd frontend
npm install
npm run dev
```

Or run both with `./start.sh`.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

GitHub Actions runs the same suite on every push and pull request, alongside `tsc --noEmit` and a
production frontend build — see `.github/workflows/ci.yml`.

## CLI

The analysis pipeline is also runnable standalone, without the web app:

Run it as a module from `backend/`, so the `app` package resolves:

```bash
cd backend
source .venv/bin/activate
python -m app.analysis.analyze path/to/audio.mp3 --prompt "flag every income claim"

# Or with a built-in preset instead of a prompt
python -m app.analysis.analyze path/to/audio.mp3 --preset income-claims

# Skip transcription and analyze an existing transcript
python -m app.analysis.analyze --transcript path/to/transcript.txt --prompt "find filler words"
```

## API

Interactive Swagger docs at http://localhost:8000/docs.

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/jobs` | Upload media and start processing |
| GET | `/api/jobs` | List jobs |
| GET | `/api/jobs/presets` | List the built-in rule presets |
| GET | `/api/jobs/{id}` | Job status and metadata |
| DELETE | `/api/jobs/{id}` | Delete a job and its files |
| GET | `/api/jobs/{id}/transcript` | The transcript the analysis ran on |
| GET | `/api/jobs/{id}/violations` | List suggested edits |
| PATCH | `/api/jobs/{id}/violations/{vid}` | Set status (accepted/rejected) or action (cut/mute) |
| POST | `/api/jobs/{id}/violations/bulk-update` | Bulk accept/reject, optionally filtered by label |
| GET | `/api/jobs/{id}/audio` | Stream the original media |
| GET | `/api/jobs/{id}/audio/waveform` | Cached waveform peaks |
| POST | `/api/jobs/{id}/export` | Queue the edited render (202; poll `export_status`) |
| GET | `/api/jobs/{id}/export/download` | Download the result |
| GET | `/api/admin/stats` | System statistics |
| POST | `/api/admin/reset-database`, `/clear-storage`, `/reset-all` | Destructive wipes; gated by `ADMIN_TOKEN` when one is set |

## Analysis modes

**Prompt mode** (default) — your instruction drives the analysis. Each suggestion comes back with a
label, a cut/mute recommendation, and the model's reasoning.

**Preset mode** — a curated rulebook replaces the prompt, and suggestions come back with a rule
category and a severity. Presets live in `backend/app/analysis/presets/` as markdown; adding one is
a new file plus an entry in `PRESETS` in `prompt_analyzer.py`.

| Preset | Purpose |
|---|---|
| `income-claims` | FTC-style earnings and lifestyle claim review for direct-selling material |
| `pii-redaction` | Spoken personal, financial, and credential data, defaulted to mute |

Long transcripts are chunked at 50 segments with a 10-segment overlap so nothing is missed at a
boundary, then deduplicated by label and timestamp proximity.

## Reviewing

Every suggestion is reviewed by hand — nothing is removed until you accept it. The review screen is
built for a keyboard pass: move down the list, decide, and the selection advances on its own.

| Key | Action |
|---|---|
| `J` / `↓` | Next suggestion |
| `K` / `↑` | Previous suggestion |
| `A` | Accept and advance |
| `R` | Reject and advance |
| `M` | Toggle cut ↔ mute on the selected edit |
| `Space` | Play / pause |
| `P` | Replay just the selected clip |
| `T` | Show or hide the transcript panel |
| `?` | Show or hide the shortcut list |

The transcript panel sits on the right, off by default. It scrolls to follow playback, clicking a
line seeks the waveform to it, and lines overlapping a suggested edit are marked in that edit's
colour — so a flagged quote can be read in context rather than judged from a marker alone. Jobs
processed before transcripts were stored simply don't offer the panel; the transcript cannot be
recovered without re-transcribing, and the API says so rather than returning an empty one.

The list scrolls to follow the selection, and the keys are ignored while a modifier is held or a
text field has focus. Decision keys (`A`, `R`, `M`) are also ignored while an edit is still in
flight, so holding one down cannot stack overlapping updates; navigation stays live throughout.

## Configuration

Set in `.env` at the repo root:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | Required for analysis |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `DATABASE_PATH` | `backend/audio_compliance.db` | SQLite file location |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api` | Backend URL baked into the frontend build |
| `MAX_UPLOAD_MB` | `500` | Upload size cap; larger uploads are rejected with a 413 |
| `MAX_DURATION_MINUTES` | `120` | Media length cap, measured with `ffprobe` before queueing; media whose duration cannot be read is rejected |
| `RETENTION_HOURS` | unset | Delete jobs and their media once they are this old. Unset keeps everything forever |
| `RETENTION_SWEEP_MINUTES` | `15` | How often the retention sweeper runs |
| `ADMIN_TOKEN` | unset | Shared secret for the destructive admin routes. Unset leaves them open (fine on localhost); set it and they require an `X-Admin-Token` header |
| `SKIP_PREFLIGHT` | unset | Boot despite a failed startup check (jobs will still fail) |

## Failure modes

The backend runs a preflight at startup and refuses to boot if `OPENAI_API_KEY` is missing or
`ffmpeg`/`ffprobe` are not on PATH — both are otherwise only reached minutes into a job, where a
missing line in `.env` looks like an application bug.

Uploads are capped by size and by duration; both come back as a 413 with the limit named, and the
rejected job is not left behind in the jobs list. The duration cap fails closed — a file `ffprobe`
cannot read a duration from is rejected with a 422, since a limit that any unprobeable stream can
skip is not a limit.

When the model returns something that isn't a readable list of suggestions, that is reported rather
than silently treated as "nothing found" — a distinction that matters when the output is a
compliance review. A single unreadable chunk of a long transcript leaves the job completed with a
partial-analysis warning naming the unanalyzed timespans; if every chunk fails, the job fails. The
same applies to entries that parse but say nothing actionable — an item with no quoted text or an
unknown action fails its chunk rather than becoming an empty edit that `auto_fix` would apply.

The CLI carries the same status: the saved JSON includes `is_partial` and `failed_chunks`,
`total_segments_analyzed` counts only segments a chunk actually answered for, and a partial run
exits 2 so a script cannot read it as clean.

## Privacy

Transcription runs locally on your machine. Only the resulting transcript text is sent to the LLM
provider — never the audio. Jobs, uploads, exports, and the stored transcript stay on local disk
(SQLite plus `backend/uploads/` and `backend/exports/`). Use the admin dashboard at `/admin` to
wipe both.

The wipe endpoints delete everything and are open by default, which is only safe on a machine you
control. Set `ADMIN_TOKEN` before putting the API anywhere else; the dashboard has a field for it.

Nothing is deleted on a timer unless you ask for it. Set `RETENTION_HOURS` and a background sweeper
deletes each job — its row, its violations, its upload, and its export — once it is that old, along
with any media left on disk that no job refers to any more. A job still moving through the pipeline
is never collected however old it is, since the queue is sequential and a job can wait a long time
behind a long one. The default is unset, because on your own laptop the recordings are yours and
deleting them by surprise is the worse failure.

## License

MIT — see [LICENSE](LICENSE).
