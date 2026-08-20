# CleanCut demo — capture & assets plan

Supersedes the "Remaining work" list in `demo-state.md`. `demo-blockers-handoff.md` is dead.

## Context

The blockers are cleared (ProcessingView, the LLM output-contract fix, `_prompt_default_action`,
cosmetic removals; 250 tests passing) but none of it is committed, and no demo asset exists yet:
there is no `tests/fixtures/`, no `scripts/`, no `docs/demo/`, no `docs/assets/`.

What blocks the Remotion workspace is five `.mp4` captures of the real app (scenes 4–8) and
`docs/demo/narration.md`. Everything below exists to produce those, plus the stills and slide copy
that backfill after.

Decisions locked this session:

| Decision | Choice |
|---|---|
| Fixture length | 70–90 s, captured real-time, **no speed manipulation on my end** |
| Demo mode | **Prompt mode** — typed plain-English instruction; preset shown as a beat, not selected |
| Capture method | `page.screencast` via `playwright-cli run-code`, **not** a Playwright test spec |
| Cursor | Highlight ring overlay, no fake cursor |
| Capture density | Native 1440×900, 1:1 |
| Scene 8 ending | **Build a real post-export player** so the result plays in-app |
| Chapters / action callouts | Off. Remotion owns every title and transition. |

---

## Findings that change the choreography

Three things surfaced during exploration that the earlier plans assumed wrong.

1. **The upload screen has no submit button.** `POST /api/jobs` fires the instant a file lands on
   `#file-input`. So scene 4's beat order is: type instruction → preset beat → drop file → it goes.

2. **A native `<select>` dropdown is OS-rendered and does not appear in a CDP screencast.**
   "Open the preset dropdown" is not capturable. The in-page equivalent, which is better anyway:
   ring the `Rule preset` control, `selectOption('income-claims')` so the viewer sees the
   `Instructions` label become `(disabled — Income & Lifestyle Claims preset active)` and the
   textarea grey out, dwell, then `selectOption('')` to restore prompt mode and re-type. That shows
   the preset system *and* its effect, on-page, and still submits in prompt mode as decided.

3. **`Download Master` calls `window.open()`.** A popup backgrounds the recorded tab and CDP stops
   producing frames mid-scene. Every capture script installs `context.on('page', p => p.close())`
   before the click. This is required regardless of the post-export player.

Two `.gitignore` landmines that would silently drop the fixture:

- `*.mp3` is globally ignored → `demo_seminar.mp3` will not commit.
- `*_violations.json` is ignored → `expected_violations.json` will not commit.

---

## Order of work

### 0. Commit the tree — first, before anything else

Ten dirty files including the whole output-contract fix. One commit covering: the LLM
output-contract fix + `test_output_contract.py`, `ProcessingView`, `_prompt_default_action`, and the
cosmetic removals (sparkle, "Initializing Terminal…", empty-state copy).

### 1. `.gitignore` negations

Append, so the fixture is committable:

```
!tests/fixtures/demo/*.mp3
!tests/fixtures/demo/expected_violations.json
docs/demo/captures/raw/
tests/fixtures/demo/.cache/
```

`raw/` WebM originals stay local — they are re-encodable from nothing and would bloat the repo.
I keep them on disk and tell you where.

### 2. `tests/fixtures/demo/seminar_script.md` — **Sonnet subagent**

70–90 s of a synthetic two-speaker "business opportunity seminar". Format is
`SPEAKER | voice-instruction | text` with explicit `[PAUSE n.n]` lines, so generation is mechanical.

Budget: ~170–200 spoken words at 150 wpm, plus ~8 s of planted silence.

Planted items, from `phase-3-portfolio-plan.md` Step 1a, with the constraints the detectors actually
impose:

| Planted item | Constraint that matters |
|---|---|
| A specific dollar figure | Income Claims — the flagship hit |
| "quit your job by Christmas" | Income claim, high severity |
| A luxury-car mention | Lifestyle claim |
| "cleared up my mother's migraines" | Medical/Health claim |
| A fake phone number + email read aloud | PII — planted for the eval fixture, not flagged by `income-claims` |
| ~10–12 filler words | **Must be from `Scrubber.FILLER_WORDS`**: um, uh, ah, er, hm, like, you know — standing alone as words |
| 3 dead-air gaps | **`[PAUSE 2.5]`–`[PAUSE 3.0]`.** `detect_silence` needs ≥ 2.0 s; 1.5 s from the old plan would not fire, and 2.0 s exactly is too close to Whisper's boundary rounding |
| One Spanish sentence mid-paragraph | Code-switching |
| Near-miss control: "some people earn nothing at all" | Must **not** be flagged — proves it isn't keyword matching |

