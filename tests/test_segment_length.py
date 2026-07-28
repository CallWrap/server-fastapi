from callwrap_api.quality.checks.segment_length import check_segment_length
from callwrap_api.quality.config import CheckConfig

from callwrap_ai.schemas import Speaker, Transcript, Utterance


def make_config(**overrides) -> CheckConfig:
    defaults = dict(
        name="check_segment_length",
        enabled=True,
        threshold=0.10,
        higher_is_better=False,
        action_on_fail="human_review",
        params={"min_seconds": 0.5, "max_seconds": 60.0},
        version="test-v1",
    )
    defaults.update(overrides)
    return CheckConfig(**defaults)


def u(index, start, end):
    return Utterance(index=index, speaker=Speaker.CUSTOMER, text="말", start=start, end=end, confidence=0.9)


def test_normal_lengths_pass():
    utterances = [u(i, 0.0, 5.0) for i in range(5)]
    result = check_segment_length(Transcript(utterances=utterances), make_config())

    assert result.passed is True
    assert result.details["short_count"] == 0
    assert result.details["long_count"] == 0


def test_short_utterance_detected():
    utterances = [u(i, 0.0, 5.0) for i in range(9)]
    utterances.append(u(9, 0.0, 0.2))
    result = check_segment_length(Transcript(utterances=utterances), make_config())

    assert result.details["short_count"] == 1


def test_long_utterance_detected():
    utterances = [u(i, 0.0, 5.0) for i in range(9)]
    utterances.append(u(9, 0.0, 90.0))
    result = check_segment_length(Transcript(utterances=utterances), make_config())

    assert result.details["long_count"] == 1


def test_corrupted_duration_counted_separately():
    utterances = [u(i, 0.0, 5.0) for i in range(9)]
    utterances.append(u(9, 5.0, 2.0))  # end < start
    result = check_segment_length(Transcript(utterances=utterances), make_config())

    assert result.details["corrupted_count"] == 1
    assert result.details["short_count"] == 0
    assert result.details["long_count"] == 0


def test_boundary_values_are_normal():
    utterances = [u(0, 0.0, 0.5), u(1, 0.0, 60.0)]  # 정확히 경계값
    result = check_segment_length(Transcript(utterances=utterances), make_config())

    assert result.details["short_count"] == 0
    assert result.details["long_count"] == 0
    assert result.passed is True


def test_fails_when_ratio_exceeds_threshold():
    utterances = [u(i, 0.0, 5.0) for i in range(8)]
    utterances += [u(i, 0.0, 0.1) for i in range(8, 10)]  # 20% 짧음
    result = check_segment_length(Transcript(utterances=utterances), make_config())

    assert result.passed is False
    assert result.action == "human_review"


def test_empty_transcript_passes():
    result = check_segment_length(Transcript(utterances=[]), make_config())

    assert result.passed is True
    assert result.action == "pass"