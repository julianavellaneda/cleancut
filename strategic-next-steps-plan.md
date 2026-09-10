# Strategic Next Steps — Implementation Plan

Derived from `repository-audit-2026-09-03.md` §5.2, with the §2 and §3 items that the audit ranked
as differentiation folded into the same sequence. Multi-session by design: six phases, roughly nine
working sessions, each phase landing on `main` as a coherent thing rather than as scaffolding for
the next one.

---

## 0. Where the repo actually stands (verified 2026-09-05)

The quick wins from §5.1 are **done**. Confirmed in the tree, not assumed:

| §5.1 item | State |
|---|---|
| GHCR owner in README | Fixed (`150c069` corrected a second, quieter instance) |
| `v0.1.0` tag | **Exists** — `release.yml` has run |
| Demo GIF | `docs/assets/demo.gif` present |
| Badges | Present, including the hardcoded `1.00 / 0.92` eval badge |
| `npm run lint` in CI | Present in the `frontend` job, before the type-check |
| `dependabot.yml` | Present |
| `frontend/README.md` | Replaced |
| `docs/ARCHITECTURE.md` | Rewritten (155 lines, matches the code) |
| `CODE_OF_CONDUCT.md` / `CHANGELOG.md` | Both present |

So this plan starts from §5.2 and does not revisit any of the above.

Still open, verified by inspection today:

- ~~`backend/requirements.txt` is **nine `>=` floors and no lockfile**.~~ **Resolved 2026-09-05
  (Phase A).** `requirements.in` declares, `requirements.txt` is a `uv pip compile --universal
  --python-version 3.10 --generate-hashes` lock, and the Dockerfile, CI, `start.sh` and the
  documented setup all install it with `--require-hashes`. CI re-compiles and fails on drift.
- ~~**No `pyproject.toml`, no `ruff.toml`, no `setup.cfg`, no `mypy.ini`** anywhere under
  `backend/`.~~ **Resolved 2026-09-05 (Phase B).** One `backend/pyproject.toml` owns ruff, mypy,
  pytest and coverage; `pytest.ini` was folded into it and deleted.
- ~~**No coverage measurement.** 585 test functions, no number.~~ **Resolved 2026-09-05 (Phase B).**
  85% with branch coverage over 770 tests, floored at 83 in CI.
- ~~**No `.devcontainer/`, no `Makefile`, no `justfile`.**~~ **Resolved 2026-09-10 (Phase C).**
  `.devcontainer/` builds a digest-pinned Python 3.12 + Node 22 + FFmpeg image; `Makefile` wraps the
  commands already documented in README.md and CONTRIBUTING.md.
- ~~**No mock provider.** `_PROVIDERS` in `analysis/providers.py` is `{"openai", "anthropic"}`, and
  `get_provider` hard-fails on a missing key — so a reviewer with no API key can run the tests and
  the detector eval, but cannot run *the app*.~~ **Resolved 2026-09-10 (Phase C).**
  `CLEANCUT_MODEL=mock:demo` runs the whole pipeline with no key at all.
- **README is 414 lines** (up from the audited 396) with 20 top-level sections.
- **Zero `aria-live` anywhere in `frontend/src`** — grep returns nothing. The pipeline status
  (`converting → transcribing → analyzing → completed`) changes visually and silently.
- `TranscriptPanel.tsx` is 142 lines and read-only: click-to-seek, no editing.
- ~~Two hand-maintained architecture documents~~ **Resolved 2026-09-05.** Consolidated to a single
  `AGENTS.md` (agents.md open format, read natively by most agent tools); `CLAUDE.md` is a one-line
  `@AGENTS.md` import and `GEMINI.md` is deleted. Every phase below updates one file.

---

## 1. Sequencing principle

Three things gate everything else, in this order:

1. **The build has to be reproducible before its quality is worth gating.** A `mypy` floor over a
   dependency set that floats is a floor over a moving target. So lockfile first, quality gate
   second.
2. **The repo has to be runnable by a stranger before new features are worth showing.** A reviewer
   who cannot start the app does not evaluate the transcript editor.
3. **Only then the two features that change what CleanCut *is*** — word-level transcript editing
   (the table-stakes interaction) and the detector plugin protocol (the differentiated one).

