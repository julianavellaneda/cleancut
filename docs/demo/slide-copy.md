# CleanCut — Slide Copy

On-screen text for the five slide scenes (1, 2, 3, 9, 10). Scenes 4–8 are screen capture and have
no slide copy. Slide text is a visual anchor next to the voiceover, not a transcript of it — see
`narration.md` for the spoken line on each scene.

---

## Scene 1 — Title

**Title:** CleanCut

**Body:**
Copilot, not autopilot.

**Notes for the editor:** Title card. Wordmark first, tagline fades in half a second behind it —
don't animate them together.

---

## Scene 2 — Problem

**Title:** Editing by ear doesn't scale

**Body:**
- Hours of recording, a handful of moments
- Spotting them is the easy part
- Timestamping to the millisecond isn't

**Notes for the editor:** Build the three bullets in on the beat of the narration's three
"every ___" clauses, one per clause, not all at once.

---

## Scene 3 — Approach

**Title:** One instruction, one pass

**Body:**

```text
# naive: cut each segment, then join
for seg in matches:
    trim(seg.start, seg.end)   # rounding error
    concat_clips(clips)        # error compounds
# audible drift after a few cuts

# CleanCut: one filter graph, one render
graph = build_filter_graph(matches)
ffmpeg(-filter_complex, graph)  # single pass
```

**Notes for the editor:** Hold on the naive block first (let "rounding error" and "compounds"
land), then wipe to the one-pass block. Don't show both halves at once.

---

## Scene 9 — Architecture

**Title:** Architecture

**Body:**
FastAPI + threaded worker → faster-whisper (int8, local) → FFmpeg, one pass
Next.js 16 + wavesurfer.js on top · SQLAlchemy/SQLite underneath

- The model returns quoted text, not timestamps
- That quote is remapped onto word-level timing

**Notes for the editor:** Flow line builds left to right, matching the narration's order
(transcribe → analyze → export). Bring the two bullets in together, after the flow line settles.

---

## Scene 10 — Close

**Title:** CleanCut

**Body:**
<REPO_URL>
Built solo. Everything shown here actually runs.

**Notes for the editor:** Repo line is the largest text on the card — it's the one thing a
viewer should be able to read from a paused frame. Sign-off line sits smaller, underneath.

---

## Typography notes

- **Headline** (largest weight): scene titles — "CleanCut" (1, 10), "Editing by ear doesn't
  scale" (2), "One instruction, one pass" (3), "Architecture" (9).
- **Body**: bullets and the tagline/sign-off lines — one step down in weight/size from headline.
- **Monospace**: the scene 3 code block only. Keep both halves left-aligned at the same column so
  the wipe transition doesn't jump the text horizontally.
- Do not wrap: "Copilot, not autopilot." (scene 1), "<REPO_URL>" (scene 10), and each bullet in
  scenes 2 and 9 — they're written short specifically to hold one line at video width.
