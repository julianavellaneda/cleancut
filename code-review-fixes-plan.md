# Code Review Fixes — Phased Plan

Source: full code-review of the current working tree (90 files, 16,019 lines). 10 high-severity
findings, 9 medium-severity findings, 0 critical. This plan groups them into phases so an agent can
work a few at a time, verifying and committing after each phase before moving on.

General rules for every phase:
- Run `pytest` (backend) and `npm test` + `tsc --noEmit` (frontend) after each phase.
- Add/extend tests for the specific bug fixed, not just a smoke check.
- Keep phases small enough to review as one diff each.

---

## Progress

All work is on branch `code-review-fixes`, off `main` at `e6113a9`. One commit per phase.

| Phase | State | Commit |
|-------|-------|--------|
| 1 — Export status reporting | **Done** | `aceafda` (bundled with the pre-existing working tree) |
| 2 — Frontend upload settings | **Done** | `23ba748` |
| 3 — Dedup + timestamp alignment | **Done** | `dc7280c` |
| 4 — Export staleness invalidation | **Done** | `3ee2fe5` |
| 5 — Admin auth fail-closed | **Done** | `a6866c0` |
| 6 — Loopback-only binding | **Done** | `c6c9e63` |
| 8 — Validation & data integrity | **Done** | `2134a9c` |
| 9 — Retention, reanalysis, scrubber | **Done** | `_pending_` |
| 7, 10–11 | Not started | — |

Baseline after Phase 9: **656 backend tests**, **34 frontend tests**, `tsc --noEmit` clean,
`python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3 --suite scrub` passes
(F1 95.7%, unchanged by these fixes).

Notes left behind for whoever picks this up:

- **Phase 1** also matters to Phase 4: `export_status` is now actually visible to the frontend
  poll, which is what makes staleness observable at all.
- **Phase 3** added `Violation.is_approximate` to the *analyzer* dataclass only. It gates
  `auto_fix` (via `worker._is_pre_accepted`) and is written into the `reasoning` text so a
  reviewer sees it, but there is **no `violations` column for it** — surfacing it as a real field
  in the review UI needs a migration in `database._apply_migrations()`, `schemas.py`, `api.ts`
  and `ViolationCard`. Worth doing if Phase 8 or 9 is touching the schema anyway.
- **Phase 3** changed two private signatures: `_find_text_timestamps` now returns
  `(start, end, aligned)` and `_deduplicate_violations` takes a list of per-chunk lists rather
  than a flat list. Both are covered by `tests/test_timestamp_mapping.py` and `tests/test_dedup.py`.
- `worker._is_pre_accepted` is now the single owner of "may this be applied unreviewed" — both the
  saved `status` and the auto-rendered export ask it. Keep it that way; they used to be two
  separate expressions that could drift.
- **Phase 4** added two columns (`jobs.edit_revision`, `jobs.export_revision`) via
  `database._apply_migrations()`, so Phase 8/9 schema work has a recent example to copy. It also
  gave `exports.py` its own `EXPORT_DIR`; `routes/audio.py`, `routes/jobs.py`, `services/worker.py`
  and `services/retention.py` still each hold their own copy of the same constant, which is now
  five. Worth collapsing to one owner if a later phase is in these files anyway - the only reason
  it was not done here is that several test modules monkeypatch the per-module copies.
- **Phase 4** left `POST /export` free to queue a render while one is already in flight. That was
  true before and is not made worse by the revision tracking (the second render simply wins), but
  Phase 7's durable queue is the right place to make it explicit.
- **Phase 5** chose **503** for an unconfigured server rather than 401: with no `ADMIN_TOKEN` set
  there is no header the caller could send, so 401 would send an operator hunting for a credential
  that does not exist. `ALLOW_UNAUTHENTICATED_ADMIN=1` restores the old open behaviour and is
  ignored when a token *is* set. This is a **breaking change for existing dev setups** — anyone
  relying on the one-click reset must now set one of the two variables; say so in the PR
  description. `GET /admin/stats` is untouched, so the dashboard still loads either way.
- **Phase 5** left the loopback-binding half of its finding to Phase 6, where it belongs; the README
  privacy section now states the local-only trust model in words, which is the documentation half.
- **Phase 6** took option (a): loopback by default, one `CLEANCUT_HOST` variable to open it up. The
  variable names *the interface CleanCut is reachable on*, not a socket argument — `start.sh` hands
  it to uvicorn and to `next dev`, Compose uses it as the published interface while the container
  keeps binding `0.0.0.0` inside. Per-owner auth was explicitly **not** taken; if it is ever wanted
  it is its own project, not a phase here.
- **Phase 6** also narrowed `ALLOW_UNAUTHENTICATED_ADMIN` from Phase 5: it is honoured only on a
  loopback binding. Two settings in contradiction resolve closed, with a 503 that names which.
- **Phase 8** put all three fixes in one test module (`tests/test_input_validation.py`), since they
  share a failure *shape* rather than a module: each turned a bad input into a plausible result.
