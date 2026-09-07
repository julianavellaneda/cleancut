# Contributing to CleanCut

Thanks for looking. This is a short guide to getting the thing running and to the handful of
conventions that are load-bearing. [`AGENTS.md`](AGENTS.md) is the full architecture reference —
what every module owns and why it owns it — and it is kept current. Read it before a change that
moves anything structural.

## Setup

Follow the README's [local quickstart](README.md#quickstart-local) (Python 3.10+, Node 20.9+,
FFmpeg) to get the backend and frontend running. One line changes for contributing: install the
dev lock, not the runtime one.

```bash
cd backend
pip install --require-hashes -r requirements-dev.txt   # not requirements.txt
```

`requirements-dev.txt` is compiled from `requirements-dev.in`, which is `-r requirements.in` plus
the test-only dependencies (pytest, ruff, mypy). Installing it pulls in the runtime dependencies
too, so there is nothing to install twice.

The backend dev server binds `127.0.0.1` by default; a bare `npm run dev` for the frontend does
not — see the README's [local quickstart](README.md#quickstart-local) for the flag that matches
`start.sh`, and its [Privacy](README.md#privacy) section for what changes if you set
`CLEANCUT_HOST`.

## Adding a Python dependency

`backend/` keeps the declaration and the resolution in separate files, and only one of them is
hand-edited:

| File | Hand-edited? | What it is |
|---|---|---|
| `requirements.in` | **yes** | What CleanCut depends on, and the oldest version of each that works |
| `requirements.txt` | no | The compiled resolution — every version, pinned, with hashes. This is what installs |
| `requirements-dev.in` | **yes** | `-r requirements.in` plus the test-only dependencies |
| `requirements-dev.txt` | no | Same, compiled |

Add the floor to the `.in`, then re-compile **both** locks in the same commit:

```bash
# uv 0.12.10 — the version .github/workflows/ci.yml pins
cd backend
uv pip compile requirements.in \
  --universal --python-version 3.10 --generate-hashes --output-file requirements.txt
uv pip compile requirements-dev.in \
  --universal --python-version 3.10 --generate-hashes --output-file requirements-dev.txt
```

Use the `uv` version CI uses. A different one can format the lock header differently and fail the
drift check on an otherwise correct commit.

Each flag on those commands is doing a specific job:

- `--universal` is what makes one file serve macOS-arm64 development, `ubuntu-latest` CI, and
  `python:3.12-slim` all at once. It resolves for every platform and emits environment markers
  instead of baking in the machine that ran the compile.
- `--python-version 3.10` is a *lower* bound under `--universal`, not the compiling machine's own
  version. It is 3.10 because that is the floor the README promises.
- A package that dropped 3.10 support appears twice in the lock, each copy behind its own marker.
  That duplication is the mechanism working, not a bug.
- `--generate-hashes` pairs with the `--require-hashes` every consumer installs with. Without both
  flags, the hashes are decoration.

CI re-runs those two compile commands and fails on any diff, so a `.in` edited without a
re-compile cannot merge. The locks' first two lines record the exact command that produced them —
never hand-edit a `.txt`; a re-compile silently overwrites the edit, and
`tests/test_dependency_locks.py` fails it first.

## Running what CI runs

CI is [`.github/workflows/ci.yml`](.github/workflows/ci.yml): **11 checks** — 7 backend, 4
frontend — all reproducible locally, none of which need an API key.

```bash
# Backend
cd backend && source .venv/bin/activate

# 1. Lock drift: the recompiled locks match what's committed.
#    Re-run the two compile commands from "Adding a Python dependency" above, then:
git diff --exit-code -- requirements.txt requirements-dev.txt

# 2-4. Formatting, linting, types. Every flag lives in backend/pyproject.toml, so
#      these stay bare commands here and in CI - a flag on the call site would be
#      a second place the behaviour is defined.
ruff format --check app tests conftest.py
ruff check app tests conftest.py
mypy

# 5. Tests plus the coverage floor.
pytest --cov=app --cov-config=pyproject.toml --cov-report=term-missing

# 6. The scorer and the labels, graded against a recorded run. Deterministic:
#    no model, no media, no key.
python -m app.eval.run ../tests/fixtures/demo/seed_job.json

# 7. The detectors as they stand on this commit, against the real clip and the
#    committed word-level transcript. The gate that would catch a scrubber regression.
python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3 \
  --suite scrub --min-precision 0.95 --min-recall 0.85

# Frontend
cd ../frontend
npm run lint        # 8
npx tsc --noEmit     # 9
npm test            # 10
npm run build        # 11
```

CI's actual check 3 is `ruff check --no-fix --output-format=github app tests conftest.py`. Both
flags are about the invocation, not the rule set: `--no-fix` stops CI from silently rewriting
files whose changes you'd never see, and `--output-format=github` turns violations into inline
annotations on the PR diff. Neither changes what gets flagged, so the bare command above catches
the same problems locally.

`python -m app.eval.run --live MEDIA` grades the whole pipeline instead — transcription and the
LLM call included. It is opt-in because it costs money and cannot be deterministic. Run it if you
touched the analyzer; CI will not.

The eval prints its scorecard rather than only passing or failing, so a run that drifts while
still clearing its floors is visible in the build log. If your change moves those numbers, say so
in the PR and say why.

`pytest` on its own is the fast thing and stays that way — the coverage flags are not in
`addopts`, because they roughly double the run and get in a debugger's way. Run the full command
above before pushing; the floor itself lives in `pyproject.toml`, not on the command line.

A note on the two backend tools: `ruff` and `mypy` are pinned in `requirements-dev.txt` like
everything else, so Dependabot will bump them. A ruff release can change what `ruff format`
produces, and a mypy release can find something new. Both are legitimate reasons for a follow-up
commit *inside the bot's PR* — neither is a reason to pin the tools outside the lock, which is
where they would quietly stop being updated at all.

## Conventions

**Backend.** Validation is Pydantic in `schemas.py`; logic lives in `services/`; routing in
`routes/` stays thin. A rule that decides something destructive gets exactly one owner — see how
`exports.py` owns `EXPORT_DIR` and the cut/mute partition, and how `worker._is_pre_accepted` is the
single answer to "may this be applied unreviewed". `tests/test_export_dir_owner.py` enforces the
first of those with an AST pass, which should tell you how seriously it is meant.

`ruff check`, `ruff format --check` and `mypy` all run clean; a suppression needs a comment saying
why, the same rule the frontend has. `backend/pyproject.toml` configures all three and holds no
`[project]` table — it is configuration, not a package manifest, because `conftest.py` at the
backend root is what puts that directory on `sys.path` and lets tests import `app.*` by the path
uvicorn uses. There is no blanket per-file ignore list and there should not be one: that is how a
lint gate becomes decoration. The one place a rule is switched off wholesale is B008 for FastAPI's
`Depends`/`Form`/`File` parameters, because there the rule is wrong — see the comment in that file,
and the `Form(...)` note below.

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
