# Development Plan — ai-audio-editing

Derived from `RECOMMENDATIONS.md` plus a read of the actual codebase (Aug 2026).

The recommendations doc assumes the product works and only needs repackaging. It mostly does — but the
audit below found four defects that would break a demo, and one confidentiality problem that has to be
handled before the repo goes public. Those come first; the packaging work in `RECOMMENDATIONS.md` follows.

---

## Codebase audit — what's actually there

**Working and genuinely impressive:**

- `backend/app/services/media_editor.py` — FFmpeg `trim`/`atrim` + `concat` filter graphs, A/V-sync-preserving,
  single pass. This is the technically strongest file in the repo and the thing to brag about.
- `backend/app/analysis/prompt_analyzer.py` — chunked sliding-window LLM analysis (50 seg / 10 overlap) with
  dedup, plus word-level timestamp remapping of LLM-quoted text. Real engineering, not a wrapper.
- `backend/app/services/worker.py` — threaded queue, per-stage job status (`converting` → `transcribing` →
  `analyzing` → `exporting` → `completed`). Frontend polls it. Good long-running-media story.
- `backend/app/services/scrubber.py` — deterministic silence + filler detection off word timestamps.
- Docker Compose, `start.sh`, `.env.example`, `DATABASE_PATH` override, configurable CORS. Deploy-ready-ish.

**Defects found (all should be fixed before any demo recording):**

| # | Issue | Location | Impact |
|---|---|---|---|
| 1 | The `prompt` is silently dropped on upload | `routes/jobs.py:30` vs `lib/api.ts:98-108` | **The flagship feature is dead.** `prompt: str \| None = None` alongside `file: UploadFile = File(...)` makes FastAPI read it as a *query* param; the frontend appends it to `FormData`. It never arrives, so every job runs the default instruction. |
| 2 | Per-edit `cut`/`mute` is never honored on export | `routes/audio.py:137-140`, `jobs/[id]/page.tsx:86` | `Violation.action` is stored, returned, and rendered as a badge — then export applies one global action, hardcoded to `"cut"` by the UI. Mute is unreachable. |
| 3 | "Clean All" has no UI | `lib/api.ts:159` (`bulkUpdateViolations`) | Phase 4 of `PROGRESS.md` is marked done; the endpoint and client both exist, but nothing calls it. It's the money shot in the planned demo video. |
| 4 | `API_BASE` is hardcoded to `localhost:8000` | `lib/api.ts:5` | Ignores `NEXT_PUBLIC_API_URL`, which `frontend/Dockerfile` and `docker-compose.yml` pass as a build arg. Any deploy (Phase 5) breaks. |

**Confidentiality — this is the blocker for going public:**

`RECOMMENDATIONS.md` asks to "confirm nothing client-confidential is in git history." It is. No media was
ever committed (good), but these are in history from the first commit:

- `tests/transcripts/{medium,large-v3}/client_seminar_transcript.txt` — a full verbatim
  transcript of a real client seminar, in Spanish, naming real people, covering their personal financial
  and family history.
- The matching `*_violations.json` files — an LLM's judgment of which of those named people's statements
  violate compliance rules.
- `backend/app/analysis/bsm_rules.txt` — a direct-sales company's marketing guidelines, likely derived from a client document.
- `Audio Compliance Review.jpeg` — unreviewed; check what it shows.

Publishing this repo as-is publishes all of it. History rewrite (or a clean squash into a fresh repo) is
mandatory, not optional.

**Secondary code-health notes** (not blockers, worth knowing):

- Dual import paths for the same modules: `processor.py` does a `sys.path` hack and `from transcriber import`,
  while `scrubber.py` does `from ..analysis.transcriber import`. Two module objects, two `Violation` classes.
  Duck typing saves it today; it will break the first time someone does an `isinstance` check.
- `worker.py:177` — the `except` block writes `job.status` where `job` may be unbound if the initial query
  throws, masking the real error as a `NameError`.
- `database.py:_apply_migrations()` is a hand-rolled one-column migration. Fine for now; note the ceiling.
- `main.py` uses the deprecated `@app.on_event("startup")`.
- Zero tests. `tests/` holds fixtures only.

---

## The plan

### Phase 0 — Make it true (½ day)

Nothing else is worth doing until the demo path works end to end.

1. Fix the prompt drop: make `prompt`, `media_type`, `auto_fix`, `auto_scrub`, `bsm_mode` explicit `Form(...)`
   params in `create_job`, and send them all in the `FormData` from `api.ts`.
2. Honor per-edit actions on export: partition accepted violations by `action`, mute-pass then cut-pass (mute
   first — cutting shifts the timeline out from under the mute timestamps), or build one combined filter graph.
   Drop the global `edit_action` from `ExportRequest`, or keep it as an override.
3. Wire "Clean All": a button in `ViolationList` calling `bulkUpdateViolations(jobId, {status:'accepted'},
   ['Filler Word','Dead Air'])`, then refetch.
4. `const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"`.
5. Add a per-violation cut/mute toggle to `ViolationCard` (the badge is already there, make it clickable) —
   otherwise fix #2 has no UI surface.

**Done when:** upload → custom prompt → markers appear → toggle one to mute → Clean All the fillers →
export → downloaded file is correct. This exact sequence is the demo video, so run it as a rehearsal.

### Phase 1 — Scrub and rename (1 day)

Order matters: scrub history *before* the repo is public, rename before the README is written.

1. **Decide the public-repo strategy.** Recommended: fresh repo, single squashed initial commit, no history —
   it is faster than `git-filter-repo` and leaves no chance of a missed blob. Keep this repo private as the
   archive of real work.
