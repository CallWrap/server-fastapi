import pytest

from callwrap_api.quality.checks.stt_confidence import check_stt_confidence
from callwrap_api.quality.config import CheckConfig

from callwrap_ai.schemas import Speaker, Transcript, Utterance


def make_config(**overrides) -> CheckConfig:
    defaults = dict(
        name="check_stt_confidence",
        enabled=True,
        threshold=0.15,
        higher_is_better=False,
        action_on_fail="retry",
        params={"low_confidence_below": 0.6, "on_missing_confidence": "skip"},
        version="test-v1",
    )
    defaults.update(overrides)
    return CheckConfig(**defaults)


def make_utterance(index, confidence, start=0.0, end=1.0, text="안녕하세요"):
    return Utterance(
        index=index, speaker=Speaker.CUSTOMER, text=text, start=start, end=end, confidence=confidence
    )


def test_passes_when_confidence_high():
    transcript = Transcript(utterances=[make_utterance(i, 0.9) for i in range(10)])
    result = check_stt_confidence(transcript, make_config())

    assert result.passed is True
    assert result.action == "pass"
    assert result.details["sample_size"] == 10
    assert result.details["low_confidence_count"] == 0


def test_fails_when_too_many_low_confidence():
    utterances = [make_utterance(i, 0.9) for i in range(7)]
    utterances += [make_utterance(i, 0.3) for i in range(7, 10)]
    result = check_stt_confidence(Transcript(utterances=utterances), make_config())

    assert result.passed is False
    assert result.action == "retry"
    assert result.score == pytest.approx(0.3)
    assert result.reason is not None


def test_none_confidence_is_skipped_from_denominator():
    utterances = [make_utterance(i, 0.9) for i in range(5)]
    utterances += [make_utterance(i, None) for i in range(5, 10)]
    result = check_stt_confidence(Transcript(utterances=utterances), make_config())

    assert result.details["sample_size"] == 5
    assert result.passed is True


def test_sample_size_zero_forces_human_review():
    transcript = Transcript(utterances=[make_utterance(i, None) for i in range(3)])
    result = check_stt_confidence(transcript, make_config())

    assert result.passed is False
    assert result.action == "human_review"
    assert result.details["sample_size"] == 0


def test_empty_transcript_forces_human_review():
    result = check_stt_confidence(Transcript(utterances=[]), make_config())

    assert result.action == "human_review"
    assert result.passed is False


def test_boundary_score_equals_threshold_passes():
    config = make_config(threshold=0.2)
    utterances = [make_utterance(i, 0.9) for i in range(8)]
    utterances += [make_utterance(i, 0.3) for i in range(8, 10)]
    result = check_stt_confidence(Transcript(utterances=utterances), config)

    assert result.score == pytest.approx(0.2)
    assert result.passed is True


def test_details_contains_required_keys():
    result = check_stt_confidence(Transcript(utterances=[make_utterance(0, 0.9)]), make_config())

    assert "sample_size" in result.details
    assert result.details["checked_at_version"] == "test-v1"