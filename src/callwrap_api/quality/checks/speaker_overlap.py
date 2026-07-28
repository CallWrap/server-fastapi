"""체크 ③ — 화자 겹침. 담당: 이정민.

서로 다른 화자(상담사/고객)의 발화가 시간상 겹친 비율을 판정한다.
score = 겹친 시간 / 전체 발화 시간(무음 제외, 발화 구간들의 합집합).
낮을수록 좋음(higher_is_better=false), threshold(0.10) 초과 시 실패 → human_review.
retry가 아니라 human_review인 이유: 화자분리(pyannote)가 무너진 거라 재처리해도
같은 결과가 나온다.

1. 분모("전체 발화 구간 시간")는 통화 전체 길이가 아니라 발화 구간들의 합집합(union)
   시간이다. 통화 전체로 하면 무음 구간 때문에 비율이 왜곡된다.
2. 발화가 0개거나 1개(겹칠 대상 자체가 없음)면 action="pass"로 처리한다.
   체크①②의 human_review(판단 근거 없음)와는 다른 논리 — 여긴 애초에 위반이
   불가능한 상황이라 자명하게 문제없다고 본다. (같은 이유로 전체 발화 시간이
   0인 degenerate 케이스도 pass.)
3. 계산 방식: 화자별로 발화 구간을 각각 병합(merge — 같은 화자끼리 겹치는 것도
   하나로 합쳐지므로 같은 화자 겹침은 자연스럽게 무시됨) → 두 병합 리스트 간
   교집합 길이 합산. 화자가 상담사/고객 2종뿐이라 3자 겹침 케이스는 없다.
"""

from callwrap_api.quality.config import CheckConfig
from callwrap_api.schemas.quality import Action, GateResult, decide_passed

from callwrap_ai.schemas import Speaker, Transcript

CHECK_NAME = "check_speaker_overlap"


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:  # 겹치거나 맞닿음
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _total_duration(intervals: list[tuple[float, float]]) -> float:
    return sum(end - start for start, end in intervals)


def _overlap_duration(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """병합된(겹침 없는) 두 구간 리스트 사이의 총 교집합 길이."""
    i = j = 0
    total = 0.0
    while i < len(a) and j < len(b):
        start = max(a[i][0], b[j][0])
        end = min(a[i][1], b[j][1])
        if start < end:
            total += end - start
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def check_speaker_overlap(transcript: Transcript, config: CheckConfig) -> GateResult:
    utterances = transcript.utterances

    if not utterances:
        return GateResult(
            check_name=CHECK_NAME,
            passed=True,
            score=0.0,
            threshold=config.threshold,
            higher_is_better=config.higher_is_better,
            action="pass",
            reason=None,
            details={
                "sample_size": 0,
                "checked_at_version": config.version,
                "total_speaking_seconds": 0.0,
                "overlap_seconds": 0.0,
            },
        )

    counselor = [(u.start, u.end) for u in utterances if u.speaker == Speaker.COUNSELOR]
    customer = [(u.start, u.end) for u in utterances if u.speaker == Speaker.CUSTOMER]

    merged_counselor = _merge_intervals(counselor)
    merged_customer = _merge_intervals(customer)
    total_speaking = _total_duration(_merge_intervals(counselor + customer))
    overlap = _overlap_duration(merged_counselor, merged_customer)

    if total_speaking <= 0:
        return GateResult(
            check_name=CHECK_NAME,
            passed=True,
            score=0.0,
            threshold=config.threshold,
            higher_is_better=config.higher_is_better,
            action="pass",
            reason=None,
            details={
                "sample_size": len(utterances),
                "checked_at_version": config.version,
                "total_speaking_seconds": 0.0,
                "overlap_seconds": 0.0,
            },
        )

    score = overlap / total_speaking
    passed = decide_passed(score, config.threshold, config.higher_is_better)
    action: Action = "pass" if passed else config.action_on_fail

    return GateResult(
        check_name=CHECK_NAME,
        passed=passed,
        score=score,
        threshold=config.threshold,
        higher_is_better=config.higher_is_better,
        action=action,
        reason=f"화자 겹침 비율 초과: {score:.2f}" if not passed else None,
        details={
            "sample_size": len(utterances),
            "checked_at_version": config.version,
            "total_speaking_seconds": round(total_speaking, 3),
            "overlap_seconds": round(overlap, 3),
        },
    )