"""
Tests for Scrubber.detect_silence and the level pass behind it.

The regression these lock down: "Dead Air" used to mean nothing more than "no
Whisper segment covers this span". Room tone, applause, ambience or a music bed
all leave such a span, so all of them were offered as cuts - and under
`auto_scrub` they were pre-accepted and removed with no human in the loop.
Voice activity detection would not have helped; measured on the demo fixture,
Silero VAD flagged 3.7s of pink noise as dead air just as the gap detector did.

So detection now needs both signals to agree: the transcript proposes a span,
and an RMS pass has to confirm the audio there is actually below a level floor.
The confirmed sub-interval is what gets emitted, which also tightens boundaries
that used to run past the acoustic silence and clip the next line's onset.

The level maths is exercised on plain numpy arrays with no media anywhere; the
end-to-end case builds its room-tone variant with FFmpeg at test time, since
`tests/README.md` forbids committing media.
"""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.analysis.transcriber import Segment, TranscriptResult
from app.services import levels
from app.services.levels import DEFAULT_FLOOR_DB, find_quiet_regions
from app.services.media_editor import decode_pcm_mono
from app.services.scrubber import Scrubber

SR = 8000
FRAME = levels.FRAME_SECONDS  # 0.05s - the resolution of every boundary below

# Loud enough to sit far above any plausible floor; the maths only cares that
# it is not near -50 dBFS.
LOUD = 0.5

DEMO_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "demo"
DEMO_MP3 = DEMO_DIR / "demo_seminar.mp3"

# The three planted pauses, measured with `ffmpeg -af silencedetect=n=-50dB`.
# These are what a correct detector should report, not what the transcript says.
GROUND_TRUTH_PAUSES = [(13.297, 16.270), (34.202, 37.914), (60.160, 63.656)]

# One 50ms frame, plus a hair. A detector that is genuinely wrong is out by
# hundreds of milliseconds, not by a frame.
BOUNDARY_TOLERANCE = 0.06

# The window the room-tone variant refills with pink noise.
ROOM_TONE_WINDOW = (34.3, 37.8)


def _signal(*spans) -> np.ndarray:
    """Concatenate (seconds, amplitude) spans into one mono buffer at 8 kHz."""
    return np.concatenate([
        np.full(int(round(seconds * SR)), amplitude, dtype=np.float32)
        for seconds, amplitude in spans
    ])


def _transcript(*spans, duration: float) -> TranscriptResult:
    """A transcript with a segment over each (start, end) span. Words unused here."""
    return TranscriptResult(
        segments=[Segment(text="words", start=s, end=e, words=[]) for s, e in spans],
        language="en",
        duration=duration,
    )


def _dead_air(violations):
    return [v for v in violations if v.label == "Dead Air"]


# --------------------------------------------------------------------------
# find_quiet_regions - the level maths, on synthetic arrays
# --------------------------------------------------------------------------

def test_fully_silent_buffer_is_one_region():
    """The whole buffer is below the floor, so the whole buffer comes back."""
    assert find_quiet_regions(np.zeros(SR * 3, dtype=np.float32), SR) == [(0.0, 3.0)]


def test_fully_loud_buffer_has_no_regions():
    """Nothing is below the floor, so nothing is a candidate for a cut."""
    assert find_quiet_regions(_signal((3.0, LOUD)), SR) == []


def test_alternating_runs_are_separated():
    """Each quiet run is its own region - they must not be merged across speech."""
    x = _signal((1.0, 0.0), (1.0, LOUD), (2.0, 0.0), (1.0, LOUD), (0.5, 0.0))
    assert find_quiet_regions(x, SR) == [(0.0, 1.0), (2.0, 4.0), (5.0, 5.5)]


def test_region_at_the_very_start():
    """A leading silence must not be lost to an off-by-one at index 0."""
    assert find_quiet_regions(_signal((0.5, 0.0), (2.0, LOUD)), SR) == [(0.0, 0.5)]


def test_region_at_the_very_end():
    """A trailing silence must run to the end of the buffer, not stop a frame short."""
    assert find_quiet_regions(_signal((2.0, LOUD), (0.5, 0.0)), SR) == [(2.0, 2.5)]


