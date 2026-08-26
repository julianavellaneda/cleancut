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
  - No undo / no bulk reject. bulk-update only touches pending violations, so "Clean All" is one-way — you can't un-accept in bulk.
  - Pluggable LLM provider. OpenAI() and model="gpt-4o" are hardcoded at prompt_analyzer.py:324,630. RECOMMENDATIONS §3 flags this; adding
    Anthropic behind a small provider interface is maybe 60 lines and gives you the BYO-key demo mode for free.
  - No eval harness. §3's "flags land within N ms" idea is the one thing here that would actually differentiate you in an interview, and you
    already have tests/fixtures/demo/expected_violations.json — the fixture exists, the assertion doesn't.

  OSS packaging (what's missing to be a real public repo)

  - No LICENSE. Nothing else on this list matters as much; without it nobody can legally use it.
  - No CI. .github/ doesn't exist. A workflow running pytest + tsc --noEmit + next build is an hour's work and is table stakes for a public repo.
  - No frontend tests at all — 1,500 lines of untested TypeScript.
  - Root is cluttered with 8 planning docs (proj.md, PROGRESS.md, DEVELOPMENT_PLAN.md, phase-3-*.md, demo-*.md, GEMINI.md). Move them to
    docs/notes/ or delete; a visitor's first impression is that file list.
  - docs/ROADMAP.md shows Phases 1–4 with every box unchecked, though all four are shipped. Reads as abandoned.
  - No retention policy. §4 says "auto-delete media after N hours" is already the stance — it isn't implemented, and data_retention: false is
    advertised in the README's Privacy section without code behind it.

  My suggested order

  1. Cut the dead deps, add LICENSE + CI, tidy root docs — half a day, unblocks "public repo."
  2. Keyboard shortcuts + transcript panel — the two changes that most improve the demo video you're about to shoot.
  3. Async export + admin auth + retention — the deploy prerequisites.
  4. Eval harness — the interview differentiator.
