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
- **Interactive review** — a waveform with a marker per suggestion, keyboard-driven accept/reject.
- **Per-edit cut or mute**, honored independently on export.
- **A/V-sync-preserving export** — a single FFmpeg `trim`/`atrim` + `concat` filter graph, so video
  stays in sync with its audio across every cut.
- **Background job queue** with per-stage status (`converting` → `transcribing` → `analyzing` →
  `exporting` → `completed`), polled by the frontend.
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
| GET | `/api/jobs/{id}/violations` | List suggested edits |
| PATCH | `/api/jobs/{id}/violations/{vid}` | Set status (accepted/rejected) or action (cut/mute) |
| POST | `/api/jobs/{id}/violations/bulk-update` | Bulk accept/reject, optionally filtered by label |
| GET | `/api/jobs/{id}/audio` | Stream the original media |
| GET | `/api/jobs/{id}/audio/waveform` | Cached waveform peaks |
| POST | `/api/jobs/{id}/export` | Render the edited file |
| GET | `/api/jobs/{id}/export/download` | Download the result |
| GET | `/api/admin/stats` | System statistics |

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

## Configuration

Set in `.env` at the repo root:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | Required for analysis |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `DATABASE_PATH` | `backend/audio_compliance.db` | SQLite file location |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api` | Backend URL baked into the frontend build |

## Privacy

Transcription runs locally on your machine. Only the resulting transcript text is sent to the LLM
provider — never the audio. Jobs, uploads, and exports stay on local disk (SQLite plus
`backend/uploads/` and `backend/exports/`). Use the admin dashboard at `/admin` to wipe both.