- **Phase 8** made `schemas.EDIT_ACTIONS` the owner of `("cut", "mute")`; `routes/violations.ACTIONS`
  is now that same object. Anything else needing the pair should import it, not re-spell it.
- **Phase 8** added `TranscriptFormatError` (a `ValueError` subclass) to `transcriber`. Only the CLI
  calls `load_transcript` today; a future caller has to catch it, or a mangled file becomes a 500.
- **Phase 8** left `analyze()` returning an empty result for a 0-segment transcript, which is what it
  already did — it is now explicit rather than a side effect of deriving `chunk_size=0`. Whether a
  silent recording should *fail* instead is a real question, but it is a behaviour change to the
  worker, not a validation fix, so it was left alone.
- **Phase 6** pins `start.sh` and `docker-compose.yml` as *text* in
  `tests/test_network_binding.py`, since neither can be unit-tested by running it and a regression
  in either is a one-character edit that silently reopens the port. Those two assertions need
  updating if the scripts are reformatted.

---

## Phase 1 — Export status reporting (quick, high-impact, isolated) — DONE

**Finding #1 (High): Export polling never observes the real state**
- File: `backend/app/routes/jobs.py:309` (`_build_job_response`)
- Fix: include `export_status` and `export_error` in the response.
- Add GET route tests covering `queued`, `exporting`, `ready`, `failed` states.

This is a self-contained one-function fix with clear test coverage — good first phase to build
momentum and validate the workflow.

---

## Phase 2 — Frontend upload settings bug (isolated, frontend-only) — DONE

**Finding #8 (High): Upload settings are ignored by the frontend**
- File: `frontend/src/app/page.tsx:86`
- Fix: `handleDrop`/`handleFileInput` are memoized with empty deps but call `handleFiles`, which
  closes over `prompt`, `preset`, `autoFix`, `autoScrub`. Fix the memoization (correct deps, or drop
  the unnecessary `useCallback`).
- Add an upload-page interaction test asserting the current prompt/preset/autoFix/autoScrub values
  reach the upload call.

Independent of backend work; can run in parallel with Phase 1 if using two agents, otherwise do
sequentially.

---

## Phase 3 — Analysis correctness: dedup + timestamp alignment — DONE

These two live in the same file and are conceptually linked (both affect what gets auto-cut), so
group them together.

**Finding #6 (High): Deduplication drops legitimate nearby findings**
- File: `backend/app/analysis/prompt_analyzer.py:498`
- Fix: only deduplicate across chunks, using normalized text similarity and real interval overlap —
  not just "same label, start within 5s".

**Finding #7 (High): Timestamp alignment can cut the wrong speech**
- File: `backend/app/analysis/prompt_analyzer.py:702`
- Fix:
  - Match complete normalized token sequences instead of substring-matching only the first word.
  - Validate that timestamps are finite and in-range; never fabricate `approximate_time ± 2s` as a
    safe fallback — treat an unaligned quote as unresolved rather than silently approximating.
  - Ensure unaligned/approximate results are never auto-accepted under `auto_fix`.

Write targeted unit tests: two distinct findings 3s apart must both survive; a quote whose first
word coincidentally matches unrelated text must not be misaligned.

---

## Phase 4 — Export staleness invalidation — DONE

**Finding #2 (High): Exports remain "current" after edits change**
- Files: `backend/app/routes/violations.py:69`, `backend/app/services/worker.py:242`
- Fix: track an edit revision (or simple monotonic counter / `updated_at`) on the job server-side.
  On violation status/action change or reanalysis, invalidate or remove the existing export
  (`export_status` back to `none`, delete stale export file). Frontend should render staleness from
  the captured revision rather than only in-memory state.
- Depends conceptually on Phase 1 (export_status now actually visible), so do after Phase 1.

---

## Phase 5 — Admin auth fail-closed default — DONE

**Finding #4 (High): Destructive admin routes fail open**
- File: `backend/app/auth.py:35`
- Fix: require a token by default; only allow the current "no-op when unset" behavior behind an
  explicit dev flag (e.g. `ALLOW_UNAUTHENTICATED_ADMIN=1`) combined with documenting/enforcing
  loopback binding.
- Update `.env.example` so a blank `ADMIN_TOKEN` doesn't ship as the implied-safe default.
- Update docs (`CLAUDE.md`/README) to reflect the new default.

Small, self-contained, but security-sensitive — review carefully since it changes default startup
behavior and could break existing dev setups; call this out in the PR description.

---

## Phase 6 — Network exposure / auth posture — DONE

**Finding #3 (High): Recordings and transcripts have no authentication**
- Files: `backend/app/main.py:65`, `backend/app/routes/jobs.py:154`, `backend/app/routes/audio.py:58`
- This is the biggest-scope item: either (a) bind to loopback only by default and document
  CleanCut as local-only, or (b) add real per-owner auth across the whole API.
