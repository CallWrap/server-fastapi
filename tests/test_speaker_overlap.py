from callwrap_api.quality.checks.speaker_overlap import check_speaker_overlap
from callwrap_api.quality.config import CheckConfig

from callwrap_ai.schemas import Speaker, Transcript, Utterance


def make_config(**overrides) -> CheckConfig:
    defaults = dict(
        name="check_speaker_overlap",
        enabled=True,
        threshold=0.10,
        higher_is_better=False,
        action_on_fail="human_review",
        params={},
        version="test-v1",
    )
    defaults.update(overrides)
    return CheckConfig(**defaults)


def u(index, speaker, start, end):
    return Utterance(index=index, speaker=speaker, text="말", start=start, end=end, confidence=0.9)


def test_no_overlap_passes():
    utterances = [
        u(0, Speaker.COUNSELOR, 0.0, 2.0),
        u(1, Speaker.CUSTOMER, 2.0, 4.0),
        u(2, Speaker.COUNSELOR, 4.0, 6.0),
    ]
    result = check_speaker_overlap(Transcript(utterances=utterances), make_config())

    assert result.passed is True
    assert result.details["overlap_seconds"] == 0.0


def test_small_overlap_within_threshold_passes():
    # 전체 발화시간 10초 중 0.5초만 겹침 -> 5%
    utterances = [
        u(0, Speaker.COUNSELOR, 0.0, 5.0),
        u(1, Speaker.CUSTOMER, 4.5, 9.5),
    ]
    result = check_speaker_overlap(Transcript(utterances=utterances), make_config())

    assert result.passed is True


def test_large_overlap_fails_to_human_review():
    utterances = [
        u(0, Speaker.COUNSELOR, 0.0, 5.0),
        u(1, Speaker.CUSTOMER, 1.0, 4.0),  # 상담사 발화 안에 통째로 겹침
    ]
    result = check_speaker_overlap(Transcript(utterances=utterances), make_config())

    assert result.passed is False
    assert result.action == "human_review"


def test_same_speaker_overlap_is_ignored():
    utterances = [
        u(0, Speaker.COUNSELOR, 0.0, 3.0),
        u(1, Speaker.COUNSELOR, 1.0, 4.0),  # 같은 화자끼리 겹침 -> 무시돼야 함
    ]
    result = check_speaker_overlap(Transcript(utterances=utterances), make_config())

    assert result.details["overlap_seconds"] == 0.0
    assert result.passed is True


def test_empty_transcript_passes():
    result = check_speaker_overlap(Transcript(utterances=[]), make_config())

    assert result.passed is True
    assert result.action == "pass"


def test_single_utterance_passes():
    result = check_speaker_overlap(
        Transcript(utterances=[u(0, Speaker.COUNSELOR, 0.0, 5.0)]), make_config()
    )

    assert result.passed is True


def test_details_contains_required_keys():
    result = check_speaker_overlap(
        Transcript(utterances=[u(0, Speaker.COUNSELOR, 0.0, 1.0)]), make_config()
    )

    assert "sample_size" in result.details
    assert result.details["checked_at_version"] == "test-v1"