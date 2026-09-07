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
| `eval_labels.json` | Hand-authored ground truth: what each line is, and whether a detector should flag it. Joined onto the measured offsets by `backend/app/eval/`. |
| `transcript_words.json` | A word-level Whisper transcript of the clip, written by `scripts/dump_demo_transcript.py`. Committed so CI can grade the scrubber (`python -m app.eval.run --detectors`) without downloading a model. Re-run the script after any re-render. |

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

The three gaps are comfortably over 2 s, a holdover from when `Scrubber.detect_silence` used a 2.0 s
floor to absorb Whisper's segment-boundary jitter. The floor is now 0.75 s (`DEAD_AIR_MIN_SECONDS`),
and the emitted boundaries come from an RMS pass rather than from Whisper, so that jitter no longer
matters. Measured with `silencedetect` at -50 dB, the three pauses are 13.297→16.270,
34.202→37.914 and 60.160→63.656. `backend/tests/test_scrubber.py` asserts against exactly those
numbers, and builds a room-tone variant of the clip to prove they are still rejected when something
audible fills them.

The filler words are drawn only from `Scrubber.FILLER_WORDS`, each standing alone as its own
token — the scrubber matches word-by-word after stripping punctuation.

There is a fourth stretch of dead air nobody planted. The TTS clip for line 7 ends before its
measured slot does, and line 8 starts half a second into its own, leaving 1.01 s below -50 dBFS
across the seam: `ffmpeg -af silencedetect=n=-50dB:d=0.75` reports 53.879→54.892. It is silence by
every definition the tool uses, so `eval_labels.json` carries it as `dead-air-seam-7-8` rather than
letting a correct detection score as a hallucination. It has no slot of its own, so the label names
lines 7 and 8 together. `seed_job.json` was recorded under the old 2.0 s floor and missed it until
the 2026-08-29 re-record; the current recording finds it.

One line is a control: *"some people try this and earn nothing at all."* It is an honest disclaimer
sitting right next to the income claims, and it must **not** be flagged. If it ever starts getting
flagged, the analyzer has fallen back to keyword matching.

## Line 9 is missing from the audio

The text-to-speech call for `HOST | ... just call us at five five five, oh one three three` came
back with 0.3 s of silence, and the generator recorded that 0.3 s as the line's measured duration.
The clip runs straight from the third pause into the email line — **the spoken phone number listed
in the planted-items table is not in the recording**, nor are the two filler words on that line.

`eval_labels.json` marks those three expectations `"present": false`, with the reason attached,
which keeps them out of every recall figure. They stay recorded rather than deleted: the label is
still what the script called for, and re-rendering the clip is what fixes it. That costs one TTS
call and moves every offset after 63 s, which `backend/tests/test_scrubber.py` asserts on — a
deliberate job, not a tidy-up.

The eval harness is what found this. Nothing else reads the offsets closely enough to notice a line
of dialogue that takes three tenths of a second to say.

## expected_violations.json is the eval fixture

This file is ground truth, generated from each line's exact offset. It is worth more than the clip:
it turns "the analyzer seems accurate" into something measurable, and it is the labelled eval set
the roadmap wanted.

It holds only *timing*, because it is regenerated on every re-render and anything written into it by
hand would be lost. The judgements — which line is an income claim, which pause is dead air, which
line must never be flagged — live in `eval_labels.json` and refer to lines and pauses by index, so
they survive a re-render and follow the clip to wherever it lands.

Score a run against them with:

```bash
cd backend && python -m app.eval.run ../tests/fixtures/demo/seed_job.json
```

The full eval command set — thresholds, the detector suite, `--live` — lives in
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

## Rule

Nothing real lands here. Never commit a customer recording, a real transcript, a real name, or
real client content — see `tests/README.md`.