No real name, company, product, phone number, or email. Nothing that identifies a market.

### 3. `scripts/generate_demo_audio.py` — **Sonnet subagent**, gated on your cost approval

- `gpt-4o-mini-tts`, one call per line, distinct voice per speaker, per-line `instructions=` for tone
  (this is what makes the fillers land as speech rather than as read words).
- Reads `OPENAI_API_KEY` through `app.config.root_env_path()` — same root `.env` the backend uses.
- Caches each rendered line under `tests/fixtures/demo/.cache/` keyed by
  `sha256(voice + instructions + text)`, so re-runs and tweaks cost nothing for unchanged lines.
- `[PAUSE n]` → exactly `n` seconds of `anullsrc`.
- Concats to `demo_seminar.mp3` (mono, 64 kbps).
- Renders `demo_seminar.mp4` — static card + `showwaves` — so the video path, the HTML5 player, and
  A/V-sync-preserving cuts are all genuinely exercised.
- Emits `expected_violations.json`: true start/end for every planted item, accumulated from
  `ffprobe`'d per-line durations.
- **`--dry-run` makes zero API calls** and prints per-line character counts plus a total cost
  estimate against OpenAI's published `gpt-4o-mini-tts` rate.

**I run `--dry-run` and report the number to you before spending anything.** Expect cents, not
dollars, but you asked and it's the right gate.

### 4. Fixture outputs + README

`demo_seminar.mp3`, `demo_seminar.mp4`, `expected_violations.json`, and
`tests/fixtures/demo/README.md` stating plainly that the clip is synthetic and TTS-generated and
depicts no real person or company.

Then one real end-to-end pipeline run in **prompt mode** against the fixture to confirm the marker
set is good on camera. `demo-state.md`'s verified 12-marker run was preset mode, so prompt mode needs
its own look — this is the one re-verification the mode decision costs.

### 5. Post-export player — new, small, and it unblocks scene 8

The app currently ends at a download. Nothing plays the result.

- **Backend** — `GET /api/jobs/{job_id}/export/stream` in `backend/app/routes/audio.py`, mirroring
  `download_export` but serving inline (no `Content-Disposition: attachment`). 404 when no export
  exists. `FileResponse` already handles Range.
- **Frontend** — on `exportReady`, alongside `Download Master`, render an `<audio controls>` (or
  `<video controls>` for video jobs) pointed at the new endpoint, under a small `Result` label.
- **`lib/api.ts`** — `getExportStreamUrl(jobId)`.
- **Test** — `backend/tests/test_export_stream.py`: 404 before export; after export, 200, correct
  `media_type`, and no attachment header.

Files: `backend/app/routes/audio.py`, `frontend/src/app/jobs/[id]/page.tsx`,
`frontend/src/lib/api.ts`.

`media_editor.py`, `scrubber.py`, and the export filter graph are not touched.

### 6. `scripts/seed_demo_job.py`

Whisper costs ~32 s per take on a 70–90 s clip. Scenes 6–8 don't need it.

- `--capture-from <job_id>` snapshots a **real** completed job — Job fields, every Violation row, and
  the cached 800-float `waveform_data` — into `tests/fixtures/demo/seed_job.json`. The seeded state
  is therefore genuinely what the app produced, not hand-authored.
- Default mode reads that JSON back: deterministic job id, delete-then-insert so re-seeding is
  idempotent, copies `demo_seminar.mp3` → `backend/uploads/{job_id}.mp3`, and writes
  `waveform_data` directly so the waveform renders without an ffmpeg pass.
- `--state fresh|cleaned` — `cleaned` pre-accepts the scrub labels and one LLM edit, because
  **`Export Edited` is disabled until at least one violation is `accepted`**. Scene 8 needs
  `cleaned`; scenes 6 and 7 need `fresh`.

Cribs the row construction from `backend/tests/test_export_partition.py:52`, which is the closest
existing analogue. Field lists come from `backend/app/models.py`; scrubber-origin labels are
`"Filler Word"` and `"Dead Air"`.

### 7. The five captures → `docs/demo/captures/`

Prerequisites, every take:

```bash
# backend on 8000, production frontend on 3000 — never `next dev`, the overlay badge is in frame
cd frontend && npm run build && npm run start
playwright-cli open --browser=chromium        # chrome fails on this machine
playwright-cli resize 1440 900
```

Each scene is a standalone `scripts/capture/scene-NN-*.js` run as
`playwright-cli run-code --filename=scripts/capture/scene-06-review.js`. Each file self-contains a
~15-line `ring(page, locator, ms)` helper that reads `boundingBox()` and draws a soft highlight ring
via `page.screencast.showOverlay(...)` — `pointer-events: none`, so it never blocks the click it is
pointing at. No fake cursor.

