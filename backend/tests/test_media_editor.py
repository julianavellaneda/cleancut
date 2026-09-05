"""
Tests for the FFmpeg filter graphs in MediaEditor.

These render real audio and decode the result, because the failure modes here
are silent: a filter graph that builds fine can still produce a file where the
mute never applied or the cut landed in the wrong place.

Two bugs these cover:
  - `volume` defaults to eval=once, evaluating `between(t,...)` a single time
    at t=0, which made mute_segments a no-op that still produced valid output.
  - A filter output can only feed one consumer, so the muted stream needs an
    explicit asplit before fanning out to the per-segment atrims.
"""

import subprocess

import ffmpeg
import numpy as np
import pytest

from app.services.media_editor import MediaEditor

# 44.1kHz keeps FFmpeg's audio frame at ~23ms. The `volume` filter evaluates
# its expression once per frame, so mute boundaries quantize to that; at 8kHz a
# frame is 128ms and the boundary assertions below could not resolve it.
SR = 44100
TONE_SECONDS = 10
SILENT_RMS = 0.005

# Frame quantization (~23ms) plus RMS window quantization (10ms), rounded up.
# A mute that genuinely failed is off by whole seconds, not tens of ms.
BOUNDARY_TOLERANCE = 0.08


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    """10s of continuous 1kHz tone - any silence in the output is our doing."""
    path = tmp_path_factory.mktemp("media") / "tone.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=1000:duration={TONE_SECONDS}",
            "-ar",
            str(SR),
            str(path),
        ],
        capture_output=True,
        check=True,
    )
    return path


def _samples(path):
    raw, _ = (
        ffmpeg.input(str(path))
        .output("-", format="f32le", acodec="pcm_f32le", ac=1, ar=str(SR))
        .run(capture_stdout=True, capture_stderr=True)
    )
    return np.frombuffer(raw, dtype=np.float32)


def _duration(path):
    return float(ffmpeg.probe(str(path))["format"]["duration"])


