"""
Media editing service using FFmpeg.
Handles cutting/muting segments from both audio and video files.
"""

import logging

import ffmpeg
import numpy as np

logger = logging.getLogger(__name__)

# Every analysis pass over a whole file decodes it here first. 8 kHz mono is
# plenty for both jobs that need it - waveform peaks and an RMS level pass care
# about envelope, not about anything above 4 kHz - and it keeps a 74s clip under
# 600 KB of float32 instead of tens of MB.
DECODE_SAMPLE_RATE = 8000


class MediaEditor:
    """
    Media editor for removing or muting violation segments using FFmpeg.
    Supports both audio and video containers.
    """

    def __init__(self):
        pass

    def apply_edits(
        self,
        input_path: str,
        output_path: str,
        segments_to_cut: list[tuple[float, float]] | None = None,
        segments_to_mute: list[tuple[float, float]] | None = None,
        media_type: str = "audio"
    ):
        """
        Apply per-segment cut and mute edits in a single pass.

        Muting is applied to the untrimmed stream first, so mute timestamps stay
        on the original timeline even when cuts shift it. The trim/atrim/concat
        chain then removes the cut segments, preserving A/V sync.
        """
        cuts = self._merge_segments(segments_to_cut or [])
        mutes = self._merge_segments(segments_to_mute or [])

        if not cuts and not mutes:
            # Nothing to do - just copy/transcode
            ffmpeg.input(input_path).output(output_path).run(overwrite_output=True, quiet=True)
            return

        input_stream = ffmpeg.input(input_path)
        audio = input_stream.audio

        if mutes:
            # volume='if(between(t,t1,t2)+between(t,t3,t4),0,1)'
            # eval=frame is required - the default (once) evaluates t a single
            # time at startup, which silently disables the whole expression.
            between_clauses = [f"between(t,{start},{end})" for start, end in mutes]
            audio = audio.filter('volume', f"if({'+'.join(between_clauses)},0,1)", eval='frame')

        if not cuts:
            if media_type == "video":
                out = ffmpeg.output(input_stream.video, audio, output_path, vcodec='copy')
            else:
                out = ffmpeg.output(audio, output_path)
            out.run(overwrite_output=True, quiet=True)
            return

        # Get duration of original file
        probe = ffmpeg.probe(input_path)
        duration = float(probe['format']['duration'])

        # Calculate parts to KEEP
        keep_segments = []
        last_end = 0.0
        for start, end in cuts:
            if start > last_end:
                keep_segments.append((last_end, start))
            last_end = end

        if last_end < duration:
            keep_segments.append((last_end, duration))

        if not keep_segments:
            # Everything was removed? Create a 1s silence or handle error
            raise ValueError("All segments were removed from the media.")

        # A filter output can only feed one consumer, so fan the (possibly
        # muted) audio out explicitly. Raw input pads are split by ffmpeg
        # itself, but the volume filter's output is not.
        if len(keep_segments) > 1:
            asplit = audio.filter_multi_output('asplit', len(keep_segments))
            audio_sources = [asplit[i] for i in range(len(keep_segments))]
        else:
            audio_sources = [audio]

        # Build filter graph
        # For each keep segment, we create a trim and atrim
        v_segments = []
        a_segments = []

        for i, (start, end) in enumerate(keep_segments):
            a = audio_sources[i].filter('atrim', start=start, end=end).filter('asetpts', 'PTS-STARTPTS')
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

    def cut_segments(
        self,
        input_path: str,
        output_path: str,
        segments_to_remove: list[tuple[float, float]],
        media_type: str = "audio"
    ):
        """Cut (remove) specified segments from media while maintaining sync."""
        self.apply_edits(
            input_path, output_path,
            segments_to_cut=segments_to_remove,
            media_type=media_type
        )

    def mute_segments(
        self,
        input_path: str,
        output_path: str,
        segments_to_mute: list[tuple[float, float]],
        media_type: str = "audio"
    ):
        """Mute (silence) specified segments in media."""
        self.apply_edits(
            input_path, output_path,
            segments_to_mute=segments_to_mute,
            media_type=media_type
        )

    def _merge_segments(self, segments: list[tuple[float, float]]) -> list[tuple[float, float]]:
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


def decode_pcm_mono(media_path: str, sample_rate: int = DECODE_SAMPLE_RATE) -> np.ndarray:
    """
    Decode any FFmpeg-readable media to mono float32 PCM at ``sample_rate``.

    Raises rather than swallowing the failure, because the two callers need
    different answers to it. The waveform route can shrug and draw a flat line;
    dead-air detection cannot, since "I could not decode this" and "this file is
    silent" would otherwise be the same empty result - and one of those means
    deleting audio nobody confirmed was empty.

    The array is a **read-only** view over FFmpeg's stdout, not a copy. An hour
    of audio is ~115 MB at 8 kHz f32, and copying held two of those at once at
    the peak of every waveform request and every scrub. Every caller here reads:
    peaks slice it, ``levels.find_quiet_regions`` reshapes and casts (both of
    which work on a read-only array, and the cast copies anyway). A caller that
    genuinely needs to write should ``.copy()`` the part it is writing to -
    numpy raises on an in-place write rather than corrupting anything, so the
    mistake is loud.
    """
    out, _ = (
        ffmpeg
        .input(media_path)
        .output('-', format='f32le', acodec='pcm_f32le', ac=1, ar=str(sample_rate))
        .run(capture_stdout=True, capture_stderr=True)
    )
    return np.frombuffer(out, dtype=np.float32)


def generate_waveform_peaks(
    audio_path: str,
    num_peaks: int = 800
) -> list[float]:
    """
    Generate waveform peaks using FFmpeg and numpy (no pydub).

    Written to keep exactly one copy of the decoded audio in memory. The
    normalizing maximum used to come from ``np.max(np.abs(samples))``, which
    allocates a whole second array the size of the recording just to find one
    number; the largest magnitude is the larger of the max and the negated min,
    and neither of those allocates.
    """
    try:
        samples = decode_pcm_mono(audio_path)

        if len(samples) == 0:
            return [0.0] * num_peaks

        # Calculate samples per peak
        samples_per_peak = max(1, len(samples) // num_peaks)

        peaks = []
        # Max amplitude for normalization, without materializing abs(samples).
        max_amplitude = float(max(samples.max(), -samples.min())) or 1.0

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
