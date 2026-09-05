# CleanCut — Repository Audit

**Date:** 2026-09-03
**Branch audited:** `organic-design-system` (67 commits, clean tree)
**Perspective:** hiring manager · future contributor · enterprise buyer

---

## 0. What this repo is

**CleanCut** — a local-first, prompt-driven audio/video editor. Upload a recording, describe in
plain English what to find ("cut every filler word", "flag income claims"), and it transcribes with
word-level timestamps (`faster-whisper`), asks an LLM (OpenAI or Anthropic, router-selected), maps
quoted text back to timestamps, lets you review each suggestion on a waveform, and renders accepted
edits through a single FFmpeg filter graph.

| | |
|---|---|
| **Backend** | FastAPI, SQLAlchemy/SQLite, threaded durable job queue, FFmpeg |
| **Frontend** | Next.js 16, React 19, Tailwind v4, wavesurfer.js |
| **Analysis** | faster-whisper (int8), chunked sliding-window LLM analysis, deterministic scrubber |
| **Scale** | ~7.6k LoC backend · ~7.4k LoC frontend · 37 backend test modules / 585 test functions · 15 frontend test files · 209 tracked files |
| **Audience** | Compliance reviewers and podcast/course editors (presets are FTC income-claim and PII-redaction shaped), plus devs wanting a private "describe the edit" tool |

### Headline verdict

This is in the top ~2% of portfolio repos. The engineering *substance* is genuinely senior — a
durable queue with replay caps, export staleness revisioning, fail-closed admin auth,
prompt-injection defence in depth, a contrast-audit test that parses the CSS token sheet, and an
**eval harness that gates CI on measured detector precision/recall**. That last one alone puts it
above most ML-adjacent side projects.

The gaps are almost entirely in the *packaging and automation shell*, not the code. Fixing them is
a weekend.

---

## 1. Resume Signal & Engineering Professionalism

### 1.1 First-impression friction

| Check | Status | Note |
|---|---|---|
| Value communicated in <5s | PASS | Three-clause hook, "Copilot, not autopilot" positioning |
| Screenshots | PASS | Four, well-captioned, with real alt text |
| **Animated demo (GIF/video)** | **FAIL** | **Biggest single gap.** Five recorded `.mp4` scenes sit in `docs/demo/captures/` with a narration script, and not one is in the README |
| **Badges** | **FAIL** | Zero. `grep -c badge README.md` → 0 |
| Architecture diagram | WEAK | ASCII one-liner only; no image |
| 1-line quickstart | PASS | `cp .env.example .env && docker compose up --build` |
| README length | WEAK | 396 lines — a manual, not a pitch |

### 1.2 Production rigor

| Check | Status | Note |
|---|---|---|
| CI on push + PR | PASS | `ci.yml`, two jobs, concurrency-cancel, cached deps, commented like prose |
| Backend tests in CI | PASS | pytest, 585 test functions |
| **Eval gate in CI** | **STRONG** | Enforces `--min-precision 0.95 --min-recall 0.85` against real audio. Deterministic, no API key, runs every push. Genuinely differentiated |
| Frontend type-check + vitest + prod build | PASS | `tsc --noEmit` run separately from `next build` on purpose |
| **ESLint in CI** | **FAIL** | `npm run lint` exists in `package.json`; `ci.yml` never calls it. `CLAUDE.md` asserts "eslint runs clean" — unenforced |
| **Python lint / format / type-check** | **FAIL** | No ruff, no black, no mypy, no config of any kind |
| ~~**Backend dependency pinning**~~ | ~~**FAIL**~~ → **PASS** (2026-09-05) | ~~`requirements.txt` is all `>=` floors, no lockfile.~~ Resolved in Phase A: `requirements.in` declares, `requirements.txt` is a `uv pip compile --universal --generate-hashes` lock, and every consumer installs it with `--require-hashes`. CI re-compiles and fails on drift |
| **Dependabot / Renovate** | **FAIL** | Missing. You already ate a "pinned to a Next.js with 28 advisories" incident (commit `0d0343c`) — this is the automation that prevents the sequel |
| Pre-commit hooks | FAIL | Missing |
| Automated releases | WEAK | `release.yml` publishes both GHCR images on `v*` tags — but **zero tags exist**, so it has never run |
| Coverage reporting | FAIL | None. 585 tests and no measured coverage |
| Branch protection hints | FAIL | No signal in repo |

