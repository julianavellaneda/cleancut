# GEMINI.md

This file provides foundational mandates and contextual guidance for Gemini CLI when working in this repository.

## Project Overview

**AI Audio Editing & Compliance Review** is an AI-powered tool designed for compliance with a direct-sales company's marketing guidelines. It transcribes audio recordings, analyzes them against specific marketing guidelines using LLMs (GPT-4o), and provides a dashboard for human review and surgical audio editing (cut/mute).

### Core Philosophy: "Copilot, not Autopilot"
The system is designed to assist human reviewers, not replace them. The AI flags potential violations with reasoning and timestamps, allowing the user to make the final decision on whether to cut or mute the segment.

### Technology Stack
- **Backend**: FastAPI (Python 3.10+), SQLAlchemy (SQLite), `faster-whisper` (Transcription), `pydub` (Audio Processing), OpenAI API (Analysis).
- **Frontend**: Next.js 14/15 (TypeScript, App Router), Tailwind CSS v4, `wavesurfer.js` (Waveform visualization).
- **POC**: Modular Python CLI scripts for independent verification of the transcription and analysis pipeline.

---

## Architecture & Directory Structure

```text
.
├── backend/                # FastAPI application
│   ├── app/                # Main application logic
│   │   ├── routes/         # API endpoints (jobs, violations, audio, admin)
│   │   ├── services/       # Core logic (processor.py, audio_editor.py)
│   │   ├── models.py       # SQLAlchemy database models
│   │   └── main.py         # Entry point & CORS configuration
│   ├── uploads/            # Temporary storage for uploaded audio
│   ├── exports/            # Storage for processed/edited audio
│   └── requirements.txt    # Python dependencies
├── frontend/               # Next.js React application
│   ├── src/app/            # App router pages (Upload, Job Review, Admin)
│   ├── src/components/     # UI components (Waveform, ViolationList)
│   └── package.json        # Node.js dependencies & scripts
├── poc/                    # Proof of Concept CLI tools
│   ├── analyze.py          # Main CLI entry point
│   ├── transcriber.py      # Whisper-based transcription service
│   ├── compliance.py       # LLM-based compliance analysis
│   └── bsm_rules.txt       # Hardcoded compliance guidelines
├── tests/                  # Test datasets and scripts
└── audio/                  # Sample audio files for testing
```

---

## Building and Running

### Prerequisites
- Python 3.10+
- Node.js 18+
- FFmpeg (`brew install ffmpeg`)
- OpenAI API Key (configured in `poc/.env`)

### Backend Setup
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload # Runs on http://localhost:8000
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev # Runs on http://localhost:3000
```

### POC CLI Usage
```bash
# From root with active venv
python poc/analyze.py path/to/audio.mp3
```

---

## Development Conventions

### Coding Standards
- **Backend**: 
  - Use Pydantic for request/response validation (`schemas.py`).
  - Follow the service-layer pattern (logic in `services/`, routing in `routes/`).
  - Use `faster-whisper` with `int8` quantization for efficient local inference on Mac (M-series).
- **Frontend**: 
  - Use Functional Components and Tailwind CSS v4 for styling.
  - Use `wavesurfer.js` regions for visualizing violation intervals.
  - Strictly type all API interactions and component props.

### Workflow
0.  **Conversion**: AIFF/AIF files are automatically converted to MP3 using `pydub` before processing.
1.  **Transcription**: Handled by `faster-whisper` to get word-level timestamps.
2.  **Analysis**: Transcripts are chunked (50 segments with 10 overlap) before being sent to GPT-4o to stay within context limits and ensure detail.
3.  **Deduplication**: Violations are deduplicated based on rule similarity and timestamp proximity.
4.  **Editing**: Audio editing is done via `pydub`, applying crossfades to avoid audible clicks in the final export.

### Testing
- Sample transcripts are located in `tests/transcripts/`.
- Use `poc/analyze.py --transcript <file>` to test compliance analysis without re-running transcription.

---

## Safety & Security
- **API Keys**: Never commit `poc/.env`. Ensure `.gitignore` protects all secret files.
- **Audio Privacy**: Audio files in `uploads/` and `exports/` should be handled as sensitive user data.
- **Admin Dashboard**: The `/admin` route and `/api/admin` endpoints are currently **unauthenticated**. Access should be restricted to authorized personnel. Implementing a proper Auth provider (e.g., Clerk, NextAuth) is a priority for production.