2. Delete the client transcripts and violation JSONs. Replace with a synthetic fixture (below).
3. Rewrite `bsm_rules.txt` as a generic `examples/rules/financial-claims.md` — same categories (income claims,
   lifestyle claims, health claims, disparagement), no company naming. These rules are industry-generic FTC/MLM
   guidance; the value is the pattern, not the client's copy.
4. Rename `bsm_mode` throughout to something neutral. Suggestion: a `preset` string field (`"income-claims"`,
   `"pii-redaction"`, `null`) rather than a boolean — it generalizes, and shows product thinking.
   Touches `models.py`, `schemas.py`, `routes/jobs.py`, `worker.py`, `prompt_analyzer.py`, `api.ts`, `page.tsx`.
   Add a migration line in `_apply_migrations()`.
5. Pick the name. Of the `RECOMMENDATIONS.md` shortlist, **CleanCut** reads best — it covers both the
   compliance and the podcast/filler use cases, where "ClipComply" and "RedactAI" each lock into one.
6. Purge client-specific branding from `README.md`, `CLAUDE.md`, `proj.md`, `GEMINI.md`, `docs/`, and UI copy.
   Reposition per `RECOMMENDATIONS.md`: *describe what to find in plain English → review on a waveform →
   export a surgically edited file.*

### Phase 2 — Fresh-clone truth (½ day)

1. Delete the stale `README.md` sections: the `poc/` directory does not exist (it's `backend/app/analysis/`),
   `.env` lives at the repo root, and the POC CLI paths in `README.md` and `CLAUDE.md` are wrong.
   Verify by actually cloning into a temp dir and following your own instructions.
2. Error states that fail visibly, per `RECOMMENDATIONS.md` §3:
   - Missing `OPENAI_API_KEY` → fail at startup with a clear message, not at job time.
   - Missing `ffmpeg` → same.
   - LLM timeout / malformed JSON → `_call_llm` currently swallows `JSONDecodeError` and returns `[]`, so a
     broken response is indistinguishable from "no violations found." Surface it on the job.
   - Fix the `worker.py` unbound-`job` masking bug so failures report their real cause.
3. Upload guardrails: file size and duration caps (needed for Phase 5 anyway).

### Phase 3 — Portfolio packaging (1–2 days) — *the highest-value phase*

1. **Synthetic demo clip.** Write a 3–4 minute fake seminar script with planted violations (a specific dollar
   figure, a "quit your job" line, a luxury-car mention, a health claim) plus deliberate ums and dead air.
   TTS it or record it. This doubles as the eval fixture and replaces the client transcript. Commit it.
2. **Demo video, 2–3 min**, following the Phase 0 rehearsal path. Per `RECOMMENDATIONS.md`, the single
   highest-leverage artifact.
3. **README overhaul:** hero GIF, one-paragraph pitch, architecture diagram
   (upload → queue → Whisper → LLM → review UI → FFmpeg export), quickstart via `docker compose up`.
4. **Case study** on julianavellaneda.dev. Lead with the hard parts, which are real:
   word-level timestamp alignment of LLM-quoted text, A/V-sync-preserving trim/concat filter chains,
   sliding-window chunking with overlap dedup for hour-long transcripts, code-switching Spanish/English,
   and a job queue for multi-minute processing.
5. Resume bullet.

**This is the definition of done for portfolio scope.** Everything below is bonus.

### Phase 4 — Credibility hardening (optional, ~1 day)

- Tests on the highest-risk logic, per `RECOMMENDATIONS.md` §3: `_merge_segments`, the keep-segment inversion
  in `cut_segments`, `_find_text_timestamps`, and `_chunk_segments_with_overlap`. Pure functions, cheap to
  test, and they're exactly what an interviewer probes with "how do you know the cut is frame-accurate?"
- Eval fixture: ~5 clips with known violation timestamps, asserting flags land within N ms. Small, and
  "I eval my LLM features" is a real differentiator.
- Provider abstraction: extract the OpenAI call behind an interface, add Anthropic. Echoes JobVault's
  multi-provider design and takes an afternoon. Also switch to structured outputs to kill the
  `JSONDecodeError`-returns-empty path.
- Collapse the dual import paths into package-relative imports only.

### Phase 5 — Live demo (optional, stretch)

Demo mode first, per `RECOMMENDATIONS.md`: ship 2–3 pre-processed sample jobs seeded into the DB, uploads
disabled. Zero API cost, no abuse surface, and the review UI — the best-looking part — is what visitors see.
BYO-key upload mode second, if at all. Needs the Phase 0 `API_BASE` fix and Phase 2 caps.

### Phase 6 — Business track

Parked per `RECOMMENDATIONS.md` §5. Revisit post-offer.

---

## Sequencing

| When | Phase | Output |
|---|---|---|
| Day 1 AM | 0 | Demo path actually works |
| Day 1 PM | 1 | Renamed, scrubbed, clean public repo |
| Day 2 AM | 2 | Fresh clone works; failures are visible |
| Day 2 PM – Day 3 | 3 | Sample clip, demo video, README, case study |
| Day 4 (optional) | 4 | Tests + evals + second provider |
| Week 2 (optional) | 5 | Live demo URL |

Phases 0–3 are the whole portfolio deliverable and are roughly three days of work. The riskiest item is
the history scrub in Phase 1 — do it deliberately, and confirm with
`git log --all --pretty=format: --name-only --diff-filter=A | sort -u` on the new repo before pushing.
