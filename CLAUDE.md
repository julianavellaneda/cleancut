# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered audio compliance tool for a direct-sales company's marketing guidelines. The system transcribes audio recordings, analyzes them for compliance violations against those guidelines, and flags problematic sections with timestamps for human review.

## Architecture

**POC (Proof of Concept)** - Current phase, CLI-based pipeline:
- `analyze.py` - Main entry point, orchestrates transcription → analysis → output
- `transcriber.py` - Local audio transcription using faster-whisper (optimized for Apple Silicon)
- `compliance.py` - GPT-4o integration for compliance rule violation detection
- `bsm_rules.txt` - System prompt containing compliance rules

**Data Flow:**
1. Audio file → faster-whisper → transcript with word-level timestamps
2. Transcript → GPT-4o (with compliance rules) → JSON violations with timestamps
3. Violations mapped back to precise audio positions using word timing data

## Commands

```bash
# Setup
cd poc
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run analysis
python analyze.py audio.mp3                    # Full analysis
python analyze.py audio.mp3 --model medium     # Faster, less accurate
python analyze.py audio.mp3 --transcript-only  # Skip compliance check
python analyze.py audio.mp3 --language es      # Force Spanish

# Test individual modules
python transcriber.py audio.mp3
python compliance.py audio.mp3
```

## Environment

Requires `.env` file with:
```
OPENAI_API_KEY=your_key_here
```

System dependency: `brew install ffmpeg`

## Future Phases

- **Phase 2**: FastAPI backend with job queue, audio editing (pydub)
- **Phase 3**: Next.js frontend with wavesurfer.js waveform visualization
- **Phase 4**: Deployment (Vercel frontend, Railway/Render backend)
