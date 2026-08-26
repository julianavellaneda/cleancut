# Demo fixture

Everything in this directory is **synthetic**. It depicts no real person, company, product,
market, or recording.

| File | What it is |
|---|---|
| `seminar_script.md` | The written source. A fake two-speaker "business opportunity seminar", 175 spoken words plus three planted pauses. |
| `demo_seminar.mp3` | That script rendered by OpenAI `gpt-4o-mini-tts`, two voices, one call per line, silence inserted for each `[PAUSE n]`. |
| `demo_seminar.mp4` | The same audio over a static card with a `showwaves` overlay, so the video path and the A/V-sync-preserving export are exercised rather than claimed. |
| `expected_violations.json` | Measured start/end offsets for every line and pause, taken with `ffprobe` at generation time. |
| `seed_job.json` | A snapshot of one real completed pipeline run against this clip, replayed by `scripts/seed_demo_job.py`. |

Regenerate with:

```bash
python scripts/generate_demo_audio.py --dry-run   # prices the job, makes no API calls
python scripts/generate_demo_audio.py
```

Per-line audio is cached under `.cache/` (gitignored), so re-running after a script tweak only
pays for the lines that changed.

## Why the script says what it says

The clip is written to give every layer of the tool something to catch: a specific dollar figure,
a quit-your-job claim, a luxury-item claim, a health claim, a spoken phone number and email, ten
filler words, three dead-air gaps of 2.7–2.9 s, and one Spanish sentence mid-conversation.

The gaps are all comfortably over 2 s, which dates from when `Scrubber.detect_silence` used a
2.0 s floor to absorb Whisper's segment-boundary jitter. The floor is now 0.75 s
(`DEAD_AIR_MIN_SECONDS`) and the emitted boundaries come from an RMS pass rather than from Whisper,
so that jitter no longer matters. Measured with `silencedetect` at -50 dB the three pauses are
13.297->16.270, 34.202->37.914 and 60.160->63.656; `backend/tests/test_scrubber.py` asserts against
exactly those numbers, and builds a room-tone variant of the clip to prove they are still rejected
when something audible fills them.

The filler words are drawn only from `Scrubber.FILLER_WORDS` and each stands alone as its own
token, because the scrubber matches word-by-word after stripping punctuation.

One line is a control: *"some people try this and earn nothing at all"*. It is an honest
disclaimer sitting right next to the income claims, and it must **not** be flagged. If it ever
starts getting flagged, the analyzer has fallen back to keyword matching.

## expected_violations.json is the eval fixture

Because the generator knows each line's exact offset, this file is ground truth. It is worth more
than the clip: it turns "the analyzer seems accurate" into something measurable, and it is the
labelled eval set the roadmap wanted.

## Rule

Nothing real lands here. Never commit a customer recording, a real transcript, a real name, or
real client content — see `tests/README.md`.
