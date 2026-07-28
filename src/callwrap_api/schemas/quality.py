"""품질 게이트(②) 결과 계약.

★ 규리와 공유하는 파일. 4개 체크 함수가 모두 이 타입 하나를 반환한다.
   변경하려면 규리와 합의 후에. 필드를 늘리기 전에 details로 되는지 먼저 검토할 것.

합의 사항 (2026-07-17):
- 점수 방향을 이름으로 추측하지 않는다 → higher_is_better를 결과에 명시한다 (A안).
- 체크 함수는 정상 로직만 담당한다. 예외는 orchestrator가 통합 처리한다 (B안).
- 임계값은 코드가 아니라 config/quality_gate.yaml에서 온다.

이 파일만 dataclass인 이유: 팀 합의 시점의 형태를 그대로 유지했다.
(ai/schemas.py는 pydantic이지만 그쪽은 JSON 직렬화 계약이라 목적이 다르다.
 GateResult는 프로세스 안에서만 오가고, DB 저장은 models.py가 따로 맡는다.)
"""

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional

#: pass = 통과 / retry = ①번부터 재처리 / human_review = 사람에게 넘김
#:
#: retry vs human_review 판단 근거:
#: - retry: 원본 오디오는 멀쩡한데 처리 결과가 나쁠 때. 재처리로 나아질 수 있다.
#: - human_review: 원본 자체가 문제일 때. 재처리해도 같은 결과가 나온다.
Action = Literal["pass", "retry", "human_review"]

#: details에 반드시 들어가야 하는 키. orchestrator가 검증한다.
#: - sample_size: 점수를 계산한 모집단 크기 (발화 0개짜리 콜의 1.0과 100개짜리의 1.0을 구분)
#: - checked_at_version: 판정에 쓴 quality_gate.yaml의 version (임계값 튜닝 이력 추적)

# 참고: action이 항상 config.action_on_fail과 같아야 하는 건 아니다.
# 판정 근거 자체가 없는 경우(예: sample_size=0)는 체크 함수가 config를 무시하고
# action="human_review"로 직접 오버라이드할 수 있다 (체크①②에서 이미 이 패턴 사용 중).
# _contract_violation()은 이걸 막지 않는다 — 의도된 것.

REQUIRED_DETAIL_KEYS = ("sample_size", "checked_at_version")


@dataclass
class GateResult:
    check_name: str
    passed: bool
    score: float
    threshold: float
    higher_is_better: bool  # True면 score >= threshold가 통과
    # 기본값을 두지 않는다. 실패 결과에서 action을 깜빡하면 조용히 "pass"가 되어
    # 문제 있는 콜이 게이트를 통과해버린다. 통과할 때도 "pass"를 명시하게 한다.
    action: Action
    reason: Optional[str] = None  # 한국어, "{문제 요약}: {수치}" 형식, 80자 이내
    details: Optional[dict] = None  # 필수 키는 REQUIRED_DETAIL_KEYS 참고

    def to_dict(self) -> dict[str, Any]:
        """로깅·직렬화용. details까지 깊은 복사라 반환값을 고쳐도 원본은 안 변한다.

        DB 저장에는 쓰지 않는다 — repository가 컬럼에 명시적으로 매핑한다.
        필드가 늘었을 때 여기로 조용히 새어나가는 걸 막으려는 것.
        """
        return asdict(self)


def decide_passed(score: float, threshold: float, higher_is_better: bool) -> bool:
    """점수 방향을 반영한 통과 판정. 4개 체크가 부등호를 각자 쓰지 않게 여기로 모은다."""
    return score >= threshold if higher_is_better else score <= threshold
