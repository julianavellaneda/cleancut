# Changelog

All notable changes to CleanCut are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-05

First tagged release. Publishes `cleancut-backend` and `cleancut-frontend` to GHCR.

### Added

- **Prompt-driven analysis.** A free-form instruction ("cut every filler word", "flag any specific
  dollar figure") drives the edit, rather than a fixed rulebook. Long transcripts go through a
  chunked sliding window — 50 segments, 10 overlap, deduplicated by label and 5s proximity.
- **Rule presets** for recurring review jobs: income and lifestyle claims, and PII redaction. A
  preset is a markdown rulebook plus a registry entry, and surfaces automatically over the API.
- **Word-level transcription** via `faster-whisper` with int8 quantization for local CPU use.
  Multi-language, including code-switching mid-sentence.
- **Deterministic scrubber** for filler words and dead air, straight off the word timestamps with no
  model involved. Dead air requires two signals to agree: the transcript proposes a span and an RMS
  level pass confirms it below `DEAD_AIR_FLOOR_DB`. Ambiguous fillers ("like") are suggested but
  never applied unreviewed.
- **Interactive review** on a waveform with a marker per suggestion, plus a full keyboard path
  (`J`/`K` to move, `A`/`R` to decide and advance, `M` to flip cut/mute, `Space`, `P`, `T`, `?`).
- **Transcript panel** — the text the analysis actually ran on, kept with the job. Click to seek, it
  follows playback, and it marks which lines carry a suggested edit.
- **Re-analysis without re-transcribing.** A new prompt re-runs against the stored transcript, so
  changing the question costs one LLM call instead of another Whisper pass. Scrubber edits and the
  decisions on them survive the re-run.
- **Per-edit cut or mute**, honored independently on export.
- **A/V-sync-preserving export** — one FFmpeg `trim`/`atrim` + `concat` filter graph in a single
  pass. Export is queued like any other work, so a long re-encode never holds an HTTP request open.
- **Durable job queue** backed by a `tasks` table: the row is written before the in-memory put, the
  worker claims and retires it, and a restart replays outstanding work. A task past three attempts
  is abandoned with the reason on the job rather than killing the process on every boot.
- **Export staleness tracking.** `edit_revision` and `export_revision` mean a render can never be
  downloaded as current after the edits move underneath it.
- **Model router** — `CLEANCUT_MODEL=provider:model` selects OpenAI or Anthropic. One line of
  `.env`, no code change.
- **Eval harness** (`app/eval/`) scoring the detectors against a labelled synthetic clip:
  precision, recall and per-category coverage, with adversarial *control* labels that fail the run
  outright if flagged. The deterministic suite needs no API key, so CI gates every push on it at
  ≥0.95 precision / ≥0.85 recall. It scores 1.00 / 0.92 today.
- **Retention sweeper**, off unless `RETENTION_HOURS` is set, deleting expired terminal jobs, their
  media, and orphaned files.
- **Docker Compose and published GHCR images.** The frontend proxies `/api` to `BACKEND_ORIGIN` read
  at startup, so an image is not pinned to whatever backend built it.
- **Accessible design system** with a contrast audit that parses the token sheet and fails the build
  on a pairing below threshold, a non-suppressible focus ring, and a `prefers-reduced-motion` block.

### Security

- **Fail-closed admin auth.** The destructive `/api/admin/*` routes answer `503` when no
  `ADMIN_TOKEN` is configured, rather than running unauthenticated. `ALLOW_UNAUTHENTICATED_ADMIN`
  restores the open behaviour for local dev, and is ignored once a token is set or the host is not
  loopback.
- **Loopback-by-default binding.** `CLEANCUT_HOST` defaults to `127.0.0.1`; a non-loopback host is
  warned about at startup. `is_loopback` treats anything unrecognised as exposed and never resolves
  DNS.
- **Prompt-injection defence.** The transcript is fenced in `<transcript>` tags with any closing tag
  stripped, and both system prompts name the empty-result shape specifically — a speaker instructing
  the auditing model to report no violations produces a result indistinguishable from a clean
  recording, which is the failure worth defending against because it fails toward passing.
- **Upload limits** enforced on size and duration, failing closed on an unprobeable duration.

[Unreleased]: https://github.com/julianavellaneda/ai-audio-editing/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/julianavellaneda/ai-audio-editing/releases/tag/v0.1.0
