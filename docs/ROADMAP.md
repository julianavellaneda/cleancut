# Roadmap: AI Media Editor Revamp

This document outlines the phased transition from a specialized "Compliance Review" tool to a generalized, prompt-based AI Audio/Video Editor.

## Phase 1: Dynamic Prompting (The "Prompt-Based" Engine)
**Goal:** Replace the static compliance rules with a user-defined natural language prompt.

- [ ] **Database & API:** Update `Job` model and `POST /api/jobs` schema to include a `prompt` field.
- [ ] **Frontend:** Add a dynamic prompt input field to the upload screen.
- [ ] **LLM Integration:** Refactor `ComplianceAnalyzer` to `PromptAnalyzer`. 
    - Inject user prompt into the system instructions.
    - Update output schema to be more generic (e.g., "Label", "Action", "Reason", "Start", "End").
- [ ] **UI/UX:** Rename "Violations" to "Suggested Edits" or "Markers" throughout the application.

## Phase 2: Video Infrastructure & Extraction
**Goal:** Support `.mp4` and `.mov` uploads by extracting audio for analysis.

- [ ] **File Handling:** Update backend validators to accept common video formats.
- [ ] **Audio Extraction:** Implement a utility using `FFmpeg` to extract audio tracks from uploaded videos.
- [ ] **Frontend Player:** Integrate an HTML5 `<video>` player into the job review dashboard.
- [ ] **Syncing:** Synchronize `wavesurfer.js` waveform seeking with the video player's current time.

## Phase 3: The Unified Media Editor (FFmpeg Migration)
**Goal:** Replace `pydub` (audio-only) with `FFmpeg` to enable editing of both audio and video containers.

- [ ] **Service Refactor:** Rewrite `audio_editor.py` as `media_editor.py`.
- [ ] **Mute Logic:** Implement FFmpeg `volume=0` filters for specific intervals.
- [ ] **Cut Logic:** Implement FFmpeg `trim`/`concat` filter chains to physically remove segments while maintaining A/V sync.
- [ ] **Export:** Ensure final exports maintain original video quality and resolution.

## Phase 4: Automated "Scrubber" Features
**Goal:** Add deterministic tools for common cleaning tasks.

- [ ] **Silence Removal:** Integrate Voice Activity Detection (VAD) to auto-flag "Dead Air".
- [ ] **Filler Word Detection:** Scan Whisper's word-level timestamps for "um", "ah", "like", etc.
- [ ] **One-Click Cleanup:** Add a "Clean All" button to the UI that applies all suggested "Scrubber" edits at once.
