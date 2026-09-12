# Phase C — Runnable by a stranger

> **As built (2026-09-10).** This plan held; a few things surfaced only once the code and the image
> were actually built, beyond the four deviations from the strategic plan already recorded below:
>
> - The devcontainer's Python base image ships a Yarn apt source whose signing key has since
>   rotated, which fails `apt-get update` outright before `ffmpeg` can even be requested. Not
>   anticipated here at all; the Dockerfile removes that source file rather than re-keying it, since
>   nothing in this repo uses Yarn.
> - The Makefile's `lock` target passes `--quiet` to `uv pip compile`, not specified in the
>   Decisions below — without it, `make lock`'s two invocations print uv's full resolution output,
>   which is noise for a command whose only interesting outcome is a diff.
> - `test_makefile.py` is its own file rather than an addition to `test_dependency_locks.py`,
>   despite pinning a fact about that same lock (the `uv` version agreement with `ci.yml`) — the
>   Makefile is a big enough surface (help text, target list, the no-floors rule) to earn its own
>   test module rather than being folded into one already named for something narrower.
>
> The in-container acceptance run (Verification item 6) passed against a clean checkout; see
> `strategic-next-steps-plan.md`'s Phase C "As built" block for the numbers. It also surfaced a
> `post-create.sh` fix: the Hugging Face volume mount creates `~/.cache` itself as root, which a
> `chown -R` scoped to `~/.cache/huggingface` alone left root-owned, silently disabling pip's cache.
> `post-create.sh` now `chown`s `~/.cache` itself too, non-recursively.

## Context

Today the eval and the test suite run with no API key — a genuinely rare property for an
LLM-backed tool. The *app* does not: `_PROVIDERS` in `analysis/providers.py` only knows `openai`
and `anthropic`, and `get_provider` hard-fails on a missing key. A reviewer who clones the repo,
has no key, and has no Docker cannot see the product work at all. That gap is the highest-leverage
remaining packaging item (`strategic-next-steps-plan.md` §2.1, §5.2.3, Phase C), and it gates
everything after it: Phase D's README rewrite and Phase E's transcript editing both assume a
reader can get the app running to look at what changed.

Three pieces close it: a keyless mock provider so the pipeline runs without a key, a devcontainer
so it runs without a host toolchain either, and a `Makefile` so the ~9 commands spread across two
directories collapse into one place a stranger reads first.

### Verified in the code before writing this plan (2026-09-10, branch `phase-c-runnable`)

- `PROVIDER_API_KEYS = {"openai": ..., "anthropic": ...}` in `providers.py`; `parse_model_spec`
  rejects any provider outside that dict before `get_provider` ever looks up a key, and
  `preflight.missing_requirements` re-parses the spec and demands `spec.api_key_name`
  unconditionally. A naive `CLEANCUT_MODEL=mock:demo` fails **twice** today, not zero times — the
  strategic plan's "verify rather than assume" turns out to require a real change in both files.