### 1.3 Maintainer hygiene

| File | Status | Note |
|---|---|---|
| `CONTRIBUTING.md` | STRONG | "Running what CI runs" — every check reproducible locally with no API key |
| `SECURITY.md` | **STRONG** | Opens with "what is by design and not a vulnerability," names the threat model, points to private advisory reporting, sets an honest SLA. Better than most funded projects |
| `.github/ISSUE_TEMPLATE/` | PASS | bug_report + feature_request |
| `.github/PULL_REQUEST_TEMPLATE.md` | PASS | |
| `LICENSE` (MIT) | PASS | |
| `.gitignore` | STRONG | `.env.*` wildcard with `!.env.example`, commented with the reasoning. No secrets or `.DS_Store` tracked |
| `CODE_OF_CONDUCT.md` | **MISSING** | |
| `CHANGELOG.md` | **MISSING** | |
| `.github/FUNDING.yml` | MISSING | Correctly so, for now — see §4 |
| `.devcontainer/` | MISSING | |

### 1.4 Three concrete defects to fix before anyone reads this

1. **`README.md:89-90` advertises the wrong GHCR owner.** It says
   `ghcr.io/old-owner/cleancut-backend:v0.1.0`, but `git remote` is
   `julianavellaneda/ai-audio-editing` and `release.yml` derives the image name from
   `${{ github.repository_owner }}`. Those pull commands will 404. Compounding it: no `v*` tag has
   ever been pushed, so the images do not exist under *either* name.

