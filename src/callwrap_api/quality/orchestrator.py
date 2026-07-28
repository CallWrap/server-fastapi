"""품질 게이트(②) 오케스트레이터 — 체크 4개를 돌리고 콜 전체의 액션을 정한다.

★ 규리와 공유. 체크 함수를 추가·삭제하려면 CHECK_REGISTRY만 고치면 된다.

책임 분담 (팀 합의 B안):
- 체크 함수: 정상 로직만. 예외를 자기가 삼키지 않는다.
- 오케스트레이터(여기): 예외 통합 처리, 계약 검증, 액션 종합.

이 파일은 DB도 Celery도 모른다. 순수 함수라 테스트가 쉽다 —
DB 저장과 상태 전이는 tasks/quality_gate.py가 맡는다.
"""

from dataclasses import dataclass
from typing import Callable

from callwrap_api.quality.checks.repetition_and_gaps import (
    CHECK_NAME as REPETITION,
    check_repetition_and_gaps,
)
from callwrap_api.quality.checks.segment_length import (
    CHECK_NAME as SEGMENT_LENGTH,
    check_segment_length,
)
from callwrap_api.quality.checks.speaker_overlap import (
    CHECK_NAME as SPEAKER_OVERLAP,
    check_speaker_overlap,
)
from callwrap_api.quality.checks.stt_confidence import (
    CHECK_NAME as STT_CONFIDENCE,
    check_stt_confidence,
)
from callwrap_api.quality.config import CheckConfig, QualityGateConfig
from callwrap_api.schemas.quality import REQUIRED_DETAIL_KEYS, Action, GateResult

from callwrap_ai.schemas import Transcript

CheckFn = Callable[[Transcript, CheckConfig], GateResult]

#: 실행할 체크 전부. 순서는 판정에 영향이 없다 (액션은 우선순위로 종합한다).
CHECK_REGISTRY: dict[str, CheckFn] = {
    STT_CONFIDENCE: check_stt_confidence,
    REPETITION: check_repetition_and_gaps,
    SPEAKER_OVERLAP: check_speaker_overlap,
    SEGMENT_LENGTH: check_segment_length,
}

#: 액션 우선순위. 숫자가 클수록 강하다.
#: 사람 검토가 재시도를 이긴다 — 재처리해도 안 낫는 문제가 하나라도 있으면
#: 재시도는 시간 낭비이기 때문이다.
_ACTION_RANK: dict[Action, int] = {"pass": 0, "retry": 1, "human_review": 2}


@dataclass(frozen=True)
class GateReport:
    """게이트 전체 판정. tasks/가 이걸 보고 다음 상태를 정한다."""

    results: list[GateResult]
    action: Action
    retry_count: int

    @property
    def passed(self) -> bool:
        return self.action == "pass"

    @property
    def failed_checks(self) -> list[GateResult]:
        return [r for r in self.results if not r.passed]

    def summary_reason(self) -> str | None:
        """실패한 체크들의 reason을 합친다. web/의 검토 큐에 그대로 띄울 용도."""
        reasons = [r.reason for r in self.failed_checks if r.reason]
        return " / ".join(reasons) if reasons else None


def run_quality_gate(
    transcript: Transcript,
    config: QualityGateConfig,
    retry_count: int = 0,
) -> GateReport:
    """체크를 전부 돌리고 콜 단위 액션을 정한다.

    한 체크가 터져도 나머지는 계속 돈다. 상담사에게 "뭐가 문제였는지" 다 보여주려면
    첫 실패에서 멈추면 안 된다.
    """
    results: list[GateResult] = []

    for name, fn in CHECK_REGISTRY.items():
        check_config = config.for_check(name)
        if not check_config.enabled:
            continue
        results.append(_run_one(name, fn, transcript, check_config))

    action = _combine_actions(results, retry_count=retry_count, max_retry=config.max_retry)
    return GateReport(results=results, action=action, retry_count=retry_count)


def _run_one(
    name: str,
    fn: CheckFn,
    transcript: Transcript,
    check_config: CheckConfig,
) -> GateResult:
    """체크 하나를 예외 없이 실행한다. 어떤 경우에도 GateResult를 돌려준다."""
    try:
        result = fn(transcript, check_config)
    except Exception as exc:  # 체크 함수의 모든 예외를 여기서 흡수한다 (합의 B안)
        return _errored_result(name, check_config, exc)

    problem = _contract_violation(name, result, check_config)
    if problem:
        # 계약 위반은 조용히 넘기면 안 된다. 잘못된 판정으로 콜이 통과되는 것보다
        # 사람에게 넘기는 쪽이 안전하다.
        return _errored_result(name, check_config, ValueError(problem))

    return result


def _errored_result(name: str, check_config: CheckConfig, exc: Exception) -> GateResult:
    """터진 체크를 사람에게 넘기는 GateResult로 변환한다.

    action이 human_review인 이유: 체크가 터졌다는 건 우리 코드의 버그이거나
    예상 못 한 입력이라는 뜻이다. STT를 다시 돌려도 똑같이 터진다.

    score는 의미가 없다. 0.0은 자리를 채우는 값일 뿐이고,
    판단은 details.errored를 보고 한다.
    """
    return GateResult(
        check_name=name,
        passed=False,
        score=0.0,
        threshold=check_config.threshold,
        higher_is_better=check_config.higher_is_better,
        action="human_review",
        reason=f"체크 실행 오류: {type(exc).__name__}",
        details={
            "sample_size": 0,
            "checked_at_version": check_config.version,
            "errored": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
        },
    )


def _contract_violation(name: str, result: GateResult, check_config: CheckConfig) -> str | None:
    """GateResult가 계약을 지켰는지 본다. 어겼으면 사유 문자열, 아니면 None."""
    if not isinstance(result, GateResult):
        return f"{name}이 GateResult가 아닌 {type(result).__name__}을 반환했다."
    if result.check_name != name:
        return f"check_name이 '{result.check_name}'이다. '{name}'이어야 한다."
    if not result.passed and result.action == "pass":
        return f"{name}이 실패했는데 action이 'pass'다."
    if result.details is None:
        return f"{name}의 details가 None이다. 필수 키: {list(REQUIRED_DETAIL_KEYS)}"
    missing = [k for k in REQUIRED_DETAIL_KEYS if k not in result.details]
    if missing:
        return f"{name}의 details에 필수 키가 없다: {missing}"
    return None


def _combine_actions(results: list[GateResult], retry_count: int, max_retry: int) -> Action:
    """개별 체크 액션을 콜 단위 액션 하나로 종합한다.

    - 실패한 체크들의 액션 중 가장 강한 것을 고른다 (human_review > retry > pass).
    - retry로 결론났는데 이미 상한만큼 재시도했으면 human_review로 승격한다.
      같은 걸 무한히 다시 돌리는 대신 사람에게 넘긴다.
    """
    failed = [r for r in results if not r.passed]
    if not failed:
        return "pass"

    action = max((r.action for r in failed), key=lambda a: _ACTION_RANK[a])

    if action == "retry" and retry_count >= max_retry:
        return "human_review"
    return action
