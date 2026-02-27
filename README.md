# AI Audio Editing & Compliance Review

An AI-powered audio compliance tool designed for a direct-sales company's marketing guidelines. The system transcribes audio recordings, analyzes them for compliance violations against specific guidelines (GPT-4o), and flags problematic sections with timestamps for human review and surgical editing.

## 🚀 Key Features

- **Automated Transcription**: Powered by `faster-whisper` for high-accuracy, word-level timestamps.
- **Smart Compliance Analysis**: Uses LLMs (GPT-4o) to detect complex violations like income claims, lifestyle representations, and prohibited mentions.
- **Interactive Review Dashboard**: Visual waveform interface with markers for each violation.
- **Surgical Editing**: Options to "Cut" or "Mute" flagged segments with automated crossfades.
- **Multi-language Support**: Handles English, Spanish, and code-switching naturally.
- **AIFF Support**: Automatic conversion of AIFF files to MP3 before processing.
- **POC CLI**: Standalone command-line tools for rapid testing of the analysis pipeline.

## 🛠 Architecture

- **Backend**: FastAPI, SQLAlchemy (SQLite), Pydub (Audio), OpenAI API.
- **Frontend**: Next.js 15, Tailwind CSS v4, Wavesurfer.js.
- **POC**: Modular Python scripts for transcription and compliance logic.

---

## 📋 Prerequisites

- **Python 3.10+**
- **Node.js 18+**
- **FFmpeg**: Required for audio processing.
  ```bash
  brew install ffmpeg
  ```
- **OpenAI API Key**: Required for compliance analysis.

---

## ⚙️ Installation & Setup

### 1. Backend Setup
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Frontend Setup
```bash
cd frontend
npm install
```

### 3. Environment Configuration
Create a `.env` file in the `poc/` directory (used by both the backend and POC scripts):
```env
OPENAI_API_KEY=your_openai_api_key_here
```

---

## 🏃 Running the Application

### Start the Backend (Port 8000)
```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

### Start the Frontend (Port 3000)
```bash
cd frontend
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 🖥 POC CLI Usage

For testing the transcription and analysis pipeline independently:

```bash
# Ensure venv is active and requirements are installed
python poc/analyze.py path/to/your/audio.mp3

# Skip transcription (use existing transcript)
python poc/analyze.py --transcript tests/transcripts/medium/client_seminar_transcript.txt
```

---

## 🔗 API Documentation

The backend runs on `http://localhost:8000`. You can view the interactive Swagger docs at `http://localhost:8000/docs`.

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| **POST** | `/api/jobs` | Upload audio and start processing. |
| **GET** | `/api/jobs` | List all compliance review jobs. |
| **GET** | `/api/jobs/{id}` | Get status and metadata for a specific job. |
| **GET** | `/api/jobs/{id}/violations` | List all flagged violations for a job. |
| **PATCH** | `/api/jobs/{id}/violations/{vid}` | Update violation status (accepted/rejected). |
| **GET** | `/api/jobs/{id}/audio` | Stream the original audio file. |
| **POST** | `/api/jobs/{id}/export` | Generate edited audio based on accepted violations. |
| **GET** | `/api/jobs/{id}/export/download` | Download the finalized audio file. |

---

## 📖 Development Guide

### Workflow Details
1. **Transcription**: Split audio into segments using `faster-whisper`.
2. **Analysis**: Transcripts are processed in chunks (50 segments) to ensure high-fidelity analysis by the LLM.
3. **Review**: The frontend allows users to toggle "Cut" or "Mute" for each violation before exporting.
4. **Export**: The backend uses `pydub` to surgically edit the file, applying 50ms crossfades between segments to ensure natural audio flow.

### Testing Data
- Sample transcripts are available in `tests/transcripts/`.
- Mock violations can be triggered via the POC scripts for UI development.

---

## 🛡 Security & Privacy
- **Local Processing**: Audio transcription is performed locally (or via configured API).
- **Data Retention**: The system uses a local SQLite database (`backend/audio_compliance.db`) and local storage for uploads/exports.
- **API Security**: OpenAI API calls are made with `data_retention: false` where available to ensure compliance with privacy requirements.
