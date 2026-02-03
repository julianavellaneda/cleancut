"""
Audio editing service using pydub.
Handles cutting/muting violations from audio files.
"""

from pathlib import Path
from pydub import AudioSegment


class AudioEditor:
    """
    Audio editor for removing or muting violation segments.
    """

    def __init__(self, crossfade_ms: int = 50):
        """
        Initialize editor.

        Args:
            crossfade_ms: Crossfade duration in milliseconds for smooth cuts
        """
        self.crossfade_ms = crossfade_ms

    def load_audio(self, audio_path: str) -> AudioSegment:
        """Load audio file."""
        return AudioSegment.from_file(audio_path)

    def cut_segments(
        self,
        audio: AudioSegment,
        segments: list[tuple[float, float]],
        crossfade: bool = True
    ) -> AudioSegment:
        """
        Cut (remove) specified segments from audio.

        Args:
            audio: Source audio
            segments: List of (start_time, end_time) in seconds to remove
            crossfade: Whether to apply crossfade at cut points

        Returns:
            Edited audio with segments removed
        """
        if not segments:
            return audio

        # Sort segments by start time
        sorted_segments = sorted(segments, key=lambda x: x[0])

        # Merge overlapping segments
        merged = []
        for start, end in sorted_segments:
            if merged and start <= merged[-1][1]:
                # Extend previous segment
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        # Build result by keeping parts between cuts
        result = AudioSegment.empty()
        last_end_ms = 0

        for start, end in merged:
            start_ms = int(start * 1000)
            end_ms = int(end * 1000)

            # Add the part before this cut
            if start_ms > last_end_ms:
                segment = audio[last_end_ms:start_ms]
                if crossfade and len(result) > 0 and len(segment) > self.crossfade_ms:
                    result = result.append(segment, crossfade=self.crossfade_ms)
                else:
                    result += segment

            last_end_ms = end_ms

        # Add remaining audio after last cut
        if last_end_ms < len(audio):
            segment = audio[last_end_ms:]
            if crossfade and len(result) > 0 and len(segment) > self.crossfade_ms:
                result = result.append(segment, crossfade=self.crossfade_ms)
            else:
                result += segment

        return result

    def mute_segments(
        self,
        audio: AudioSegment,
        segments: list[tuple[float, float]]
    ) -> AudioSegment:
        """
        Mute (silence) specified segments in audio.

        Args:
            audio: Source audio
            segments: List of (start_time, end_time) in seconds to mute

        Returns:
            Audio with segments silenced
        """
        if not segments:
            return audio

        result = audio

        for start, end in segments:
            start_ms = int(start * 1000)
            end_ms = int(end * 1000)
            duration_ms = end_ms - start_ms

            if duration_ms > 0 and start_ms < len(audio):
                # Create silence of the same duration
                silence = AudioSegment.silent(
                    duration=min(duration_ms, len(audio) - start_ms),
                    frame_rate=audio.frame_rate
                )
                # Overlay silence on the segment
                result = result.overlay(silence, position=start_ms, gain_during_overlay=-120)

        return result

    def export(
        self,
        audio: AudioSegment,
        output_path: str,
        format: str = "mp3"
    ) -> str:
        """
        Export audio to file.

        Args:
            audio: Audio to export
            output_path: Output file path
            format: Output format (mp3, wav, etc.)

        Returns:
            Path to exported file
        """
        audio.export(output_path, format=format)
        return output_path


def generate_waveform_peaks(
    audio_path: str,
    num_peaks: int = 800
) -> list[float]:
    """
    Generate waveform peaks for visualization.

    Args:
        audio_path: Path to audio file
        num_peaks: Number of peaks to generate

    Returns:
        List of normalized peak values (0.0 to 1.0)
    """
    audio = AudioSegment.from_file(audio_path)

    # Convert to mono for analysis
    if audio.channels > 1:
        audio = audio.set_channels(1)

    # Get raw samples
    samples = audio.get_array_of_samples()

    # Calculate samples per peak
    samples_per_peak = max(1, len(samples) // num_peaks)

    peaks = []
    max_amplitude = max(abs(min(samples)), abs(max(samples))) or 1

    for i in range(num_peaks):
        start = i * samples_per_peak
        end = min(start + samples_per_peak, len(samples))

        if start >= len(samples):
            peaks.append(0.0)
            continue

        chunk = samples[start:end]
        if chunk:
            # Get max amplitude in this chunk
            peak = max(abs(min(chunk)), abs(max(chunk)))
            normalized = peak / max_amplitude
            peaks.append(round(normalized, 3))
        else:
            peaks.append(0.0)

    return peaks
