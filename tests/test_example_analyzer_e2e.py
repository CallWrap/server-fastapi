"""예시(stub) AI 모델 경로 end-to-end 검증 (P1, 구현사항 ②).

기존 test_pipeline_flow.py는 품질 체크를 '가짜'로 갈아끼워 분기 로직만 본다.
여기서는 **가짜를 쓰지 않는다** — STT stub이 만든 전사를 실제 품질 게이트
(실제 checks + config/quality_gate.yaml)에 통과시키고, 예시 analyzer(analyze())의
결과가 DB에 그대로 저장되는지까지 실제 경로 그대로 확인한다.

실제 모델(AI-model)로 교체돼도 이 테스트의 '경로'는 동일하다 — 바뀌는 건 analyze()가
내는 값뿐이라, 값에 대한 단언은 예시 모델 기준으로 둔다(교체 시 이 파일만 갱신).

DB가 필요하다 — CALLWRAP_TEST_DATABASE_URL이 없으면 통째로 skip한다.
"""

import os
import uuid

import pytest

TEST_DB_URL = os.environ.get("CALLWRAP_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="CALLWRAP_TEST_DATABASE_URL 없음 — DB 붙는 테스트는 건너뛴다"
)


@pytest.fixture(autouse=True)
def eager_celery():
    """Celery를 eager로 돌려 .delay() 체인을 인라인 실행한다 (transcribe→gate→analyze)."""
    from callwrap_api.tasks.app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False


def test_stub_transcript_passes_real_gate_and_example_result_is_saved():
    """가짜 체크 없이 실제 게이트 통과 → 예시 analyzer 결과가 DB에 저장되는지."""
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal
    from callwrap_api.tasks.transcribe import transcribe_task

    with SessionLocal() as db:
        call = repository.create_call(db, audio_path="/tmp/e2e.wav")
        call_id = call.id

    transcribe_task.apply(args=(str(call_id),)).get()

    with SessionLocal() as db:
        call = repository.get_call(db, call_id)
        assert call.status == "DONE", "stub 전사는 실제 게이트를 통과해 DONE까지 가야 한다"

        row = repository.get_analysis_result(db, call_id)
        assert row is not None, "예시 analyzer 결과가 저장돼야 한다"

        # 대시보드가 거르는 파생 컬럼 — enum .value 문자열로 승격됨
        assert row.consultation_type == "사용법문의"
        assert row.consultation_category == "결제및비용지급"
        assert row.grade == "일반"

        # JSONB 원본 — {value, confidence, evidence_indices} 구조가 그대로 있는지
        result = row.result
        assert result["consultation_type"]["value"] == "사용법문의"
        assert result["consultation_type"]["confidence"] == 0.95
        assert result["summary"]["value"]["title"]  # 요약 제목 비어있지 않음
        assert result["failures"] == []

        # evidence_indices가 실존 발화 index만 가리키는지 (stub 전사는 index 0~3)
        valid = {0, 1, 2, 3}
        for field in ("summary", "consultation_type", "needs_followup"):
            assert set(result[field]["evidence_indices"]) <= valid


def test_upload_endpoint_runs_full_pipeline_via_http(client, monkeypatch, tmp_path):
    """HTTP 업로드 → (eager 파이프라인) → 조회에서 DONE + 분석 결과가 보이는지.

    업로드가 저장하는 오디오 파일은 레포를 더럽히지 않게 tmp로 돌린다.
    """
    from callwrap_api.settings import get_settings

    monkeypatch.setattr(get_settings(), "audio_storage_dir", tmp_path)

    resp = client.post(
        "/api/calls/upload",
        files={"file": ("sample.wav", b"RIFF....dummy-audio", "audio/wav")},
    )
    assert resp.status_code == 202, resp.text
    call_id = resp.json()["call_id"]

    detail = client.get(f"/api/calls/{call_id}")
    assert detail.status_code == 200
    body = detail.json()

    assert body["status"] == "DONE"
    assert body["analysis"] is not None, "분석 결과(JSONB)가 조회에 실려야 한다"
    assert body["analysis"]["consultation_type"]["value"] == "사용법문의"
    assert body["analysis"]["grade"]["value"] == "일반"
    # 품질 체크 이력도 회차 0으로 쌓여 있어야 한다 (실제 게이트가 돌았다는 증거)
    assert len(body["quality_checks"]) >= 1
    assert all(c["retry_iteration"] == 0 for c in body["quality_checks"])


def test_rejects_unsupported_file_type(client):
    """계약 방어 — 허용되지 않은 확장자는 400. (파이프라인 진입 자체를 막는다)"""
    resp = client.post(
        "/api/calls/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400
