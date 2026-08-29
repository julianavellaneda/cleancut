"""
Tests for Scrubber.detect_filler_words.

Two regressions are locked down here, both surfaced by the eval harness rather
than by a bug report:

- `FILLER_WORDS` held "you know", but matching walked one word at a time, so a
  multi-word entry in that set could never fire. It sat there looking like
  coverage for two years' worth of the most common filler in English.
- The set held "hm" and Whisper writes the same sound as "Hmm". A filler is a
  noise before it is a word and the model picks a spelling freely, so the
  spellings it actually emits have to be listed.

The third known miss is not fixable here: Whisper dropped "Er," from the demo
clip's transcript altogether, and a detector that reads the transcript cannot
find a word that is not in it.
"""

import pytest

from app.analysis.transcriber import Segment, TranscriptResult, Word
from app.services.scrubber import Scrubber


def _transcript(words, gap=0.0):
    """One segment whose words run back to back from t=0, 0.2s each."""
    built = []
    t = 0.0
    for text in words:
        built.append(Word(text=text, start=t, end=t + 0.2, probability=0.9))
        t += 0.2 + gap
    text = " ".join(w.strip() for w in words)
    return TranscriptResult(
        segments=[Segment(text=text, start=0.0, end=t, words=built)],
        language="en",
        duration=t,
    )


def test_a_two_word_filler_is_found_as_one_suggestion():
    found = Scrubber.detect_filler_words(_transcript([" you", " know,", " the", " thing"]))

    assert len(found) == 1
    assert found[0].text == "you know,"
    assert (found[0].start_time, found[0].end_time) == (0.0, 0.4)


def test_a_bare_you_is_not_a_filler():
    """The phrase is the filler; the pronoun on its own is the sentence."""
    assert Scrubber.detect_filler_words(_transcript([" what", " changed", " for", " you"])) == []


def test_the_phrase_wins_over_the_words_inside_it():
    """
    "know" is not in the set, so a word-at-a-time pass would emit nothing here
    even after the phrase was added, if the phrase were checked second.
    """
    found = Scrubber.detect_filler_words(_transcript([" I", " mean,", " yes"]))

    assert [v.text for v in found] == ["I mean,"]


@pytest.mark.parametrize("spelling", ["Hmm.", "Um,", "Umm", "uhh", "Er,", "Ah,"])
def test_whisper_spelling_variants_all_count(spelling):
    found = Scrubber.detect_filler_words(_transcript([" So,", f" {spelling}", " right"]))

    assert [v.text for v in found] == [spelling]


def test_agreement_noises_are_left_alone():
    """
    "mhm" and "uh-huh" are a spoken "yes", not hesitation. Cutting one deletes
    an answer, which is a worse error than leaving a filler in.
    """
    assert Scrubber.detect_filler_words(_transcript([" Mhm.", " Uh-huh."])) == []


def test_adjacent_fillers_merge_into_one_edit():
    found = Scrubber.detect_filler_words(_transcript([" So,", " um,", " you", " know,", " yes"]))

    assert len(found) == 1
    assert found[0].text == "um, you know,"
    assert found[0].reasoning == "Detected multiple consecutive filler words."


def test_fillers_far_apart_stay_separate():
    found = Scrubber.detect_filler_words(_transcript([" um,", " a", " b", " c", " uh"], gap=0.6))

    assert len(found) == 2


# --- words that are only sometimes fillers ----------------------------------


def test_an_unevidenced_like_is_suggested_but_not_trusted():
    """
    Still found - in a seminar recording it usually is a hesitation - but
    nothing around it says so, and `auto_scrub` cutting it unattended turns
    "email us like at grow.spark" into a sentence missing a word.
    """
    found = Scrubber.detect_filler_words(_transcript([" email", " us", " like", " at"]))

    assert [v.text for v in found] == ["like"]
    assert found[0].is_ambiguous is True
    assert "ordinary word" in found[0].reasoning


def test_a_comma_wrapped_like_is_evidenced():
    """Whisper punctuated it as an aside, which is the cue."""
    found = Scrubber.detect_filler_words(_transcript([" it", " was,", " like,", " huge"]))

    assert [v.text for v in found] == ["like,"]
    assert found[0].is_ambiguous is False


def test_a_like_leaning_on_a_hesitation_is_evidenced():
    """"um like" is a stumble however it was punctuated."""
    found = Scrubber.detect_filler_words(_transcript([" so", " um", " like", " yeah"]))

    assert found[-1].is_ambiguous is False


def test_a_sentence_final_like_is_not_evidenced_by_its_full_stop():
    """
    A full stop can open the gap a hesitation drops into but never closes one:
    "that's what I like." is the sentence this must not cut unattended.
    """
    found = Scrubber.detect_filler_words(_transcript([" what", " I", " like."]))

    assert [v.is_ambiguous for v in found] == [True]


@pytest.mark.parametrize("words,expected", [
    ([" and,", " you", " know,", " let's", " dive"], False),
    ([" do", " you", " know", " the", " number"], True),
    # Half a bracket is not a bracket: "do you know," is a real question with a
    # comma after it, not an aside dropped into the middle of one.
    ([" do", " you", " know,", " the", " number"], True),
])
def test_the_phrases_are_judged_the_same_way(words, expected):
    """Both phrases are ambiguous entries; the punctuation is what decides."""
    found = Scrubber.detect_filler_words(_transcript(words))

    assert [v.is_ambiguous for v in found] == [expected]


def test_a_merged_span_is_only_as_safe_as_its_least_certain_member():
    """
    The merge covers the "um" too, so laundering the run's certainty would put
    an unevidenced "like" inside an auto-cut.
    """
    found = Scrubber.detect_filler_words(_transcript([" I", " like", " that", " um"]))

    assert len(found) == 1
    assert found[0].is_ambiguous is True
    assert "check before cutting" in found[0].reasoning


@pytest.mark.parametrize("spelling", ["Um,", "uh", "Hmm", "ah", "er"])
def test_a_sound_needs_no_corroboration(spelling):
    """
    There is no sentence in which "umm" carries meaning, so the spelling is the
    whole of the evidence.
    """
    found = Scrubber.detect_filler_words(_transcript([" and", f" {spelling}", " then"]))

    assert [v.is_ambiguous for v in found] == [False]


def test_the_two_sets_partition_the_filler_words():
    """One owner for the pair - a word in both would be judged by whichever
    branch ran first."""
    assert not (Scrubber.UNAMBIGUOUS_FILLERS & Scrubber.AMBIGUOUS_FILLERS)
    assert Scrubber.FILLER_WORDS == (
        Scrubber.UNAMBIGUOUS_FILLERS | Scrubber.AMBIGUOUS_FILLERS
    )


def test_every_multi_word_entry_lives_in_the_phrase_list():
    """
    The bug this file exists for, as an assertion: a space in FILLER_WORDS is
    dead coverage, since matching there is word by word.
    """
    assert not [w for w in Scrubber.FILLER_WORDS if " " in w]
