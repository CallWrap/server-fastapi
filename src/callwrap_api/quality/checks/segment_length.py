"""체크 ④ — 세그먼트 길이. 담당: 이정민.

극단적으로 짧거나(<0.5초) 긴(>60초) 발화, 데이터가 파손된(end<start) 발화의 비율을
판정한다. score = 비정상 발화 수 / 전체 발화 수. threshold(0.10) 초과 시 실패 →
human_review (세그멘테이션이 무너진 거라 재처리로 안 나아짐).

1. 발화 0개면 action="pass" (체크③과 동일 논리 — 위반이 애초에 불가능).
2. end < start(데이터 파손)는 short/long과 안 섞고 details.corrupted_count로 따로
   집계 — 원인이 다르므로(세그멘테이션 문제 vs 데이터 파손 버그) 섞으면 튜닝 때
   뭘 고쳐야 할지 구분이 안 된다.
3. 경계값은 <, >로 비교한다. 정확히 min_seconds(0.5초)·max_seconds(60초)는 정상.

"""

from callwrap_api.quality.config import CheckConfig
from callwrap_api.schemas.quality import Action, GateResult, decide_passed

from callwrap_ai.schemas import Transcript

CHECK_NAME = "check_segment_length"


def check_segment_length(transcript: Transcript, config: CheckConfig) -> GateResult:
    utterances = transcript.utterances
    sample_size = len(utterances)

    if sample_size == 0:
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
                "short_count": 0,
                "long_count": 0,
                "corrupted_count": 0,
            },
        )

    min_seconds = config.params["min_seconds"]
    max_seconds = config.params["max_seconds"]

    short_count = long_count = corrupted_count = 0
    for u in utterances:
        duration = u.end - u.start
        if duration < 0:
            corrupted_count += 1
        elif duration < min_seconds:
            short_count += 1
        elif duration > max_seconds:
            long_count += 1

    abnormal = short_count + long_count + corrupted_count
    score = abnormal / sample_size
    passed = decide_passed(score, config.threshold, config.higher_is_better)
    action: Action = "pass" if passed else config.action_on_fail

    return GateResult(
        check_name=CHECK_NAME,
        passed=passed,
        score=score,
        threshold=config.threshold,
        higher_is_better=config.higher_is_better,
        action=action,
        reason=f"비정상 길이(짧음/김/파손) 발화 비율 초과: {score:.2f}" if not passed else None,
        details={
            "sample_size": sample_size,
            "checked_at_version": config.version,
            "short_count": short_count,
            "long_count": long_count,
            "corrupted_count": corrupted_count,
        },
    )