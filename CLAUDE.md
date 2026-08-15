# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered audio compliance tool for a direct-sales company's marketing guidelines. The system transcribes audio recordings, analyzes them for compliance violations against those guidelines, and flags problematic sections with timestamps for human review.

**Philosophy**: "Copilot, not Autopilot" - The AI flags violations for human review, it does not automatically edit audio. See `proj.md` for full project vision.

## Architecture

The project has three main components:

```
ai-audio-editing/
├── poc/                    # Original CLI-based proof of concept
│   ├── analyze.py          # Main CLI entry point
│   ├── transcriber.py      # Whisper transcription (faster-whisper)
│   ├── compliance.py       # GPT-4o compliance analysis
│   ├── bsm_rules.txt       # compliance rules
│   └── .env                # API keys (not committed)
├── backend/                # FastAPI backend
│   ├── app/
│   │   ├── main.py         # FastAPI entry + CORS
│   │   ├── database.py     # SQLite setup
│   │   ├── models.py       # SQLAlchemy: Job, Violation
│   │   ├── schemas.py      # Pydantic request/response
│   │   ├── routes/
│   │   │   ├── jobs.py     # Upload, status, list
│   │   │   ├── violations.py # List, update status
│   │   │   ├── audio.py    # Stream, waveform, export
│   │   │   └── admin.py    # Reset, storage, stats
│   │   └── services/
│   │       ├── processor.py    # Wraps POC transcriber + compliance
│   │       └── audio_editor.py # pydub cut/mute operations
│   ├── uploads/            # Uploaded audio files
│   ├── exports/            # Edited audio output
│   └── requirements.txt
├── frontend/               # Next.js 14 frontend
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx           # Upload page
│   │   │   ├── admin/page.tsx     # Admin dashboard
│   │   │   └── jobs/[id]/page.tsx # Review interface
│   │   ├── components/
│   │   │   ├── Waveform.tsx       # wavesurfer + markers
│   │   │   ├── ViolationList.tsx  # Sidebar list
│   │   │   └── ViolationCard.tsx  # Detail + actions
│   │   └── lib/
│   │       └── api.ts             # API client
│   └── package.json
└── tests/                  # Test data and transcripts
```

**Data Flow:**
1. Upload audio via frontend → FastAPI saves to `uploads/`
2. Backend calls POC transcriber (faster-whisper) → transcript with timestamps
3. Backend calls POC compliance analyzer (GPT-4o) → violations with timestamps
4. Violations stored in SQLite, returned to frontend
5. User reviews violations on waveform, accepts/rejects each
6. Export generates edited audio with accepted violations cut/muted

## Commands

```bash
# Backend setup
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start backend (port 8000)
uvicorn app.main:app --reload

# Backend tests (from backend/)
pip install -r requirements-dev.txt
pytest

# Frontend setup
cd frontend
npm install

# Start frontend (port 3000)
npm run dev
```

**Full app**: Run both backend and frontend, then open http://localhost:3000

**POC CLI** (still available):
```bash
# Setup (from project root)
source .venv/bin/activate
pip install -r poc/requirements.txt

# Full analysis
python poc/analyze.py audio.mp3

# Skip transcription - use existing transcript
python poc/analyze.py --transcript tests/transcripts/large-v3/client_seminar_transcript.txt
```

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/jobs` | Upload audio, start processing |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/jobs/{id}` | Job details + violation count |
| GET | `/api/jobs/{id}/violations` | List violations for job |
| PATCH | `/api/jobs/{id}/violations/{vid}` | Update: accepted/rejected |
| GET | `/api/jobs/{id}/audio` | Stream original audio |
| GET | `/api/jobs/{id}/audio/waveform` | Waveform peaks JSON |
| POST | `/api/jobs/{id}/export` | Generate edited audio |
| GET | `/api/jobs/{id}/export/download` | Download edited file |
| GET | `/api/admin/stats` | System-wide statistics |
| POST | `/api/admin/reset-database` | Wipe all database records |
| POST | `/api/admin/clear-storage` | Delete all audio files |
| POST | `/api/admin/reset-all` | Wipe database + storage |

## Database Schema (SQLite)

```sql
-- jobs table
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending, processing, completed, failed
    duration_seconds REAL,
    language TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_message TEXT,
    waveform_data TEXT  -- JSON cached peaks
);

-- violations table
CREATE TABLE violations (
    id TEXT PRIMARY KEY,
    job_id TEXT REFERENCES jobs(id),
    text TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    rule_violated TEXT,
    severity TEXT,  -- high, medium, low
    reasoning TEXT,
    status TEXT DEFAULT 'pending',  -- pending, accepted, rejected
    edit_action TEXT DEFAULT 'cut'  -- cut, mute
);
```

## Environment

Requires `.env` file in `poc/` directory:
```
OPENAI_API_KEY=your_key_here
```

System dependency: `brew install ffmpeg`

## Test Data

```
tests/
├── transcripts/
│   ├── large-v3/    # Transcripts from Whisper large-v3 model
│   │   └── client_seminar_transcript.txt
│   └── medium/      # Transcripts from Whisper medium model
│       └── client_seminar_transcript.txt
└── scripts/
```

## Key Implementation Details

- **Transcriber**: faster-whisper with int8 quantization for M4 Mac performance
- **ComplianceAnalyzer**: Chunked analysis with sliding window for long transcripts (>100 segments)
  - Default: 50 segments per chunk, 10 segment overlap
  - Violations deduplicated by rule + timestamp proximity
- **AudioEditor**: pydub for cut/mute operations with crossfade
- **Waveform**: wavesurfer.js with regions plugin for violation markers
- **Processing**: Synchronous for MVP (single-user local use)

## Common Issues

**"Unexpected response format" from GPT-4o**: Check the raw response - the compliance analyzer handles various JSON formats but may encounter unexpected output.

**Slow transcription**: Use `--model medium` or `--model small` for faster (less accurate) transcription.

**CORS errors**: Ensure backend is running on port 8000 and frontend on port 3000.

**Database issues**: Use the **Admin Dashboard** (/admin) to reset the database or storage. Alternatively, delete `backend/audio_compliance.db` manually.
