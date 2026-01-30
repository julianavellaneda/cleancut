# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered audio compliance tool for a direct-sales company's marketing guidelines. The system transcribes audio recordings, analyzes them for compliance violations against those guidelines, and flags problematic sections with timestamps for human review.

**Philosophy**: "Copilot, not Autopilot" - The AI flags violations for human review, it does not automatically edit audio. See `proj.md` for full project vision.

## Architecture

**POC (Proof of Concept)** - Current phase, CLI-based pipeline:

```
poc/
├── analyze.py      # Main CLI entry point
├── transcriber.py  # Whisper transcription (faster-whisper, Apple Silicon optimized)
├── compliance.py   # GPT-4o compliance analysis with chunked processing
├── bsm_rules.txt   # System prompt containing compliance rules
└── .env            # API keys (not committed)
```

**Data Flow:**
1. Audio file → faster-whisper → transcript with word-level timestamps
2. Transcript → GPT-4o (with compliance rules) → JSON violations with timestamps
3. Violations mapped back to precise audio positions using word timing data

**Key Implementation Details:**
- `Transcriber` class uses faster-whisper with int8 quantization for M4 Mac performance
- `ComplianceAnalyzer` uses **chunked analysis with sliding window** for long transcripts (>100 segments)
  - Default chunk size: 50 segments (~2-3 minutes of audio)
  - Default overlap: 10 segments between chunks (catches violations at boundaries)
  - Aggressive "forensic auditor" prompt forces LLM to find ALL violations, not just the first
  - Violations deduplicated (by rule + timestamp proximity) and sorted at the end
- Transcript format: `[0.0s - 2.2s] Text content here` (one segment per line)
- `load_transcript()` function can parse saved transcript files back into `TranscriptResult` objects

## Commands

```bash
# Setup (from project root)
python3 -m venv .venv
source .venv/bin/activate
pip install -r poc/requirements.txt

# Full analysis (transcription + compliance)
python poc/analyze.py audio.mp3
python poc/analyze.py audio.mp3 --model medium     # Faster transcription, less accurate
python poc/analyze.py audio.mp3 --language es      # Force Spanish detection

# Skip transcription - use existing transcript (faster iteration on compliance rules)
python poc/analyze.py --transcript tests/transcripts/large-v3/client_seminar_transcript.txt
python poc/analyze.py -T transcript.txt --chunk-size 30   # Smaller chunks = more thorough
python poc/analyze.py -T transcript.txt --no-overlap      # Faster but may miss boundary violations

# Transcription only (no compliance analysis)
python poc/analyze.py audio.mp3 --transcript-only

# Custom compliance rules
python poc/analyze.py audio.mp3 --rules custom_rules.txt

# Test individual modules
python poc/transcriber.py audio.mp3
python poc/compliance.py audio.mp3
```

## Test Data

```
tests/
├── transcripts/
│   ├── large-v3/    # Transcripts from Whisper large-v3 model
│   │   └── client_seminar_transcript.txt
│   └── medium/      # Transcripts from Whisper medium model
│       └── client_seminar_transcript.txt
└── scripts/
```

Use `--transcript` flag to iterate on compliance rules without re-running slow transcription.

## Environment

Requires `.env` file in `poc/` directory:
```
OPENAI_API_KEY=your_key_here
```

System dependency: `brew install ffmpeg`

## Exit Codes

- `0`: No violations found
- `1`: Some violations found (medium/low severity)
- `2`: High severity violations found

## Future Phases

- **Phase 2**: FastAPI backend with job queue, audio editing (pydub)
- **Phase 3**: Next.js frontend with wavesurfer.js waveform visualization
- **Phase 4**: Deployment (Vercel frontend, Railway/Render backend)

## Common Issues

**"Unexpected response format" from GPT-4o**: The compliance analyzer handles various JSON response formats (array, object with `violations` key, single violation object). If you see this, the LLM returned something unexpected - check the raw response.

**Slow transcription**: Use `--model medium` or `--model small` for faster (but less accurate) transcription. Or use `--transcript` to skip transcription entirely when iterating on compliance rules.

**Chunk size tuning**: Default is 50 segments with 10-segment overlap. Use `--chunk-size 30` for more thorough analysis (more API calls, higher cost). Use `--no-overlap` for faster analysis if boundary violations aren't a concern. Use `--overlap 20` to increase overlap for very critical content.
