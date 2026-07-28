from callwrap_api.quality.checks.repetition_and_gaps import check_repetition_and_gaps
from callwrap_api.quality.config import CheckConfig

from callwrap_ai.schemas import Speaker, Transcript, Utterance


def make_config(**overrides) -> CheckConfig:
    defaults = dict(
        name="check_repetition_and_gaps",
        enabled=True,
        threshold=0.10,
        higher_is_better=False,
        action_on_fail="retry",
        params={"ngram_size": 5, "max_ngram_repeats": 3, "min_chars_per_second": 1.0},
        version="test-v1",
    )
    defaults.update(overrides)
    return CheckConfig(**defaults)


def make_utterance(index, text, start=0.0, end=10.0):
    return Utterance(index=index, speaker=Speaker.CUSTOMER, text=text, start=start, end=end, confidence=0.9)


NORMAL_TEXT = "안녕하세요 상담원입니다 무엇을 도와드릴까요 확인해보겠습니다"
REPEATED_WORD_TEXT = " ".join(["네"] * 20)
REPEATED_PHRASE_TEXT = " ".join(["잠시만요 확인 중입니다 기다려 주세요"] * 3)


def test_passes_normal_text():
    transcript = Transcript(utterances=[make_utterance(i, NORMAL_TEXT) for i in range(10)])
    result = check_repetition_and_gaps(transcript, make_config())

    assert result.passed is True
    assert result.details["repetition_count"] == 0
    assert result.details["under_text_count"] == 0


def test_detects_single_word_repetition():
    utterances = [make_utterance(i, NORMAL_TEXT) for i in range(9)]
    utterances.append(make_utterance(9, REPEATED_WORD_TEXT))
    result = check_repetition_and_gaps(Transcript(utterances=utterances), make_config())

    assert result.details["repetition_count"] == 1
    assert result.passed is True  # 10개 중 1개(10%) — threshold(0.10) 이내


def test_detects_phrase_block_repetition():
    utterances = [make_utterance(i, NORMAL_TEXT) for i in range(9)]
    utterances.append(make_utterance(9, REPEATED_PHRASE_TEXT))
    result = check_repetition_and_gaps(Transcript(utterances=utterances), make_config())

    assert result.details["repetition_count"] == 1


def test_fails_when_repetition_ratio_exceeds_threshold():
    utterances = [make_utterance(i, NORMAL_TEXT) for i in range(7)]
    utterances += [make_utterance(i, REPEATED_WORD_TEXT) for i in range(7, 10)]
    result = check_repetition_and_gaps(Transcript(utterances=utterances), make_config())

    assert result.passed is False
    assert result.action == "retry"


def test_detects_under_text():
    utterances = [make_utterance(i, NORMAL_TEXT) for i in range(9)]
    utterances.append(make_utterance(9, "네네네", start=0.0, end=10.0))
    result = check_repetition_and_gaps(Transcript(utterances=utterances), make_config())

    assert result.details["under_text_count"] == 1


def test_zero_duration_utterance_excluded_from_under_text():
    utterances = [make_utterance(i, NORMAL_TEXT) for i in range(9)]
    utterances.append(make_utterance(9, "네", start=5.0, end=5.0))
    result = check_repetition_and_gaps(Transcript(utterances=utterances), make_config())

    assert result.details["under_text_count"] == 0


def test_sample_size_zero_forces_human_review():
    result = check_repetition_and_gaps(Transcript(utterances=[]), make_config())

    assert result.action == "human_review"
    assert result.passed is False


def test_utterance_flagged_once_even_if_both_conditions_match():
    utterances = [make_utterance(i, NORMAL_TEXT) for i in range(9)]
    utterances.append(make_utterance(9, REPEATED_WORD_TEXT, start=0.0, end=100.0))
    result = check_repetition_and_gaps(Transcript(utterances=utterances), make_config())

    assert round(result.score * 10) == 1  # 반복+과소 둘 다 걸려도 분자는 1