Common shape:

```js
async page => {
  page.context().on('page', p => p.close());          // kill the download popup
  await page.screencast.start({
    path: 'docs/demo/captures/raw/scene-06-review.webm',
    size: { width: 1440, height: 900 },
  });
  // ... beats, ~1s dwell after each ...
  await page.screencast.stop();
}
```

**Not used:** `showChapter()` (blurs the page, bakes a title card that will collide with your slide
layer), `video-show-actions`, `page.pause()`, tracing.

| Scene | Source | Beats |
|---|---|---|
| `scene-04-upload` | live | `pressSequentially(instruction, {delay: 60})` → ring the preset control → select `income-claims`, dwell on the greyed textarea → restore `None`, re-type → `setInputFiles('#file-input')` → `Processing Upload...` |
| `scene-05-pipeline` | live, same session | Stages stepping: `Converting → Transcribing → Analyzing → Ready to review`, real time, ~32 s. You ramp this in Remotion; I hand you the raw file. |
| `scene-06-review` | seeded `fresh` | **The money shot.** Wait for `Play` to enable, play ~6 s so the playhead crosses the waveform, pause, click a marker in the sidebar, dwell on the quoted text landing on the exact words, `▶ Play Clip`. Most takes. |
| `scene-07-cut-mute-cleanall` | seeded `fresh` | `Accept` an edit → flip the `On export` control cut→mute → `Clean All (N)` → it vanishes as the count hits zero |
| `scene-08-export` | seeded `cleaned` | `Export Edited` → `Exporting...` → `Download Master` → click (popup suppressed) → the new inline player, pressed play, result audibly and visibly shorter |

Over-shoot every duration. Dwell ~1 s after each action.

**I shoot scene 6 first and ping you with it before shooting the other four**, so you can check
framing against the Remotion comp.

Selectors are all role/text/`#id` — there are zero `data-testid` attributes in the frontend. Watch
the typographic characters in real strings: `—` in the Instructions label, `…` in `Loading…`,
`“ ”` around quoted text, `←` and `▶` in buttons.

### 8. Transcode

WebM originals stay in `captures/raw/`; H.264 goes to `docs/demo/captures/`:

```bash
ffmpeg -i docs/demo/captures/raw/scene-06-review.webm \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
  -r 30 -movflags +faststart \
  docs/demo/captures/scene-06-review.mp4
```

### 9. Stills → `docs/assets/`

3–4 PNGs via `playwright-cli screenshot --hires` against the seeded job: upload screen, review UI
mid-playback, an expanded marker card, the export-complete state.

### 10. `docs/demo/narration.md` — **Sonnet subagent**, then the `plain-english` skill

All ten scenes, per-scene word counts at 150 wpm. Slides 70–90% density, demo scenes **30–50%** —
the picture carries those. Written to be read aloud: short sentences, no clause stacking.

### 11. `docs/demo/slide-copy.md` — **Sonnet subagent**

Problem statements + the naive-cut snippet; architecture one-liner + repo URL.

---

## Standing constraints

- **No fabricated metrics.** A number goes on screen only if it is derivable from
  `expected_violations.json` or measured on this machine.
- Synthetic fixtures only. No real recording, name, or client content.
- Writing → Sonnet subagent. Engineering → me.
- `.env` is at the repo root.
- `media_editor.py`, `scrubber.py`, the export filter graph: **do not touch.**

---

## Verification

1. `cd backend && pytest` — 250 passing before step 5, plus the new `test_export_stream.py` after.
2. `cd frontend && npx tsc --noEmit` — clean, after the post-export player lands.
3. `python scripts/generate_demo_audio.py --dry-run` — zero API calls, prints the cost. **Stop here
   for your approval.**
4. After generation: `ffprobe tests/fixtures/demo/demo_seminar.mp3` — duration in 70–90 s.
5. One real prompt-mode run end to end: upload → markers across every detector category →
   accept → toggle one to mute → Clean All → export → `ffprobe` the output and confirm the duration
   drop matches the accepted cut total to the millisecond, as `demo-state.md` already established for
   preset mode.
6. `python scripts/seed_demo_job.py --state fresh` then reload `/jobs/<id>` — waveform renders with
   no ffmpeg pass, marker count matches the captured job.
7. Each capture: play the `.mp4` and confirm no dev overlay, no browser chrome artifact, no real
   filename, no chapter card.

## What you get, and when

Blocking you: five `.mp4`s + `docs/demo/narration.md`. Stills and slide copy backfill after.
Plus the exported `.mp3`/`.mp4` result as loose assets, in case you want the before/after in the edit
rather than only inside scene 8.

Two gates where I stop and wait: the TTS cost number at step 3, and scene 6's framing at step 7.
