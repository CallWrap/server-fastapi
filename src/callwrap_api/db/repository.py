"""DB 접근 헬퍼. 라우터·태스크가 SQLAlchemy를 직접 만지지 않게 모아둔다."""

import logging
import uuid
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from callwrap_api.db.models import AnalysisResultRow, Call, QualityCheckResult
from callwrap_api.db.session import SessionLocal
from callwrap_api.quality.orchestrator import GateReport
from callwrap_api.state import CallStatus, assert_transition

from callwrap_ai.schemas import AnalysisResult

logger = logging.getLogger(__name__)


def get_call(db: Session, call_id: uuid.UUID) -> Call | None:
    return db.get(Call, call_id)


def create_call(db: Session, audio_path: str) -> Call:
    call = Call(audio_path=audio_path, status=CallStatus.UPLOADED.value, retry_count=0)
    db.add(call)
    db.commit()
    db.refresh(call)
    return call


def set_status(db: Session, call: Call, target: CallStatus) -> Call:
    """상태를 바꾼다. 허용되지 않은 전이면 InvalidTransition이 난다.

    상태를 문자열로 직접 대입하지 말고 항상 이 함수를 쓴다 — FSM을 우회하는
    코드가 하나라도 생기면 전이 규칙은 문서로 전락한다.
    """
    assert_transition(call.call_status, target)
    call.status = target.value
    db.commit()
    db.refresh(call)
    return call


def mark_failed(call_id: uuid.UUID) -> None:
    """콜을 FAILED로 떨어뜨린다. 태스크가 예외로 죽을 때 쓴다.

    다른 함수와 달리 db 세션을 받지 않고 안에서 새로 연다. 실패 시점에는 호출자의
    세션이 이미 롤백됐거나 깨져 있을 수 있어 그걸 재사용하면 상태 기록까지 같이 죽는다.

    여기서는 예외를 밖으로 내보내지 않는다. 이 함수가 터지면 원래 예외를 가려서
    진짜 원인을 잃는다 — 상태 기록 실패보다 원인 파악이 중요하다.
    """
    try:
        with SessionLocal() as db:
            call = db.get(Call, call_id)
            if call is None or call.call_status is CallStatus.DONE:
                # DONE은 종착이라 FAILED로 못 간다. 이미 끝난 콜이면 건드리지 않는다.
                return
            if call.call_status is CallStatus.FAILED:
                return
            call.status = CallStatus.FAILED.value
            db.commit()
    except Exception:  # noqa: BLE001 — 원래 예외를 가리지 않는 게 목적
        logger.exception("FAILED 상태 기록 실패: call_id=%s", call_id)


def increment_retry(db: Session, call: Call) -> Call:
    call.retry_count += 1
    db.commit()
    db.refresh(call)
    return call


def save_gate_report(db: Session, call: Call, report: GateReport) -> list[QualityCheckResult]:
    """GateReport의 개별 결과를 quality_check_results에 쌓는다 (덮어쓰지 않는다)."""
    rows = [
        QualityCheckResult(
            call_id=call.id,
            check_name=result.check_name,
            passed=result.passed,
            score=result.score,
            threshold=result.threshold,
            higher_is_better=result.higher_is_better,
            action=result.action,
            reason=result.reason,
            details=result.details,
            retry_iteration=report.retry_count,
        )
        for result in report.results
    ]
    db.add_all(rows)
    db.commit()
    return rows


def _promoted_value(judgment: object | None) -> str | None:
    """Judgment에서 승격 컬럼용 문자열을 뽑는다. 부분 실패(None)면 None.

    judgment.value가 enum이면 그 문자열 값(예: "악성콜"), 아니면 str()로.
    """
    if judgment is None:
        return None
    value = getattr(judgment, "value", None)
    if isinstance(value, Enum):
        return value.value
    return None if value is None else str(value)


def save_analysis_result(
    db: Session, call: Call, result: AnalysisResult
) -> AnalysisResultRow:
    """분석 결과를 저장한다. 콜당 1건 — 이미 있으면 새로 만들지 않는다(멱등).

    result 전체를 JSONB로 충실히 저장하고, 대시보드가 거르는 유형·분류·등급만
    파생 컬럼으로 승격한다. 소분류↔중분류 정합은 여기서 검증하지 않는다 —
    analyze()가 낸 판정을 저장 계층이 재검증하지 않는다 (B안 철학).
    """
    existing = get_analysis_result(db, call.id)
    if existing is not None:
        logger.warning("콜 %s 분석 결과가 이미 있다. 중복 저장 건너뜀.", call.id)
        return existing

    row = AnalysisResultRow(
        call_id=call.id,
        # mode="json"이라 enum·중첩 모델·list가 전부 JSON 원시값으로 직렬화된다.
        result=result.model_dump(mode="json"),
        consultation_type=_promoted_value(result.consultation_type),
        consultation_category=_promoted_value(result.consultation_category),
        grade=_promoted_value(result.grade),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_analysis_result(db: Session, call_id: uuid.UUID) -> AnalysisResultRow | None:
    return db.scalars(
        select(AnalysisResultRow).where(AnalysisResultRow.call_id == call_id)
    ).first()


def list_gate_results(
    db: Session, call_id: uuid.UUID, retry_iteration: int | None = None
) -> list[QualityCheckResult]:
    """콜의 품질 체크 결과. retry_iteration을 주면 그 회차만."""
    stmt = select(QualityCheckResult).where(QualityCheckResult.call_id == call_id)
    if retry_iteration is not None:
        stmt = stmt.where(QualityCheckResult.retry_iteration == retry_iteration)
    stmt = stmt.order_by(
        QualityCheckResult.retry_iteration, QualityCheckResult.checked_at
    )
    return list(db.scalars(stmt))

def list_calls(
    db: Session,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Call]:
    """콜 목록. status로 필터링 가능 (예: NEEDS_HUMAN_REVIEW로 검토 대기열).

    최신순(updated_at desc) 정렬 — 상담사가 최근에 걸린 것부터 보게.
    """
    stmt = select(Call)
    if status is not None:
        stmt = stmt.where(Call.status == status)
    stmt = stmt.order_by(Call.updated_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt))