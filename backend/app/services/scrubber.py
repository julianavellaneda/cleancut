"""
Deterministic scrubber service for silence and filler word detection.
"""

from collections.abc import Sequence

from ..analysis.prompt_analyzer import Violation
from ..analysis.transcriber import TranscriptResult, Word
from . import levels


class Scrubber:
    """
    Provides deterministic editing suggestions like silence removal and filler word detection.
    """

    # Common fillers, spelled the way Whisper actually writes them. "Hmm" and
    # "umm" are the same sound as "hm" and "um" and Whisper picks between the
    # spellings freely, so every variant it emits has to be listed rather than
    # inferred - collapsing repeated letters would also fold real words in.
    #
    # These are sounds, not words: there is no sentence in which "umm" is
    # carrying meaning, so finding one is the whole of the evidence needed.
    UNAMBIGUOUS_FILLERS = {
        "um",
        "umm",
        "uhm",
        "uh",
        "uhh",
        "ah",
        "ahh",
        "er",
        "erm",
        "hm",
        "hmm",
    }

    # Words that are a filler *sometimes*. "I like this", "a car like that",
    # "we err on the side of caution", "do you know the number" - every one of
    # those is the same spelling doing real work in the sentence, and cutting it
    # deletes meaning rather than noise. They are still detected, because most
    # of the time in a seminar recording they really are hesitations; what they
    # do not get is the benefit of the doubt when nobody is looking. See
    # `_has_disfluency_cue`.
    AMBIGUOUS_FILLERS = {
        "like",
        "err",
    }

    FILLER_WORDS = UNAMBIGUOUS_FILLERS | AMBIGUOUS_FILLERS

    # Fillers that span more than one word. Matching is word by word off the
    # timestamps, so a multi-word entry in FILLER_WORDS could never fire; these
    # are matched as a run of consecutive words instead, longest first.
    #
    # Both are ambiguous by the same argument as AMBIGUOUS_FILLERS, and there
    # is no unambiguous phrase to sit beside them - a filler long enough to be
    # two words is long enough to be a clause.
    FILLER_PHRASES = (
        ("you", "know"),
        ("i", "mean"),
    )

    # Whisper's own punctuation, read as evidence. A parenthetical hesitation
    # comes back comma-wrapped ("and, you know, let's just dive"); a "like"
    # doing grammatical work does not.
    #
    # The two lists differ on purpose. Anything that closes a clause can open
    # the gap a hesitation drops into, but only a comma, dash or ellipsis can
    # *close* one - a full stop after "like" is the end of "that's what I
    # like", which is the sentence this must not cut.
    _OPENS_A_GAP = (",", ".", "!", "?", ";", ":", "—", "…")
    _CLOSES_AN_ASIDE = (",", "—", "…")

    @staticmethod
    def _normalize(text: str) -> str:
        """Lowercase a word and drop the punctuation Whisper hangs off it."""
        return text.strip().lower().strip('.,?!:;\u2026\u201c\u201d"')

    @staticmethod
    def detect_silence(
        transcript: TranscriptResult,
        quiet_regions: Sequence[tuple[float, float]] | None = None,
        min_silence_len: float | None = None,
    ) -> list[Violation]:
        """
        Identify spans that are both un-transcribed and acoustically quiet.

        Two signals, because either one alone is wrong:

        - The transcript says where nobody is *speaking*. On its own that flags
          room tone, applause, a music bed and ambience as dead air, and under
          ``auto_scrub`` deletes them unreviewed. Voice activity detection makes
          the same mistake - it answers the same question.
        - Amplitude says where there is *nothing*. On its own it misses a cough
          or an HVAC hum, which are audible but are not speech.

        So the transcript proposes and the level pass disposes. The emitted
        interval is the *quiet* one, not the transcript gap: Whisper's segment
        boundaries run loose by a few hundred milliseconds and were clipping the
        soft onset of the following line, while the amplitude boundaries land
        within a frame of what ``ffmpeg -af silencedetect`` reports.

        Args:
            transcript: The transcribed result
            quiet_regions: ``(start, end)`` spans below the level floor, from
                :func:`app.services.levels.find_quiet_regions`. ``None`` means
                the level pass could not run - see below.
            min_silence_len: Minimum duration in seconds to flag as 'Dead Air'.
                Defaults to :func:`app.services.levels.min_quiet_seconds`.

        Returns:
            List of suggested 'cut' violations for silent segments

        ``quiet_regions=None`` returns nothing at all. Falling back to the
        transcript gaps would silently reinstate the exact bug this confirmation
        step exists to fix, and "we could not measure it" is not a reason to
        offer someone a cut - least of all with ``auto_scrub`` pre-accepting it.
        The caller is responsible for telling the user why detection was skipped;
        see ``worker._process_job_sequentially``.
        """
        if quiet_regions is None:
            return []

        if min_silence_len is None:
            min_silence_len = levels.min_quiet_seconds()

        # Candidates: where the transcript has nothing to say. Each is a
        # (start, end, text, description) tuple; the description becomes the
        # human-readable half of the reasoning string.
        candidates: list[tuple[float, float, str, str]] = []

        if not transcript.segments:
            # No speech anywhere. The whole file is a candidate - but still only
            # a candidate: 74 minutes of music transcribes to nothing at all.
            candidates.append(
                (
                    0.0,
                    transcript.duration,
                    "[Total Silence]",
                    f"no speech detected in {transcript.duration:.1f}s of audio",
                )
            )
        else:
            # 1. Silence at the very beginning
            candidates.append(
                (
                    0.0,
                    transcript.segments[0].start,
                    "[Initial Silence]",
                    f"a {transcript.segments[0].start:.1f}s lead-in before the first line",
                )
            )

            # 2. Silence between segments
            for i in range(len(transcript.segments) - 1):
                curr_end = transcript.segments[i].end
                next_start = transcript.segments[i + 1].start
                candidates.append(
                    (
                        curr_end,
                        next_start,
                        "[Gap]",
                        f"a {next_start - curr_end:.1f}s gap between transcript segments",
                    )
                )

            # 3. Silence at the very end
            trailing = transcript.duration - transcript.segments[-1].end
            candidates.append(
                (
                    transcript.segments[-1].end,
                    transcript.duration,
                    "[Final Silence]",
                    f"a {trailing:.1f}s tail after the last line",
                )
            )

        floor = levels.floor_db()
        silences = []

        for cand_start, cand_end, text, description in candidates:
            # Intersection can only shrink a candidate, so one already under the
            # floor can never produce a qualifying span.
            if cand_end - cand_start < min_silence_len:
                continue

            for quiet_start, quiet_end in quiet_regions:
                start = max(cand_start, quiet_start)
                end = min(cand_end, quiet_end)
                length = end - start

                if length < min_silence_len:
                    continue

                # Every qualifying sub-interval is emitted, not just the longest.
                # A cough or a door in the middle of a pause splits it in two,
                # and the right edit is to cut around the noise rather than
                # through it - or to leave one half and take the other.
                silences.append(
                    Violation(
                        text=text,
                        start_time=start,
                        end_time=end,
                        label="Dead Air",
                        action="cut",
                        reasoning=(
                            f"{length:.1f}s below {floor:.0f} dBFS with no speech "
                            f"transcribed - {description}."
                        ),
                    )
                )

        return silences

    @staticmethod
    def _has_disfluency_cue(words: Sequence[Word], start: int, end: int) -> bool:
        """
        Whether a run of words that *spells* a filler is evidenced as one.

        Only asked of the ambiguous entries, and answered from what is already
        on the page rather than from a guess about grammar:

        - Whisper wrote it as an aside. The word before it closes a clause and
          the run itself ends on a comma or a dash: "and, you know, let's".
          "we err on the side" and "a car like that" carry neither mark.
        - It is touching a sound that can only be a hesitation. "um like" is a
          stumble whichever way it was punctuated.

        No cue is not a verdict of "not a filler" - the suggestion is still
        made. It is a verdict of "not without a human", which is what
        ``Violation.is_ambiguous`` carries.
        """
        before = Scrubber._normalize(words[start - 1].text) if start > 0 else None
        after = Scrubber._normalize(words[end].text) if end < len(words) else None
        if (
            before in Scrubber.UNAMBIGUOUS_FILLERS
            or after in Scrubber.UNAMBIGUOUS_FILLERS
        ):
            return True

        # Segment start counts as an opening: the line before it ended.
        opened = start == 0 or words[start - 1].text.rstrip().endswith(
            Scrubber._OPENS_A_GAP
        )
        closed = words[end - 1].text.rstrip().endswith(Scrubber._CLOSES_AN_ASIDE)
        return opened and closed

    @staticmethod
    def detect_filler_words(transcript: TranscriptResult) -> list[Violation]:
        """
        Identify common filler words using word-level timestamps.

        Matching is longest-first per segment and, for the entries that are only
        sometimes fillers, evidence-gated: see :meth:`_has_disfluency_cue`. An
        unevidenced match is still returned - it is marked ``is_ambiguous`` so
        that ``auto_scrub`` leaves it for a human instead of cutting it.

        Args:
            transcript: The transcribed result with word_timestamps=True

        Returns:
            List of suggested 'cut' violations for filler words
        """
        max_phrase = max((len(p) for p in Scrubber.FILLER_PHRASES), default=0)

        fillers = []
        for segment in transcript.segments:
            if not segment.words:
                continue

            words = segment.words
            cleaned = [Scrubber._normalize(w.text) for w in words]

            i = 0
            while i < len(words):
                # Longest match first, so "you know" wins over a bare "you".
                match_len = 0
                matched = ""
                ambiguous = False
                for size in range(min(max_phrase, len(words) - i), 1, -1):
                    if tuple(cleaned[i : i + size]) in Scrubber.FILLER_PHRASES:
                        match_len = size
                        matched = " ".join(cleaned[i : i + size])
                        ambiguous = True
                        break

                if not match_len and cleaned[i] in Scrubber.FILLER_WORDS:
                    match_len = 1
                    matched = cleaned[i]
                    ambiguous = matched in Scrubber.AMBIGUOUS_FILLERS

                if not match_len:
                    i += 1
                    continue

                # An ambiguous spelling that Whisper punctuated as an aside, or
                # that is leaning on a hesitation, has been evidenced; the rest
                # go out marked for review.
                if ambiguous and Scrubber._has_disfluency_cue(words, i, i + match_len):
                    ambiguous = False

                # What was found, and nothing about how sure of it we are:
                # that is `is_ambiguous`, which each surface renders itself.
                reasoning = f"Detected common filler word '{matched}'."

                run = words[i : i + match_len]
                fillers.append(
                    Violation(
                        text=" ".join(w.text.strip() for w in run),
                        start_time=run[0].start,
                        end_time=run[-1].end,
                        label="Filler Word",
                        action="cut",
                        reasoning=reasoning,
                        is_ambiguous=ambiguous,
                    )
                )
                i += match_len

        if not fillers:
            return []

        # Merge consecutive filler words into a single violation if they are close
        merged = []
        current = fillers[0]

        for next_v in fillers[1:]:
            # If gap between words is less than 0.5 seconds, merge them
            if next_v.start_time - current.end_time < 0.5:
                current.end_time = next_v.end_time
                current.text += " " + next_v.text
                # The merged span is only as safe to cut unattended as its
                # least certain member: a confident "um" next to an unevidenced
                # "like" would otherwise carry the "like" into an auto-cut.
                current.is_ambiguous = current.is_ambiguous or next_v.is_ambiguous
                current.reasoning = "Detected multiple consecutive filler words."
            else:
                merged.append(current)
                current = next_v

        merged.append(current)
        return merged
