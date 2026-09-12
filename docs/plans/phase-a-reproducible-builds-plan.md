# Phase A — Reproducible builds

> **Status: shipped 2026-09-05.** Three things came out differently from the plan below, all
> recorded in `strategic-next-steps-plan.md` §Phase A:
>
> - **A1's hand-written lock header is impossible.** `uv` rewrites the header on every compile, and
>   `--custom-compile-command` is single-line only — a newline in it emits an *uncommented* line and
>   corrupts the requirements file. uv's default header already records the exact regenerating
>   command, so that stands, and the "do not hand-edit" warning lives in the `.in` headers,
>   `CONTRIBUTING.md`, and `backend/tests/test_dependency_locks.py`.
> - **A4's drift guard survived.** `astral-sh/uv#1530` did not reproduce on uv 0.12.10; re-compiles
>   are byte-identical, so the guard is in CI rather than dropped.
> - **The A5 test became its own module**, `backend/tests/test_dependency_locks.py`, because it
>   spans `ci.yml` and `start.sh` as well as the Dockerfile — `test_docker_layout.py` is the wrong
>   home for an assertion about CI.
>
> None of the three stated risks materialised: hashes resolved cleanly (`onnxruntime`,
> `ctranslate2` included), `anthropic>=1.0.0` resolves to 1.4.0, and the 3.10 lower bound held.

## Context

`backend/requirements.txt` is nine `>=` floors and nothing else. `backend/Dockerfile` installs
straight from it, CI installs from `requirements-dev.txt`, and `start.sh` installs from
`requirements.txt`. Every one of those resolves against PyPI-as-of-now, so `docker compose up
--build` in three months is a materially different application than it is today — different FastAPI,
different pydantic, different `faster-whisper`/`ctranslate2`/`onnxruntime`.

That matters more here than in most repos because of what lands downstream. Phase B floors coverage
and adds a mypy gate; Phase C promises a stranger can boot the thing. A quality gate over a
dependency set that floats is a floor over a moving target, and the eval's `1.00 / 0.92` — hardcoded
into a README badge and floored in CI at `0.95 / 0.85` — is a claim about a specific resolution of
`faster-whisper` and `numpy`, not about the source tree alone.

Outcome: a committed, hashed, fully-pinned resolution that Docker, CI and a local `venv` all install
from, that Dependabot can actually regenerate, and that a re-compile reproduces byte-for-byte.

Source: `strategic-next-steps-plan.md` §Phase A (A1–A3), `repository-audit-2026-09-03.md` §5.2.1.
Two deliberate deviations from that spec are recorded under **Decisions** below.

---

## Decisions

### D1. Naming: `.in` is the declaration, `.txt` is the lock

The written plan said `requirements.txt` (floors) + `requirements.lock` (compiled). That breaks
Dependabot. `dependabot-core`'s `python/lib/dependabot/python/pip_compile_file_matcher.rb` only
treats a file as a pip-compile lockfile when it **ends in `.txt`** and either its header matches
`--output-file[=\s]+<name>` or a sibling `<name>.in` manifest exists. A `.lock` file matches neither
test, so Dependabot would fall back to parsing `requirements.txt` as a plain floors file, open PRs
bumping floors nothing installs, and never touch the lock — green automation that changes nothing,
which is the exact failure A2 of the written plan warns about.

So:

```
backend/
  requirements.in         declaration — the >= floors and their comments
  requirements.txt        GENERATED — the resolution, pinned + hashed
  requirements-dev.in     "-r requirements.in" + pytest, httpx
  requirements-dev.txt    GENERATED
```

Side benefit: `Dockerfile`, `ci.yml`, `start.sh`, `README.md`, `AGENTS.md` and `CONTRIBUTING.md`
keep naming `requirements.txt` and silently begin installing the lock. Only the Dockerfile changes,
and only to add `--require-hashes`.

The comments in today's `requirements.txt` are real decisions (the both-providers-installed note, the
`faster-whisper`-brings-Silero note) and move to `requirements.in` **verbatim**. They must not be
lost into a generated file.

### D2. Universal resolution, lower bound 3.10

