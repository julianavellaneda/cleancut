# Project Progress: AI Media Editor Revamp

## Phase 1: Dynamic Prompting (The "Prompt-Based" Engine)
- [x] **Database & API:** Update `Job` model and `POST /api/jobs` schema to include a `prompt` field.
- [x] **Frontend:** Add a dynamic prompt input field to the upload screen.
- [x] **LLM Integration:** Refactor `ComplianceAnalyzer` to `PromptAnalyzer`.
    - [x] Inject user prompt into the system instructions.
    - [x] Update output schema to be more generic.
- [x] **UI/UX:** Rename "Violations" to "Suggested Edits" or "Markers" throughout the application.

## Phase 2: Video Infrastructure & Extraction
- [x] **File Handling:** Update backend validators to accept common video formats.
- [x] **Audio Extraction:** Implement a utility using `FFmpeg` to extract audio tracks from uploaded videos (handled by Whisper/FFmpeg-python).
- [x] **Frontend Player:** Integrate an HTML5 `<video>` player into the job review dashboard.
- [x] **Syncing:** Synchronize `wavesurfer.js` waveform seeking with the video player's current time.

## Phase 3: The Unified Media Editor (FFmpeg Migration)
- [x] **Service Refactor:** Rewrite `audio_editor.py` as `media_editor.py` using `ffmpeg-python`.
- [x] **Mute Logic:** Implement FFmpeg `volume=0` filters for specific intervals.
- [x] **Cut Logic:** Implement FFmpeg `trim`/`concat` filter chains to physically remove segments while maintaining A/V sync.
- [x] **Export:** Ensure final exports maintain original video quality and resolution.

## Phase 4: Automated "Scrubber" Features
- [x] **Silence Removal:** Integrate Voice Activity Detection (VAD) to auto-flag "Dead Air".
- [x] **Filler Word Detection:** Scan Whisper's word-level timestamps for "um", "ah", "like", etc.
- [x] **One-Click Cleanup:** Add a "Clean All" button to the UI that applies all suggested "Scrubber" edits at once.
