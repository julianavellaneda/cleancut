# CleanCut

[![CI](https://github.com/julianavellaneda/ai-audio-editing/actions/workflows/ci.yml/badge.svg)](https://github.com/julianavellaneda/ai-audio-editing/actions/workflows/ci.yml)
[![detector eval: 1.00 precision / 0.92 recall](https://img.shields.io/badge/detector%20eval-1.00%20precision%20%2F%200.92%20recall-brightgreen)](#eval)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![GHCR](https://img.shields.io/badge/ghcr.io-cleancut-2496ED?logo=docker&logoColor=white)](https://github.com/julianavellaneda/ai-audio-editing/pkgs/container/cleancut-backend)

Describe what to find in plain English. Review it on a waveform. Export a surgically edited file.

CleanCut transcribes audio or video with word-level timestamps, sends the transcript to an LLM
along with your instruction ("cut every filler word", "flag any specific dollar figure", "mute
anything that sounds like a phone number"), and turns the answers back into precise timestamps.
You review each suggestion on a waveform, accept or reject it, choose cut or mute per edit, and
export a single re-encoded file.

**Copilot, not autopilot.** Nothing is removed without a human accepting it.

![Reviewing suggested edits on the waveform: the playhead crosses the file, a suggestion opens to
show the model's quoted text against its exact timestamps, the clip replays, and the edit is
accepted](docs/assets/demo.gif)

*Reviewing a seminar recording. Full-quality captures of the whole flow — upload, pipeline, review,
cut versus mute, export — are in [`docs/demo/captures/`](docs/demo/captures/).*

## Quickstart (Docker)

```bash
cp .env.example .env      # then add your model API key
docker compose up --build
```

Open http://localhost:3000.

### Published images

Every `v*` git tag publishes both images to GHCR, for running CleanCut without building it. The
image tag drops the leading `v` — a `v0.1.0` tag publishes `0.1.0`, a moving `0.1`, and `latest`:

```bash
docker pull ghcr.io/julianavellaneda/cleancut-backend:0.1.0
docker pull ghcr.io/julianavellaneda/cleancut-frontend:0.1.0
```

These are **`linux/amd64` only**. On Apple Silicon, add `--platform linux/amd64` and Docker Desktop
runs them emulated — which is slow enough for Whisper that building locally, or `docker compose up
--build`, is the better trade on an M-series Mac.

The frontend image is not tied to any particular backend: the browser calls the frontend's own
`/api` and its server proxies to `BACKEND_ORIGIN`, which is read at startup, so pointing it
somewhere else is an environment variable rather than a rebuild.

`docker compose up --build` stays the path this repo is set up for — Compose is what wires the two
together, mounts the volumes and publishes on loopback. The published images are for anyone who
would rather not build.

## Quickstart (local)

Requires Python 3.10+, Node 20.9+, and FFmpeg (`brew install ffmpeg`).

```bash
# 1. Environment — a .env at the repo root, read by the backend
cp .env.example .env      # then add your model API key

# 2. Backend (port 8000)
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements.txt   # pinned + hashed lock
uvicorn app.main:app --reload

# 3. Frontend (port 3000), in a second terminal
cd frontend
npm install
npm run dev
```

Or run both with `./start.sh`.

`uvicorn --reload` above defaults to loopback on its own, but a bare `npm run dev` does not — Next
binds every interface unless you pass `--hostname`. `start.sh` and Docker Compose both bind loopback
by default and read `CLEANCUT_HOST` to change it; the hand-typed commands above never read that
variable. To match `start.sh`'s default, run `npm run dev -- --hostname 127.0.0.1`, or just use
`./start.sh`. See [Privacy](#privacy) for what runs unauthenticated on that port.

## Key features

- **Word-level transcription** via `faster-whisper`, with int8 quantization for local CPU use.
- **Prompt-driven analysis** — a free-form instruction, not a fixed rulebook.
- **Rule presets** for recurring review jobs (income and lifestyle claims, PII redaction), selectable
  in place of a prompt.
- **Deterministic scrubber** — silence and filler-word detection straight off the word timestamps,
  no LLM involved, plus a one-click "Clean All" for those.
- **Interactive review** — a waveform with a marker per suggestion and full keyboard-driven
  accept/reject. See [Reviewing](#reviewing) for the key map.
- **Searchable transcript panel** — the transcript the analysis actually ran on, kept with the job.
  Click a line to seek there, watch it follow playback, and see which lines carry a suggested edit.
- **Ask again without re-transcribing** — a new prompt or preset re-runs the analysis against the
  stored transcript, so changing the question costs one LLM call instead of another Whisper pass.
  Filler-word and dead-air edits, and your decisions on them, are kept across the re-run.
- **Per-edit cut or mute**, honored independently on export.
- **A/V-sync-preserving export** — a single FFmpeg `trim`/`atrim` + `concat` filter graph, so video
  stays in sync with its audio across every cut.
- **Background job queue** with per-stage status (`converting` → `transcribing` → `analyzing` →
  `exporting` → `completed`), polled by the frontend. Export is queued the same way, so a long
  re-encode never holds an HTTP request open.
- **Multi-language**, including code-switching between English and Spanish mid-sentence.
- **Bring your own model** — `CLEANCUT_MODEL=provider:model` picks the vendor and the model
  (`openai:gpt-4o`, `anthropic:claude-opus-5`). One line of `.env`, no code change.
- **Measured, not asserted** — a labelled synthetic clip and an eval harness that scores the
  detectors against it: precision, recall, and per-category coverage, run on every build.

## Screenshots

**Describe the job.** Free-form instructions, or a rule preset in place of them. Scrubber mode adds
the deterministic filler and silence pass; auto-apply pre-accepts what the detectors are sure of.

![The CleanCut upload screen: instructions field, rule preset picker, auto-apply and scrubber toggles, and a drop zone](docs/assets/01-upload.png)

**Review on the waveform.** Every suggestion is a marker over the audio and a row in the sidebar.
This one is the scrubber's: a filler word, found off the word timestamps with no model involved.

![The review screen: seventeen suggested edits beside a waveform with the spans to cut shaded, and a card for the filler word “um”](docs/assets/02-review.png)

**Read the reasoning before deciding.** The same screen with an LLM-found income claim selected —
the quoted span, why it was flagged, and the choice between cutting it and muting it.

![The review screen with an income claim selected, showing the quoted sentence, the model's reasoning, and the cut/mute toggle](docs/assets/03-marker-card.png)

**Export what you accepted.** One FFmpeg pass over the accepted edits — 1:14 of recording down to
0:56, playable in place before you download it.

![The review screen after an export: accepted edits marked, a result player showing 0:56 against the original's 1:14, and a Download edited file button](docs/assets/04-export-complete.png)

## Architecture

| Layer | Stack |
|---|---|
| Backend | FastAPI, SQLAlchemy (SQLite), FFmpeg, OpenAI API |
| Frontend | Next.js 16, Tailwind CSS v4, Wavesurfer.js |
| Analysis | `faster-whisper` transcription, chunked sliding-window LLM analysis (OpenAI or Anthropic) |

```
upload → queue → Whisper (word timestamps) → LLM analysis → review UI → FFmpeg export
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full pipeline, the durable task queue, and
how export staleness is tracked.

## Tests

```bash
cd backend
pip install --require-hashes -r requirements-dev.txt
pytest

cd ../frontend
npm test          # vitest + Testing Library, in jsdom - no browser needed
```

GitHub Actions runs both suites, plus the rest of the backend and frontend gates, on every push and
pull request. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full list of checks CI runs and how to
run them locally. Nothing in that list needs an API key.

## Eval

"The analyzer seems accurate" is not a claim worth making, so there is a number behind it.

`tests/fixtures/demo/` holds a synthetic two-speaker seminar clip with every detector's target
planted at a known offset: income, lifestyle and health claims, ten filler words, three dead-air
pauses, a code-switch into Spanish, and contact details. Alongside it, `eval_labels.json` records
what each line is and whether it should be flagged.

```bash
cd backend && source .venv/bin/activate
python -m app.eval.run ../tests/fixtures/demo/seed_job.json
```

```
  precision  100.0%   (17 suggestions graded)
  recall      93.8%   (16 labels in scope)
  F1          96.8%

By category:
  income-claim     ############  1/1
  lifestyle-claim  ############  2/2
  health-claim     ############  1/1
  filler           ##########..  7/8
  dead-air         ############  4/4
```

That run scores a recorded snapshot of the real pipeline. It needs no API key, no model and no
media, which is why it runs in CI — but it grades the scorer and the labels, not today's code.

To grade the detectors as they stand on this commit, run them against the real audio and the
committed word-level transcript. Still free, so CI gates on this one too:

```bash
python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3 --suite scrub
```

```
  precision  100.0%   (11 suggestions graded)
  recall      91.7%   (12 labels in scope)
  F1          95.7%

By category:
  filler           ##########..  7/8
  dead-air         ############  4/4
```

**This is the run the badge at the top of this file tracks** — its 1.00 precision / 0.92 recall is
this scorecard's 100% / 91.7%, rounded.

The one filler it misses is an "Er," that Whisper dropped from the transcript altogether — the
scrubber reads word timestamps, so a word the model never wrote is not a word it can find. The two
that used to be missed were the harness earning its keep: `FILLER_WORDS` held `"you know"` while
matching walked one word at a time, so the most common filler in English could never fire, and the
set spelled a sound `"hm"` that Whisper writes as `"Hmm"`.

A suggestion that quotes one tight clause of a labelled line counts: cutting less is the better
answer for an editor, and coverage is measured against the shorter of the two spans. The clip also
contains two controls, an honest earnings disclaimer between two income claims and a neutral
follow-up question. Flagging either fails the run outright, whatever the aggregate numbers say.

See [CONTRIBUTING.md](CONTRIBUTING.md) for `--live`, `--json`, and the `--min-recall` /
`--min-precision` thresholds CI enforces.

## CLI

The analysis pipeline is also runnable standalone, without the web app:

Run it as a module from `backend/`, so the `app` package resolves:

```bash
cd backend
source .venv/bin/activate
python -m app.analysis.analyze path/to/audio.mp3 --prompt "flag every income claim"

# Or with a built-in preset instead of a prompt
python -m app.analysis.analyze path/to/audio.mp3 --preset income-claims

# Skip transcription and analyze an existing transcript
python -m app.analysis.analyze --transcript path/to/transcript.txt --prompt "find filler words"
```

## API

Interactive Swagger docs at http://localhost:8000/docs. The full endpoint contract — request and
response shapes, every status code, the schema — is in
[docs/SPECIFICATION.md](docs/SPECIFICATION.md).

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/jobs` | Upload media and start processing |
| GET | `/api/jobs` | List jobs, paginated (`limit` default 50, max 200, plus `offset`) |
| GET | `/api/jobs/{id}` | Job status and metadata |
| GET | `/api/jobs/{id}/violations` | List suggested edits |
| POST | `/api/jobs/{id}/violations/bulk-update` | Bulk accept/reject/undo, filtered by label, id, or source status |
| POST | `/api/jobs/{id}/export` | Queue the edited render (202; poll `export_status`) |
| GET | `/api/jobs/{id}/export/download` | Download the result |
| GET | `/api/admin/stats` | System statistics |

## Analysis modes

**Prompt mode** (default) — your instruction drives the analysis. Each suggestion comes back with a
label, a cut/mute recommendation, and the model's reasoning.

**Preset mode** — a curated rulebook replaces the prompt, and suggestions come back with a rule
category and a severity. Presets live in `backend/app/analysis/presets/` as markdown; adding one is
a new file plus an entry in `PRESETS` in `prompt_analyzer.py`.

| Preset | Purpose |
|---|---|
| `income-claims` | FTC-style earnings and lifestyle claim review for direct-selling material |
| `pii-redaction` | Spoken personal, financial, and credential data, defaulted to mute |

Long transcripts go through a chunked sliding window so nothing is missed at a boundary, and a
finding two chunks both report is collapsed on overlapping spans and matching text rather than on
timestamp proximity. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) has the chunk size, the overlap
and the exact matching rule.

## Reviewing

Every suggestion is reviewed by hand — nothing is removed until you accept it. The review screen is
built for a keyboard pass: move down the list, decide, and the selection advances on its own.

| Key | Action |
|---|---|
| `J` / `↓` | Next suggestion |
| `K` / `↑` | Previous suggestion |
| `A` | Accept and advance |
| `R` | Reject and advance |
| `M` | Toggle cut ↔ mute on the selected edit |
| `Space` | Play / pause |
| `P` | Replay just the selected clip |
| `T` | Show or hide the transcript panel |
| `?` | Show or hide the shortcut list |

The transcript panel sits on the right, off by default. It scrolls to follow playback, clicking a
line seeks the waveform to it, and lines overlapping a suggested edit are marked in that edit's
colour — so a flagged quote can be read in context rather than judged from a marker alone. Jobs
processed before transcripts were stored simply don't offer the panel; the transcript cannot be
recovered without re-transcribing, and the API says so rather than returning an empty one.

The list scrolls to follow the selection, and the keys are ignored while a modifier is held or a
text field has focus. Decision keys (`A`, `R`, `M`) are also ignored while an edit is still in
flight, so holding one down cannot stack overlapping updates; navigation stays live throughout.

## Configuration

Set in `.env` at the repo root:

| Variable | Default | Purpose |
|---|---|---|
| `CLEANCUT_MODEL` | `openai:gpt-4o` | Which model analyses the transcript, as `provider:model`. `openai` or `anthropic` |
| `OPENAI_API_KEY` | — | Required when `CLEANCUT_MODEL` names `openai` |
| `ANTHROPIC_API_KEY` | — | Required when `CLEANCUT_MODEL` names `anthropic` |
| `CLEANCUT_HOST` | `127.0.0.1` | Which interface `start.sh` and Docker Compose listen on. Loopback by default; `0.0.0.0` exposes it to the network, which the unauthenticated media routes are not built for |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `DATABASE_PATH` | `backend/audio_compliance.db` | SQLite file location |
| `BACKEND_ORIGIN` | `http://localhost:8000` | Where the frontend's own server finds the backend. The browser calls the frontend's `/api` and Next proxies it here, so the backend's address is never compiled into the page |
| `NEXT_PUBLIC_API_URL` | unset | Set it to have the browser call the backend directly instead of through the proxy. Cross-origin, so `CORS_ORIGINS` must name the frontend — and it is baked into the build, so changing it means rebuilding |
| `MAX_UPLOAD_MB` | `500` | Upload size cap; larger uploads are rejected with a 413 |
| `MAX_DURATION_MINUTES` | `120` | Media length cap, measured with `ffprobe` before queueing; media whose duration cannot be read is rejected |
| `DEAD_AIR_FLOOR_DB` | `-50.0` | dBFS below which audio counts as silence for dead-air detection |
| `DEAD_AIR_MIN_SECONDS` | `0.75` | Shortest dead-air span worth suggesting |
| `RETENTION_HOURS` | unset | Delete jobs and their media once they are this old. Unset keeps everything forever |
| `RETENTION_SWEEP_MINUTES` | `15` | How often the retention sweeper runs |
| `ADMIN_TOKEN` | unset | Shared secret for the destructive admin routes, sent as an `X-Admin-Token` header. Unset **disables** those routes (503) rather than leaving them open |
| `ALLOW_UNAUTHENTICATED_ADMIN` | unset | `1` leaves the destructive admin routes open with no token, the way they used to be. For a machine you control only; ignored when `ADMIN_TOKEN` is set, and ignored once `CLEANCUT_HOST` is not loopback |
| `SKIP_PREFLIGHT` | unset | Boot despite a failed startup check (jobs will still fail) |

## Failure modes

The backend runs a preflight at startup and refuses to boot if the configured provider's API key is
missing or `ffmpeg`/`ffprobe` are not on PATH. Both are otherwise only reached minutes into a job,
where a missing line in `.env` looks like an application bug.

Uploads are capped by size and by duration; both come back as a 413 with the limit named, and the
rejected job is not left behind in the jobs list. The duration cap fails closed — a file `ffprobe`
cannot read a duration from is rejected with a 422, since a limit that any unprobeable stream can
skip is not a limit.

Both caps are enforced after the multipart body has already been spooled to disk, so
`MAX_UPLOAD_MB` bounds what CleanCut *keeps*, not what a client can make it receive. See
[SECURITY.md](SECURITY.md) for what that means on a deployment past localhost.

When the model returns something that isn't a readable list of suggestions, that is reported rather
than silently treated as "nothing found" — a distinction that matters when the output is a
compliance review. A single unreadable chunk of a long transcript leaves the job completed with a
partial-analysis warning naming the unanalyzed timespans; if every chunk fails, the job fails. The
same applies to entries that parse but say nothing actionable: an item with no quoted text or an
unknown action fails its chunk rather than becoming an empty edit that `auto_fix` would apply.

Work queued for the worker survives a restart: a deploy, a crash or a closed laptop no longer
throws away a job that had already been accepted and not yet run. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the queue is made durable and how it recovers.

The CLI carries the same status: the saved JSON includes `is_partial` and `failed_chunks`,
`total_segments_analyzed` counts only segments a chunk actually answered for, and a partial run
exits 2 so a script cannot read it as clean.

## Privacy

Transcription runs locally on your machine. Only the resulting transcript text is sent to the LLM
provider, never the audio. Jobs, uploads, exports, and the stored transcript stay on local disk
(SQLite plus `backend/uploads/` and `backend/exports/`). Use the admin dashboard at `/admin` to
wipe both.

The rest of the API is unauthenticated: anything that can reach the port can list the jobs, stream
the original recording, read the transcript and download the export. The port is the access
control, and it is loopback by default for `start.sh` and Docker Compose. See
[SECURITY.md](SECURITY.md) for the admin-token setup, what `CLEANCUT_HOST=0.0.0.0` changes, and the
guidance for running CleanCut anywhere past your own machine.

Nothing is deleted on a timer unless you ask for it. Set `RETENTION_HOURS` and a background sweeper
deletes each job — its row, its violations, its upload, and its export — once it is that old, along
with any media left on disk that no job refers to any more. A job still moving through the pipeline
is never collected however old it is, since the queue is sequential and a job can wait a long time
behind a long one. The default is unset, because on your own laptop the recordings are yours and
deleting them by surprise is the worse failure.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) covers setup, the checks CI runs and the conventions that are
load-bearing; [`AGENTS.md`](AGENTS.md) is the full architecture reference — and the file AI coding
agents read, in the [agents.md](https://agents.md) open format.

Security reports go through [SECURITY.md](SECURITY.md), not a public issue — and note that the
unauthenticated routes described under [Privacy](#privacy) are a design decision, documented there.

## License

MIT — see [LICENSE](LICENSE).
