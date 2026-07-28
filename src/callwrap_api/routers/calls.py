"""콜 업로드·조회 API. 담당: 이정민.

web/(재혁)이 쓰는 엔드포인트다. 응답 스키마를 바꾸면 프론트가 깨지므로 먼저 공유할 것.
"""

import uuid
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from callwrap_api.state import CallStatus
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from callwrap_api.db import repository
from callwrap_api.db.session import get_db
from callwrap_api.settings import get_settings
from callwrap_api.tasks.transcribe import transcribe_task

router = APIRouter(prefix="/api/calls", tags=["calls"])

#: 허용 확장자. 상담 녹취는 wav가 기본이고 나머지는 편의용.
ALLOWED_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac"}


class UploadResponse(BaseModel):
    call_id: uuid.UUID
    status: str


class GateResultResponse(BaseModel):
    """quality_check_results 한 행. web/의 검토 화면이 이걸 표시한다."""

    check_name: str
    passed: bool
    score: float | None
    threshold: float | None
    higher_is_better: bool | None
    action: str | None
    reason: str | None
    details: dict | None
    retry_iteration: int
    checked_at: datetime


class CallDetailResponse(BaseModel):
    call_id: uuid.UUID
    status: str
    retry_count: int
    created_at: datetime
    updated_at: datetime
    quality_checks: list[GateResultResponse] = Field(default_factory=list)
    # AnalysisResult 전체(JSON). 분석 전이면 None.
    # 필드별 {value, confidence, evidence_indices} 구조 그대로 — 프론트가 confidence로
    # 3-tier를, evidence_indices로 근거 하이라이트를 그린다.
    analysis: dict | None = None


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED, response_model=UploadResponse)
def upload_call(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """음성 파일을 받아 call_id를 즉시 돌려주고 파이프라인을 큐에 넣는다.

    202를 쓰는 이유: 전사는 수십 초 걸린다. 여기서 기다리면 상담사가 묶인다.
    클라이언트는 call_id로 폴링한다.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"지원하지 않는 형식이다: '{suffix or '확장자 없음'}' "
            f"(허용: {sorted(ALLOWED_SUFFIXES)})",
        )

    settings = get_settings()
    settings.audio_storage_dir.mkdir(parents=True, exist_ok=True)

    # 파일명은 클라이언트가 준 값이라 믿지 않는다 — 경로 탈출·중복을 피해 새로 짓는다.
    audio_path = settings.audio_storage_dir / f"{uuid.uuid4()}{suffix}"
    audio_path.write_bytes(file.file.read())

    call = repository.create_call(db, audio_path=str(audio_path))
    transcribe_task.delay(str(call.id))

    return UploadResponse(call_id=call.id, status=call.status)


@router.get("/{call_id}", response_model=CallDetailResponse)
def get_call(call_id: uuid.UUID, db: Session = Depends(get_db)) -> CallDetailResponse:
    """콜 상태와 품질 체크 이력. 프론트가 폴링하는 엔드포인트."""
    call = repository.get_call(db, call_id)
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="콜을 찾을 수 없다.")

    rows = repository.list_gate_results(db, call_id)
    analysis_row = repository.get_analysis_result(db, call_id)
    return CallDetailResponse(
        call_id=call.id,
        status=call.status,
        retry_count=call.retry_count,
        created_at=call.created_at,
        updated_at=call.updated_at,
        analysis=analysis_row.result if analysis_row is not None else None,
        quality_checks=[
            GateResultResponse(
                check_name=r.check_name,
                passed=r.passed,
                score=r.score,
                threshold=r.threshold,
                higher_is_better=r.higher_is_better,
                action=r.action,
                reason=r.reason,
                details=r.details,
                retry_iteration=r.retry_iteration,
                checked_at=r.checked_at,
            )
            for r in rows
        ],
    )

class CallSummaryResponse(BaseModel):
    """목록 조회용 — 품질체크 이력은 안 담는다(무거움). 필요하면 단건 조회로."""

    call_id: uuid.UUID
    status: str
    retry_count: int
    created_at: datetime
    updated_at: datetime


class CallListResponse(BaseModel):
    items: list[CallSummaryResponse]
    limit: int
    offset: int


@router.get("", response_model=CallListResponse)
def list_calls(
    status_filter: str | None = Query(
        default=None, alias="status", description="예: NEEDS_HUMAN_REVIEW"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> CallListResponse:
    """콜 목록 조회. status 쿼리로 필터링하면 검토 대기열처럼 쓸 수 있다."""
    if status_filter is not None and status_filter not in {s.value for s in CallStatus}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"모르는 status: {status_filter!r} (허용: {[s.value for s in CallStatus]})",
        )

    calls = repository.list_calls(db, status=status_filter, limit=limit, offset=offset)
    return CallListResponse(
        items=[
            CallSummaryResponse(
                call_id=c.id,
                status=c.status,
                retry_count=c.retry_count,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in calls
        ],
        limit=limit,
        offset=offset,
    )