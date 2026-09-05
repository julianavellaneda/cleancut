# Contributing to CleanCut

Thanks for looking. This is a short guide to getting the thing running and to the handful of
conventions that are load-bearing. [`AGENTS.md`](AGENTS.md) is the full architecture reference —
what every module owns and why it owns it — and it is kept current. Read it before a change that
moves anything structural.

## Setup

CleanCut needs Python 3.10+, Node 18+, and FFmpeg (`brew install ffmpeg`, or your package
manager's equivalent). Configuration is a single `.env` **at the repo root**, not in a
subdirectory — `backend/app/config.py` walks up to find it.

```bash
cp .env.example .env      # then add your model API key

cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt   # the compiled lock
uvicorn app.main:app --reload

cd ../frontend
npm install
npm run dev
```

Or `./start.sh` for both. Both bind `127.0.0.1`; see the README's Privacy section for why that is
the default and what changing it means.

## Adding a Python dependency

`backend/` keeps the declaration and the resolution in separate files, and only one of them is
hand-edited:

| File | Hand-edited? | What it is |
|---|---|---|
| `requirements.in` | **yes** | What CleanCut depends on, and the oldest version of each that works |
| `requirements.txt` | no | The compiled resolution — every version, pinned, with hashes. This is what installs |
| `requirements-dev.in` | **yes** | `-r requirements.in` plus the test-only dependencies |
| `requirements-dev.txt` | no | Same, compiled |

Add the floor to the `.in`, then re-compile **both** locks in the same commit. `uv` is pinned to the
version CI uses; a different one can format the header differently and fail the drift check on an
otherwise correct commit.

```bash
# uv 0.12.10 — the version .github/workflows/ci.yml pins
cd backend
uv pip compile requirements.in \
  --universal --python-version 3.10 --generate-hashes --output-file requirements.txt
uv pip compile requirements-dev.in \
  --universal --python-version 3.10 --generate-hashes --output-file requirements-dev.txt
```

`--universal` is what makes one file serve macOS-arm64 development, `ubuntu-latest` CI and
`python:3.12-slim` at once: it resolves for every platform and emits environment markers instead of
baking in the machine that ran the compile. `--python-version 3.10` is a *lower* bound under
`--universal`, and it is 3.10 because that is the version the README promises — expect packages that
dropped it to appear twice with markers, which is the mechanism working. `--generate-hashes` pairs
with the `--require-hashes` every consumer installs with; without both, the hashes are decoration.

CI re-runs those two commands and fails on any diff, so a `.in` edited without a re-compile cannot
merge. The locks' first two lines record the exact command that produced them — never hand-edit a
`.txt`; a re-compile silently overwrites the edit, and `tests/test_dependency_locks.py` fails it
first.

## Running what CI runs

CI is `.github/workflows/ci.yml`. Five checks, all reproducible locally, none of which need an API
key:

```bash
# Backend
cd backend && source .venv/bin/activate

# The locks match their .in files. Re-run the two compile commands from
# "Adding a Python dependency" above, then:
git diff --exit-code -- requirements.txt requirements-dev.txt

pytest

# The scorer and the labels, graded against a recorded run. Deterministic:
# no model, no media, no key.
python -m app.eval.run ../tests/fixtures/demo/seed_job.json

# The detectors as they stand on your commit, against the real clip and the
# committed word-level transcript. This is the gate that would catch a
# scrubber regression.
python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3 \
  --suite scrub --min-precision 0.95 --min-recall 0.85

# Frontend
cd ../frontend
npm run lint && npx tsc --noEmit && npm test && npm run build
```

`python -m app.eval.run --live MEDIA` grades the whole pipeline instead, transcription and LLM call
included. It is opt-in because it costs money and cannot be deterministic — run it if you touched
the analyzer, but CI will not.

The eval prints its scorecard rather than only passing or failing, so a run that drifts while still
clearing its floors is visible in the build log. If your change moves those numbers, say so in the
PR and say why.

## Conventions

**Backend.** Validation is Pydantic in `schemas.py`; logic lives in `services/`; routing in
`routes/` stays thin. A rule that decides something destructive gets exactly one owner — see how
`exports.py` owns `EXPORT_DIR` and the cut/mute partition, and how `worker._is_pre_accepted` is the
single answer to "may this be applied unreviewed". `tests/test_export_dir_owner.py` enforces the
first of those with an AST pass, which should tell you how seriously it is meant.

**Database.** A new column goes in `database._apply_migrations()` — a hand-rolled additive
migration run at every startup — with a case in `backend/tests/test_migrations.py`. A new *table*
needs no entry there; `init_db`'s `create_all` picks it up.

**Frontend.** Functional components, Tailwind v4, strictly typed API calls. Tests live next to what
they test (`Foo.test.tsx`) and run under vitest in jsdom. `eslint` runs clean; a suppression needs a
comment saying why.

Memoization is a decision, not a dependency-array reflex. `useCallback` is for callbacks that close
over nothing reactive; anything reading component state stays un-memoized, and a callback that must
stay current inside a long-lived effect goes through a ref. `AGENTS.md` has the bullet, with the
three places in this codebase where getting it wrong caused a real bug.

**Fixtures must be synthetic.** Never commit a real recording, a real transcript, or anything
identifying a real person. `tests/fixtures/demo/` is a generated two-speaker clip precisely so this
project never has to hold anyone's audio.

**Docs.** If you change the architecture, update [`AGENTS.md`](AGENTS.md). It is the single source
of truth, in the [agents.md](https://agents.md) format that Codex, Cursor, Copilot, Gemini CLI, Aider
and others read natively; the root `CLAUDE.md` is a one-line `@AGENTS.md` import, so there is one
file to edit and nothing to keep in sync. It used to be two — a hand-maintained `GEMINI.md` mirror,
which drifted far enough to state the opposite of the truth about admin auth. Do not reintroduce a
per-tool copy.

## Commits and pull requests

Look at `git log` before writing one. Subjects here name the symptom rather than the patch — "every
queued job vanished when the process did" — and bodies explain the reasoning, not the diff. No
conventional-commit prefixes.

Small PRs. If a change needs a paragraph of justification, put the paragraph in the commit message
where it will still be there in two years.

Add an entry under `## [Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md) for anything a user would
notice — a new capability, a changed default, a fixed failure. Not every commit needs one; a
refactor nobody can observe does not. A changelog nobody is asked to update stops after one
release.

## Reporting a security issue

Not through an issue — see [SECURITY.md](SECURITY.md). Note especially that CleanCut's
unauthenticated routes are a documented design decision, not an oversight.
