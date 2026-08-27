  Bugs / inaccuracies I'd fix first

  1. README claims a feature that doesn't exist. "Interactive review — a waveform with a marker per suggestion, keyboard-driven accept/reject."
     There is no key handler anywhere in frontend/src (I grepped for keydown/onKeyDown). Either build it (it's ~20 lines: A/R/J/K/space/M) or drop
     the claim. Building it is better — reviewing 80 filler words by mouse is the actual UX bottleneck, and it's the most demo-visible
     improvement per line of code.

  3. Admin endpoints are unauthenticated. POST /api/admin/reset-database, /clear-storage, /reset-all will wipe everything for anyone who can reach
     port 8000. Fine on localhost, disqualifying the moment you deploy the demo in RECOMMENDATIONS §4. Needs at least a shared-secret header
     gate, off by default locally.
  4. Export is synchronous. POST /{job_id}/export runs apply_edits inline. A 2-hour video re-encode blocks that request until FFmpeg finishes, and
     the frontend has no timeout handling — it just sits on "Exporting...". Everything else in the pipeline goes through the worker queue; export
     should too, with status: "exporting" polling like the rest.

  Feature gaps worth building

  - ~~The transcript is thrown away.~~ **Shipped.** `jobs.transcript` (segments only),
    `GET /api/jobs/{id}/transcript`, and a searchable click-to-seek panel behind `T` on the review
    screen. Re-running analysis without re-transcribing is now possible but not yet built.
    Original note: It's computed, used, and never persisted — no column, no endpoint, no UI. Users can't read the transcript,
    search it, or see a flagged quote in context. This is the biggest missing feature in the product: a transcript panel with the flagged spans
    highlighted, click-to-seek, is what turns it from "a list of markers" into an editor. It also unlocks re-running analysis with a different
    prompt without re-transcribing (currently a new prompt = a full Whisper re-run).
  - ~~No undo / no bulk reject.~~ **Shipped.** `bulk-update` now filters on `from_status` (default
    `pending`, so the sweep itself is unchanged) and on an explicit `ids` list, and the review page
    captures the swept ids so "Undo Clean All" puts back that sweep rather than every scrubber edit
    now sitting at accepted. The route also validates `status`/`action`, which it never did.
    Original note: bulk-update only touches pending violations, so "Clean All" is one-way — you can't un-accept in bulk.
  - ~~Pluggable LLM provider.~~ **Shipped.** `analysis/providers.py` + `CLEANCUT_MODEL="provider:model"`
    (`openai:gpt-4o` default, `anthropic:claude-opus-5` supported). Preflight checks the configured
    provider's key rather than `OPENAI_API_KEY` unconditionally, and a refusal on the Anthropic path
    becomes a named per-chunk gap instead of an empty answer that reads as a clean recording.
    Original note: OpenAI() and model="gpt-4o" are hardcoded at prompt_analyzer.py:324,630.
  - ~~No eval harness.~~ **Shipped.** `backend/app/eval/` scores a run against the labelled clip -
    precision, recall, per-category coverage, and two control lines that fail the run if flagged.
    `eval_labels.json` holds the judgements next to the generated offsets; the recorded demo run is
    graded in pytest and printed in CI, and `--live` measures the pipeline as it stands.
    It earned its keep immediately: the demo clip's line 9 renders as 0.3s of silence, so the spoken
    phone number the fixture advertises is not in the audio, and `Scrubber.FILLER_WORDS` could never
    match its own multi-word entry "you know" (word-by-word matching) or Whisper's "Hmm" (the set
    had "hm"). **Both scrubber bugs are now fixed** - `FILLER_PHRASES` matches runs of words and the
    set lists the spellings Whisper emits - taking the detector run from 1.00 / 0.75 to
    1.00 / 0.92, with CI's recall floor raised from 0.70 to 0.85 behind it. The remaining filler
    miss is an "Er," Whisper dropped from the transcript, which is not the scrubber's to find.
    `seed_job.json` is now a pre-fix snapshot; re-recording it costs a transcription and a
    completion.
    Original note: §3's "flags land within N ms" idea is the one thing here that would actually differentiate you in an interview, and you
    already have tests/fixtures/demo/expected_violations.json — the fixture exists, the assertion doesn't.

  OSS packaging (what's missing to be a real public repo)

  - ~~No LICENSE.~~ **Shipped.**
  - ~~No CI.~~ **Shipped.** `.github/workflows/ci.yml`: pytest, both eval modes, tsc, vitest, next build.
  - ~~No frontend tests at all.~~ **Shipped.** vitest + Testing Library in jsdom, `npm test`, wired
    into CI. Covers the bulk-sweep logic, the undo affordance, the re-analysis form, and the API
    client's request shapes. The review page's keyboard handling and the waveform are still uncovered.
  - ~~Root is cluttered with planning docs.~~ **Done.** `proj.md` -> `docs/DESIGN_NOTES.md`,
    `REDESIGN_CONTEXT.md` and this file -> `docs/notes/`. `GEMINI.md` stays at the root because a
    tool reads it there, like `CLAUDE.md`.
  - ~~docs/ROADMAP.md shows Phases 1–4 with every box unchecked.~~ **Done.**
  - ~~No retention policy.~~ **Shipped** (`services/retention.py`). Original note: §4 says "auto-delete media after N hours" is already the stance — it isn't implemented, and data_retention: false is
    advertised in the README's Privacy section without code behind it.

  My suggested order

  1. Cut the dead deps, add LICENSE + CI, tidy root docs — half a day, unblocks "public repo."
  2. Keyboard shortcuts + transcript panel — the two changes that most improve the demo video you're about to shoot.
  3. Async export + admin auth + retention — the deploy prerequisites.
  4. Eval harness — the interview differentiator.
