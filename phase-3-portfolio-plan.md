# Phase 3 — Portfolio Packaging: Development Plan

Scope: everything in `DEVELOPMENT_PLAN.md` Phase 3 — synthetic demo clip, demo video, README
overhaul, case study, resume bullet — plus the public-repo cutover that gates shipping any of it.

Decisions locked (Aug 2026):

| Decision | Choice |
|---|---|
| Demo audio | Generated with OpenAI TTS (`gpt-4o-mini-tts`) from a script I write |
| Demo video | Real screen capture of the live app + your voiceover |
| Case study | Markdown delivered in this repo; you port it to julianavellaneda.dev |
| Repo | Fresh GitHub repo, single squashed commit, no history; this repo stays private |

Everything below is my work unless marked **[YOU]**. Your side is collected separately in
`phase-3-your-checklist.md`.

---

## Tooling decision (asked first: what can Claude Code skills do here?)

**Already installed and genuinely useful:**

- `playwright-cli` — drives the browser to produce a *deterministic* run of the review UI. This is
  how the README hero GIF gets made without a shaky hand-recorded take, and it doubles as a smoke
  test of the demo path.
- `plain-english` — self-audit pass over the README and case study so they don't read as
  AI-generated. Non-negotiable for a portfolio document.
- `dataviz` / `artifact-diagramming` — only if the architecture diagram becomes a real drawing
  rather than a Mermaid block.
- `code-review` — one pass over whatever Phase 3 code lands.

**Third-party skills I looked at and am NOT recommending:**

- `claude-gif`, `wilwaldon/Claude-Code-Video-Toolkit`, `vorec` (screen recording with AI narration),
  `video-to-high-quality-gif`. They all wrap `ffmpeg` two-pass `palettegen` — which is four lines I
  can write directly, against an ffmpeg you already have installed and a repo that already depends
  on it. Installing them costs a `curl | bash` from an unaudited third-party repo for zero
  capability I don't have. Skip.

**One exception, worth a timeboxed try: `digitalsamba/claude-code-video-toolkit`.**

This is not the same category as the ones above. MIT-licensed, no mandatory API keys, and it is a
*workspace* rather than a plugin — you clone it and run `claude` inside that directory, so it never
touches the CleanCut repo. Video gets produced there and the MP4 is copied out. Clean separation.

Its `product-demo` template is a Remotion project with scene-based composition — title, problem,
solution, demo, stats, CTA — plus an animated background, browser/terminal chrome, narrator
picture-in-picture, and spring-animated stats cards. That is real capability I do not otherwise
have, which is why the blanket "skip third-party" call doesn't hold here.

**Where it fits: as the wrapper, not the substance.** The core of the video stays a real screen
capture of the working app with your voice over it — that is the part that earns credibility, and
no generated marketing sequence replaces it. What the template can add is the polish at the edges:

- Shot 1's title card (0:00–0:15)
- Shot 8's architecture / repo card (2:40–2:55)
- A stats card, *only* if the eval fixture in Step 1c produces a real number

**Two traps to avoid:**

1. The template's house style is "dark tech aesthetic with stats cards and a CTA" — a SaaS launch
   ad. On an engineering portfolio piece that can actively backfire, making a real system look like
   a product pitch for something that isn't a product. Use its scaffolding, override its tone.
2. Never put a fabricated metric on a stats card. Either the eval fixture yields a real accuracy
   number or the stats scene gets cut. An invented figure is the fastest way to lose an interview.

**Cost:** Node + Remotion install, learning the scene config, render time. Call it 2–3 hours, and it
is entirely additive — it happens *after* the screen capture exists and blocks nothing. If the
bookends look worse than a plain ffmpeg title card after two hours, we throw them away and lose
nothing.

Its other commands (`/record-demo` for Playwright capture, `/generate-voiceover` via ElevenLabs) I'd
skip: Step 2 already scripts Playwright directly, and your own voice beats synthesized narration for
a portfolio piece.

**Not a skill, but the real tool:** `ffmpeg`, which this project already requires. Every asset
below — silence padding, concat, MP3→MP4 waveform render, GIF palette — is ffmpeg.

---

## Step 0 — Pre-flight: does the demo path actually work today?

Before writing a script for a clip, confirm the sequence the video depends on still runs. Phase 0
claims it does; last verification was before the preset refactor and the upload-limits commit.

1. `docker compose up --build` from a clean checkout in a temp dir.
2. Upload a scratch clip → prompt mode → markers appear → toggle one to mute → Clean All fillers →
   export → download → verify the output with `ffprobe` (duration shrank, A/V still in sync).
