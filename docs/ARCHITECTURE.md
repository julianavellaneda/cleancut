# Architecture: CleanCut

This document describes the evolved architecture supporting dynamic AI prompts and video processing.

## System Overview

The system follows a decoupled architecture where the **Frontend** (Next.js) handles visualization, the **API** (FastAPI) manages state and jobs, and a **Background Worker** (Python/Celery-style) handles heavy media processing.

### Data Flow (Future State)

1.  **Ingestion:** User uploads a Media File (Audio/Video) + a Prompt (e.g., "Remove stutters").
2.  **Pre-processing:** 
    - If Video: Extract Audio Track via FFmpeg.
    - If Audio: Normalize/Convert to MP3.
3.  **Transcription:** `faster-whisper` generates a word-level timestamped transcript.
4.  **Semantic Analysis:** 
    - The Prompt + Transcript are sent to GPT-4o.
    - GPT-4o identifies segments matching the prompt and returns a JSON list of timestamps.
5.  **Deterministic Analysis (Optional):**
    - VAD (Voice Activity Detection) flags silences.
    - Regex/Pattern matching flags filler words.
6.  **Review:** User reviews suggested edits on a synchronized Waveform + Video Player.
7.  **Final Edit (Export):**
    - The backend constructs a complex FFmpeg filter graph.
    - Video and Audio are cut/muted in a single pass to ensure sync.
    - The resulting file is served for download.

## Key Components

### 1. `PromptAnalyzer` (formerly ComplianceAnalyzer)
- **Role:** Bridges the user's intent with the transcript.
- **Input:** `Transcript`, `User Prompt`.
- **Output:** `JSON[{start, end, label, action, confidence}]`.

### 2. `MediaProcessor`
- **Role:** Orchestrates the heavy lifting.
- **Tech:** `FFmpeg` for extraction and format conversion. `Whisper` for STT.

### 3. `MediaEditor` (formerly AudioEditor)
- **Role:** The "Surgical" unit.
- **Tech:** `ffmpeg-python`. It must handle frame-accurate cuts for video to prevent stuttering.

### 4. Frontend Dashboard
- **Role:** Interactive review.
- **Tech:** `wavesurfer.js` for audio visualization, React `<video>` for playback, and `Zustand/Context` for state management of markers.
