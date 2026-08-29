# Roadmap: CleanCut Revamp

**Status: Phases 1–4 are shipped.** Kept as the record of how the product got here. The decisions
behind the current shape live in `DESIGN_NOTES.md`; the factual inventory is in
`notes/REDESIGN_CONTEXT.md`.

This document outlines the phased transition from a specialized "Compliance Review" tool to a generalized, prompt-based AI Audio/Video Editor.

## Phase 1: Dynamic Prompting (The "Prompt-Based" Engine)
**Goal:** Replace the static, hardcoded rulebook with a user-defined natural language prompt.

- [x] **Database & API:** Update `Job` model and `POST /api/jobs` schema to include a `prompt` field.
- [x] **Frontend:** Add a dynamic prompt input field to the upload screen.
- [x] **LLM Integration:** Refactor `ComplianceAnalyzer` to `PromptAnalyzer`. 
    - Inject user prompt into the system instructions.
    - Update output schema to be more generic (e.g., "Label", "Action", "Reason", "Start", "End").
- [x] **UI/UX:** Rename "Violations" to "Suggested Edits" or "Markers" throughout the application.

## Phase 2: Video Infrastructure & Extraction
**Goal:** Support `.mp4` and `.mov` uploads by extracting audio for analysis.

- [x] **File Handling:** Update backend validators to accept common video formats.
- [x] **Audio Extraction:** Implement a utility using `FFmpeg` to extract audio tracks from uploaded videos.
- [x] **Frontend Player:** Integrate an HTML5 `<video>` player into the job review dashboard.
- [x] **Syncing:** Synchronize `wavesurfer.js` waveform seeking with the video player's current time.

## Phase 3: The Unified Media Editor (FFmpeg Migration)
**Goal:** Replace `pydub` (audio-only) with `FFmpeg` to enable editing of both audio and video containers.

- [x] **Service Refactor:** Rewrite `audio_editor.py` as `media_editor.py`.
- [x] **Mute Logic:** Implement FFmpeg `volume=0` filters for specific intervals.
- [x] **Cut Logic:** Implement FFmpeg `trim`/`concat` filter chains to physically remove segments while maintaining A/V sync.
- [x] **Export:** Ensure final exports maintain original video quality and resolution.

## Phase 4: Automated "Scrubber" Features
**Goal:** Add deterministic tools for common cleaning tasks.

- [x] **Silence Removal:** Auto-flag "Dead Air" — a transcript gap *plus* an RMS level pass below
      `DEAD_AIR_FLOOR_DB` must agree. (VAD was specified but rejected: it makes the same mistake as
      gap-detection, flagging room tone, applause and music beds.)
- [x] **Filler Word Detection:** Scan Whisper's word-level timestamps for "um", "ah", "like", etc.
- [x] **One-Click Cleanup:** Add a "Clean All" button to the UI that applies all suggested "Scrubber" edits at once.