3. Repeat once in preset mode (`income-claims`).
4. Log every rough edge — slow spinner, unlabeled button, ugly empty state. These get fixed in
   Step 4, not skipped.

**Output:** a defect list. If it's non-trivial, it gets fixed before recording, not after.

---

## Step 1 — Synthetic demo clip

Everything here is invented. No client content, no real names, no real numbers.

### 1a. The script — `tests/fixtures/demo/seminar_script.md`

A 3–4 minute fake "business opportunity seminar," two speakers (host + guest), written to plant one
of every category the tool detects so the demo has something to catch at every layer:

| Planted item | Why it's there |
|---|---|
| A specific dollar figure ("$14,200 in my fourth month") | Income claim — the flagship preset hit |
| "You can quit your job by Christmas" | Income/lifestyle claim, high severity |
| A luxury-car mention | Lifestyle claim, medium severity |
| "It cleared up my mother's migraines" | Health claim |
| A fake phone number + email read aloud | PII preset, demoes **mute** rather than cut |
| ~12 filler words (um, uh, like, you know) | Deterministic scrubber, no LLM |
| 3 dead-air gaps of 1.5–3s | Silence detection |
| One Spanish sentence mid-paragraph | Code-switching — a real differentiator, and true of the engine |
| A near-miss line ("some people earn nothing at all") | Proves it isn't just keyword matching |

The script is written as `SPEAKER | voice-instruction | text` lines with explicit `[PAUSE 2.4]`
markers, so audio generation is mechanical and reproducible.

### 1b. Generator — `scripts/generate_demo_audio.py`