Phases A–C are hygiene and are cheap. D and E are real product work and each own multiple sessions.
F is the "if this becomes a product" tier and is explicitly *not* committed to here.

---

## Phase A — Reproducible builds (1 session) — ✅ **DONE 2026-09-05**

**Audit reference:** §5.2.1. **Why first:** everything downstream measures something, and a
measurement over a floating dependency set is not a measurement.

> **As built, with two deviations from A1–A3 below. What shipped is authoritative; the spec that
> follows is kept for the reasoning.**
>
> 1. **Naming inverted.** Not `requirements.txt` (floors) + `requirements.lock` (compiled), but
>    `requirements.in` (floors) + `requirements.txt` (compiled). Dependabot's
>    `pip_compile_file_matcher.rb` recognises a pip-compile lockfile only when the name ends in
>    `.txt` **and** either the content matches `--output-file <name>` or a sibling `<name>.in`
>    exists. A `.lock` matches neither, so Dependabot would have fallen back to reading the floors
>    and never touched the lock — exactly the "runs green and changes nothing" failure A2 warns
>    about, caused by A1's own naming. Side benefit: every consumer filename is unchanged.
> 2. **`--universal`, lower bound 3.10.** A2 did not say what to resolve *for*. A host resolution on
>    macOS does not install on linux. `--universal` emits environment markers instead, so one file
>    serves dev, CI and the image; `--python-version 3.10` is a lower bound under it and keeps the
>    README's promise honest. Packages that dropped 3.10 appear twice with markers.
>
> Also: the A1 "hand-written header comment" is **not** possible — `uv` rewrites the header on every
> compile and `--custom-compile-command` is single-line only (a newline emits an uncommented line
> and corrupts the file). uv's own header already records the exact regenerating command; the
> warning lives in the `.in` headers, `CONTRIBUTING.md` and `backend/tests/test_dependency_locks.py`.
>
> The A3 CI drift guard **was** cheap and did survive: re-compiles are byte-identical on uv 0.12.10.
> The A4 hash risk did not materialise — `onnxruntime`/`ctranslate2` hashed and installed fine.

### A1. Compile a lockfile

Use `uv` rather than `pip-compile`: it is one static binary, it is materially faster in CI, and it
emits a `requirements.txt`-format lock that plain `pip install -r` understands — which matters
because the Dockerfile and CI should not have to learn a new installer to benefit from the lock.

```bash
cd backend
uv pip compile requirements.txt   -o requirements.lock       --generate-hashes
uv pip compile requirements-dev.txt -o requirements-dev.lock --generate-hashes
```

Keep `requirements.txt` as the **declaration** (the floors, and the comments on them — the
`faster-whisper`/Silero note and the both-providers-installed note are real decisions and must not be
lost into a generated file). The `.lock` files are the **resolution**. Say that in a header comment
at the top of each lock, because a generated file with no explanation invites someone to hand-edit
it.

### A2. Point the consumers at the lock

- `backend/Dockerfile`: `COPY requirements.txt requirements.lock .` then
  `pip install --no-cache-dir --require-hashes -r requirements.lock`.
  `--require-hashes` is the point of `--generate-hashes`; without it the hashes are decoration.
- `.github/workflows/ci.yml`, backend job: install from `requirements-dev.lock`, and change
  `cache-dependency-path` to it.
- `CONTRIBUTING.md`: the local install line becomes the lock too, so "running what CI runs" stays
  literally true — that claim is the file's whole thesis.
- `.github/dependabot.yml`: confirm the pip ecosystem points at the directory holding the files it
  should bump. Dependabot updating `requirements.txt` while Docker installs `requirements.lock` is
  the failure mode where the automation runs green and changes nothing.

### A3. Document the regeneration ritual

A short section in `CONTRIBUTING.md`: when you add a dependency, add the floor **and** re-compile
both locks in the same commit. Add a CI guard if it is cheap — re-run `uv pip compile` and fail if
the lock is dirty. If that proves slow or flaky, skip it; the contributing note carries most of the
value.

**Acceptance:** `docker compose up --build` from a cold cache installs byte-identical versions twice
in a row. CI green. `git diff` on a re-compile is empty.

**Risk:** `--generate-hashes` can choke on a package with no wheel for the runner's platform.
`faster-whisper` pulls `onnxruntime`, which is the usual suspect. If hashes fight the build, drop
`--generate-hashes` and `--require-hashes` and keep the pinned lock — pinning is 90% of the benefit;
say in the lock header why hashes are absent so nobody "fixes" it back.

