# Handoff — CleanCut

Written 2026-08-29. Branch `code-review-fixes`, clean tree, HEAD `fdbe2f8`.

The five items this file records as done were implemented on top of `a62fa08` and committed
one per item on 2026-08-29: review flags, the `EXPORT_DIR` collapse, the eslint fixes, the
review-surface tests, and the `seed_job.json` re-record. The eslint commit lands *before* the
tests commit, since `Waveform.test.tsx` pins the ref fix that commit makes.

Read `CLAUDE.md` first — it is the architecture reference and it is current. This file only covers
what is *not* in it: where the work stopped and what is worth picking up.

---

## Where things stand

Every plan this repo has carried is finished:

- **`docs/ROADMAP.md`** — Phases 1–4, all boxes checked. Kept as a record, not a queue.
- **The code-review fixes plan** — 11 phases, all done, one commit each. Deleted in `a62fa08`; its
  durable reasoning was transcribed into `CLAUDE.md` before it went. Recover it with
  `git show 605394e:code-review-fixes-plan.md` if you want the per-phase notes.
- **`docs/notes/2026-08-21-repo-analysis.md`** — every item struck through as shipped. Deleted in
  the same commit; `git show 605394e:docs/notes/2026-08-21-repo-analysis.md`.

So **there is no recorded "next"**. The items below are the threads those finished plans
deliberately left behind, each re-verified against the code on 2026-08-29.

Baseline: 708 backend tests, 77 frontend tests, `tsc --noEmit` clean, `eslint` clean, `npm audit`
clean, eval F1 95.7% (detectors) / 96.8% (recorded run).

All three numbered items are done, and so are the eslint warnings and the `seed_job.json`
re-record. What is left in "Smaller, genuinely optional" below is three reasoned decisions *not*
to act, kept so the reasoning is not re-derived. There is nothing in this file left to do.

---

## ~~1. Surface `is_approximate` / `is_ambiguous` as real fields~~ — done 2026-08-29

Both are columns on `violations` now, migrated in `database._apply_migrations()` (which grew a
per-table dispatch to reach a second table at all), carried through `ViolationResponse` and
`api.ts`, and rendered as a header badge plus one explanatory sentence in `ViolationCard`, a `⚠` in
`ViolationList`, and a `Check:` line in the analysis CLI. `reasoning` is now only ever the
detector's own words. `_is_pre_accepted` is untouched and still the single owner of the rule; the
flags are deliberately absent from `ViolationUpdate` so no client can clear one. See the "Review
flags" bullet in `CLAUDE.md`.

## ~~2. Collapse `EXPORT_DIR` to one owner~~ — done 2026-08-29

`services/exports.py` holds the only copy. The five others are gone: routes and the worker read
`exports.EXPORT_DIR` at call time, and the functions that still take an override resolve it through
`exports.export_dir(explicit)`. `retention.job_files`/`delete_job_files`/`purge_expired` took it as
a *default argument*, which bound the value at import and ignored a patch, so those now default to
`None`. The worker calls `exports.ensure_export_dir()` before both renders (the auto-fix branch
never created the directory at all). Seven test fixtures that patched two or three per-module
copies now patch one name. `tests/test_export_dir_owner.py` pins it: an AST pass asserting no other
module declares the constant and none binds it as a default, plus one redirect fixture every
consumer has to honour. See the `exports.py` bullet in `CLAUDE.md`.

## ~~3. Test the review surface that has no tests~~ — done 2026-08-29

Two new files, 33 tests, no production code changed.

`src/app/jobs/[id]/keyboard.test.tsx` (15) covers the documented contract — `J`/`K` and the arrows,
`A`/`R` deciding *and advancing*, `M`, `Space`, `P`, `T`, `?` — plus the three guards, which are the
half worth having: a modifier combination is a browser shortcut, a keystroke in a text field is
text, and `Space` on a focused `<button>` belongs to that button. It mocks `Waveform` as a real
`forwardRef` exposing the three `WaveformHandle` methods as spies; the existing `page.test.tsx`
mocks it as a `<div>`, which would let `Space` and `P` "pass" while calling nothing.

`src/components/Waveform.test.tsx` (18) covers the handle's arithmetic against a mocked
`wavesurfer.js`: the `duration === 0` guards (a clip played before the file loaded seeked to `NaN`),
the half-second pre-roll clamped at 0, `seekTo` clamped to the file, the auto-pause timer being
cleared by a retrigger, by a `seekTo`, and by unmount, the video-element path, the ±5s skips, and
the region colours and click wiring.

