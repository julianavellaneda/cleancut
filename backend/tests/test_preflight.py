"""
Tests for the startup environment check.

Both hard dependencies are only reached inside the background worker, minutes
after an upload, so without a preflight a missing key or a missing ffmpeg
surfaces as a mysteriously failed job rather than a setup error.
"""

import pytest

from app.preflight import (
    PreflightError,
    missing_requirements,
    model_notice,
    verify_environment,
)

FULL_ENV = {"OPENAI_API_KEY": "sk-test"}


def all_present(name):
    return f"/usr/local/bin/{name}"


def nothing_present(name):
    return None


def test_complete_environment_has_no_problems():
    assert missing_requirements(FULL_ENV, all_present) == []


def test_complete_environment_starts():
    verify_environment(FULL_ENV, all_present)  # must not raise


def test_missing_api_key_is_reported():
    problems = missing_requirements({}, all_present)

    assert len(problems) == 1
    assert "OPENAI_API_KEY" in problems[0]


def test_blank_api_key_counts_as_missing():
    """`OPENAI_API_KEY=` in .env sets the variable to an empty string."""
    problems = missing_requirements({"OPENAI_API_KEY": "   "}, all_present)

    assert any("OPENAI_API_KEY" in p for p in problems)


def test_missing_ffmpeg_is_reported():
    problems = missing_requirements(FULL_ENV, nothing_present)

    assert any("ffmpeg" in p for p in problems)
    assert any("brew install ffmpeg" in p for p in problems)


def test_ffprobe_checked_separately_from_ffmpeg():
    """ffprobe is packaged apart from ffmpeg on some distributions."""
    problems = missing_requirements(
        FULL_ENV, lambda name: None if name == "ffprobe" else "/usr/bin/ffmpeg"
    )

    assert len(problems) == 1
    assert "ffprobe" in problems[0]


def test_every_problem_is_reported_at_once():
    """One restart per missing dependency would be a miserable setup loop."""
    problems = missing_requirements({}, nothing_present)

    assert len(problems) == 3


def test_verify_raises_listing_all_problems():
    with pytest.raises(PreflightError) as excinfo:
        verify_environment({}, nothing_present)

    message = str(excinfo.value)
    assert "OPENAI_API_KEY" in message
    assert "ffmpeg" in message
    assert "ffprobe" in message


def test_skip_preflight_allows_a_broken_environment(capsys):
    verify_environment({"SKIP_PREFLIGHT": "1"}, nothing_present)

    assert "WARNING" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["true", "YES", "1"])
def test_skip_preflight_accepts_common_truthy_spellings(value):
    verify_environment({"SKIP_PREFLIGHT": value}, nothing_present)


@pytest.mark.parametrize("value", ["0", "false", "", "no"])
def test_skip_preflight_off_still_raises(value):
    with pytest.raises(PreflightError):
        verify_environment({"SKIP_PREFLIGHT": value}, nothing_present)


def test_app_runs_preflight_before_serving(monkeypatch):
    """
    The check has to be wired into the lifespan, not merely importable.

    Pin it here: a broken environment must stop startup rather than let the
    server come up and fail every job.
    """
    from fastapi.testclient import TestClient

    import app.main as main

    monkeypatch.setattr(
        main,
        "verify_environment",
        lambda: (_ for _ in ()).throw(PreflightError("boom")),
    )

    with pytest.raises(PreflightError):
        with TestClient(main.app):
            pass


def test_the_mock_provider_needs_no_key():
    assert missing_requirements({"CLEANCUT_MODEL": "mock:demo"}, all_present) == []


def test_the_mock_provider_still_needs_ffmpeg():
    """No key is not no requirements: transcription and export still run FFmpeg."""
    problems = missing_requirements({"CLEANCUT_MODEL": "mock:demo"}, nothing_present)

    assert any("ffmpeg" in p for p in problems)


def test_a_missing_key_suggests_the_mock_as_a_way_in():
    problems = missing_requirements({}, all_present)

    assert "mock:demo" in problems[0]


def test_startup_names_the_real_model():
    assert model_notice({"CLEANCUT_MODEL": "anthropic:claude-opus-5"}) == (
        "Analysis model: anthropic:claude-opus-5"
    )


def test_startup_names_the_default_when_unset():
    assert model_notice({}) == "Analysis model: openai:gpt-4o"


def test_startup_says_nothing_about_a_spec_preflight_already_rejected():
    assert model_notice({"CLEANCUT_MODEL": "mistral:large"}) is None
