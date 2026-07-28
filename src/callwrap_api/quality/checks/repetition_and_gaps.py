"""체크 ② — 반복·과소 텍스트. 담당: 김규리.

[설명]
n-gram 반복(Whisper hallucination 전형)과 발화 길이 대비 과소 텍스트로 의심되는
발화 비율을 판정한다. score = 의심 발화 수 / 전체 발화 수. 낮을수록 좋음,
threshold(0.10) 초과 시 실패 → retry.

[결정 사항]
1. n-gram 단위는 어절(공백 기준 토큰)로 한다 (음절 단위 아님).
2. 반복 의심: 같은 어절 n-gram(ngram_size=5)이 연속 max_ngram_repeats(3)회 이상 등장.
3. 과소 텍스트 의심: len(text) / (end - start) < min_chars_per_second(1.0).
   단 end - start <= 0인 발화는 이 체크의 판정 대상에서 제외한다 — 체크④(segment_length, 정민 담당) 관할.
4. 분모(전체 발화 수)가 0이면 체크①과 동일하게 action="human_review"로 오버라이드, passed=False 직접 명시.
5. details에 repetition_count, under_text_count를 나눠 담는다 (튜닝용, 한 발화가 둘 다 해당해도 각각 카운트).

[공유 사항 없음] — stt/ 정규화와 무관하게 이 체크는 독립적으로 완결됨.
"""

from callwrap_api.quality.config import CheckConfig
from callwrap_api.schemas.quality import Action, GateResult, decide_passed

from callwrap_ai.schemas import Transcript

CHECK_NAME = "check_repetition_and_gaps"


from collections import Counter

def _has_ngram_repetition(text: str, ngram_size: int, max_repeats: int) -> bool:
    """어절 n-gram이 텍스트 안에서 max_repeats회 이상 등장하면 True.

    인접 윈도우 연속 비교가 아니라 전체 등장 빈도로 판정한다 — 그래야
    "네 네 네 네 네"류 단어 반복과 "구절 구절 구절"류 어절 단위 반복을 둘 다 잡는다.
    """
    words = text.split()
    if len(words) < ngram_size:
        return False
    ngrams = [tuple(words[i : i + ngram_size]) for i in range(len(words) - ngram_size + 1)]
    return any(count >= max_repeats for count in Counter(ngrams).values())


def _is_under_text(text: str, start: float, end: float, min_chars_per_second: float) -> bool:
    duration = end - start
    if duration <= 0:
        return False  
    return (len(text) / duration) < min_chars_per_second


def check_repetition_and_gaps(transcript: Transcript, config: CheckConfig) -> GateResult:
    ngram_size = config.params["ngram_size"]
    max_ngram_repeats = config.params["max_ngram_repeats"]
    min_chars_per_second = config.params["min_chars_per_second"]

    utterances = transcript.utterances
    sample_size = len(utterances)

    if sample_size == 0:
        return GateResult(
            check_name=CHECK_NAME,
            passed=False,
            score=0.0,
            threshold=config.threshold,
            higher_is_better=config.higher_is_better,
            action="human_review",
            reason="판정할 발화 없음: sample_size=0",
            details={
                "sample_size": 0,
                "checked_at_version": config.version,
                "repetition_count": 0,
                "under_text_count": 0,
            },
        )

    repetition_count = under_text_count = suspect_count = 0
    for u in utterances:
        is_rep = _has_ngram_repetition(u.text, ngram_size, max_ngram_repeats)
        is_under = _is_under_text(u.text, u.start, u.end, min_chars_per_second)
        repetition_count += is_rep
        under_text_count += is_under
        suspect_count += is_rep or is_under

    score = suspect_count / sample_size
    passed = decide_passed(score, config.threshold, config.higher_is_better)
    action: Action = "pass" if passed else config.action_on_fail

    return GateResult(
        check_name=CHECK_NAME,
        passed=passed,
        score=score,
        threshold=config.threshold,
        higher_is_better=config.higher_is_better,
        action=action,
        reason=f"반복·과소 텍스트 의심 발화 비율 초과: {score:.2f}" if not passed else None,
        details={
            "sample_size": sample_size,
            "checked_at_version": config.version,
            "repetition_count": repetition_count,
            "under_text_count": under_text_count,
        },
    )