One lock has to install on macOS-arm64 dev, `ubuntu-latest` CI, and `python:3.12-slim`. A host
resolution on darwin does not install on linux. `--universal` emits environment markers instead,
producing one plain-pip-installable file valid on every platform, and treats `--python-version` as a
*lower bound* rather than an exact version.

`README.md` and `CONTRIBUTING.md` claim Python 3.10+ while CI and the image are 3.12. Keeping the
claim honest means locking at 3.10; universal resolution absorbs the cost as marker-split entries
(numpy 2.3 dropped 3.10, so expect both a `< '3.11'` and a `>= '3.11'` line). No doc change needed.

### D3. Delete `backend/app/analysis/requirements.txt`

Unreferenced, 4 lines, contradicts the real declaration (`faster-whisper>=1.0.0` vs `>=0.10.0`),
lists `pydub` which is not a dependency, and ships into the image via `COPY app/ ./app/`. Once
`requirements.txt` means "the lock", a second unlocked contradictory one inside the package is the
file someone eventually installs by accident.

---

## Steps

### A0. Pin the toolchain

Local `uv` is **0.7.8** (May 2025) — old. Upgrade it first, record the exact version, and use that
same version in CI's `astral-sh/setup-uv`. The drift guard (A4) compares a locally-compiled file
against a CI-compiled one; two uv versions that format headers or resolve differently make it fail
spuriously. One version string, named in `CONTRIBUTING.md` and in `ci.yml`.

### A1. Split declaration from resolution

- `git mv backend/requirements.txt backend/requirements.in` — content unchanged, comments intact.
- `git mv backend/requirements-dev.txt backend/requirements-dev.in`; change its first line to
  `-r requirements.in`.
- `git rm backend/app/analysis/requirements.txt` (D3).
- Compile, from `backend/`:

```bash
uv pip compile requirements.in \
  --universal --python-version 3.10 --generate-hashes \
  -o requirements.txt

uv pip compile requirements-dev.in \
  --universal --python-version 3.10 --generate-hashes \
  -o requirements-dev.txt
```

  Use `--output-file` rather than `-o` if the emitted header should satisfy Dependabot's *header*
  test as well as its `.in`-sibling test; the sibling test alone is sufficient, so this is
  belt-and-braces.

- Prepend a hand-written header comment to each generated file, above uv's own: what generated it,
  which command regenerates it, that it must not be hand-edited, and that `.in` is where a
  dependency is added. A generated file with no explanation invites a hand-edit.

### A2. Point the consumers at the lock

| File | Change |
|---|---|
| `backend/Dockerfile` | `pip install --no-cache-dir --require-hashes -r requirements.txt`. Add `pip install --upgrade pip` before it. `--require-hashes` is the entire point of `--generate-hashes`; without it the hashes are decoration. |
| `backend/.dockerignore` | The existing `requirements-dev.txt` exclusion stays correct (that name is now the dev lock). Add `requirements.in` and `requirements-dev.in` alongside it. |
| `.github/workflows/ci.yml` | Install step becomes `pip install --require-hashes -r requirements-dev.txt`. `cache-dependency-path` already points at `backend/requirements-dev.txt` and now points at a real lock — **no edit needed**, which is the payoff of D1. |
| `start.sh` (line 30) | `pip install -q --require-hashes -r requirements.txt`. |
| `.github/dependabot.yml` | Rewrite the stale header note (lines 10–12) which says a lock does not exist. Record that the pip entry at `/backend` now drives Dependabot's pip-compile path, and *why* the files are named the way they are (D1) so nobody renames them back. |

`docker-compose.yml`, `release.yml` and `backend/pytest.ini` need no change — Compose inherits the
Dockerfile, release only builds images, pytest touches none of this.

### A3. Document the regeneration ritual

New short section in `CONTRIBUTING.md`, and the install line in its Setup block stays literally
correct (it already says `requirements-dev.txt`). Content: adding a dependency means adding the
floor to the `.in` **and** re-compiling both locks in the same commit, with the pinned `uv` version.
`AGENTS.md`'s Commands block gains the same, plus a Conventions bullet stating the `.in`/`.txt`
split and the Dependabot reason behind it.