Every test was checked by mutation — reverting the behaviour it names fails it. Two did not, and
were rewritten: the clamp test pressed `k` three times against a three-item list, which lands on the
first item under a wrap-around too, and the "still processing" test asserts what it can observe
(nothing happens) rather than claiming to pin the `job.status` check, since with no suggestions
loaded the bindings are inert either way.

---

## Smaller, genuinely optional

- ~~**9 eslint warnings**~~ — done 2026-08-29. `eslint` is clean, and the four hook warnings were
  each a real defect rather than a missing entry:
  - `Waveform`'s `onTimeUpdate` was called from inside the effect that *creates and destroys*
    WaveSurfer, so the handler kept calling the **first** render's callback forever. It now reads a
    ref, which fixes that without the other option's cost — listing the prop would reload the audio
    on every unmemoized parent render. One test kills both mutations.
  - The review page's `loadData` depended on `selectedViolation`; the obvious fix (list `loadData`
    in its effect) would have re-fetched the job and the whole violation list on every click in the
    sidebar. It seeds through the functional setter instead, and `page.test.tsx` pins the
    call counts so that fix cannot be applied later by accident.
  - `app/page.tsx:31` was the flagged one. The four functions it calls close over **nothing
    reactive** — the poll ref, the API client, four setters — so memoizing them is safe and is not
    the Phase 2 shape at all; the trap is `handleFiles`, which reads four pieces of state and stays
    un-memoized. The comment above `handleDragOver` now has a counterpart saying which side of the
    line each function is on, and a test asserts the mount effect still runs once.
  - The review page's poll read `job.status`/`job.export_status` off the object while listing the
    optional chains; extracting both to locals lets it name what it re-arms on.

  One judgement call beyond the warnings: `uploadProgress` was "assigned but never used" — tracked
  per file, cleared after five seconds, and rendered nowhere. Deleting it was the smaller diff, but
  a multi-file drop is one request per file and `error` only ever holds the *last* failure, so a
  partially failed drop read as a wholly failed one. It is rendered now, with a test.
- ~~**`tests/fixtures/demo/seed_job.json` is a pre-scrubber-fix snapshot.**~~ — done 2026-08-29.
  Re-recorded from a real pipeline run of `demo_seminar.mp3` through the running app (same demo
  prompt, `auto_fix`/`auto_scrub` off), waveform peaks cached by one `GET .../audio/waveform` before
  the capture. The saved run went from 14 suggestions at 100% / 75.0% (F1 85.7%) to 17 at
  100% / 93.8% (F1 96.8%), and its misses from four to one: `filler-er-1`, the "Er," Whisper drops
  from the transcript, which the detector run misses for the same reason. So the snapshot and the
  detectors now agree, which is what makes the two eval modes comparable again.
  `scripts/seed_demo_job.py` also captures `is_approximate`/`is_ambiguous` now — they were added to
  `violations` after the last capture, so a replayed demo showed no review flags at all (the new
  recording carries one: the ambiguous "like" at 65.5 s). Three assertions in `test_eval.py` moved
  with it (the recall floor, `dead-air` 3/4 -> 4/4, and the miss list), plus the stale notes in
  `tests/fixtures/demo/README.md`, `eval_labels.json` and the CI comment.
- **A 0-segment transcript returns an empty result rather than failing.** Phase 8 made this
  explicit rather than a side effect of deriving `chunk_size=0`, and deliberately stopped there:
  whether a silent recording should *fail* is a worker behaviour change, not a validation fix.
- **The upload body cap is reverse-proxy work.** Starlette spools the multipart body to disk before
  any handler runs, so `MAX_UPLOAD_MB` bounds what CleanCut keeps, not what a client can make it
  receive. Documented in the README's "Failure modes"; not fixable in this repo.
- **The waveform lock dict never evicts** — one `threading.Lock` per job the process has ever
  generated peaks for. Judged not worth the eviction race. Revisit only at six figures of jobs in
  one process.

---

## Before you start

- `backend/uploads/` holds ~657 local dev files that `backend/audio_compliance.db` still
  references. Gitignored, so it is local clutter only — clear both together or neither.
- Run `pytest` (from `backend/`) and `npm test` + `npx tsc --noEmit` (from `frontend/`) after each
  change. The eval gate is
  `python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3 --suite scrub`, which
  is free: no model, no API key.
- `GEMINI.md` mirrors `CLAUDE.md` and drifted badly enough last time to state the opposite of the
  truth about admin auth. If you change the architecture, change both.
