# CleanCut — Demo Narration

Voiceover script for a ~3-minute portfolio demo. Read aloud at **150 wpm** (2.5 words/second).
Scenes 1, 2, 3, 9, 10 are slides; scenes 4–8 are screen capture.

Each scene lists a **Budget**: the scene's duration, the hard word ceiling at 150 wpm, and a
target density band — 70–90% for slide scenes (the voice carries the scene), 30–50% for demo
scenes (the picture carries it, narration fills gaps). **Actual** is the real count and its
percentage of the 150-wpm ceiling.

---

## Scene 1 — Title

**On screen:** Title slide.
**Budget:** 12 s · 30 words max at 150 wpm · target 70–90% density → 21–27 words

> This is CleanCut. Describe what you want out of a recording in plain English: filler words, off-brand claims, dead air. It finds them. You decide what goes.

**Actual:** 27 words (90%)

---

## Scene 2 — Problem

**On screen:** Problem slide.
**Budget:** 22 s · 55 words max at 150 wpm · target 70–90% density → 39–50 words

> Say you have two hours of recorded talk. You need every income claim, every filler word, every awkward pause. You could listen by ear and write down timestamps. Spotting the moment is the easy part. Pinning down where it starts and ends, to the millisecond, is not.

**Actual:** 47 words (85%)

---

## Scene 3 — Approach

**On screen:** Approach slide with a code/pseudocode snippet showing naive per-segment cut-and-concat drift.
**Budget:** 20 s · 50 words max at 150 wpm · target 70–90% density → 35–45 words

> Describe what to find, in plain English. A model finds it in the transcript. Then comes the hard part. Trim each segment separately and rounding error stacks up. You can hear the drift after a few cuts. It has to happen in one pass.

**Actual:** 44 words (88%)

---

## Scene 4 — Upload

**On screen:** Screen capture. Upload screen — an instruction is typed, a preset is selected then switched back, scrubber mode is checked, a file is dropped and upload starts.
**Budget:** 18 s · 45 words max at 150 wpm · target 30–50% density → 14–22 words

> Type an instruction. Switch to a preset, and it takes over. Switch back. Turn on the scrubber. Drop a file in.

**Actual:** 21 words (47%)

---

## Scene 5 — Pipeline

**On screen:** Screen capture. Progress stepper: Transcribing, Analyzing, Exporting, Ready to review.
**Budget:** 12 s · 30 words max at 150 wpm · target 30–50% density → 9–15 words

> Transcribing, analyzing, exporting. The real pipeline, running end to end.

**Actual:** 10 words (33%)

---

## Scene 6 — Review (centrepiece)

**On screen:** Screen capture. Waveform with coloured markers, playhead moving, a marker opens a card with quote, reasoning, and timecode; Play Clip plays that span.
**Budget:** 26 s · 65 words max at 150 wpm · target 30–50% density → 20–32 words

> Every marker is a suggestion. Nothing goes until you accept it. Click one and you see the model's exact quote, its reasoning, a timecode. Play the clip. It lands on the words.

**Actual:** 32 words (49%)

---

## Scene 7 — Cut, mute, clean

**On screen:** Screen capture. One edit switched from cut to mute and accepted; Clean All accepts every filler word and dead-air gap, then disappears.
**Budget:** 18 s · 45 words max at 150 wpm · target 30–50% density → 14–22 words

> Switch this to mute, not cut. Accept it. Clean All takes every filler word and gap at once. No model involved.

**Actual:** 21 words (47%)

---

## Scene 8 — Export

**On screen:** Screen capture. Export runs, a download button appears, the edited result plays back — visibly shorter.
**Budget:** 18 s · 45 words max at 150 wpm · target 30–50% density → 14–22 words

> Export runs as one FFmpeg pass. Download it, or play it back here. Shorter, and the sync holds.

**Actual:** 18 words (40%)

---

## Scene 9 — Architecture

**On screen:** Architecture slide.
**Budget:** 22 s · 55 words max at 150 wpm · target 70–90% density → 39–50 words

> The stack: FastAPI, SQLAlchemy on SQLite, a threaded worker queue. Next.js on the front, wavesurfer for the waveform. Transcription is faster-whisper, quantized, running locally. The model returns quoted text, not timestamps. Mapping that quote back onto word-level timing is where the accuracy actually lives.

**Actual:** 44 words (80%)

---

## Scene 10 — Close

**On screen:** Repo / close slide.
**Budget:** 12 s · 30 words max at 150 wpm · target 70–90% density → 21–27 words

> CleanCut is on my GitHub. Link below. It's the whole path: transcription, LLM analysis, review, and export, wired together and working. Thanks for watching.

**Actual:** 24 words (80%)

---

## Totals

| Scene | Duration | Words | Density |
|---|---|---|---|
| 1 — Title | 12 s | 27 | 90% |
| 2 — Problem | 22 s | 47 | 85% |
| 3 — Approach | 20 s | 44 | 88% |
| 4 — Upload | 18 s | 21 | 47% |
| 5 — Pipeline | 12 s | 10 | 33% |
| 6 — Review | 26 s | 32 | 49% |
| 7 — Cut/mute/clean | 18 s | 21 | 47% |
| 8 — Export | 18 s | 18 | 40% |
| 9 — Architecture | 22 s | 44 | 80% |
| 10 — Close | 12 s | 24 | 80% |
| **Total** | **180 s (3:00)** | **288** | — |