---

## Phase B — Backend quality gate (1–2 sessions) — ✅ **DONE 2026-09-05**

**Audit reference:** §5.2.2. The frontend has lint + types + tests + build in CI. The backend has
pytest and two eval runs and nothing else. This closes the asymmetry.

> **As built, with four deviations from B1–B6 below. What shipped is authoritative; the spec that
> follows is kept for the reasoning.**
>
> 1. **`pytest.ini` was deleted, not left alone.** B1 did not anticipate that `pytest.ini`
>    **outranks** `pyproject.toml` and wins *silently* — no conflict, no warning. Coverage settings
>    added to the new file while that one survived would have been a no-op that looked exactly like
>    a working gate. Its contents moved verbatim; `configfile: pyproject.toml` and the rootdir were
>    verified afterwards.
> 2. **mypy covers `app/analysis/` only** — B3's stated fallback, taken for a reason B3 did not
>    predict. Over the whole package mypy reports 195 errors and **122 are one root cause**:
>    `models.py` declares columns the SQLAlchemy 1.x way, so `job.status = "completed"` reads as
>    assigning `str` to `Column[str]`. That fires wherever the ORM is touched — most of `services/`
>    *and* `routes/* — so it is not something a per-module scope can route around, and it is not the
>    `numpy` typing B3 expected to be the hard part. **Migrating the models to `Mapped[...]` is what
>    unblocks widening this**, and it is a runtime change to the data layer that needs its own
>    commit. Also: `strict = true` cannot be scoped per-module at all (it is global-only and ignored
>    without warning), so the twelve flags it implies are spelled out instead.
> 3. **Line length 88, measured not chosen.** `ruff format --diff` added 3634 / 2398 / 1675 lines at
>    79 / 88 / 100. The raw count is the wrong metric — a wider setting buys its smaller diff by
>    *joining* lines a human split — so 88 won as the width where the reflow is overwhelmingly
>    splitting genuinely over-long lines. The sweep was verified semantically inert by comparing
>    every touched file's parsed AST, and `.git-blame-ignore-revs` was added so 62 files of reflow do
>    not bury the commit messages this repo uses as documentation.
> 4. **B6 pre-commit was skipped.** Judged the least valuable item in the phase, and CI already
>    enforces everything it would have.
>
> Also, unplanned: `app/analysis/` had **no `__init__.py`** — the only subpackage without one, which
> made it reachable under two module names and would have stopped mypy before it checked anything.
> Ruff found five real defects on the way through (exception chaining, two `zip()`s that could
> silently truncate, a shared `ExportRequest()` instance, a test asserting nothing), each fixed in
> its own commit. Coverage measured **85%** with branch coverage; floored at 83.
>
> The B4 instruction to record per-module numbers in the commit message was followed — the thin
> spots are `processor` 44 and `transcriber` 67, and `analyze.py` reads 0% only because its nine
> tests run it in a subprocess.

### B1. `pyproject.toml` at `backend/`

One file owning ruff, mypy and coverage config. Do **not** convert the project to a
`pyproject`-installed package — `conftest.py` putting the backend root on `sys.path` is what makes
tests import `app.*` exactly as uvicorn does, and that is deliberate. This file is config only.

### B2. Ruff

Start with `E`, `F`, `I` (import sorting), `UP`, `B`. Run `ruff format` once over `backend/app` and
`backend/tests` as a **single mechanical commit with no logic changes**, so the diff of the next
commit is reviewable. Line length: match what the code already does — measure before choosing, don't
impose 88 on a codebase written to something else and generate a thousand-line reflow.

Expect real findings. Triage them: fix the genuine ones, and `# noqa` with a reason for anything
where the rule is wrong about this code. A blanket per-file ignore list is how a lint gate becomes
decoration.

### B3. Mypy, scoped

`--strict` over `app/services/` and `app/analysis/` only, as the audit specifies. Those are the two
packages where a type error is a silent wrong answer rather than a 500. Routes and models stay out —
SQLAlchemy and FastAPI decorators generate the most annotation noise for the least caught.