- Recommendation: start with (a) — bind Docker/`start.sh` to `127.0.0.1` by default, require an
  explicit opt-in flag/env var to bind `0.0.0.0`, and document the local-only trust model clearly.
  Full multi-user auth is a much larger effort and should be its own separate project if ever
  needed.
- **Decision (taken):** (a). `CLEANCUT_HOST` defaults to `127.0.0.1` in `start.sh` (uvicorn *and*
  `next dev`) and as the published interface in `docker-compose.yml`; `app/network.py` owns what
  counts as loopback; a non-loopback host prints a startup warning; `ALLOW_UNAUTHENTICATED_ADMIN`
  is honoured only on loopback. Full multi-user auth was declined as out of scope.

---

## Phase 7 — Durable job queue (largest, do last, own session)

**Finding #5 (High): All queued work disappears on restart**
- File: `backend/app/services/worker.py:28`
- Fix: replace/augment the in-memory `queue.Queue` with a durable outbox — a DB table of pending
  tasks (`process`/`export`/`reanalyze`), reconciled at startup: any job left in a non-terminal
  status gets re-enqueued.
- This is the largest architectural change in the list. Give it its own full session, with its own
  design pass (schema for the task table, idempotency on reconciliation, migration) before coding.
- Do this after the smaller correctness fixes (Phases 1–5) so the queue changes aren't fighting
  concurrent edits to `worker.py` from Phase 4.

---

## Phase 8 — Medium-severity batch A: validation & data integrity — DONE

Small, mechanical validation fixes — group together:

1. **Invalid chunk settings can silently skip transcript sections** —
   `backend/app/analysis/prompt_analyzer.py:457`. Reject zero/negative chunk size and negative
   overlap at config load / call time.
2. **Invalid export actions silently become cuts** — `backend/app/schemas.py:107`. Reject any
   action other than `cut`/`mute` instead of defaulting to `cut`.
3. **Malformed transcript files can report a false-clean result** —
   `backend/app/analysis/transcriber.py:138`. Surface an error/warning when non-timestamped lines
   are discarded and analyzed-segment count is zero on a nonempty file.

---

## Phase 9 — Medium-severity batch B: retention, reanalysis, scrubber

1. **Retention can delete a queued export** — `backend/app/services/retention.py:156`. Also check
   `export_status` (`queued`/`exporting`) before sweeping, not just `job.status`.
2. **Failed reanalysis associates old suggestions with the new prompt** —
   `backend/app/services/worker.py:285`. On failure, restore the old prompt metadata alongside the
   preserved old findings.
3. **Ambiguous lexical fillers may be auto-cut** — `backend/app/services/scrubber.py:20`. Tighten
   filler-word matching (e.g. require surrounding disfluency cues, or drop the riskiest ambiguous
   entries from auto-accept under `auto_scrub`).

---

## Phase 10 — Medium-severity batch C: performance & infra hygiene

1. **Home polling performs an unbounded N+1 query** — `backend/app/routes/jobs.py:154`. Use a
   count query / eager load instead of materializing every job's violation collection.
2. **Waveform generation has a large concurrent memory footprint** —
   `backend/app/services/media_editor.py:167`. Add a per-job single-flight lock; consider streaming
   the PCM decode instead of holding the full buffer twice.
3. **Container builds are not hermetic** — `frontend/Dockerfile:5`, `frontend/src/app/layout.tsx:2`.
   Add `.dockerignore` files (exclude `.venv`, `node_modules`, `.next`); address the Google Fonts
   live-network build dependency (self-host or use `next/font` with fallback).
4. **Upload limits run after multipart spooling** — `backend/app/routes/jobs.py:60`. Document as a
   defense-in-depth gap; real fix is at the reverse proxy/ASGI layer, outside this repo's control —
   note it in docs rather than a code change, unless the user wants an ASGI-level body-size guard
   added here too.

---

## Phase 11 — Dependency upgrade

**Finding #10 (High): The pinned Next.js version has known high-severity advisories**
- File: `frontend/package.json:17`
- Fix: upgrade Next.js to 16.3.3+, regenerate lockfile, rerun `npm test`, `npm run build`,
  `tsc --noEmit`, and `npm audit --omit=dev`.
- Do this last / in its own phase since a major dependency bump can introduce unrelated breakage
  that's easier to isolate once the logic fixes above are already in and tested.

---

## Suggested execution order

1. ~~Phase 1 (export status)~~ — done
2. ~~Phase 2 (upload settings)~~ — done
3. ~~Phase 3 (dedup + timestamp alignment)~~ — done
4. ~~Phase 4 (export invalidation)~~ — done
5. ~~Phase 5 (admin auth default)~~ — done
6. ~~Phase 6 (network exposure)~~ — done
7. ~~Phase 8 (validation)~~ — done. ~~Phase 9 (retention/reanalysis/scrubber)~~ — done. **Phase 10 — start here.**
8. Phase 11 (Next.js upgrade) — isolate dependency churn
9. Phase 7 (durable queue) — largest, do last with its own design pass
