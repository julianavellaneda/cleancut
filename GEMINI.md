# GEMINI.md

This file provides foundational mandates and contextual guidance for Gemini CLI when working in this
repository. It mirrors `CLAUDE.md`; keep the two in sync when the architecture changes.

## Project Overview

**CleanCut** is a prompt-driven audio and video editor. Describe what to find in plain English, review
the AI's suggestions on a waveform, export a surgically edited file. It transcribes media with
word-level timestamps, analyzes the transcript with an LLM, and renders accepted edits with FFmpeg.

### Core Philosophy: "Copilot, not Autopilot"
The system assists human reviewers rather than replacing them. The AI flags segments with reasoning
and timestamps; the user decides whether to cut, mute, or ignore each one.

Even under `auto_fix`/`auto_scrub`, two kinds of suggestion are always left pending: one whose quote
could not be placed against the transcript (`violations.is_approximate` — the span is the model's
estimate) and one matched on a spelling that is only sometimes a filler (`is_ambiguous` — "like",
"you know"). `worker._is_pre_accepted` is the single owner of that rule; the columns exist so the
review UI can show *which* rows were held back, and `reasoning` stays the detector's own words.

### Technology Stack
- **Backend**: FastAPI (Python 3.10+), SQLAlchemy (SQLite), `faster-whisper` (transcription),
  FFmpeg (editing), OpenAI or Anthropic (analysis, selected by `CLEANCUT_MODEL`).
- **Frontend**: Next.js 16 (TypeScript, App Router), Tailwind CSS v4, `wavesurfer.js`.

---

## Architecture & Directory Structure

```text
.
├── backend/                    # FastAPI application
│   ├── app/
│   │   ├── analysis/           # transcriber.py, prompt_analyzer.py, analyze.py (CLI)
│   │   │   └── presets/        # Rule preset markdown rulebooks
│   │   ├── eval/               # spec.py, scoring.py, run.py (accuracy against the demo labels)
│   │   ├── routes/             # jobs, violations, audio, admin
│   │   ├── services/           # worker.py, task_store.py, processor.py, scrubber.py,
│   │   │                       # media_editor.py, exports.py, levels.py, retention.py,
│   │   │                       # transcripts.py
│   │   ├── models.py           # SQLAlchemy models (Job, Violation, Task)
│   │   ├── database.py         # SQLite setup + additive migrations
│   │   ├── auth.py             # ADMIN_TOKEN gate for the destructive admin routes
│   │   ├── network.py          # CLEANCUT_HOST: loopback-by-default binding
│   │   └── main.py             # Entry point & CORS
│   ├── tests/                  # pytest suite
│   ├── uploads/                # Uploaded media
│   └── exports/                # Edited output
├── frontend/                   # Next.js application
│   ├── src/app/                # Upload, job review, admin pages
│   ├── src/components/         # Waveform, ViolationList, ViolationCard
│   └── src/lib/api.ts          # Typed API client
├── docs/                       # Architecture, spec, roadmap
└── tests/                      # Media fixtures (synthetic only)
```

---

## Building and Running

### Prerequisites
- Python 3.10+, Node.js 20.9+, FFmpeg (`brew install ffmpeg`)
- A `.env` at the **repo root** holding the key for the configured provider (`OPENAI_API_KEY`, or
  `ANTHROPIC_API_KEY` when `CLEANCUT_MODEL` names anthropic). `ADMIN_TOKEN` and `CLEANCUT_HOST`
  live there too; see `.env.example`.

### Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

Both at once: `./start.sh`. Containerized: `docker compose up --build`.

### CLI
```bash
cd backend && source .venv/bin/activate
python -m app.analysis.analyze path/to/audio.mp3 --prompt "flag every income claim"
python -m app.analysis.analyze path/to/audio.mp3 --preset income-claims
```

The CLI is a module, not a script: `analysis/` imports are package-relative, so
`python app/analysis/analyze.py` cannot resolve them.

---

## Development Conventions

### Coding Standards
- **Backend**:
  - Use Pydantic for request/response validation (`schemas.py`).
  - Follow the service-layer pattern (logic in `services/`, routing in `routes/`).
  - Use `faster-whisper` with `int8` quantization for efficient local inference on M-series Macs.
  - Multipart upload fields must be declared as `Form(...)`, never bare defaults — a bare default
    makes FastAPI read them as query params and they silently never arrive.
- **Frontend**:
  - Functional components, Tailwind CSS v4.
  - `wavesurfer.js` regions to visualize suggested-edit intervals.
  - Strictly type all API interactions and component props.
  - Read the API base from `NEXT_PUBLIC_API_URL`; never hardcode a host.

### Workflow
0. **Conversion**: AIFF/AIF is converted to MP3, and video has its audio extracted, via FFmpeg.
1. **Transcription**: `faster-whisper` produces word-level timestamps.
2. **Analysis**: transcripts are chunked (50 segments, 10 overlap) before going to the LLM, either
   with the user's prompt or with a preset rulebook from `analysis/presets/`.
3. **Deduplication**: suggestions are deduplicated *across* chunks only, on normalized text and real
   interval overlap — two distinct findings seconds apart must both survive.
4. **Scrubbing**: silence and filler words are detected deterministically, without the LLM.
5. **Export**: a single FFmpeg `trim`/`atrim` + `concat` filter graph applies mutes then cuts,
   keeping video in sync with its audio.

### Testing
- Backend: `cd backend && pytest`.
- Frontend: `cd frontend && npm test` (vitest + Testing Library in jsdom) and `npx tsc --noEmit`.
- Accuracy: `python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3
  --suite scrub` scores the deterministic detectors against the labelled demo clip for free. This
  is what CI gates on.
- Fixtures in `tests/` must be synthetic. Never commit a real customer recording or transcript.

---

## Safety & Security
- **API Keys**: never commit `.env`. Ensure `.gitignore` covers all secret files.
- **Media Privacy**: files in `uploads/` and `exports/` are sensitive user data. Transcription runs
  locally; only transcript text reaches the LLM provider.
- **Admin Dashboard**: the destructive `/api/admin` routes are gated on an `ADMIN_TOKEN` header and
  **fail closed** — with no token configured they answer 503, not a pass. `GET /api/admin/stats`
  stays open so the dashboard loads on an unconfigured server.
- **Network binding**: every other route is unauthenticated, so the interface *is* the access
  control. `CLEANCUT_HOST` defaults to `127.0.0.1`; treat exposing it as a deployment decision, and
  add real per-owner auth before hosting this for more than one person.
