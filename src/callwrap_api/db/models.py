"""SQLAlchemy 모델. ★ 규리와 공유 — 스키마 변경은 반드시 Alembic 마이그레이션과 함께.

status 문자열의 진실은 state.CallStatus다. 여기서는 VARCHAR로 저장한다
(Postgres ENUM 타입을 쓰면 상태 하나 추가할 때마다 마이그레이션이 필요해서
 7주짜리 프로젝트에는 부담이 크다 — docs/decisions.md 참고).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from callwrap_api.state import CallStatus


class Base(DeclarativeBase):
    pass


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audio_path: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=CallStatus.UPLOADED.value)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    quality_checks: Mapped[list["QualityCheckResult"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    # 콜당 분석 1건 (call_id UNIQUE). 아직 분석 전이면 None.
    analysis: Mapped["AnalysisResultRow | None"] = relationship(
        back_populates="call", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def call_status(self) -> CallStatus:
        """VARCHAR 컬럼을 FSM enum으로. 상태 전이 검사는 항상 이걸 통해서."""
        return CallStatus(self.status)


class QualityCheckResult(Base):
    """체크 1회 실행 결과. GateResult 하나가 여기 한 행이 된다.

    재시도할 때마다 행을 새로 쌓는다(덮어쓰지 않는다) — retry_iteration으로 구분.
    Week 7 임계값 튜닝에서 "재시도가 실제로 점수를 올렸는가"를 봐야 하는데,
    덮어쓰면 그 데이터가 사라진다.
    """

    __tablename__ = "quality_check_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    check_name: Mapped[str] = mapped_column(String, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    higher_is_better: Mapped[bool | None] = mapped_column(Boolean)
    action: Mapped[str | None] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(Text)
    # details는 체크마다 키가 다르다. JSONB라 나중에 details->>'sample_size'로 조회 가능.
    details: Mapped[dict | None] = mapped_column(JSONB)
    checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    retry_iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    call: Mapped[Call] = relationship(back_populates="quality_checks")


class AnalysisResultRow(Base):
    """analyze()의 결과 1건. 콜당 1행 (call_id UNIQUE).

    저장 전략 (docs/decisions.md 참고):
    - `result` JSONB가 진실의 원본 — AnalysisResult 전체를 충실히 직렬화한다.
      계약(ai/schemas.py)이 자주 바뀌므로(유형·분류 개정) 형태 변화를 JSONB가 흡수한다.
      confidence·evidence_indices·요약 텍스트·소분류 29종은 전부 여기 안에 있다.
    - consultation_type/category/grade는 대시보드가 필터·집계하는 저카디널리티 값이라
      파생 컬럼으로 승격한다. 저장 시 result에서 뽑아 넣는다(중복이지만 조회가 목적).
    """

    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # UNIQUE — 콜당 분석 1건. 재분석은 정상 플로우가 아니다(DONE은 FSM상 종착).
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # ── 승격 컬럼 (result에서 파생, 대시보드 필터·집계용). 부분 실패 시 None ──
    consultation_type: Mapped[str | None] = mapped_column(String)
    consultation_category: Mapped[str | None] = mapped_column(String)
    grade: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    call: Mapped[Call] = relationship(back_populates="analysis")


# 검토 큐가 "NEEDS_HUMAN_REVIEW인 콜 목록"을 자주 조회한다.
Index("idx_calls_status", Call.status)

# 대시보드가 등급·유형으로 집계한다 (악성콜 카운트, 유형 분포).
Index("idx_analysis_grade", AnalysisResultRow.grade)
Index("idx_analysis_type", AnalysisResultRow.consultation_type)

# 콜 하나의 특정 회차 결과를 뽑는 게 가장 흔한 조회 패턴이다 (검토 UI, 튜닝 분석).
Index("idx_check_call", QualityCheckResult.call_id, QualityCheckResult.retry_iteration)