def _rms_windows(path, window_ms=10):
    """RMS per window. Windowing avoids mistaking a sine's zero crossings for silence."""
    s = _samples(path)
    w = SR * window_ms // 1000
    return np.array(
        [np.sqrt(np.mean(s[i * w : (i + 1) * w] ** 2)) for i in range(len(s) // w)]
    )


def _silent_span(path, window_ms=10):
    """(start, end) seconds of the contiguous silent run, or None."""
    rms = _rms_windows(path, window_ms)
    quiet = np.where(rms < SILENT_RMS)[0]
    if len(quiet) == 0:
        return None
    assert len(quiet) == quiet[-1] - quiet[0] + 1, "silence is not contiguous"
    return quiet[0] * window_ms / 1000, (quiet[-1] + 1) * window_ms / 1000


@pytest.fixture
def out(tmp_path):
    return tmp_path / "out.wav"


# --- cut only ---------------------------------------------------------------


def test_cut_only_shortens_by_removed_duration(tone, out):
    MediaEditor().apply_edits(str(tone), str(out), segments_to_cut=[(2.0, 3.0)])
    assert _duration(out) == pytest.approx(TONE_SECONDS - 1.0, abs=0.05)


def test_cut_only_leaves_no_silence(tone, out):
    """Cutting removes audio outright - it must not leave a silent gap behind."""
    MediaEditor().apply_edits(str(tone), str(out), segments_to_cut=[(2.0, 3.0)])
    assert _silent_span(out) is None


def test_multiple_cuts_are_all_removed(tone, out):
    MediaEditor().apply_edits(
        str(tone), str(out), segments_to_cut=[(1.0, 2.0), (5.0, 6.5), (8.0, 8.5)]
    )
    assert _duration(out) == pytest.approx(TONE_SECONDS - 3.0, abs=0.05)


def test_overlapping_cuts_are_merged_not_double_counted(tone, out):
    """Overlapping segments span 2.0-4.0, so exactly 2s should come off."""
    MediaEditor().apply_edits(
        str(tone), str(out), segments_to_cut=[(2.0, 3.5), (3.0, 4.0)]
    )
    assert _duration(out) == pytest.approx(TONE_SECONDS - 2.0, abs=0.05)


def test_cut_at_start_of_file(tone, out):
    MediaEditor().apply_edits(str(tone), str(out), segments_to_cut=[(0.0, 2.0)])
    assert _duration(out) == pytest.approx(TONE_SECONDS - 2.0, abs=0.05)


def test_cut_to_end_of_file(tone, out):
    MediaEditor().apply_edits(
        str(tone), str(out), segments_to_cut=[(8.0, TONE_SECONDS)]
    )
    assert _duration(out) == pytest.approx(8.0, abs=0.05)


def test_cutting_everything_raises(tone, out):
    with pytest.raises(ValueError, match="All segments were removed"):
        MediaEditor().apply_edits(
            str(tone), str(out), segments_to_cut=[(0.0, TONE_SECONDS)]
        )


# --- mute only --------------------------------------------------------------


def test_mute_only_preserves_duration(tone, out):
    MediaEditor().apply_edits(str(tone), str(out), segments_to_mute=[(5.0, 6.0)])
    assert _duration(out) == pytest.approx(TONE_SECONDS, abs=0.05)


def test_mute_actually_silences_the_segment(tone, out):
    """Guards the eval=once bug, where the file was valid but never muted."""
    MediaEditor().apply_edits(str(tone), str(out), segments_to_mute=[(5.0, 6.0)])
    span = _silent_span(out)
    assert span is not None, "mute produced no silence at all"
    assert span[0] == pytest.approx(5.0, abs=BOUNDARY_TOLERANCE)
    assert span[1] == pytest.approx(6.0, abs=BOUNDARY_TOLERANCE)


def test_mute_leaves_surrounding_audio_intact(tone, out):
    MediaEditor().apply_edits(str(tone), str(out), segments_to_mute=[(5.0, 6.0)])
    rms = _rms_windows(out)
    assert rms[0] > SILENT_RMS  # before
    assert rms[-1] > SILENT_RMS  # after


# --- mixed ------------------------------------------------------------------


def test_mixed_cut_and_mute_duration(tone, out):
    MediaEditor().apply_edits(
        str(tone), str(out), segments_to_cut=[(2.0, 3.0)], segments_to_mute=[(5.0, 6.0)]
    )
    assert _duration(out) == pytest.approx(TONE_SECONDS - 1.0, abs=0.05)


def test_mixed_mute_shifts_by_preceding_cut(tone, out):
    """
    The mute is requested at 5.0-6.0 on the original timeline. A 1s cut at
    2.0-3.0 happens before it, so in the exported file the silence must land
    at 4.0-5.0. Getting this backwards is the classic ordering bug.
    """
    MediaEditor().apply_edits(
        str(tone), str(out), segments_to_cut=[(2.0, 3.0)], segments_to_mute=[(5.0, 6.0)]
    )
    span = _silent_span(out)
    assert span is not None
    assert span[0] == pytest.approx(4.0, abs=BOUNDARY_TOLERANCE)
    assert span[1] == pytest.approx(5.0, abs=BOUNDARY_TOLERANCE)


def test_mute_before_cut_is_unshifted(tone, out):
    """A mute earlier than every cut keeps its original position."""
    MediaEditor().apply_edits(
        str(tone), str(out), segments_to_cut=[(7.0, 8.0)], segments_to_mute=[(2.0, 3.0)]
    )
    span = _silent_span(out)
    assert span is not None
    assert span[0] == pytest.approx(2.0, abs=BOUNDARY_TOLERANCE)


def test_many_cuts_with_mute_does_not_break_the_graph(tone, out):
    """
    Several cuts means several atrim branches all consuming the muted stream.
    Without an explicit asplit, FFmpeg rejects the graph outright.
    """
    MediaEditor().apply_edits(
        str(tone),
        str(out),
        segments_to_cut=[(1.0, 1.5), (3.0, 3.5), (6.0, 6.5), (8.0, 8.5)],
        segments_to_mute=[(4.5, 5.0)],
    )
    assert _duration(out) == pytest.approx(TONE_SECONDS - 2.0, abs=0.05)
    assert _silent_span(out) is not None


def test_no_edits_still_produces_output(tone, out):
    MediaEditor().apply_edits(str(tone), str(out))
    assert out.exists()
    assert _duration(out) == pytest.approx(TONE_SECONDS, abs=0.05)


# --- legacy wrappers --------------------------------------------------------


def test_cut_segments_wrapper(tone, out):
    MediaEditor().cut_segments(str(tone), str(out), [(2.0, 3.0)])
    assert _duration(out) == pytest.approx(TONE_SECONDS - 1.0, abs=0.05)


def test_mute_segments_wrapper(tone, out):
    MediaEditor().mute_segments(str(tone), str(out), [(5.0, 6.0)])
    assert _duration(out) == pytest.approx(TONE_SECONDS, abs=0.05)
    assert _silent_span(out) is not None


# --- segment merging (pure) -------------------------------------------------


@pytest.mark.parametrize(
    "segments,expected",
    [
        ([], []),
        ([(1.0, 2.0)], [(1.0, 2.0)]),
        ([(3.0, 4.0), (1.0, 2.0)], [(1.0, 2.0), (3.0, 4.0)]),  # sorted
        ([(1.0, 3.0), (2.0, 4.0)], [(1.0, 4.0)]),  # overlapping
        ([(1.0, 2.0), (2.0, 3.0)], [(1.0, 3.0)]),  # touching
        ([(1.0, 5.0), (2.0, 3.0)], [(1.0, 5.0)]),  # contained
        ([(1.0, 2.0), (3.0, 4.0)], [(1.0, 2.0), (3.0, 4.0)]),  # disjoint
    ],
)
def test_merge_segments(segments, expected):
    assert MediaEditor()._merge_segments(segments) == expected
