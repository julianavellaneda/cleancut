"""
Media editing service using FFmpeg.
Handles cutting/muting segments from both audio and video files.
"""

import os
import json
import logging
import ffmpeg
import subprocess
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

class MediaEditor:
    """
    Media editor for removing or muting violation segments using FFmpeg.
    Supports both audio and video containers.
    """

    def __init__(self):
        pass

    def cut_segments(
        self,
        input_path: str,
        output_path: str,
        segments_to_remove: List[Tuple[float, float]],
        media_type: str = "audio"
    ):
        """
        Cut (remove) specified segments from media while maintaining sync.
        Uses complex filter graphs for efficient single-pass processing.
        """
        if not segments_to_remove:
            # Just copy/transcode if no segments to remove
            ffmpeg.input(input_path).output(output_path).run(overwrite_output=True, quiet=True)
            return

        # Sort and merge overlapping segments
        merged = self._merge_segments(segments_to_remove)
        
        # Get duration of original file
        probe = ffmpeg.probe(input_path)
        duration = float(probe['format']['duration'])

        # Calculate parts to KEEP
        keep_segments = []
        last_end = 0.0
        for start, end in merged:
            if start > last_end:
                keep_segments.append((last_end, start))
            last_end = end
        
        if last_end < duration:
            keep_segments.append((last_end, duration))

        if not keep_segments:
            # Everything was removed? Create a 1s silence or handle error
            raise ValueError("All segments were removed from the media.")

        # Build filter graph
        # For each keep segment, we create a trim and atrim
        input_stream = ffmpeg.input(input_path)
        v_segments = []
        a_segments = []

        for i, (start, end) in enumerate(keep_segments):
            a = input_stream.audio.filter('atrim', start=start, end=end).filter('asetpts', 'PTS-STARTPTS')
            a_segments.append(a)
            
            if media_type == "video":
                v = input_stream.video.filter('trim', start=start, end=end).filter('setpts', 'PTS-STARTPTS')
                v_segments.append(v)

        if media_type == "video":
            joined = ffmpeg.concat(*[s for pair in zip(v_segments, a_segments) for s in pair], v=1, a=1).node
            out = ffmpeg.output(joined[0], joined[1], output_path)
        else:
            joined = ffmpeg.concat(*a_segments, v=0, a=1).node
            out = ffmpeg.output(joined[0], output_path)

        out.run(overwrite_output=True, quiet=True)

    def mute_segments(
        self,
        input_path: str,
        output_path: str,
        segments_to_mute: List[Tuple[float, float]],
        media_type: str = "audio"
    ):
        """
        Mute (silence) specified segments in media.
        """
        if not segments_to_mute:
            ffmpeg.input(input_path).output(output_path).run(overwrite_output=True, quiet=True)
            return

        merged = self._merge_segments(segments_to_mute)
        
        # Build volume filter string
        # volume='if(between(t,t1,t2),0,1)'
        # For multiple segments: volume='if(between(t,t1,t2)+between(t,t3,t4),0,1)'
        between_clauses = [f"between(t,{start},{end})" for start, end in merged]
        filter_str = f"if({'+'.join(between_clauses)},0,1)"

        input_stream = ffmpeg.input(input_path)
        a = input_stream.audio.filter('volume', filter_str)

        if media_type == "video":
            out = ffmpeg.output(input_stream.video, a, output_path, vcodec='copy')
        else:
            out = ffmpeg.output(a, output_path)

        out.run(overwrite_output=True, quiet=True)

    def _merge_segments(self, segments: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        """Sort and merge overlapping segments."""
        if not segments:
            return []
        
        sorted_segments = sorted(segments, key=lambda x: x[0])
        merged = []
        for start, end in sorted_segments:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged


def generate_waveform_peaks(
    audio_path: str,
    num_peaks: int = 800
) -> list[float]:
    """
    Generate waveform peaks using FFmpeg and numpy (no pydub).
    """
    import numpy as np

    try:
        # Extract raw PCM audio data using FFmpeg
        out, _ = (
            ffmpeg
            .input(audio_path)
            .output('-', format='f32le', acodec='pcm_f32le', ac=1, ar='8000')
            .run(capture_stdout=True, capture_stderr=True)
        )
        
        # Convert byte data to numpy array
        samples = np.frombuffer(out, dtype=np.float32)
        
        if len(samples) == 0:
            return [0.0] * num_peaks

        # Calculate samples per peak
        samples_per_peak = max(1, len(samples) // num_peaks)
        
        peaks = []
        # Max amplitude for normalization
        max_amplitude = np.max(np.abs(samples)) or 1.0

        for i in range(num_peaks):
            start = i * samples_per_peak
            end = min(start + samples_per_peak, len(samples))
            
            if start >= len(samples):
                peaks.append(0.0)
                continue
                
            chunk = samples[start:end]
            if len(chunk) > 0:
                peak = np.max(np.abs(chunk))
                normalized = float(peak / max_amplitude)
                peaks.append(round(normalized, 3))
            else:
                peaks.append(0.0)
                
        return peaks
    except Exception as e:
        logger.error(f"Error generating waveform: {str(e)}")
        return [0.0] * num_peaks