### A4. Drift guard in CI

A step before the install: `astral-sh/setup-uv` at the pinned version, re-compile both files, then
`git diff --exit-code -- backend/requirements.txt backend/requirements-dev.txt`. uv, like pip-tools,
prefers versions already present in the output file, so a re-compile is stable without `--upgrade`.

**Treat this as best-effort.** `astral-sh/uv#1530` reports hashes being rewritten without
`--upgrade`. If the guard proves flaky, delete it and keep the `CONTRIBUTING.md` note, which carries
most of the value. Do not spend the session fighting it.

### A5. Pin the invariants in a test

`backend/tests/test_docker_layout.py` already pins Dockerfile-adjacent layout by parsing files as
text (`test_backend_dockerignore_excludes_media_and_venv`), and `test_export_dir_owner.py` sets the
precedent for pinning a single-owner rule. Add, in the house style:

- `backend/Dockerfile` installs with `--require-hashes -r requirements.txt`.
- `requirements.in` and `requirements-dev.in` exist; `requirements-dev.in` starts `-r requirements.in`.
- Both `.txt` files carry the generated-file header and contain **no** `>=` line and **no** line
  lacking a `--hash=`. That is what catches a hand-edit.
- `backend/app/analysis/requirements.txt` does not exist.

---

## Risks

**Hashes fight the resolve.** `faster-whisper` pulls `onnxruntime`/`ctranslate2`; a package with no
wheel for a marker combination can break `--generate-hashes`. `--universal` makes this *less* likely
than the plan assumed (hashes are emitted for every platform wheel rather than only the host's), but
if it does bite: drop `--generate-hashes` and `--require-hashes`, keep the pinned lock, and say in
the lock header **why** hashes are absent so nobody "fixes" it back. Pinning is 90% of the benefit.
Loosen the A5 hash assertion in the same commit if so.

**`anthropic>=1.0.0` may not resolve.** Flagged during exploration as a floor worth checking against
what is actually on PyPI. If it fails, correct the floor in `requirements.in` and note it.

**3.10 lower bound rejects a modern pin.** If a direct dependency has dropped 3.10 entirely and
universal resolution cannot satisfy both ends, fall back to `--python-version 3.12` and narrow the
"Python 3.10+" claim in `README.md` and `CONTRIBUTING.md` in the same commit — do not leave the docs
claiming support the lock cannot deliver.

---

## Verification

1. `cd backend && uv pip compile requirements.in --universal --python-version 3.10 --generate-hashes -o requirements.txt`
   then `git diff --exit-code backend/requirements.txt` → empty. Same for dev.
2. Fresh venv on this machine: `pip install --require-hashes -r requirements-dev.txt`, then `pytest`
   green, then both eval commands from `CONTRIBUTING.md`'s "Running what CI runs" — the detector eval
   must still print **1.00 / 0.92**. If it moves, the resolution changed a detector's behaviour and
   the README badge changes in the same commit (standing obligation 3).
3. `docker compose build --no-cache backend` twice; `docker run --rm <img> pip freeze` diffed between
   the two → identical. This is the acceptance criterion from the written plan.
4. `docker compose up --build`, upload the demo clip, confirm the full
   transcribe → analyze → review → export loop.
5. `pytest backend/tests/test_docker_layout.py` — the new assertions.
6. CI green on the branch, including the drift guard if it survived A4.

## Standing obligations for this session

- `AGENTS.md` in the same commit (A3). `CLAUDE.md` stays a one-line `@AGENTS.md` import.
- `CHANGELOG.md` gets an entry.
- Mark the item done in `repository-audit-2026-09-03.md` (line 62 FAIL row, line 319 remediation),
  `quick-wins-implementation-plan.md` (lines 145–146, 236), and
  `strategic-next-steps-plan.md` (§0 open list, Session ledger row 1) — recording D1 and D2 as
  deviations, since the ledger is the record of what actually happened.
- No tag this session; `v0.2.0` is planned for the end of Phase C.