def test_trailing_partial_frame_is_dropped_not_padded():
    """
    Zero-padding the final partial frame would read as silence whether or not it
    is, inventing a dead-air region at the end of every file whose length is not
    a whole number of frames.
    """
    x = np.concatenate([_signal((1.0, LOUD)), np.full(SR // 100, LOUD, dtype=np.float32)])
    assert find_quiet_regions(x, SR) == []


def test_buffer_shorter_than_one_frame_has_no_regions():
    """Too little audio to measure is not the same as silence."""
    assert find_quiet_regions(np.zeros(10, dtype=np.float32), SR) == []


def test_short_regions_are_still_returned():
    """
    Length filtering belongs after the intersection, not here: a four-second
    transcript gap holding only 0.3s of real quiet is the case that matters, and
    only the scrubber can see that.
    """
    x = _signal((1.0, LOUD), (0.1, 0.0), (1.0, LOUD))
    assert find_quiet_regions(x, SR) == [(1.0, 1.1)]


def test_floor_argument_changes_what_counts_as_quiet():
    """A quiet-but-audible bed is silence at one floor and content at another."""
    bed = _signal((2.0, 0.01))  # -40 dBFS
    assert find_quiet_regions(bed, SR, floor=-30.0) == [(0.0, 2.0)]
    assert find_quiet_regions(bed, SR, floor=-50.0) == []


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def test_floor_and_minimum_default_when_unset():
    assert levels.floor_db({}) == DEFAULT_FLOOR_DB
    assert levels.min_quiet_seconds({}) == levels.DEFAULT_MIN_QUIET_SECONDS


def test_floor_and_minimum_read_from_the_environment():
    assert levels.floor_db({"DEAD_AIR_FLOOR_DB": "-42.5"}) == -42.5
    assert levels.min_quiet_seconds({"DEAD_AIR_MIN_SECONDS": "1.5"}) == 1.5


def test_malformed_settings_fall_back_rather_than_crash():
    """A typo in .env should not take the API down - same rule as limits.py."""
    assert levels.floor_db({"DEAD_AIR_FLOOR_DB": "quiet please"}) == DEFAULT_FLOOR_DB
    assert levels.min_quiet_seconds({"DEAD_AIR_MIN_SECONDS": ""}) == levels.DEFAULT_MIN_QUIET_SECONDS


def test_non_positive_minimum_falls_back():
    """"0" would flag the gap between every two words; nobody means that."""
    assert levels.min_quiet_seconds({"DEAD_AIR_MIN_SECONDS": "0"}) == levels.DEFAULT_MIN_QUIET_SECONDS
    assert levels.min_quiet_seconds({"DEAD_AIR_MIN_SECONDS": "-3"}) == levels.DEFAULT_MIN_QUIET_SECONDS


# --------------------------------------------------------------------------
# detect_silence - the intersection
# --------------------------------------------------------------------------

def test_candidate_fully_quiet_is_emitted_whole():
    transcript = _transcript((0.0, 5.0), (10.0, 15.0), duration=15.0)
    found = _dead_air(Scrubber.detect_silence(transcript, [(5.0, 10.0)], min_silence_len=0.75))

    assert len(found) == 1
    assert (found[0].start_time, found[0].end_time) == (5.0, 10.0)
    assert found[0].action == "cut"


def test_partly_quiet_candidate_is_trimmed_to_the_quiet_part():
    """
    The point of the amplitude pass. Whisper's segment boundaries run loose, and
    emitting the transcript gap clipped the soft onset of the following line;
    the quiet sub-interval is what actually wants cutting.
    """
    transcript = _transcript((0.0, 5.0), (10.0, 15.0), duration=15.0)
    found = _dead_air(Scrubber.detect_silence(transcript, [(5.4, 9.2)], min_silence_len=0.75))

    assert len(found) == 1
    assert (found[0].start_time, found[0].end_time) == (5.4, 9.2)


def test_candidate_with_no_quiet_at_all_is_dropped():
    """
    The room-tone regression in miniature: five seconds nobody speaks over, but
    something is audible there, so it is not dead air and must not be offered.
    """
    transcript = _transcript((0.0, 5.0), (10.0, 15.0), duration=15.0)
    assert _dead_air(Scrubber.detect_silence(transcript, [(20.0, 25.0)], min_silence_len=0.75)) == []


def test_quiet_but_too_short_is_dropped():
    transcript = _transcript((0.0, 5.0), (10.0, 15.0), duration=15.0)
    assert _dead_air(Scrubber.detect_silence(transcript, [(5.0, 5.5)], min_silence_len=0.75)) == []


def test_a_noise_inside_a_gap_splits_it_into_two_suggestions():
    """
    A cough or a door mid-pause. The right edit is to cut around it rather than
    through it, so every qualifying sub-interval is offered separately.
    """
    transcript = _transcript((0.0, 5.0), (15.0, 20.0), duration=20.0)
    found = _dead_air(Scrubber.detect_silence(
        transcript, [(5.0, 9.0), (9.4, 15.0)], min_silence_len=0.75))

    assert [(v.start_time, v.end_time) for v in found] == [(5.0, 9.0), (9.4, 15.0)]


def test_leading_silence_is_confirmed_against_amplitude():
    transcript = _transcript((6.0, 10.0), duration=10.0)
    found = _dead_air(Scrubber.detect_silence(transcript, [(0.0, 5.7)], min_silence_len=0.75))

    assert len(found) == 1
    assert found[0].text == "[Initial Silence]"
    assert (found[0].start_time, found[0].end_time) == (0.0, 5.7)


def test_trailing_silence_is_confirmed_against_amplitude():
    transcript = _transcript((0.0, 4.0), duration=10.0)
    found = _dead_air(Scrubber.detect_silence(transcript, [(4.3, 10.0)], min_silence_len=0.75))

    assert len(found) == 1
    assert found[0].text == "[Final Silence]"
    assert (found[0].start_time, found[0].end_time) == (4.3, 10.0)


def test_transcript_with_no_segments_still_needs_confirmation():
    """
    An hour of music transcribes to nothing at all. "No speech" is not "no
    audio", so the whole-file case is a candidate like any other.
    """
    empty = TranscriptResult(segments=[], language="en", duration=60.0)

    assert _dead_air(Scrubber.detect_silence(empty, [], min_silence_len=0.75)) == []

    found = _dead_air(Scrubber.detect_silence(empty, [(0.0, 60.0)], min_silence_len=0.75))
    assert len(found) == 1
    assert found[0].text == "[Total Silence]"


def test_no_quiet_regions_means_no_suggestions():
    """
    ``None`` is "the level pass could not run". Falling back to transcript gaps
    would reinstate the exact bug this confirmation exists to prevent, and under
    auto_scrub that means deleting audio nobody confirmed was empty. The worker
    warns the user instead.
    """
    transcript = _transcript((0.0, 5.0), (10.0, 15.0), duration=15.0)
    assert Scrubber.detect_silence(transcript, None) == []
    assert Scrubber.detect_silence(transcript) == []


def test_minimum_length_defaults_to_the_configured_setting(monkeypatch):
    transcript = _transcript((0.0, 5.0), (10.0, 15.0), duration=15.0)
    monkeypatch.setenv("DEAD_AIR_MIN_SECONDS", "6.0")

    assert _dead_air(Scrubber.detect_silence(transcript, [(5.0, 10.0)])) == []


def test_reasoning_names_both_signals():
    """
    The suggestion has to say what was actually measured - a reviewer deciding
    whether to accept a cut needs to know it was confirmed, not merely inferred.
    """
    transcript = _transcript((0.0, 5.0), (10.0, 15.0), duration=15.0)
    reasoning = Scrubber.detect_silence(transcript, [(5.0, 10.0)], min_silence_len=0.75)[0].reasoning

    assert "dBFS" in reasoning
    assert "no speech" in reasoning


# --------------------------------------------------------------------------
# End to end on the demo fixture, including the room-tone false positive
# --------------------------------------------------------------------------

pytestmark_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or not DEMO_MP3.exists(),
    reason="needs ffmpeg and the demo fixture",
)


def _demo_transcript() -> TranscriptResult:
    """
    The demo clip's transcript, with each planted pause widened by a second.

    Built from `expected_violations.json` - the generator recorded every line's
    real offset - rather than by running Whisper, which would make this test
    slow and non-deterministic for no gain.

    The widening reproduces what Whisper actually does: measured on this clip
    its gaps ran ~0.24s longer than the acoustic silence and ate into the next
    line's onset. If the intersection works, that slop is trimmed back off and
    the emitted boundaries land on the amplitude ones regardless.
    """
    lines = json.loads((DEMO_DIR / "expected_violations.json").read_text())["lines"]
    slop = 1.0
    segments = []

    for i, line in enumerate(lines):
        start, end = line["start"], line["end"]
        if i > 0 and start - lines[i - 1]["end"] > 1.0:
            start += slop
        if i + 1 < len(lines) and lines[i + 1]["start"] - end > 1.0:
            end -= slop
        segments.append(Segment(text=line["text"], start=start, end=end, words=[]))

    return TranscriptResult(segments=segments, language="en", duration=74.0)


@pytest.fixture(scope="module")
def room_tone_mp3(tmp_path_factory):
    """
    The demo clip with planted pause 2 refilled with low-level pink noise.

    A stand-in for room tone, ambience, applause or a music bed - anything a
    user would never want silently deleted. Generated here rather than
    committed: fixtures in this repo stay synthetic and media stays out of git.
    """
    if shutil.which("ffmpeg") is None or not DEMO_MP3.exists():
        pytest.skip("needs ffmpeg and the demo fixture")

    lo, hi = ROOM_TONE_WINDOW
    out = tmp_path_factory.mktemp("roomtone") / "demo_seminar_roomtone.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(DEMO_MP3),
         "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.06:d=74",
         "-filter_complex",
         f"[1:a]volume=enable='between(t,{lo},{hi})':volume=1,"
         f"volume=enable='not(between(t,{lo},{hi}))':volume=0[amb];"
         f"[0:a][amb]amix=inputs=2:duration=first:normalize=0[out]",
         "-map", "[out]", "-ar", "24000", str(out)],
        capture_output=True, check=True,
    )
    return out


