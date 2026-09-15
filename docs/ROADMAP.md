# Roadmap: CleanCut Revamp

**Status: Phases 1–4 are shipped.** Kept as the record of how the product got here. The decisions
behind the current shape live in `DESIGN_NOTES.md`; the current contract is in
`SPECIFICATION.md`.

This document records the phased transition from CleanCut's original incarnation — a specialized
"Compliance Review" tool hardcoded to one rulebook — to the generalized, prompt-based audio/video
editor described in `AGENTS.md`.

## Phase 1: Dynamic Prompting (The "Prompt-Based" Engine)
**Goal:** Replace the static, hardcoded rulebook with a user-defined natural language prompt.

- [x] **Database & API:** Updated `Job` model and `POST /api/jobs` schema to include a `prompt`
      field.
- [x] **Frontend:** Added a dynamic prompt input field to the upload screen.
- [x] **LLM Integration:** Refactored `ComplianceAnalyzer` to `PromptAnalyzer`.
    - Injected the user prompt into the system instructions.
    - Updated the output schema to be more generic (e.g., "Label", "Action", "Reason", "Start",
      "End").
- [x] **UI/UX:** Renamed "Violations" to "Suggested Edits" / "Markers" throughout the application.

## Phase 2: Video Infrastructure & Extraction
**Goal:** Support `.mp4` and `.mov` uploads by extracting audio for analysis.

- [x] **File Handling:** Updated backend validators to accept common video formats.
- [x] **Audio Extraction:** Implemented a utility using FFmpeg to extract audio tracks from
      uploaded videos.
- [x] **Frontend Player:** Integrated an HTML5 `<video>` player into the job review dashboard.
- [x] **Syncing:** Synchronized `wavesurfer.js` waveform seeking with the video player's current
      time.

## Phase 3: The Unified Media Editor (FFmpeg Migration)
**Goal:** Replace `pydub` (audio-only) with FFmpeg to enable editing of both audio and video
containers.

- [x] **Service Refactor:** Rewrote `audio_editor.py` as `media_editor.py`.
- [x] **Mute Logic:** Implemented FFmpeg `volume=0` filters for specific intervals.
- [x] **Cut Logic:** Implemented FFmpeg `trim`/`concat` filter chains to physically remove
      segments while maintaining A/V sync.
- [x] **Export:** Confirmed final exports maintain original video quality and resolution.

## Phase 4: Automated "Scrubber" Features
**Goal:** Add deterministic tools for common cleaning tasks.

- [x] **Silence Removal:** Auto-flags "Dead Air" — a transcript gap plus an RMS level pass below
      `DEAD_AIR_FLOOR_DB` must agree. VAD was specified for this and rejected; see
      [`ARCHITECTURE.md`](ARCHITECTURE.md#dead-air-detection) for why.
- [x] **Filler Word Detection:** Scans Whisper's word-level timestamps for "um", "ah", "like", etc.
- [x] **One-Click Cleanup:** Added a "Clean All" button that applies all suggested "Scrubber"
      edits at once.
