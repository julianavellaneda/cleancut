"""
Deterministic scrubber service for silence and filler word detection.
"""

from typing import List
from ..analysis.transcriber import TranscriptResult, Word
from ..analysis.prompt_analyzer import Violation


class Scrubber:
    """
    Provides deterministic editing suggestions like silence removal and filler word detection.
    """
    
    # Common filler words to detect
    FILLER_WORDS = {"um", "uh", "ah", "er", "hm", "like", "you know"}

    @staticmethod
    def detect_silence(transcript: TranscriptResult, min_silence_len: float = 2.0) -> List[Violation]:
        """
        Identify gaps in transcription that exceed min_silence_len.
        
        Args:
            transcript: The transcribed result
            min_silence_len: Minimum duration in seconds to flag as 'Dead Air'
            
        Returns:
            List of suggested 'cut' violations for silent segments
        """
        silences = []
        if not transcript.segments:
            # If no speech detected, the entire file might be silence
            if transcript.duration > min_silence_len:
                silences.append(Violation(
                    text="[Total Silence]",
                    start_time=0.0,
                    end_time=transcript.duration,
                    label="Dead Air",
                    action="cut",
                    reasoning=f"No speech detected in {transcript.duration:.1f}s of audio."
                ))
            return silences

        # 1. Check silence at the very beginning
        if transcript.segments[0].start > min_silence_len:
            silences.append(Violation(
                text="[Initial Silence]",
                start_time=0.0,
                end_time=transcript.segments[0].start,
                label="Dead Air",
                action="cut",
                reasoning=f"Initial silence of {transcript.segments[0].start:.1f}s detected."
            ))

        # 2. Check silence between segments
        for i in range(len(transcript.segments) - 1):
            curr_end = transcript.segments[i].end
            next_start = transcript.segments[i+1].start
            silence_len = next_start - curr_end
            
            if silence_len > min_silence_len:
                silences.append(Violation(
                    text="[Gap]",
                    start_time=curr_end,
                    end_time=next_start,
                    label="Dead Air",
                    action="cut",
                    reasoning=f"Silence gap of {silence_len:.1f}s detected between segments."
                ))

        # 3. Check silence at the very end
        if transcript.duration - transcript.segments[-1].end > min_silence_len:
            silences.append(Violation(
                text="[Final Silence]",
                start_time=transcript.segments[-1].end,
                end_time=transcript.duration,
                label="Dead Air",
                action="cut",
                reasoning=f"Final silence of {transcript.duration - transcript.segments[-1].end:.1f}s detected."
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