@pytestmark_ffmpeg
def test_level_pass_matches_ffmpeg_silencedetect():
    """
    Precondition - the rest of these tests prove nothing if the level pass does
    not agree with the reference implementation on the unmodified clip.
    """
    regions = [r for r in find_quiet_regions(decode_pcm_mono(str(DEMO_MP3)))
               if r[1] - r[0] >= 2.0]

    assert len(regions) == len(GROUND_TRUTH_PAUSES)
    for (start, end), (truth_start, truth_end) in zip(regions, GROUND_TRUTH_PAUSES):
        assert start == pytest.approx(truth_start, abs=BOUNDARY_TOLERANCE)
        assert end == pytest.approx(truth_end, abs=BOUNDARY_TOLERANCE)


@pytestmark_ffmpeg
def test_planted_pauses_are_flagged_at_amplitude_boundaries():
    """All three pauses found, with the transcript's slop trimmed back off."""
    found = _dead_air(Scrubber.detect_silence(
        _demo_transcript(),
        find_quiet_regions(decode_pcm_mono(str(DEMO_MP3))),
        min_silence_len=0.75,
    ))

    assert len(found) == len(GROUND_TRUTH_PAUSES)
    for violation, (truth_start, truth_end) in zip(found, GROUND_TRUTH_PAUSES):
        assert violation.start_time == pytest.approx(truth_start, abs=BOUNDARY_TOLERANCE)
        assert violation.end_time == pytest.approx(truth_end, abs=BOUNDARY_TOLERANCE)


