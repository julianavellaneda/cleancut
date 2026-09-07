# Design notes

Why CleanCut is shaped the way it is. These are the decisions that were not obvious up front, kept
because the reasoning still governs the code.

## 1. Copilot, not autopilot

The tempting version of this tool deletes the flagged sections itself and hands back a finished file.
It should not, for three reasons:

1. **Context risk.** Editing rules are nuanced. "Don't discuss income earned outside this business"
   sounds mechanical until a speaker says "I used to work at a bank, and back then…" — cut that and
   the following sentence loses its setup and the audio goes jumpy.
2. **Audio fidelity.** Hard cuts made by code sound unnatural: clipped breaths, ambient room tone
   snapping in and out.
3. **Liability.** If the model misses something or cuts the wrong thing, the person distributing the
   file carries the consequence. A human has to sign off.

So the product is a **review dashboard**. The AI listens, marks regions on a timeline, cites its
reasoning, and the human clicks accept or reject.

## 2. The pipeline

The pipeline's shape — stage order, data flow, the queue — is `ARCHITECTURE.md`'s job. This section
keeps only the *why* behind each stage.

### Transcription — the ears

Word-level timestamps are the whole foundation; without them there is no way to know *where* to cut.
`faster-whisper` with int8 quantization runs locally at usable speed on an M-series CPU, handles
Spanish and English, and — importantly — handles code-switching mid-sentence, transcribing each
language as itself.

Running transcription locally rather than through an API is also the privacy story: only text leaves
the machine, never audio.

### Analysis — the brain

A capable model is required here, not a small one: the job includes distinguishing "partnership" in
the legal sense from "partnership" meaning a spouse.

**The hard part is mapping back.** The model quotes text; the player needs timestamps. The quoted
string is located in the transcript, disambiguated by the model's approximate time when it appears
more than once, then narrowed to word-level start/end within the matched segment. This is
`_find_text_timestamps`, and it is what makes the markers land on the right syllable rather than the
right paragraph.

**Long recordings need chunking.** A two-hour transcript is large, and models degrade on
find-everything tasks long before they hit a context limit. `ARCHITECTURE.md` has the chunk size, the
overlap and the current deduplication rule — the rule was rewritten once already, after the original
version (label plus timestamp proximity) deleted distinct findings that happened to sit close
together.

### Silence and filler — no LLM

Silence removal and filler-word detection are deterministic problems. Detecting speech gaps and
matching filler tokens against word timestamps is exact, free, and instant. Using a language model
for it would be slower, more expensive, and less reliable. This is the `scrubber`, and its output is
what the "Clean All" button bulk-accepts.

### Export — the scalpel

Editing runs through a single FFmpeg filter graph rather than a sequence of passes. `trim`/`atrim`
plus `concat` removes intervals from video and audio streams together, so they cannot drift out of
sync — which is exactly what happens if you cut the audio and video separately. Mutes are applied
before cuts; `ARCHITECTURE.md` has the reason.

## 3. Prompts vs. presets

The original tool hardcoded one rulebook. Generalizing it to a free-form prompt made it far more
useful, but lost something real: recurring review work wants a consistent, versioned, auditable set
of rules, not a sentence retyped from memory each time.

Hence both. A **prompt** is the default and covers one-off editing. A **preset** is a checked-in
markdown rulebook (`analysis/presets/`) that replaces the prompt and returns rule categories and
severities instead of free-form labels. A preset is a file plus a registry entry — deliberately cheap
to add, so a new review domain does not require touching the analyzer.

## 4. Known pitfalls

- **Hallucinations.** The model will flag innocent content. This is precisely why the human review
  interface is mandatory rather than a nicety.
- **Diarization.** With a translator present, a prohibited statement exists twice — once in each
  language. Both need flagging. The preset rulebooks instruct the model to do this, but true speaker
  separation would need something like `pyannote.audio`.

Two pitfalls that used to be listed here are fixed:

- A silent parse failure used to make a broken LLM response indistinguishable from "found nothing" —
  `_call_llm` swallowed the `JSONDecodeError` and returned an empty list. `_parse_llm_response` now
  raises `AnalysisError` instead: a bad chunk leaves the job `completed` with a partial-analysis
  warning, and a transcript where every chunk fails fails the job outright.
- The admin routes used to wipe the database and storage with no auth at all. Admin auth now fails
  closed — see [`SECURITY.md`](../SECURITY.md).