`numpy` typing in `services/levels.py` and `media_editor.py` will be the hard part; the read-only
`np.frombuffer` view in `decode_pcm_mono` is exactly the kind of thing mypy will want spelled out.
That is fine — spelling it out is documentation of an invariant `AGENTS.md` currently carries only in
prose.

**If `--strict` over both packages turns out to be a multi-session slog, ship `app/analysis/` strict
and `app/services/` non-strict with a TODO**, rather than dropping the gate to nothing. Do not
extend Phase B past two sessions; report what was left non-strict.

### B4. Coverage with a floor

```
pytest --cov=app --cov-report=term-missing --cov-fail-under=<floor>
```

Measure first, then set the floor at roughly the measured number minus 2 points. Setting an
aspirational floor that fails on day one means the first thing anyone does is lower it. The
interesting output is not the aggregate — it is which modules come back thin. Record the initial
per-module numbers in the commit message so the next session can see movement.

### B5. Wire into CI

New steps in the backend job, cheapest-first (the same argument already written into `ci.yml` for
the frontend lint step): ruff → mypy → pytest+cov → eval scorecard → detector eval.

### B6. Pre-commit (optional, same session if time)

`.pre-commit-config.yaml` with ruff, ruff-format and the trailing-whitespace/EOF basics. Opt-in via
`pre-commit install`, documented in `CONTRIBUTING.md`. Never a CI requirement — CI must not depend on
a hook a contributor may not have run.

**Acceptance:** `ruff check`, `ruff format --check`, `mypy` (at the agreed scope) and
`pytest --cov --cov-fail-under` all pass locally and in CI. `CONTRIBUTING.md` lists every one of them
under "running what CI runs".

**Doc obligation:** the Conventions section of `AGENTS.md` gains the backend gate.

---

## Phase C — Runnable by a stranger (1–2 sessions) — ✅ **DONE 2026-09-10**

**Audit reference:** §2.1 and §5.2.3. Today the eval and the tests run with no API key — a genuinely
rare property. The *app* does not. This closes that gap and is the highest-leverage remaining
packaging work.

> **As built, with eight deviations from C1–C3 below. What shipped is authoritative; the spec that
> follows is kept for the reasoning.**
>
> 1. **The mock is its own module, `analysis/mock_provider.py`, not a branch inside
>    `providers.py`.** Its keyword table and sentence-matching logic would otherwise compete for
>    attention with the provider registry every other reader of that file needs; `providers.py`
>    only wires it in, via a `_mock_provider` factory imported on use.
> 2. **`preflight.py` needed a real code change, not just a check that it already does the right
>    thing.** C1 read as "verify rather than assume"; in fact `missing_requirements` needed a new
>    branch for `api_key_name is None`, and a new `model_notice()` function was added so the server
>    prints either `Analysis model: <spec>` or a three-line mock `WARNING` at startup — there was no
>    existing startup line naming the model at all before this phase.
> 3. **Every label carries a `Mock: ` prefix, beyond the `MOCK PROVIDER` reasoning prefix C1 called
>    for.** A suggestion is visible in the sidebar list by its label alone, with the reasoning one
>    click away; C1's design constraint 4 ("impossible to mistake for a real analysis") was not met
>    by the reasoning prefix on its own.
> 4. **Node is copied out of a digest-pinned `node:22-bookworm-slim` image via a multi-stage
>    `COPY`, not added through a devcontainer "feature."** Features are pinned by major tag and
>    float exactly the way C2 warned an unpinned base image would.
> 5. **`.github/dependabot.yml` gained a `docker` entry for `/.devcontainer`,** not scoped by C2 —
>    needed so the two digest pins age like every other dependency in this repo instead of going
>    stale silently.
> 6. **The Python devcontainer base ships a Yarn apt source whose signing key has since rotated,**
>    which fails `apt-get update` outright before anything else can install. Not anticipated by C2
>    at all; nothing here uses Yarn, so the Dockerfile removes that source file rather than
>    re-keying it.
> 7. **`make eval` carries no `--min-*` floors, and `make lock` re-compiles via
>    `uvx --from uv==$(UV_VERSION)`** rather than assuming `uv` is installed on the host — both
>    choices C3 left open. A threshold in the Makefile would be a second, driftable copy of
>    `ci.yml`'s; `uvx` means `make lock` works with no global `uv` install.
>    `backend/tests/test_makefile.py` is a separate test file (not folded into
>    `test_dependency_locks.py`) pinning the uv-version agreement with `ci.yml` and the no-floors
>    rule.
> 8. **Two Makefile targets beyond C3's list: `help` (the default goal) and `install`.** A Makefile
>    with no `help` target contradicts the whole point of a devcontainer — nothing should have to be
>    read to get started.
>
> Also found during the in-container acceptance run, not anticipated by C2: `post-create.sh`'s
> `chown -R` on the Hugging Face cache directory left its *parent*, `~/.cache`, still owned by root
> — mounting that named volume creates `~/.cache` itself as root first — which silently disabled
> pip's cache. `post-create.sh` now also `chown`s `~/.cache` itself, non-recursively, alongside the
> recursive chown on its `huggingface` subdirectory.
>
> **Acceptance, verified twice.** On the host with no keys (`OPENAI_API_KEY=` and
> `ANTHROPIC_API_KEY=` blank): the demo clip uploaded, completed in 24s, produced 7 `Mock:`
> suggestions (plus the scrubber's) all on word timings with none approximate; accepting and
> exporting them cut the original 74.00s to 47.10s, exactly the 26.90s accepted. Separately,
> **in-container**, against a clean copy of the checkout (no `.env`, no `.venv`, no
> `node_modules`, the container's own ffmpeg, Whisper medium pre-seeded into the HF volume so this
> run did not test that download itself): `post-create.sh` ran in ~40s and wrote `.env` with
> `CLEANCUT_MODEL=mock:demo`; `./start.sh` booted both servers and printed the mock warning; through
> the frontend's `/api` proxy on :3000, an upload completed in 20s with 18 suggestions (7 `Mock:`,
> none approximate), and accepting and exporting the 7 cut the original 74.06s to 47.23s (26.82s
> accepted). An actual GitHub Codespaces boot is still **not** tested.