@pytestmark_ffmpeg
def test_room_tone_variant_is_audibly_above_the_floor(room_tone_mp3):
    """
    Precondition. If the filter graph silently failed to mix the noise in, the
    regression test below would pass for entirely the wrong reason.
    """
    samples = decode_pcm_mono(str(room_tone_mp3))
    window = samples[int(34.5 * SR):int(37.5 * SR)]
    level = 20 * np.log10(np.sqrt((window.astype(np.float64) ** 2).mean()))

    assert level > DEFAULT_FLOOR_DB


@pytestmark_ffmpeg
def test_room_tone_is_not_flagged_as_dead_air(room_tone_mp3):
    """
    The regression. Nobody speaks over the room tone, so the transcript still
    proposes that span - and the old detector cut it. The level pass now vetoes
    it, while the two genuinely empty pauses are still found.
    """
    found = _dead_air(Scrubber.detect_silence(
        _demo_transcript(),
        find_quiet_regions(decode_pcm_mono(str(room_tone_mp3))),
        min_silence_len=0.75,
    ))

    overlapping = [v for v in found if v.start_time < 38.5 and v.end_time > 33.5]
    assert overlapping == [], "room tone was flagged as dead air"

    assert len(found) == 2
    for violation, (truth_start, truth_end) in zip(found, [GROUND_TRUTH_PAUSES[0],
                                                           GROUND_TRUTH_PAUSES[2]]):
        assert violation.start_time == pytest.approx(truth_start, abs=BOUNDARY_TOLERANCE)
        assert violation.end_time == pytest.approx(truth_end, abs=BOUNDARY_TOLERANCE)
