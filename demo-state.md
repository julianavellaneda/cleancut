# CleanCut demo — current state

Last updated: 2026-08-19. This is the authoritative status of the Phase 3 demo-video work.
`demo-blockers-handoff.md` is superseded (its D2 diagnosis is wrong).

## Context

A portfolio demo video is being produced in a **separate** workspace
(`claude-code-video-toolkit`, Remotion `product-demo` template).
That workspace owns scenes 1, 2, 3, 9, 10 (slides) and the final render.

**This repo produces the raw material**: five Playwright screen captures of the real running app
(scenes 4–8), stills, narration, and slide copy. Nothing here renders video. Do not install
Remotion or the toolkit in this repo.

Scenes 4–8: upload+prompt (18s) · pipeline (12s) · review on waveform (26s, the money shot) ·
cut vs mute + Clean All (18s) · export (18s).

## Status: blockers cleared, capture not started

### Done and verified

| Item | State |
|---|---|
| D1 processing view | `frontend/src/components/ProcessingView.tsx`, wired at `jobs/[id]/page.tsx`. Verified on screen at 1440×900. |
| D3 prompt-mode action default | `_prompt_default_action()` in `prompt_analyzer.py`. Deterministic, tested. |
| D4 "Initializing Terminal…" | Gone. |
| D5 sparkle on Clean All | Gone. |
| Empty-state copy | "No edits suggested for this recording". |
| **LLM recall bug** | **Fixed — see below. This was the big one.** |

Test suite: **250 passing** (was 213). `tsc --noEmit` clean.

### The LLM recall bug (found this session, not in the original defect list)

`_call_llm` pins `response_format={"type": "json_object"}` while both system prompts asked for a
top-level **JSON array**. Incompatible. The model resolved it by returning a **single bare
violation object**, and `_parse_llm_response`'s defensive bare-object branch accepted that as one
suggestion.

Measured: a transcript with six blatant violations across five categories analyzed to **exactly
one**, 3/3 runs, deterministically. Silent data loss — the same class of failure `AnalysisError`
exists to prevent, arriving through the prompt instead of the parser.

Fix: both prompts now specify `{"violations": [...]}`. Same transcript → **5 violations, 3/3
runs**. The near-miss control ("some people earn nothing at all") is still correctly ignored, so
specificity did not regress.

Guarded by `backend/tests/test_output_contract.py` (9 tests), confirmed to **fail** against the
pre-fix prompts.

### D2 — the original diagnosis was wrong

`demo-blockers-handoff.md` claims Whisper splitting a sentence across segments caused
"you could quit your job by Christmas" to be missed. **Disproved**: it is missed 3/3 even when the
sentence is joined into a single segment. The real cause was the output-contract bug above.

The cross-segment alignment code that was written for the wrong diagnosis
(`_find_text_across_segments`) is nonetheless correct and worth keeping — verified to map a
split quote to 22.01–26.07s, which transcribes back word-for-word with no over-cut.

## Verified end-to-end (do not re-run)

70.2s synthetic clip, `income-claims` preset → 12 markers (5 LLM across 4 categories, 7 scrubber).
Accepted all, set one to mute, exported: **70.181s → 50.641s** against 19.540s of accepted cuts.
Exact to the millisecond.

Mute-before-cut ordering confirmed by per-second RMS on the exported audio: silence lands at the
predicted post-cut offset. A/V sync holds on the video path (video 16.640s / audio 16.606s, both
`start_time=0`).

**`media_editor.py`, `scrubber.py`, and the export filter graph are correct. Do not touch them.**

## Pipeline timing (measured on this machine, M-series)

| Source | Transcribing | Analyzing | Total |
|---|---|---|---|
| 19.9s | 9.3s | 2.1s | 11.4s |
| 70.2s | 28.8s | 3.4s | 32.2s |

Fits `transcribe ≈ 1.6 + 0.39 × duration`; analyze ≈ 2–3.5s per chunk.

**Consequence for scene 5:** 12 seconds of live pipeline needs a ~20-second source clip, which is
far too thin to fill the waveform for scene 6. A 3–4 minute fixture would run ~75s of pipeline.
You cannot have both in real time.

**Open decision (waiting on Julian):** recommendation is a **70–90 second fixture** — already
yields 12 markers across every detector category — and a ~2.5× speed ramp on scene 5 in Remotion.
Capture real, ramp in edit. The alternative is a longer fixture with a steeper ramp.

## Capture prerequisites

- Capture against a **production build** (`next build && next start`), not `next dev`. The dev
  overlay puts an "N" badge and a "1 Issue" pill in frame.
  - That issue is a StrictMode double-invoke aborting wavesurfer's fetch on remount. Dev-only,
    not a real bug.
- Viewport **1440×900**, `deviceScaleFactor: 2`.
- `playwright-cli open --browser=chromium`. `--browser=chrome` fails on this machine — see the
  `playwright-cli-chromium-shim` memory note.
- Deliberate dwell time (~1s after each click); visible, eased mouse cursor (inject an overlay —
  Playwright hides the cursor).
- No real filenames or names on screen. Synthetic fixture only.
- Encode H.264 yuv420p, `+faststart`, 30fps. Output to `docs/demo/captures/`.

## Remaining work, in order

1. **Seminar script** — `tests/fixtures/demo/seminar_script.md`. Delegate to a Sonnet subagent.
   Planted-items table is in `phase-3-portfolio-plan.md` Step 1a.
2. **`scripts/generate_demo_audio.py`** — OpenAI `gpt-4o-mini-tts`. **Run `--dry-run` and get
   Julian's approval on cost before spending.**
3. Fixture outputs: `demo_seminar.mp3` / `.mp4`, `expected_violations.json`, fixture README.
4. **`scripts/seed_demo_job.py`** — seed a processed job from committed JSON so captures re-shoot
   in seconds instead of waiting on Whisper.
5. **`scripts/demo_flow.spec.ts`** — five separate takes → `docs/demo/captures/`.
6. Stills → `docs/assets/`.
7. **`docs/demo/narration.md`** — Sonnet writes, then run the `plain-english` skill over it.
   150 wpm. Slides 70–90% density, demo scenes 30–50%.
8. `docs/demo/slide-copy.md` — problem statements + naive-cut snippet; architecture + repo URL.

**Blocking the toolkit workspace:** only the five capture files and `docs/demo/narration.md`.

## Standing constraints

- **No fabricated metrics anywhere.** No invented accuracy numbers.
- Fixtures must be synthetic. Never commit a real recording, name, or client content.
- Writing (script, narration, slide copy, case study, README prose) → Sonnet subagent.
  Engineering (Playwright, seeding, ffmpeg, generator, rehearsal) → main agent.
- `.env` is at the repo root, not in `backend/`.

## Uncommitted as of this writing

`prompt_analyzer.py`, `globals.css`, `jobs/[id]/page.tsx`, `ViolationList.tsx`, `lib/api.ts`,
plus new files `ProcessingView.tsx`, `test_output_contract.py`, `test_prompt_mode_action.py`,
`test_timestamp_mapping.py`. **Commit before continuing.**
