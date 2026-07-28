"""analysis_results 저장·조회 + GET 응답 확장 검증 (#11). 담당: 이정민.

DB가 필요하다 — CALLWRAP_TEST_DATABASE_URL 없으면 전체 skip.
"""

import io
import os
import uuid

import pytest

from callwrap_ai.schemas import (
    AnalysisResult,
    ConsultationCategory,
    ConsultationGrade,
    ConsultationSubcategory,
    ConsultationType,
    Judgment,
    Summary,
)

TEST_DB_URL = os.environ.get("CALLWRAP_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="CALLWRAP_TEST_DATABASE_URL 없음 — DB 붙는 테스트는 건너뛴다"
)


def make_result(*, with_failures: bool = False) -> AnalysisResult:
    """v0.2.0 계약 기준 분석 결과 하나. 부분 실패 케이스도 만들 수 있다."""
    if with_failures:
        # 유형·분류·소분류 판정이 실패한 케이스 — 승격 컬럼이 None이어야 한다
        return AnalysisResult(
            summary=Judgment(
                value=Summary(title="결제 오류 문의", inquiry="문의 요약", resolution="처리 요약"),
                confidence=0.9,
                evidence_indices=[0, 1],
            ),
            consultation_type=None,
            consultation_category=None,
            consultation_subcategory=None,
            grade=Judgment(value=ConsultationGrade.NORMAL, confidence=0.7),
            needs_followup=Judgment(value=False, confidence=0.8),
            needs_faq=Judgment(value=True, confidence=0.6),
            failures=["classify_type", "classify_category"],
        )
    return AnalysisResult(
        summary=Judgment(
            value=Summary(
                title="바우처 결제 방법 문의",
                inquiry="고객이 바우처 결제가 안 된다고 문의함.",
                resolution="상담사가 결제 수단 재등록 절차를 안내함.",
            ),
            confidence=0.92,
            evidence_indices=[0, 2],
        ),
        consultation_type=Judgment(value=ConsultationType.USAGE, confidence=0.88, evidence_indices=[1]),
        consultation_category=Judgment(value=ConsultationCategory.PAYMENT, confidence=0.81),
        consultation_subcategory=Judgment(
            value=ConsultationSubcategory.PAYMENT_METHOD_ERROR, confidence=0.55
        ),
        grade=Judgment(value=ConsultationGrade.NORMAL, confidence=0.9),
        needs_followup=Judgment(value=False, confidence=0.85),
        needs_faq=Judgment(value=True, confidence=0.66),
        failures=[],
    )


def make_call(status: str = "ANALYZING"):
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal
    from callwrap_api.state import CallStatus

    with SessionLocal() as db:
        call = repository.create_call(db, audio_path="/tmp/a.wav")
        # 저장 테스트를 위해 ANALYZING까지 전이시켜둔다
        repository.set_status(db, call, CallStatus.TRANSCRIBING)
        repository.set_status(db, call, CallStatus.QUALITY_CHECK)
        repository.set_status(db, call, CallStatus.PASSED)
        repository.set_status(db, call, CallStatus.ANALYZING)
        return str(call.id)


def test_save_and_get_roundtrip():
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal

    call_id = make_call()
    result = make_result()
    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        repository.save_analysis_result(db, call, result)

    with SessionLocal() as db:
        row = repository.get_analysis_result(db, uuid.UUID(call_id))
    assert row is not None
    # JSONB 원본이 계약 그대로 왕복하는지 (재파싱해서 동등성 확인)
    restored = AnalysisResult.model_validate(row.result)
    assert restored == result


def test_promoted_columns_extracted():
    """유형·분류·등급이 승격 컬럼에 문자열로 들어갔는지 (대시보드 조회용)."""
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal

    call_id = make_call()
    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        row = repository.save_analysis_result(db, call, make_result())

    assert row.consultation_type == ConsultationType.USAGE.value
    assert row.consultation_category == ConsultationCategory.PAYMENT.value
    assert row.grade == ConsultationGrade.NORMAL.value


def test_partial_failure_promoted_columns_are_null():
    """유형·분류 판정이 실패(None)하면 승격 컬럼도 NULL이어야 한다."""
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal

    call_id = make_call()
    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        row = repository.save_analysis_result(db, call, make_result(with_failures=True))

    assert row.consultation_type is None
    assert row.consultation_category is None
    assert row.grade == ConsultationGrade.NORMAL.value  # 등급은 성공했으므로 값 있음
    # result 안에는 failures가 그대로 보존
    assert AnalysisResult.model_validate(row.result).failures == [
        "classify_type",
        "classify_category",
    ]


def test_save_is_idempotent():
    """콜당 1건 — 두 번 저장해도 중복 행이 안 생긴다."""
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal

    call_id = make_call()
    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        first = repository.save_analysis_result(db, call, make_result())
        second = repository.save_analysis_result(db, call, make_result())
    assert first.id == second.id


def test_get_call_api_includes_analysis():
    """GET /api/calls/{id} 응답에 analysis가 담겨 나오는지 (프론트 연동)."""
    from fastapi.testclient import TestClient

    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal
    from callwrap_api.main import app

    call_id = make_call()
    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        repository.save_analysis_result(db, call, make_result())

    with TestClient(app) as client:
        resp = client.get(f"/api/calls/{call_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"] is not None
    # 필드별 {value, confidence, evidence_indices} 구조가 프론트에 그대로 전달되는지
    assert body["analysis"]["consultation_type"]["value"] == ConsultationType.USAGE.value
    assert body["analysis"]["consultation_type"]["confidence"] == 0.88
    assert body["analysis"]["summary"]["value"]["title"] == "바우처 결제 방법 문의"


def test_get_call_api_analysis_null_before_analysis():
    """분석 전 콜은 analysis가 null."""
    from fastapi.testclient import TestClient

    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal
    from callwrap_api.main import app

    with SessionLocal() as db:
        call = repository.create_call(db, audio_path="/tmp/b.wav")
        call_id = str(call.id)

    with TestClient(app) as client:
        resp = client.get(f"/api/calls/{call_id}")
    assert resp.status_code == 200
    assert resp.json()["analysis"] is None
