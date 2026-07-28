"""체크 ① — STT 신뢰도. 담당: 김규리.

[설명]
발화(Utterance) 중 confidence가 낮은 것의 비율로 전사 품질을 판정한다.
score = (confidence < params.low_confidence_below인 발화 수) / sample_size.
낮을수록 좋음(higher_is_better=false), threshold(0.15) 초과 시 실패 → retry.

[결정 사항]
1. avg_logprob → confidence(0~1) 정규화는 stt/에서 처리한다.
   이 체크는 Utterance.confidence가 이미 0~1로 정규화되어 들어온다고 가정한다.
   원시 avg_logprob 값이나 정규화 로직은 여기서 다루지 않는다.
2. confidence가 None인 발화(params.on_missing_confidence == "skip")는 분모(sample_size)에서 제외한다.
3. 분모(sample_size)가 0이면 — 모든 발화가 skip됐거나 발화 자체가 없는 경우 —
   config.action_on_fail(retry)을 따르지 않고 action="human_review"로 오버라이드한다.
   score 계산 근거 자체가 없어 decide_passed()를 쓰지 않고 passed=False를 직접 명시한다.

[공유사항]
- Utterance.confidence는 stt/에서 반드시 0~1로 정규화해서 넘길 것 (avg_logprob 원시값 그대로 넘기지 말 것).
- 정규화가 불가능한 발화는 confidence=0이 아니라 None으로 넘길 것 — on_missing_confidence=skip 로직이 None 기준으로 판별한다.
- 정규화 공식은 stt/ 구현 시점에 docs/decisions.md에 기록할 것.
"""

from callwrap_api.quality.config import CheckConfig
from callwrap_api.schemas.quality import Action, GateResult, decide_passed

from callwrap_ai.schemas import Transcript

CHECK_NAME = "check_stt_confidence"


def check_stt_confidence(transcript: Transcript, config: CheckConfig) -> GateResult:
    low_confidence_below = config.params["low_confidence_below"]
    # on_missing_confidence="skip"만 구현 — yaml에 다른 값이 들어오면 바로 드러나야 함
    on_missing_confidence = config.params.get("on_missing_confidence", "skip")
    if on_missing_confidence != "skip":
        raise NotImplementedError(
            f"on_missing_confidence={on_missing_confidence!r} 미지원 (skip만 구현됨)"
        )

    counted = [u for u in transcript.utterances if u.confidence is not None]
    sample_size = len(counted)

    if sample_size == 0:
        return GateResult(
            check_name=CHECK_NAME,
            passed=False,
            score=0.0,
            threshold=config.threshold,
            higher_is_better=config.higher_is_better,
            action="human_review",  # config.action_on_fail 무시 — 판정 근거 자체가 없음
            reason="신뢰도 판정 가능한 발화 없음: sample_size=0",
            details={
                "sample_size": 0,
                "checked_at_version": config.version,
                "low_confidence_count": 0,
            },
        )

    low_confidence_count = sum(1 for u in counted if u.confidence < low_confidence_below)
    score = low_confidence_count / sample_size
    passed = decide_passed(score, config.threshold, config.higher_is_better)
    action: Action = "pass" if passed else config.action_on_fail

    return GateResult(
        check_name=CHECK_NAME,
        passed=passed,
        score=score,
        threshold=config.threshold,
        higher_is_better=config.higher_is_better,
        action=action,
        reason=f"낮은 신뢰도 발화 비율 초과: {score:.2f}" if not passed else None,
        details={
            "sample_size": sample_size,
            "checked_at_version": config.version,
            "low_confidence_count": low_confidence_count,
        },
    )