### C1. The `mock` provider

Add `MockProvider` to `analysis/providers.py` and `"mock"` to `_PROVIDERS`, reached by
`CLEANCUT_MODEL=mock:demo`.

Design constraints, in order of importance:

1. **It must not need a key.** `get_provider`'s missing-key check is keyed off `PROVIDER_API_KEYS`;
   the mock needs an exemption there, written as an explicit branch with a comment, not as a
   sentinel empty string.
2. **It must return something the real parser accepts.** It returns raw text like every other
   provider; `_parse_llm_response` and `_validate_entries` stay untouched. If the mock's output has
   to bypass validation, the mock is wrong.
3. **It must be deterministic and transcript-derived.** Not a fixed canned list — a canned list
   returns findings for a recording that does not contain them, which is worse than nothing for a
   demo. Have it scan the transcript it is given for a small keyword set and quote real spans back.
   That way the review UI shows suggestions that actually land on the waveform where the words are.
4. **It must be impossible to mistake for a real analysis.** Every suggestion's `reasoning` starts
   with something like `MOCK PROVIDER —`, and startup logs the provider name. A demo that quietly
   looks like a real compliance pass is a liability given the target market.

Then: `preflight.py` must not demand a key when the configured provider is the mock (it already
checks the *configured* provider's key, so verify rather than assume); `.env.example` gains a
commented `CLEANCUT_MODEL=mock:demo` line; README quickstart gains a "no API key? run it anyway"
paragraph; a test in `backend/tests/` pins that the mock needs no key and that its output survives
`_validate_entries`.

### C2. `.devcontainer/`

Python 3.12 + Node 22 + system ffmpeg in one image, `postCreateCommand` installing from both locks
and running `npm ci`. Pin the base image by digest or the devcontainer floats exactly the way Phase A
just fixed the backend. Combined with C1, "Open in Codespaces → it runs" becomes true.

### C3. `Makefile`

The README carries ~9 commands across two directories. Targets: `dev`, `test`, `lint`, `eval`,
`eval-live`, `lock`, `docker`. Thin wrappers only — the Makefile documents the commands, it must not
become a second place where CI's behaviour is defined. `CONTRIBUTING.md` keeps the explicit commands
alongside, since that file's value is that it mirrors CI literally.

**Acceptance:** a checkout with no `.env`, no API key and no ffmpeg on the host runs the full
upload → transcribe → analyze → review → export loop inside the devcontainer.

---

## Phase D — README split and accessibility (1 session)

**Audit reference:** §5.2.6 and §2.2. Small, and worth doing before the feature phases so the new
features have a sane document to be added to.

### D1. Split the README

414 lines → ~120. Target structure: hook → badges → demo GIF → key features → quickstart → **the
eval numbers** → contributing → license. The eval section stays in the README; it is the
differentiator and it is what the badge links to (confirm the anchor slug survives the split — a
broken badge link is worse than no badge).

Move out, verbatim where possible:

- `docs/CONFIGURATION.md` ← the environment-variable table (README §Configuration)
- `docs/API.md` ← the endpoint table + §Analysis modes + §CLI
- `docs/FAILURE_MODES.md` ← §Failure modes + §Privacy, cross-linked from `SECURITY.md`

Leave a one-line pointer at each excision point. Check every relative link in `CONTRIBUTING.md`,
`SECURITY.md`, `docs/ARCHITECTURE.md` and the issue templates afterwards.

### D2. `aria-live` for the pipeline

Confirmed missing today. `ProcessingView.tsx` is where it goes: an `aria-live="polite"`
`role="status"` region announcing the stage transitions, plus terminal states (`completed`,
`failed`) and the export lifecycle. `FailedView` should be `role="alert"`. Announce the *stage*, not
the polling tick — a region that re-announces on every 3s poll is worse than silence.

Pin it in `ProcessingView.test.tsx` (which already exists), the same way `contrast.test.ts` pins
colour: assert the live region exists and carries the stage text.

### D3. `eslint-plugin-jsx-a11y`

Add beyond Next's defaults, in `frontend/eslint.config.mjs`. The CI lint step already exists, so this
is one config edit plus whatever it finds. Expect findings on the waveform region markers and the
custom toggle/radio components.

### D4. CLI `--help` audit

Verify `app/analysis/analyze.py`'s argparse carries an epilog with a worked *module* invocation
(`python -m app.analysis.analyze`). The `python analyze.py` footgun is a documented Common Issue; the
`--help` text is where someone hits it.

---

## Phase E — Word-level transcript editing (2–3 sessions)

**Audit reference:** §3.1 and §5.2.4. The category-defining interaction, and the pieces are already
in place: word timings are persisted (transcript schema v2), `TranscriptPanel` already does
click-to-seek, `Waveform` already exposes `seekTo`/`playClip`, and the export pipeline already takes
an arbitrary set of spans.

**The framing that keeps this consistent with the product's philosophy:** deleting a word in the
transcript does not edit the audio. It **creates a suggestion, already accepted**, in exactly the
same `violations` table every other edit lives in. "Copilot, not autopilot" survives, the export
path is unchanged, undo is the existing reject flow, and the waveform shows the deletion the moment
it is made because it is the same kind of object it already renders. Any design where transcript
edits are a second, parallel edit list is the wrong one — it means two things can disagree about
what the export contains.

### Session D1 — backend

- `GET /api/jobs/{id}/transcript` currently returns lines. Add word-level output (behind a query
  param, or as a second field) so the panel can render selectable words. Words are stored and
  currently served to nobody; this is the reader they were stored for.
- New route: `POST /api/jobs/{id}/violations/from-selection`, taking a word-index range (not raw
  timestamps — the server owns the mapping from words to spans, and a client computing timestamps is
  a client that can drift from the stored transcript). It creates a `Violation` with
  `status="accepted"`, a distinguishing `label` (e.g. `"Manual Edit"`), and `action` from the
  request.
- It must go through `mark_export_invalidated` in the **same transaction** as the insert. Every
  route that moves the accepted set already does; this is a new one and the rule applies to it.
- Deletion of a manual edit is the existing PATCH to `rejected`, not a new DELETE route.
- Decide and **document** how manual edits interact with re-analysis. Proposed: they survive, on the
  same argument as the scrubber's suggestions — they are not answers to the prompt. That is a change
  to `_process_reanalysis`'s delete filter, and it belongs in `AGENTS.md`'s re-analysis section.

### Session D2 — frontend

- `TranscriptPanel` gains word-level rendering and a selection model (click a word, shift-click to
  extend, drag to select a run). Keep click-to-seek: a *click* seeks, a *selection* is what offers
  the delete affordance. Do not overload one gesture with both.
- Selected-and-deleted words render struck through and dimmed **with a token, never with
  `opacity`** — the design system's third rule, and this is exactly the situation that tempts a
  violation.
- Keyboard path, since the review screen is fully keyboard-operable and a text feature that is not
  would be a visible regression: arrow keys move the word cursor, shift extends, `Backspace`/`Delete`
  creates the edit. Add them to `KeyboardLegend` and to the `?` overlay in the same commit.
- Tests: extend `TranscriptPanel`'s coverage for selection and the delete call; extend
  `keyboard.test.tsx` for the new bindings and the existing text-input/modifier guards.

### Session D3 — integration, docs, buffer

Waveform regions for manual edits; README/`docs/` copy; `AGENTS.md`. Treat this session as real, not
as slack — this feature touches the transcript, the violation lifecycle, re-analysis and the
keyboard map.

**Acceptance:** delete three words in the transcript, see three regions on the waveform, export, and
hear exactly those three words missing. Reject one, export again, hear it return.

---

## Phase F — Detector plugin protocol (2 sessions)

**Audit reference:** §3.2.2 and §5.2.5. The differentiation play. The sentence it buys — *"pluggable
detectors, each graded by the same CI-gated precision/recall harness"* — is only true if the second
half is built, so the eval integration is not an optional follow-up to this phase. It **is** this
phase.

### Session F1 — the protocol

Formalize what already exists twice. `Scrubber` (deterministic, reads transcript + audio) and
`PromptAnalyzer` (LLM, reads transcript) are two implementations of one shape that has never been
written down.

- A `Detector` protocol in `app/analysis/` or a new `app/detectors/`:
  `detect(transcript, audio_path, context) -> list[Suggestion]`, where `Suggestion` is the dataclass
  the worker already copies onto `Violation` rows (including `is_approximate` and `is_ambiguous` —
  those flags are the protocol's most important field, because they are how a detector says "do not
  apply this unreviewed", and `worker._is_pre_accepted` stays their single reader).
- Refactor `Scrubber` and `PromptAnalyzer` to satisfy it. **This must be behaviour-preserving**: the
  detector eval is the proof, and it must score 1.00 / 0.92 before and after. If it moves, the
  refactor changed something.
- A registry with entry-point discovery (`importlib.metadata.entry_points(group="cleancut.detectors")`),
  built-ins registered through the same mechanism they document, so the built-in path and the
  third-party path cannot diverge.
- Failure isolation: a third-party detector that raises must degrade the job to a named partial
  warning, exactly as a failed LLM chunk does. It must never fail the job and never silently return
  nothing — an empty result is indistinguishable from a clean recording, which is the same trap
  `DATA_NOT_INSTRUCTIONS` exists to defend against.
- Security note in `SECURITY.md`: an installed detector is arbitrary code with the transcript and the
  media. Say so plainly; that file already does this well for the other design decisions.

### Session F2 — per-detector eval + an example plugin

- `app/eval/run.py` gains `--detector <name>`, scoring one registered detector against a named suite.
- A worked example plugin in `examples/` or a sibling directory — a profanity detector is the
  obvious one — with its own labels and a documented score. The example is the documentation; a
  protocol with no reference implementation gets implemented wrong.
- `docs/DETECTORS.md`: write one, register it, score it.

**Acceptance:** an out-of-tree package installs, appears in the registry, runs on a job, and produces
a precision/recall number from the existing harness.

---

## Phase G — Not scheduled, listed so the decision is explicit

The audit's remaining §3 items. Each is defensible; none is committed to here, and none should start
before F lands.

| Item | Audit ref | Why it waits |
|---|---|---|
| SSE streaming, replacing polling | §3.2.1 | The polling path is already well optimized (`/api/jobs/active`, merged updates, one final read). The win is *first suggestion in seconds on a 40-minute file*, which is real — but it is an architecture change to a path that currently works, and it should follow the features, not precede them. |
| OpenTelemetry + cost ledger | §3.2.3 | Cheap and reads as production experience, but it is the substrate for a paid tier that does not exist. Do it when there is a second operator. |
| EDL / FCPXML / CSV export | §3.1 | The cheapest of the three and the interop wedge. Strong candidate to pull forward into a spare session — the accepted-edit list is already the exact data an EDL needs. |
| Speaker diarization | §3.1 | Large. A model dependency, a schema change, and a new UI dimension. |
| Batch / multi-file | §3.1 | The durable queue makes it tractable; the UI is the work. |
| User-authored presets in the UI | §3.1 | Blocked on Phase F in spirit — a preset editor and a detector registry answer the same question and should share a design. |

Still explicitly **not** doing, per audit §5.3: no `FUNDING.yml`, no support SLA, and no weakening of
the unauthenticated-by-default local-first design.

---

## Session ledger

| # | Phase | Scope | Done when |
|---|---|---|---|
| ~~1~~ | ~~A~~ | **Done 2026-09-05.** `uv` locks, Dockerfile, CI drift guard, CONTRIBUTING, `tests/test_dependency_locks.py` | ✅ Re-compile byte-identical; 755 tests and both evals green on a fresh lock install; detector eval still 1.00 / 0.92 |
| ~~2~~ | ~~B~~ | **Done 2026-09-05.** `pyproject.toml`, ruff + format sweep at 88, CI steps | ✅ `ruff check` and `format --check` green in CI; 5 real defects fixed on the way |
| ~~3~~ | ~~B~~ | **Done 2026-09-05.** mypy over `app/analysis/`, coverage floor 83 (measured 85). Pre-commit skipped | ✅ Backend gate is format → lint → types → cov; widening mypy is blocked on the SQLAlchemy `Mapped[...]` migration |
| ~~4~~ | ~~C~~ | **Done 2026-09-10.** `mock_provider.py`, `providers.py`/`preflight.py` wiring, `.env.example`, README | ✅ Verified on the host with no keys: demo clip completed, 7 `Mock:` suggestions on word timings, accepted and exported (74.00s → 47.10s) |
| ~~5~~ | ~~C~~ | **Done 2026-09-10.** `.devcontainer/`, `Makefile`, dependabot docker entry | ✅ Image builds with the pinned toolchain (Python 3.12.11, Node v22.23.2, npm 10.9.8, ffmpeg 5.1.9); full loop verified in-container against a clean checkout (18 suggestions, 7 `Mock:`, 74.06s → 47.23s). Actual Codespaces boot not tested |
| 6 | D | README split, `aria-live`, jsx-a11y, CLI help | README ≤ ~130 lines, all links live |
| 7 | E | Transcript editing — backend | Route creates accepted edits, invalidates export |
| 8 | E | Transcript editing — frontend + keyboard | Delete a word, see the region |
| 9 | E | Integration, `AGENTS.md` | Export omits exactly the deleted words |
| 10 | F | `Detector` protocol, registry, refactor | Eval still 1.00 / 0.92 |
| 11 | F | `--detector` eval mode, example plugin, docs | Out-of-tree detector scores |

Sessions 1–6 are hygiene and can be reordered freely. 7–9 and 10–11 are each a unit; do not leave
either half-done across a long gap.

---

## Standing obligations for every session

1. **`AGENTS.md`, in the same commit as the change.** One file now, so there is no mirror to drift.
   Keep it that way: `CLAUDE.md` is a one-line `@AGENTS.md` import and must not accrue architecture
   of its own, and no new per-tool copy should be introduced. `docs/ARCHITECTURE.md` is a map, not a
   mirror — depth may differ, facts may not.
2. **`CHANGELOG.md` gets an entry.** It exists now and is seeded at v0.1.0; an empty changelog after
   eleven sessions is worse than none.
3. **The eval numbers are load-bearing.** `1.00 / 0.92` is hardcoded into a README badge and floored
   in CI at 0.95 / 0.85. Any change that moves them updates the badge in the same commit — `ci.yml`
   already says so in a comment.
4. **The design system's four rules are not negotiable** for any frontend work: colour only from
   `globals.css` tokens, `--faint` never renders text, no `opacity` on live text, no suppressed focus
   ring.
5. **Tag as you go.** `v0.1.0` exists and `release.yml` works. A tag at the end of Phase C
   (`v0.2.0` — reproducible, gated, runnable without a key) and at the end of Phase E
   (`v0.3.0` — transcript editing) makes the release automation a habit rather than a thing that ran
   once.

---

*Planned against `main` @ `150c069`, 2026-09-05. Source: `repository-audit-2026-09-03.md` §5.2, §3,
§2. No code changed while writing this.*