- Parses the script, one TTS call per line via `gpt-4o-mini-tts`, distinct voice per speaker,
  per-line tone instructions (the model is steerable — that's what makes the fillers land naturally).
- Inserts exact silence for `[PAUSE n]` with `anullsrc`.
- Concatenates to `tests/fixtures/demo/demo_seminar.mp3` (mono, 64 kbps ≈ 2 MB, commits fine — no
  Git LFS needed).
- Also renders `demo_seminar.mp4`: a static title card + `showwaves` overlay, so the *video* path,
  the HTML5 player, and A/V-sync-preserving cuts are all exercised in the demo rather than claimed.
- Idempotent, caches per-line audio, and works with `--dry-run` to price the job first (a 4-minute
  script is a few cents).
- Reads `OPENAI_API_KEY` from the same root `.env` the backend uses.

### 1c. Ground truth — `tests/fixtures/demo/expected_violations.json`

Because the generator knows each line's exact offset, it can emit true start/end timestamps for
every planted item. This file is worth more than the clip:

- It's the eval fixture Phase 4 wanted ("flags land within N ms") — now free.
- New test `backend/tests/test_demo_fixture_eval.py`, marked `@pytest.mark.llm` and skipped without
  an API key, asserting the analyzer catches the planted items within a tolerance.
- "I have a labeled eval set for my LLM feature" is a line worth having in the case study, and this
  makes it true rather than aspirational.

### 1d. Fixture README

`tests/fixtures/demo/README.md` stating plainly that the clip is synthetic, TTS-generated, and
depicts no real person or company. The repo convention already requires synthetic fixtures; this
makes it self-evident to anyone browsing.

---

## Step 2 — Deterministic UI capture (the README hero)

A hand-driven recording of a browser is shaky and un-rerunnable. A scripted one is neither.

- `scripts/demo_flow.spec.ts` (Playwright, via the `playwright-cli` skill): seeds a pre-processed
  demo job, opens the review page, plays a few seconds of waveform, opens a marker, toggles it to
  mute, clicks Clean All, exports, downloads. Paced with deliberate dwell time so it reads on video.
- Playwright records the run to `.mp4`.
- `scripts/make_hero_gif.sh` — ffmpeg two-pass `palettegen`/`paletteuse`, 12 fps, ~960px wide,
  target under 5 MB so GitHub renders it inline. Output: `docs/assets/hero.gif`.
- Plus 3–4 stills for the README and case study: upload screen, review UI mid-playback, an expanded
  marker card, the export/download state.

Re-runnable, so a UI tweak later doesn't mean re-shooting anything by hand.

### Supporting: `scripts/seed_demo_job.py`

Seeds the DB with a fully processed demo job (transcript, markers, waveform cached) from committed
JSON. Three payoffs: the Playwright capture doesn't wait 3 minutes on Whisper; the video can be
re-shot instantly; and it's the exact groundwork Phase 5's zero-cost "demo mode" deploy needs.

---

## Step 3 — Demo video (2–3 min)

You record and narrate; I write everything you read and follow.

**Deliverable: `docs/demo/shot-list.md`** — a shot-by-shot storyboard with timings and the exact
narration for each beat:

| # | Time | On screen | Narration beat |
|---|---|---|---|
| 1 | 0:00–0:15 | Upload screen | The problem: hours of recorded content, manual review |
| 2 | 0:15–0:35 | Typing a plain-English prompt | The core idea — instruction, not a fixed rulebook |
| 3 | 0:35–0:55 | Job status stepping through stages | Real pipeline: convert → transcribe → analyze |
| 4 | 0:55–1:30 | Review UI, waveform, markers | Copilot not autopilot; click a marker, hear it, see the quote land on the exact words |
| 5 | 1:30–1:50 | Toggle a PII marker to mute | Cut vs mute per edit |
| 6 | 1:50–2:10 | Clean All fillers | Deterministic scrubber, one click, no LLM cost |
| 7 | 2:10–2:40 | Export, download, play result | A/V sync preserved across every cut — the hard part |
| 8 | 2:40–2:55 | Architecture card | Stack in one breath, repo link |

Also delivered:

- `docs/demo/narration.md` — the full voiceover script, timed, written to be read aloud (short
  sentences, no clause stacking), run through the `plain-english` pass.
- `docs/demo/recording-setup.md` — window size (1440×900 keeps text legible after compression),
  browser zoom, what to hide (bookmarks bar, notifications, any real filename), pre-flight checklist
  so a take isn't wasted.
- `docs/demo/captions.srt` — captions matching the narration, so it works muted on your site.
- After you hand me the raw take: ffmpeg pass for trim, normalize audio (`loudnorm`), encode a web
  MP4 (H.264, faststart) plus a compressed version for the site.

**[YOU]** Record the take and the voiceover. Details in your checklist.

---

## Step 4 — Fix what the rehearsal exposed

Step 0's defect list, plus anything that looks bad on camera. Expect a handful of small items:
empty-state copy, a spinner with no label, a marker card that wraps badly at demo width, a
too-quiet accept/reject affordance. Small, high-leverage, and all of it is visible in the artifact
a hiring manager actually watches.

Bounded to a half day. Anything larger gets written down as future work rather than absorbed here.

---

## Step 5 — README overhaul

The current README is accurate — it needs to be *persuasive*, in this order:

1. Hero GIF, above everything.
2. One-paragraph pitch (mostly written already).
3. **Demo video link** — right under the pitch, not buried.
4. Architecture diagram as a Mermaid block (renders natively on GitHub, no image to maintain):
   `upload → queue → Whisper (word timestamps) → chunked LLM analysis → review UI → FFmpeg export`.
5. Quickstart, verified by an actual fresh clone into a temp dir — I follow my own instructions
   literally and fix whatever fails.
6. **"Try it with the included demo clip"** — a three-command path using the committed fixture, so
   anyone can reproduce the video without supplying their own media.
7. **"How it works"** — three short subsections on the parts worth bragging about: word-level
   timestamp remapping of LLM-quoted text, the sliding-window chunking with overlap dedup, the
   single-pass A/V-sync-preserving filter graph.
8. **Limitations, stated plainly** — SQLite and a threaded in-process queue (not multi-worker),
   English/Spanish tested only, LLM cost scales with transcript length, assistive review and not
   automated compliance. Honesty here reads as senior; omission reads as naivety when it comes up
   in an interview.
9. License + a line stating all fixtures are synthetic.

Final pass with the `plain-english` skill.

---

## Step 6 — Case study — `docs/CASE_STUDY.md`

Written for the portfolio site, delivered as markdown you paste over. Structure:

1. **The problem** — reviewing hours of recorded content by ear for regulated speech, generalized
   to the category (no client named, no industry specifics that identify one).
2. **What it does** — three sentences and the hero GIF.
3. **The hard parts** — the section that earns the interview, one subsection each:
   - *Word-level timestamp alignment.* An LLM returns quoted text, not timestamps. Fuzzy-matching a
     quote back onto Whisper's word timeline is where the accuracy actually lives.
   - *A/V-sync-preserving edits.* Why naive per-segment cut-and-concat drifts, and why one
     `trim`/`atrim` + `concat` graph in a single pass doesn't. Includes why mutes are applied before
     cuts — cutting shifts the timeline out from under mute timestamps.
   - *Long transcripts.* 50-segment sliding window, 10-segment overlap, dedup by label and timestamp
     proximity. Why the overlap exists and what it costs.
   - *Failure modes made visible.* An unreadable LLM response raises rather than returning `[]`; one
     bad chunk completes with a partial warning; all chunks failing fails the job. The version where
     "broken" and "nothing found" were indistinguishable is the honest before-picture.
   - *Code-switching.* Spanish/English mid-sentence, and what that breaks in naive text matching.
4. **Architecture** — the diagram plus why threaded queue / SQLite were the right call at this scale
   and what would replace them at the next one.
5. **What I'd do differently** — provider abstraction from day one, structured outputs instead of
   JSON parsing, evals earlier. Concrete, not performative.
6. **Stack + links** — repo, demo video, one metric if the eval fixture gives a clean one.

Then the `plain-english` pass. Case studies are where AI-voice tells are most expensive.

**Length target:** 900–1300 words. Long enough to prove depth, short enough to finish.

---

## Step 7 — Resume bullet — `docs/RESUME_BULLET.md`

Three variants: one line, two lines, and a short paragraph for a portfolio card. Leading with the
technical specifics (word-level alignment, filter-graph editing, chunked LLM analysis) rather than
"built an AI app," which is what everyone else's bullet says.

---

## Step 8 — Public repo cutover

Last, so nothing half-finished goes out.

1. **[YOU]** Create the empty public repo on GitHub (name: `cleancut`).
2. I prepare a clean tree in a temp dir: working files copied, no `.git`, `git init`, one commit.
3. Pre-push verification, all of it before any remote is added:
   - `git log --all --pretty=format: --name-only --diff-filter=A | sort -u` — every file ever added,
     read in full.
   - `grep -ri` sweep for the client name, its acronym, the real people's names, and the Spanish
     transcript's distinctive phrases across tree *and* history.
   - Confirm `uploads/`, `exports/`, `*.db`, `.env` are gitignored and absent.
   - Confirm the only media committed is the synthetic demo clip.
4. Add `LICENSE` (MIT) and `.env.example` sanity check.
5. **[YOU]** Push, set the description and topics, add the demo video link.
6. This repo stays private as the archive of the real work.

---

## Sequencing

| Order | Step | Effort | Blocks |
|---|---|---|---|
| 1 | Step 0 rehearsal | 1 h | everything |
| 2 | Step 1 demo clip + eval fixture | 3 h | 2, 3 |
| 3 | Step 4 fixes from rehearsal | 2–4 h | 3 |
| 4 | Step 2 Playwright capture + hero GIF | 2 h | 5 |
| 5 | Step 3 video prep → **[YOU]** record → my post-pass | 2 h me + ~1 h you | 5, 6 |
| 6 | Step 5 README | 2 h | 8 |
| 7 | Step 6 case study | 3 h | — |
| 8 | Step 7 resume bullet | 20 min | — |
| 9 | Step 8 repo cutover | 1 h + **[YOU]** | — |

Roughly two focused days of my work, plus about ninety minutes of yours (recording, one GitHub
repo, and pasting the case study).

---

## Risks

- **The rehearsal finds something big.** Most likely candidate is timestamp drift on the export
  under the new preset path. Mitigation: Step 0 runs first, and Step 4 is explicitly budgeted.
- **TTS fillers sound fake.** Synthetic "um"s can land wrong. Mitigation: `gpt-4o-mini-tts` is
  steerable per line; if it still sounds off, the fallback is you reading the same script — the
  script is the asset, the voice is swappable.
- **Hero GIF over GitHub's inline size limit.** Mitigation: shorter loop, 12 fps, 960px, and a
  linked MP4 if the GIF still won't behave.
- **Scope creep into Phase 4.** The eval fixture is a Phase 4 item that Phase 3 gets for free, and
  that's the only Phase 4 work being pulled forward. Provider abstraction and the broader test pass
  stay out.

---

## Definition of done

- A synthetic demo clip, its ground-truth labels, and a passing eval test are committed.
- A hero GIF and stills are in `docs/assets/`.
- A 2–3 minute narrated demo video exists, encoded for web, linked from the README.
- The README opens with the GIF and its quickstart has been verified from a genuine fresh clone.
- `docs/CASE_STUDY.md` and `docs/RESUME_BULLET.md` are written and cleaned.
- A public repo exists with one squashed commit and zero client content, verified by full
  file-history read.
