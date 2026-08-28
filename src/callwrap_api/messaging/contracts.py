"""Spring ↔ FastAPI 메시지 계약 (스키마).

- JobRequest: Spring → FastAPI. "이 콜을 분석해줘."
- ResultMessage: FastAPI → Spring. "분석 끝났어(또는 검토 필요/실패)."

"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from callwrap_ai.schemas import AnalysisResult, Transcript

#: 계약 버전. 필드 추가는 minor, 의미 변경/삭제는 major로 올린다.
SCHEMA_VERSION = "1.0"


class ResultStatus(str, Enum):
    """결과 메시지의 종착 상태. FSM의 종착 상태 중 Spring이 구분해야 하는 것만."""

    DONE = "DONE"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    FAILED = "FAILED"


class JobRequest(BaseModel):
    """Spring이 발행하는 분석 요청.

    call_id는 Spring이 발급한다(합의 ③). FastAPI는 이 id를 그대로 콜 식별자로 쓰고
    결과에 실어 회신한다 — 요청↔결과 상관관계 키.
    """

    schema_version: str = SCHEMA_VERSION
    call_id: uuid.UUID
    #: 오디오 위치. Spring이 업로드하고 FastAPI가 여기서 받아온다(합의 ②).
    audio_uri: str
    audio_format: str | None = None
    #: Spring 도메인 정보(상담사·상담일시 등). FastAPI는 해석하지 않는다.
    metadata: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime | None = None


class QualitySummary(BaseModel):
    """품질 게이트 요약. NEEDS_HUMAN_REVIEW일 때 Spring이 사유를 보여주는 데 쓴다."""

    passed: bool
    failed_checks: list[str] = Field(default_factory=list)


class ResultMessage(BaseModel):
    """FastAPI가 발행하는 분석 결과.

    - status=DONE: analysis 채워짐(부분 실패는 analysis.failures로). transcript도 함께 실린다 —
      상담사 화면의 전사 패널은 이 필드가 없으면 원본 발화를 보여줄 방법이 없다.
    - status=NEEDS_HUMAN_REVIEW: analysis=None, quality.failed_checks로 사유 전달.
    - status=FAILED: error에 원인, analysis=None.
    """

    schema_version: str = SCHEMA_VERSION
    call_id: uuid.UUID
    status: ResultStatus
    analysis: dict[str, Any] | None = None
    #: DONE일 때만 채워진다. Transcript.model_dump(mode="json") 그대로.
    transcript: dict[str, Any] | None = None
    quality: QualitySummary | None = None
    failures: list[str] = Field(default_factory=list)
    error: str | None = None
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def build_done(call_id: uuid.UUID, analysis: AnalysisResult, transcript: Transcript) -> ResultMessage:
    """분석 성공(DONE). analysis와 표시용 마스킹 전사를 싣는다(부분 실패는 analysis.failures로)."""
    return ResultMessage(
        call_id=call_id,
        status=ResultStatus.DONE,
        analysis=analysis.model_dump(mode="json"),
        transcript=transcript.model_dump(mode="json"),
        failures=analysis.failures,
    )


def build_human_review(call_id: uuid.UUID, failed_checks: list[str]) -> ResultMessage:
    """품질 게이트에서 사람 검토로 넘어감."""
    return ResultMessage(
        call_id=call_id,
        status=ResultStatus.NEEDS_HUMAN_REVIEW,
        quality=QualitySummary(passed=False, failed_checks=failed_checks),
    )


def build_failed(call_id: uuid.UUID, error: str) -> ResultMessage:
    """처리 중 예외로 실패."""
    return ResultMessage(call_id=call_id, status=ResultStatus.FAILED, error=error)
