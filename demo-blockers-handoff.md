# Handoff — fix the demo blockers before video capture

You are working in the **CleanCut** repo
(`ai-audio-editing`). Read `CLAUDE.md` first.

## Why this work exists

A portfolio demo video is being produced in a separate workspace. Five of its ten scenes are
Playwright-driven screen captures of this app running for real. A rehearsal of the full demo path
has already been run; it passed on the pipeline itself but surfaced five defects that will be
visible on camera or that block a scene outright.

**Your job is those five fixes, nothing else.** Capture, video, and fixture generation are handled
separately. Do not create demo media, Playwright specs, or narration.

## Already verified — do not re-run

The rehearsal is done. These facts are established; take them as given.

- `pytest` in `backend/`: **213 passed**. Keep it that way.
- Prompt mode, mp3: upload → transcribe → analyze → complete → accept all → export → download.
  19.876s in, 16.886s out — exactly the accepted cut duration.
- Preset mode `income-claims`, mp4: same path, `rule_violated="Income Claims"`, `severity="high"`.
- A/V sync holds on export: video 16.640s / audio 16.606s, both `start_time=0`.
- Mute-before-cut ordering is correct, confirmed by per-second RMS on the exported audio — silence
  lands at the predicted post-cut offset (4.24–7.88s).

**The backend export path, `media_editor.py`, and the scrubber are correct. Do not touch them.**

## The five defects

### D1 — No processing state on the review page `[BLOCKER]`

`frontend/src/app/jobs/[id]/page.tsx`

`isProcessing()` is defined at line 13 and used to drive polling (line 53), but never used for
rendering. There is a `failed` branch (line 136) and a loading branch (line 131), and no branch for
`converting` / `transcribing` / `analyzing` / `exporting`. So while a job processes, the page renders
the **full review UI**: empty sidebar, "Select an edit to review", and a `<Waveform>` pointed at a
file that has not been processed.

Video scene 5 is twelve seconds of "`converting → transcribing → analyzing` stepping live". That
screen does not exist.

**Build it.** A staged progress view, rendered when `isProcessing(job.status)` is true, showing all
pipeline stages at once with the current one active, completed ones marked done, and upcoming ones
pending. Stage order:

```
converting → transcribing → analyzing → exporting → completed
```

`converting` only occurs for `.aif`/`.aiff` uploads (`backend/app/services/worker.py`), and
`exporting` only when `auto_fix` or `auto_scrub` is set. Both must render correctly when skipped —
a stage the job never enters should not read as "stuck" or "failed".

Requirements:

- Legible at **1440×900** — this gets filmed. Stage labels at readable size, not 10px.
- Show the filename and, if known, `duration_seconds`.
- Visible motion on the active stage so a still frame reads as "working", but no frantic spinner.
- Existing 3s poll interval stays; the view must update as status changes.
- Match the app's existing restrained visual tone. No emoji, no gradients, no marketing language.

This is the one item where design quality matters — it is twelve seconds of a portfolio video.
Propose the layout before building it.

### D2 — Recall gap on sentences split across segments `[INVESTIGATE, do not over-fix]`

In the rehearsal, "you could quit your job by Christmas" was **not** flagged in either mode, despite
`backend/app/analysis/presets/income-claims.md` naming it verbatim ("No claims about ... 'quitting
your job'").

Probable cause: Whisper split it across two segments —

```
11.01-13.69  You know, ah, honestly, you could quit your job
13.69-17.01  by Christmas if you just, like, follow the system.
```

The near-miss control line ("some people earn nothing at all") was correctly **not** flagged, so
specificity is fine. This is a recall problem on split sentences, not over-flagging.

Investigate in `backend/app/analysis/prompt_analyzer.py`. Determine whether the chunk text handed to
the model preserves enough cross-segment context for a claim spanning a boundary to be seen as one
statement.

**Constraint:** if the fix is a prompt change, it must not increase false positives — re-check that
the near-miss line still goes unflagged. If the honest answer is "this is a real limitation of
segment-level analysis", say so and stop. A documented limitation is worth more here than a prompt
hack that inflates recall by flagging everything. Report what you find before changing anything.

### D3 — Prompt mode picks `action` arbitrarily `[MINOR]`

The same income-claim sentence returned `action="cut"` in preset mode and `action="mute"` in prompt
mode, with nothing in the instruction favouring either. In prompt mode the model chooses freely.

Video scene 7 is built on "cut vs mute is a deliberate choice". An arbitrary-looking default
undercuts it. Give prompt mode a sane default — `cut` unless the instruction implies redaction — or
make the basis for the choice explicit. Whatever you pick, cover it in `backend/tests/`.

### D4 — "Initializing Terminal…" `[COSMETIC, on camera]`

`frontend/src/app/jobs/[id]/page.tsx:131`. Nothing here is a terminal. Leftover from an older visual
direction, and it clashes with the tone of the piece. Replace with something plain.

### D5 — `✨ Clean All (n)` `[COSMETIC, on camera]`

`frontend/src/components/ViolationList.tsx:80`. Drop the sparkle. It is the one AI-product tell on an
otherwise sober UI, and it sits centre-frame in scene 7.

### Minor, fix only if trivial

`frontend/src/app/jobs/[id]/page.tsx:201` — the main panel shows "Select an edit to review" even when
a completed job has zero edits to select. The sidebar already handles this case correctly
(`ViolationList.tsx:161`, "No edits suggested"), so this is low-stakes.

## Explicitly out of scope

- `media_editor.py`, `scrubber.py`, the export filter graph — verified correct, leave alone.
- Any demo media, fixture, Playwright spec, seeding script, or narration.
- Remotion, the video toolkit, or anything video-rendering. **Do not install them in this repo.**
- Redesigning the review UI beyond D1's new view.
- The upload page, apart from what D1 requires.

## How to run and verify

```bash
# backend, port 8000
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload

# frontend, port 3000
cd frontend && npm run dev

# tests — must stay at 213 passing
cd backend && source .venv/bin/activate && pytest
```

For D1, you need a job that stays in a processing state long enough to look at. Upload any audio
file through the UI; transcription with the `medium` Whisper model takes long enough to inspect
every stage. Do not add a fake delay to production code to make this easier.

## Done when

- A processing view exists, renders every pipeline stage, and is legible at 1440×900.
- D2 is either fixed without new false positives, or documented as a limitation with the reasoning.
- Prompt mode's `action` default is deliberate and tested.
- No "Terminal", no sparkle.
- `pytest` still reports 213 passed.
- A short summary of what changed and what you chose not to change, and why.

## Notes

- Fixtures in this repo must be synthetic. Never commit real recordings, names, or client content.
- `.env` lives at the repo root, not in `backend/`.
- Frontend is Next.js 16 / Tailwind v4, functional components, strictly typed API calls.

---

# SUPERSEDED — read `demo-state.md` instead

This document's diagnosis of D2 is **wrong**. It states the cause is Whisper
splitting sentences across segments. That was disproved: the same content is
missed even when joined into a single segment.

The real cause, and the state of every item here, is in `demo-state.md`.
Keep this file only as the record of what was originally believed.
