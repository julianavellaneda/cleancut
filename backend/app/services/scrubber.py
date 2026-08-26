"""
Deterministic scrubber service for silence and filler word detection.
"""

from typing import List, Sequence, Tuple
from ..analysis.transcriber import TranscriptResult, Word
from ..analysis.prompt_analyzer import Violation
from . import levels


class Scrubber:
    """
    Provides deterministic editing suggestions like silence removal and filler word detection.
    """
    
    # Common filler words to detect
    FILLER_WORDS = {"um", "uh", "ah", "er", "hm", "like", "you know"}

    @staticmethod
    def detect_silence(
        transcript: TranscriptResult,
        quiet_regions: Sequence[Tuple[float, float]] | None = None,
        min_silence_len: float | None = None,
    ) -> List[Violation]:
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
        candidates: List[Tuple[float, float, str, str]] = []

        if not transcript.segments:
            # No speech anywhere. The whole file is a candidate - but still only
            # a candidate: 74 minutes of music transcribes to nothing at all.
            candidates.append((
                0.0, transcript.duration, "[Total Silence]",
                f"no speech detected in {transcript.duration:.1f}s of audio",
            ))
        else:
            # 1. Silence at the very beginning
            candidates.append((
                0.0, transcript.segments[0].start, "[Initial Silence]",
                f"a {transcript.segments[0].start:.1f}s lead-in before the first line",
            ))

            # 2. Silence between segments
            for i in range(len(transcript.segments) - 1):
                curr_end = transcript.segments[i].end
                next_start = transcript.segments[i + 1].start
                candidates.append((
                    curr_end, next_start, "[Gap]",
                    f"a {next_start - curr_end:.1f}s gap between transcript segments",
                ))

            # 3. Silence at the very end
            trailing = transcript.duration - transcript.segments[-1].end
            candidates.append((
                transcript.segments[-1].end, transcript.duration, "[Final Silence]",
                f"a {trailing:.1f}s tail after the last line",
            ))

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
                silences.append(Violation(
                    text=text,
                    start_time=start,
                    end_time=end,
                    label="Dead Air",
                    action="cut",
                    reasoning=(
                        f"{length:.1f}s below {floor:.0f} dBFS with no speech "
                        f"transcribed - {description}."
                    ),
                ))

        return silences

    @staticmethod
    def detect_filler_words(transcript: TranscriptResult) -> List[Violation]:
        """
        Identify common filler words using word-level timestamps.
        
        Args:
            transcript: The transcribed result with word_timestamps=True
            
        Returns:
            List of suggested 'cut' violations for filler words
        """
        fillers = []
        for segment in transcript.segments:
            if not segment.words:
                continue
            
            for word in segment.words:
                # Clean word for matching (lowercase and remove punctuation)
                clean_word = word.text.strip().lower().strip(".,?!:;")
                
                if clean_word in Scrubber.FILLER_WORDS:
                    fillers.append(Violation(
                        text=word.text.strip(),
                        start_time=word.start,
                        end_time=word.end,
                        label="Filler Word",
                        action="cut",
                        reasoning=f"Detected common filler word '{clean_word}'."
                    ))
        
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
                current.reasoning = "Detected multiple consecutive filler words."
            else:
                merged.append(current)
                current = next_v
                
        merged.append(current)
        return merged
