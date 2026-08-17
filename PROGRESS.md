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

---

# Portfolio track (see `DEVELOPMENT_PLAN.md`)

## Phase 0: Make it true
- [x] `prompt` and the other multipart fields arrive as `Form(...)` params
- [x] Per-edit `cut`/`mute` honored on export (mutes applied before cuts)
- [x] "Clean All" wired to `bulkUpdateViolations`
- [x] `API_BASE` reads `NEXT_PUBLIC_API_URL`
- [x] Per-violation cut/mute toggle in `ViolationCard`

## Phase 1: Scrub and rename
- [ ] **Decide the public-repo strategy** — history still contains the client transcripts,
      violation JSONs, rules file, and review screenshot. Blocker for going public.
- [x] Client transcripts and violation JSONs deleted from the working tree
- [x] `Audio Compliance Review.jpeg` deleted (screenshot of a real client job)
- [x] `bsm_rules.txt` rewritten as generic preset rulebooks in `backend/app/analysis/presets/`
- [x] `bsm_mode` boolean renamed to a `preset` string field, with a backfilling migration
- [x] Name picked: **CleanCut**
- [x] Client references purged from `README.md`, `CLAUDE.md`, `GEMINI.md`, `proj.md`, `docs/`, UI copy

## Phase 2: Fresh-clone truth
- [x] `README.md` and `CLAUDE.md` describe the real layout (no `poc/`, root `.env`, module-form CLI)
- [x] Missing `OPENAI_API_KEY` / `ffmpeg` / `ffprobe` fail at startup via `app/preflight.py`,
      listing every unmet requirement at once. `SKIP_PREFLIGHT=1` overrides.
- [x] Unreadable LLM responses raise `AnalysisError` instead of returning `[]`. One bad chunk
      completes the job with a partial-analysis warning; all chunks failing fails the job.
- [x] `worker.py` unbound-`job` masking bug fixed — failures report their real cause
- [x] Failed jobs render their reason in the review UI; partial analyses show a warning banner
- [x] Upload guardrails: `MAX_UPLOAD_MB` (streamed, 413) and `MAX_DURATION_MINUTES` (ffprobe, 413)
- [x] `@app.on_event("startup")` replaced with a lifespan context

Remaining: Phase 3 (synthetic demo clip, demo video, README hero, case study) is content work.