2. **`docs/ARCHITECTURE.md` is stale and actively contradicts the code.** It is headed "Data Flow
   (**Future State**)", describes a "Python/**Celery**-style" worker, claims
   "`Zustand`/Context for state management of markers" (zustand is not a dependency), and lists
   "**VAD** (Voice Activity Detection) flags silences" — which both `ROADMAP.md` and `CLAUDE.md`
   record as explicitly *rejected*, because VAD makes the same mistake as gap-detection and flags
   room tone, applause and music beds. A reviewer who opens `docs/` first learns the wrong
   architecture from the file named ARCHITECTURE.

3. **`frontend/README.md` is untouched `create-next-app` boilerplate** — "First, run the development
   server: `npm run dev` / `yarn dev` / `pnpm dev` / `bun dev`". Delete it or replace with three
   lines.

Related, lower severity: `GEMINI.md` (201 lines) mirrors `CLAUDE.md` (708 lines) and `CLAUDE.md`
itself records that it has drifted badly enough in the past to state the opposite of the truth about
admin auth. Two hand-maintained copies of one architecture document is a drift generator.

### 1.5 Resume impact bullets (STAR, quantified)

> **Built and shipped CleanCut, a local-first AI media editor (FastAPI + Next.js 16 + FFmpeg,
> ~15k LoC)** that turns a plain-English instruction into reviewable, timestamp-accurate cuts.
> Designed a chunked sliding-window LLM analyzer (50-segment windows, 10-segment overlap,
> deduplicated by label + 5s proximity) that maps quoted model output back onto word-level Whisper
> timestamps, and shipped a single-pass FFmpeg `trim`/`atrim`+`concat` filter graph preserving A/V
> sync across arbitrary cut and mute sets.

> **Replaced "the analyzer seems accurate" with a number.** Authored a labelled synthetic evaluation
> corpus and a scoring harness — span-overlap matching, per-category recall, and adversarial
> *control* labels that fail the run outright if flagged — then wired it into CI as a hard gate at
> ≥0.95 precision / ≥0.85 recall. It caught two silent detector defects, including a multi-word
> filler phrase that could never match a word-at-a-time scanner. Deterministic and API-key-free, so
> it runs on every push at zero cost.

> **Hardened a single-operator tool into something safe to deploy**, closing 11 phased reliability
> and security defects across 585 backend tests: a durable SQLite-backed task queue with crash
> replay and a 3-attempt poison-task cutoff; monotonic edit/export revision counters so a stale
> render can never be downloaded as current; fail-closed admin auth (503 on an unconfigured token
> rather than open); loopback-by-default network binding; and `<transcript>`-fenced prompt-injection
> defence against a speaker instructing the auditing model to report zero violations.

---

## 2. Product Design & Developer Experience (DX)

### 2.1 Zero-to-one onboarding — strong

Docker Compose works. `.env.example` exists. `start.sh` runs both halves. `CONTRIBUTING.md` mirrors
CI exactly. The demo fixture (`tests/fixtures/demo/`) ships committed, so the eval and detector runs
need **no API key** — that "reproduce CI locally with no secrets" property is rare and worth saying
louder in the README than it currently is.

Missing:

- **No `.devcontainer/`.** For a project requiring Python 3.10+, Node 18+, *and* a system FFmpeg,
  a devcontainer is the highest-leverage onboarding file you don't have.
- **No `Makefile` / `justfile`.** The README carries ~9 distinct commands across two directories.
  `make dev`, `make test`, `make eval` would collapse that to three.
- **No mock / offline LLM mode.** A `CLEANCUT_MODEL=mock:demo` provider — the router already
  abstracts a single `complete(system_prompt, user_prompt) -> str` — would let anyone run the whole
  app end to end with no API key. That is the difference between "clone and look" and "clone and
  use."

### 2.2 Interface & API ergonomics — the strongest part of the repo

The design system is **enforced by tests, not by discipline**:

- `app/contrast.test.ts` parses `globals.css`, holds text pairings to 4.5:1 and non-text UI to 3:1,
  and greps for `text-faint` to fail the build if anyone renders words in the non-text token.
- Full keyboard review path (`J/K/A/R/M/Space/P/T/?`) with modifier-key and text-input guards, both
  halves pinned by tests (`keyboard.test.tsx`, `Waveform.test.tsx`).
- A global, non-suppressible focus ring in `@layer base`.
- A `prefers-reduced-motion` block covering both keyframes, each with a static frame that reads the
  same.
- Waveform regions encode `action` (cut vs. mute), not `severity`, with a legend under the transport
  — because two dimensions in one swatch are not guessable.
- Backend error copy is unusually careful: 413 with the limit named, 422 for an unprobeable
  duration (fails closed), 409 rather than 404 for a job that exists but is in flight, 503 rather
  than 401 for admin routes where no header the caller could send would help.

Remaining a11y / DX gaps:

- **No automated a11y linting.** The contrast test is bespoke and excellent; ARIA roles, labels and
  landmarks are unaudited. Add `eslint-plugin-jsx-a11y` beyond Next's defaults, or `axe-core` in a
  vitest pass.
- **No documented `aria-live` region** for the async pipeline (`converting → transcribing →
  analyzing → completed`). A polling status that only changes visually is invisible to a screen
  reader.
- **CLI `--help` unaudited.** Confirm `app/analysis/analyze.py`'s argparse carries an epilog with a
  worked example, given the module-invocation footgun (`python -m app.analysis.analyze`, not
  `python analyze.py`) is already a documented Common Issue.

### 2.3 Copy & narrative — excellent, and too long

The voice is confident and specific in a way that reads as real engineering judgement: *"The one
filler it misses is an 'Er,' that Whisper dropped from the transcript altogether — the scrubber
reads word timestamps, so a word the model never wrote is not a word it can find."* No amateurish
phrasing anywhere; no "revolutionary", no "seamless", no emoji-headed feature lists.

But 396 lines is a manual. Split it:

- **README (~120 lines):** hook → demo GIF → key features → quickstart → the eval numbers → license.
- **`docs/CONFIGURATION.md`:** the environment variable table.
- **`docs/API.md`:** the endpoint table + analysis modes.
- **`docs/FAILURE_MODES.md`:** failure modes + privacy + threat model (cross-linked from
  `SECURITY.md`).

---

## 3. Missing Features & Technical Differentiation

### 3.1 Table-stakes gaps vs. Descript / AutoCut / auto-editor

- **No word-level transcript *editing*.** The category-defining interaction (Descript) is: delete a
  word in the text, the audio deletes. You already store word timestamps and already have a
  click-to-seek transcript panel — you are one interaction away from the feature everyone expects
  from this product category.
- **No batch / multi-file processing.** No "apply this prompt to 40 recordings", no CLI directory
  mode.
- **No EDL / FCPXML / CSV export.** Professionals want the edit list in Premiere, Resolve or
  Audition, not only a rendered MP3. Cheap to build, and it is the interop wedge for the enterprise
  conversation in §4.
- **No user-authored presets in the UI.** A preset is a markdown file plus a Python dict edit, so a
  team that wants its own compliance rulebook must fork the repo.
- **No webhooks, no API auth, no programmatic client.** Everything is unauthenticated
  single-operator by design (documented in `SECURITY.md`), which is correct for the current scope
  but is the ceiling on it.
- **No speaker diarization.** "Cut everything the interviewer said" is a top-3 requested edit and
  needs speaker labels.

### 3.2 Three high-leverage enhancements

1. **Streaming pipeline with SSE progress, replacing polling.**
   The frontend currently polls `/api/jobs/active` on a timer (already well optimized — small
   payload, merged into rendered cards, one final full read). Replacing it with Server-Sent Events
   carrying per-stage progress *and streaming suggestions as each LLM chunk returns* means a
   40-minute recording shows its first suggestion in seconds instead of after the last chunk.
   Demonstrates async/streaming architecture and removes the polling loop entirely.

2. **A detector plugin system.**
   You already have two detector families (the LLM analyzer and the deterministic scrubber) plus a
   provider router with a one-method interface. Formalize a `Detector` protocol —
   `detect(transcript, audio) -> list[Suggestion]` — with entry-point discovery, and third parties
   can ship a profanity detector, a crosstalk detector, a brand-safety detector, **and score it
   against your existing eval harness**. "Pluggable detectors, each graded by the same CI-gated
   precision/recall harness" is a genuinely impressive sentence and no competitor in this space has
   it.

3. **OpenTelemetry spans across the pipeline, plus a cost ledger.**
   Trace `upload → convert → transcribe → analyze → export` with per-stage duration, tokens
   consumed and dollars spent per job, surfaced on the admin dashboard. Cheap to build, reads
   immediately as production experience, and it is the substrate the paid tier in §4 bills against.

---

## 4. Monetization & Commercialization

The domain is unusually favourable. **FTC income-claim review for direct-selling companies is a
real, budgeted compliance function**, and the `income-claims` preset aims straight at it. That is
not a hobbyist niche — it is a regulated one where a missed claim is legal exposure.

### 4.1 Open-core / gated enterprise

Keep the local single-operator tool MIT. Gate the following behind a commercial license:

- **SSO/SAML + OIDC.**
- **RBAC — reviewer vs. approver.** Compliance workflows *require* two-person sign-off; this is not
  a nice-to-have in the target market.
- **An immutable audit log** of every accept/reject with reviewer identity and timestamp. The
  architecture is already close: `Violation.status` transitions *are* the audit events, they simply
  are not recorded as history. Make the decision ledger append-only and it becomes an evidentiary
  record.
- **Organization-wide custom rulebooks** with versioning and an approval workflow.
- **Retention and data-residency policies** (`RETENTION_HOURS` is the seed of this).
- **A management console** over many workers.

### 4.2 Cloud / hosted SaaS

**CleanCut Cloud** — upload, GPU-accelerated Whisper, team review queues, shareable review links,
Slack/Teams notification on completion. Price per hour of media processed ($2–6/hr is the market
band) with a seat component for reviewers.

The natural adjacent product is a **Compliance Review API**: POST a recording URL plus a rulebook,
get back a scored report. Sold to direct-selling compliance departments and to the agencies that
service them, at per-recording pricing. **The eval harness is the sales asset here** — you can state
a measured precision and recall for a given rulebook, which nobody else in that market does.

### 4.3 Sponsorship & micro-monetization

- **`FUNDING.yml`: not yet.** Add GitHub Sponsors + Polar once there are stars; an empty sponsor
  page reads worse than no sponsor page.
- **Polar bounties suit the plugin-detector roadmap.** Someone wants a Portuguese filler-word set,
  they fund it.
- **Realistic near-term revenue is not sponsorship.** It is a paid "custom rulebook + integration"
  engagement at roughly $5–15k for a single compliance department, with the OSS repo as the
  credibility artifact.
- **Enterprise support SLA:** only once a `v1.0.0` tag exists. Offering an SLA on a repo with zero
  releases is not credible.

---

## 5. Prioritized Action Plan

### 5.1 Quick wins (<1 hour each, in priority order)

1. **Fix the GHCR owner in `README.md:89-90`** — `old-owner` → `julianavellaneda` (or fix the
   remote). Then `git tag v0.1.0 && git push --tags` so `release.yml` actually runs and the images
   it advertises exist. *(Deferred by decision — see §5.4.)*
2. **Put a demo GIF at the top of the README.** `docs/demo/captures/scene-06-review.mp4` and
   `scene-08-export.mp4` already exist:
   ```bash
   ffmpeg -i docs/demo/captures/scene-06-review.mp4 \
     -vf "fps=12,scale=900:-1:flags=lanczos,palettegen" /tmp/pal.png
   ffmpeg -i docs/demo/captures/scene-06-review.mp4 -i /tmp/pal.png \
     -lavfi "fps=12,scale=900:-1:flags=lanczos[x];[x][1:v]paletteuse" docs/assets/demo.gif
   ```
   Or embed the MP4 directly — GitHub renders it inline. **Highest ROI change in this document.**
3. **Add badges:** CI status, license, Python 3.10+, GHCR image, and — the differentiated one — a
   hardcoded **`detector eval: 1.00 precision / 0.92 recall`** badge. Nobody else has that badge.
4. **Add `npm run lint` as a step in `ci.yml`**, so `CLAUDE.md`'s "eslint runs clean" is enforced
   rather than asserted.
5. **Add `.github/dependabot.yml`** — pip, npm and github-actions ecosystems, weekly.
6. **Delete or replace `frontend/README.md`** (create-next-app boilerplate).
7. **Rewrite or delete `docs/ARCHITECTURE.md`** — it currently documents Celery, Zustand and VAD,
   none of which are true.
8. **Add `CODE_OF_CONDUCT.md`** (Contributor Covenant) and a `CHANGELOG.md` seeded with v0.1.0.

### 5.2 Strategic next steps (1–2 weeks)

1. ~~**Reproducible backend builds.**~~ **Done 2026-09-05.** Compiled with `uv pip compile
   --universal --generate-hashes`. Note the naming deviation from this item's wording: the lock is
   `requirements.txt` and the floors moved to `requirements.in`, *not* a `requirements.lock` —
   Dependabot only recognises a pip-compile lockfile ending in `.txt`, so `.lock` would have left
   the automation permanently green and permanently useless. See `.github/dependabot.yml`.
2. **Backend quality gate.** `ruff` (lint + format) and `mypy --strict` over `app/services/` and
   `app/analysis/`, both in CI. Add `pytest --cov` with a floor — 585 tests and no idea what they
   cover.
3. **A `mock` provider plus a devcontainer.** Makes the repo runnable end to end by a reviewer with
   no API key and no FFmpeg install.
4. **Word-level transcript editing.** The table-stakes interaction, and you are closer to it than
   any clone of a competitor would be.
5. **Detector plugin protocol, with per-plugin eval.** The technical differentiation play, and the
   foundation for both community contribution and the commercial tier.
6. **README split** — 396 lines → a ~120-line pitch plus `docs/CONFIGURATION.md`, `docs/API.md`,
   `docs/FAILURE_MODES.md`.

### 5.3 Deliberately *not* recommended

- **Do not add `FUNDING.yml` yet** (§4.3).
- **Do not offer a support SLA** before `v1.0.0` exists.
- **Do not weaken the unauthenticated-by-default design** to look more "enterprise". It is
  documented, reasoned and correct for a local-first tool, and `SECURITY.md` defends it better than
  most projects defend anything.

### 5.4 Decisions taken during this audit

- **No code changes were made.** This document is the sole deliverable, by request.
- **v0.1.0 release deferred.** The release workflow stays untriggered until the quick wins land.
  Until then the README's GHCR pull commands reference images that do not exist and should either be
  corrected to say "with v0.1.0" or removed.

---

*Audit performed against `organic-design-system` @ `3e922b9`.*