- `PromptAnalyzer` wraps each chunk as `[12.3s - 15.0s] segment text` lines inside
  `<transcript>…</transcript>`. Prompt mode's contract is `text, approximate_time, label, action,
  reasoning`; preset mode's is `text, approximate_time, rule_violated, severity, reasoning`.
  `_map_to_timestamps` places a quote by substring match against segment text, then word timings —
  so a mock quoting a real sentence verbatim lands exactly, not approximately.
- mypy runs `--strict` over `app/analysis/` only; `mock_provider.py` lives there and is held to the
  same bar as `providers.py` — no loosening for being a stub.
- `start.sh` exits if there is no root `.env`, so `post-create.sh` must write one rather than rely
  on `start.sh` tolerating its absence.
- GNU make on macOS is 3.81 — no `.ONESHELL` — so the Makefile targets that floor.
- Whisper (`faster-whisper`, "medium", ~1.5 GB) downloads from Hugging Face on the first job. The
  mock removes the API-key requirement, not the network requirement for that download — the
  devcontainer's Hugging Face cache volume (C2) speeds up a *second* boot, not the first.
- The demo clip contains an income claim ("$11,400"), lifestyle claims ("quit my job", "sports
  car", "Paid for in cash"), health claims ("migraines just disappeared", "cleared them up"), a
  spoken email ("grow.spark at lumenrise-living.com"), and a CONTROL line — "some people try this
  and earn nothing at all" — that must never fire. The rule table is built against this clip and
  deliberately excludes "earn", since the control line contains it.

## Deviations from the strategic plan

The strategic plan sketches C1–C3 at a level a lead engineer's read of the code then had to correct
in four places:

1. **The mock provider is a new module, not an addition to `providers.py`.** The strategic plan
   says "Add `MockProvider` to `analysis/providers.py`". Decision: `mock_provider.py`, imported by
   `providers.py`, with no third-party imports of its own. `providers.py` stays the router; a
   keyword matcher with a rule table is a different kind of code from the two provider adapters and
   earns its own file rather than bloating the module mypy already treats as load-bearing.
2. **Preflight needs a real change, not a check.** The strategic plan's "verify rather than assume"
   implies the existing check might already be correct. It is not — see "Verified in the code"
   above. Both `parse_model_spec` and `preflight.missing_requirements` gain an explicit keyless
   branch.
3. **The devcontainer is two stages, both pinned by digest, plus a new Dependabot ecosystem
   entry.** The strategic plan says "pin the base image by digest" (singular). Decision: Node is
   copied out of an official `node:22-bookworm-slim` image into the
   `mcr.microsoft.com/devcontainers/python:1-3.12-bookworm` stage rather than installed via a
   devcontainer "feature" — features float on a major tag, exactly what Phase A fixed for Python
   dependencies. Two FROM lines means two digests, so `.github/dependabot.yml` gains a `docker`
   ecosystem entry for `/.devcontainer`; a pin nobody ever bumps is its own kind of failure.
4. **The Makefile gains `help` (default) and `install`, beyond the strategic plan's seven named
   targets.** `help` so an unfamiliar Makefile says what it does before anything runs; `install`
   because `dev` assumes the venv and `node_modules` already exist, and a bare checkout has
   neither.

None of these change what Phase C is *for*; they change how C1 and C2 are built.

## Decisions

### C1 — Mock provider

`backend/app/analysis/mock_provider.py` defines `MockProvider` and registers it in `_PROVIDERS` as
`"mock"`, reached via `CLEANCUT_MODEL=mock:demo` (the model half of the spec is accepted but
unused — there is only one mock).

**Keyless, explicitly.** A `KEYLESS_PROVIDERS = frozenset({"mock"})` sits next to
`PROVIDER_API_KEYS`. `parse_model_spec` accepts a provider from either set, and
`ModelSpec.api_key_name` becomes `str | None`. `get_provider` and `preflight.missing_requirements`
each grow an explicit `if spec.api_key_name is None:` branch with a comment — not an empty-string
sentinel threaded through the key lookup, which would make "no key needed" and "key configured as
empty" the same code path.

**Real output, real parser.** `MockProvider.complete` returns raw JSON text, exactly like the
OpenAI and Anthropic adapters; `_parse_llm_response` and `_validate_entries` are untouched. If the
mock's output needed a parser exception to pass, the mock would be wrong. A test pushes real mock
output through the real parser to prove this.

**Deterministic and transcript-derived, not canned.** A fixed list of findings would flag a
recording that doesn't contain them — worse than nothing for a demo, since it teaches a reviewer to
distrust the tool the first time they try a different clip. Instead `MockProvider` parses the
fenced `[start - end] text` lines out of the wrapped transcript, splits each segment into
sentences, and runs them against a small ordered rule table: Income Claim (dollar figures),
Lifestyle Claim ("quit my job" / "sports car" / "paid for in cash" / "retire early" / "luxury"),
Health Claim ("cure(d)" / "disappeared" / "cleared them up" / "healed"), and Contact Details
(email-shaped or spoken "x at y.com", phone-number shaped — action `mute`). It quotes the whole
matching sentence verbatim, which is what lets `_find_text_timestamps` place it exactly rather than
approximately.

**Picks the JSON contract by reading the prompt, the way a real model has to.** If the system
prompt asks for `"rule_violated"`, the mock answers the preset contract (rule_violated + severity,
falling back to the preset's `default_action`); otherwise it answers the prompt contract (label +
action). A test builds both real system prompts from `prompt_analyzer.py` rather than hardcoding
copies, so drift in the real prompts breaks the test instead of silently breaking the mock.

**Impossible to mistake for real analysis, three separate ways** — because a demo that quietly
looks like a genuine compliance pass is a liability for this specific market: every label /
`rule_violated` is prefixed `Mock: `, visible on the violation list, the waveform tooltip and the
card, not buried in a detail panel nobody opens; every `reasoning` starts `MOCK PROVIDER —` and
says outright that no model read the transcript; and the backend prints the configured analysis
model at startup, with a loud warning when it resolves to the mock, via a `model_notice()` helper
in `preflight.py` called from the lifespan — the same pattern `network.exposure_warning` already
uses for a non-loopback host.

**No fence, no silent pass.** If the user prompt has no `<transcript>` fence, `MockProvider` raises
`ProviderError` rather than returning `{"violations": []}` — an empty result is indistinguishable
from a clean recording everywhere downstream, the exact failure `DATA_NOT_INSTRUCTIONS` exists to
defend against.

**The mock ignores the user's instruction.** It is a keyword matcher, not a model reading the
prompt, and its `reasoning` says so. A job-level warning banner was considered and rejected: it
would require the worker to know which provider ran, threading provenance through a layer that has
none today. The label prefix gives the same visibility from inside the provider instead.

**Docs and tests.** `.env.example` gains a commented `CLEANCUT_MODEL=mock:demo` line. New
`backend/tests/test_mock_provider.py` covers: no key required, output survives the real parser,
both JSON contracts, demo-transcript quotes land aligned rather than approximate, the control line
is never flagged, a missing fence raises rather than returning empty, and output is deterministic
across two runs on the same input. `test_providers.py` and `test_preflight.py` each get the keyless
branch covered.

### C2 — Devcontainer

`.devcontainer/Dockerfile` is two stages, both FROM lines pinned by `@sha256` digest:
`node:22-bookworm-slim` (used only to copy the Node binary and npm out) and
`mcr.microsoft.com/devcontainers/python:1-3.12-bookworm` (Python 3.12, the `vscode` user), plus
`apt-get install ffmpeg`. Node comes from an official image rather than a devcontainer "feature"
because features are pinned by major tag and float — exactly the problem Phase A fixed for the
backend's own dependencies, and there is no reason to reintroduce it one layer up. Both stages use
the same Debian release so the copied Node binary's glibc matches what it runs against.

`.github/dependabot.yml` gains a `docker` ecosystem entry for `/.devcontainer`, so the two digests
get bumped by PR instead of going stale silently — a pin nobody ever moves is its own failure mode,
the same argument that justified the drift guard in Phase A.

`devcontainer.json` mounts named volumes over `backend/.venv`, `frontend/node_modules`, and the
Hugging Face cache. The first two exist because a local "Reopen in Container" bind-mounts a
checkout that already has macOS-built binaries sitting in exactly those paths — the same trap
`AGENTS.md` already documents for the frontend's own Docker build, one layer further out. The third
exists so the ~1.5 GB Whisper model survives a container rebuild instead of re-downloading every
time. All three paths stay where `start.sh` and the Makefile already expect them, so neither needs
a container-specific branch. `forwardPorts` covers 3000 and 8000; the default loopback
`CLEANCUT_HOST` keeps working unmodified because VS Code and Codespaces forward from inside the
container, not from a host bind.

`.devcontainer/post-create.sh` runs once: `chown` the volume mounts (they arrive root-owned),
create the venv, `pip install --require-hashes -r requirements-dev.txt`, `npm ci`, and — only if no
`.env` exists yet — write one from `.env.example` with `CLEANCUT_MODEL=mock:demo` and no key set.
An existing `.env` is never touched, so a contributor who mounts a real key does not have it
overwritten on a rebuild.

Tests: `backend/tests/test_dependency_locks.py`'s consumer list grows to include
`post-create.sh` and the `Makefile`, since both now install from the locks and belong on the list
that keeps them honest. New `backend/tests/test_devcontainer.py` pins the digest-pinned FROM lines,
the three volume mounts, and the Dependabot entry.

### C3 — Makefile

Targets: `help` (default, lists the rest), `install`, `dev` (→ `./start.sh`), `test` (fast pytest +
`npm test`), `lint` (`ruff format --check`, `ruff check`, `mypy`, `npm run lint`, `tsc --noEmit`),
`eval` (the two free evals), `eval-live`, `lock`, `docker` (→ `docker compose up --build`). Written
for GNU make 3.81, so no `.ONESHELL` and no newer-make syntax.

Thin wrappers only. Tool flags stay in `backend/pyproject.toml`; `eval` prints the scorecards
without CI's `--min-*` floors, which stay defined only in `ci.yml`. The Makefile must not become a
second place CI's behavior is defined — that duplication is exactly the failure mode `AGENTS.md`
already calls out for the `.in`/`.txt` split and for `EXPORT_DIR`. `CONTRIBUTING.md` keeps its
explicit command list alongside the Makefile, since that file's whole value is that it mirrors CI
literally; the Makefile is the short path for someone who wants a job running, not the record of
what CI actually runs.

`lock` runs the exact uv version CI pins (0.12.10) through `uvx`, rather than whatever `uv` happens
to be on the contributor's PATH — a mismatched uv version formats the lock header differently and
fails the drift check for a reason that has nothing to do with the dependency change being made. A
test asserts the Makefile's pinned version equals `ci.yml`'s, so the two cannot drift apart
silently.

## Steps

Files touched, in build order — the reasoning for each is in Decisions above, not repeated here.

**C1**: `providers.py` (`KEYLESS_PROVIDERS`, `str | None` on `api_key_name`, the keyless branches
in `parse_model_spec` and `get_provider`) → new `mock_provider.py` → register `"mock"` in
`_PROVIDERS` → `preflight.py` (keyless branch in `missing_requirements`, new `model_notice()`
called from the lifespan) → `.env.example` → new `test_mock_provider.py`, plus additions to
`test_providers.py` and `test_preflight.py`.

**C2**: `.devcontainer/Dockerfile`, `.devcontainer/devcontainer.json`, `.devcontainer/post-create.sh`
→ `.github/dependabot.yml` (`docker` ecosystem entry) → new `test_devcontainer.py`, plus the
`test_dependency_locks.py` consumer-list addition.

**C3**: root `Makefile` (nine targets) → a backend test asserting its `lock` target's uv version
matches `ci.yml`'s.

**Docs, last, same commit as the code (standing obligation 1):** `README.md` ("No API key? Run it
anyway", devcontainer/Codespaces, `make`), `CONTRIBUTING.md` (devcontainer + Makefile, alongside
the explicit commands), `AGENTS.md` (Commands, Environment, a Key Implementation Details paragraph
for the mock provider), `docs/ARCHITECTURE.md` (mock as a third provider entry), `CHANGELOG.md`
(`[Unreleased]`), and `strategic-next-steps-plan.md` marked done in the Phase A/B "as built" style.
Tagging `v0.2.0` after merge is a user action (standing obligation 5), not done in this session.

## Risks

- **The first job still needs network access**, mock or not — Whisper's medium model (~1.5 GB)
  downloads from Hugging Face on first use regardless of which analysis provider is configured. The
  devcontainer's Hugging Face cache volume only helps a *second* container boot; it does not make
  the mock provider's promise ("no API key needed") stretch to "no network needed."
- **Medium Whisper is slow on a 2-core Codespace.** Out of scope for this phase — noted so it isn't
  mistaken for a bug when a Codespaces demo takes noticeably longer than a local run.
- **Dependabot's `docker` ecosystem and a two-stage, dual-digest Dockerfile are a new combination
  in this repo.** Worth a first real PR from Dependabot as a smoke test before trusting the
  automation the way Phase A's pip ecosystem is now trusted.
- **A reviewer skimming quickly might still take mock output at face value.** Mitigated by the
  three independent layers in C1 (label prefix, reasoning prefix, startup warning) rather than any
  single one of them, since any one alone can be scrolled past.

## Verification

1. Backend gate: `ruff format --check`, `ruff check`, `mypy` (scope unchanged — `app/analysis/`
   strict), `pytest --cov=app --cov-config=pyproject.toml --cov-report=term-missing`, floor
   unchanged.
2. Both evals unchanged: `python -m app.eval.run ../tests/fixtures/demo/seed_job.json` and
   `python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3 --suite scrub` still
   print 1.00 / 0.92. Neither touches the mock provider, so this is a regression check, not new
   coverage.
3. Frontend untouched — no `npm test` regressions, no new frontend files.
4. `docker build -f .devcontainer/Dockerfile .` succeeds and the resulting image reports Python
   3.12, Node 22, and a working `ffmpeg` binary.
5. A local end-to-end run with `CLEANCUT_MODEL=mock:demo` and no `OPENAI_API_KEY` /
   `ANTHROPIC_API_KEY` set: upload the demo clip, watch it reach `completed`, and confirm the
   violation list shows `Mock:`-prefixed suggestions landing on the income/lifestyle/health/contact
   spans described above, with the CONTROL line absent.
6. Full acceptance per the strategic plan: a checkout with no `.env`, no API key, and no `ffmpeg` on
   the host runs upload → transcribe → analyze → review → export inside the devcontainer.

## Standing obligations for this session

- `AGENTS.md` in the same commit as the code (Commands, Environment, Key Implementation Details).
  `CLAUDE.md` stays a one-line `@AGENTS.md` import.
- `CHANGELOG.md` gets an `[Unreleased]` entry.
- The eval numbers are load-bearing (1.00 / 0.92, badge + CI floor at 0.95 / 0.85). This phase
  should not move them; if it somehow does, the badge changes in the same commit.
- The design system's four rules apply to any frontend touch this phase makes — none is currently
  planned, since C1–C3 are backend and tooling only.
- Tag `v0.2.0` after merge, per the strategic plan's standing obligation 5 — a user action, done
  outside this session.

---

*Planned against branch `phase-c-runnable`, 2026-09-10. Source:
`strategic-next-steps-plan.md` §Phase C, plus the lead engineer's decisions recorded above after
reading `providers.py`, `preflight.py`, `prompt_analyzer.py`, `start.sh`, and the demo fixtures. No
code changed while writing this.*
