"""GET /api/calls 목록 조회. DB 필요 — CALLWRAP_TEST_DATABASE_URL 없으면 skip."""

import os

import pytest

TEST_DB_URL = os.environ.get("CALLWRAP_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="CALLWRAP_TEST_DATABASE_URL 없음 — DB 붙는 테스트는 건너뛴다"
)


def make_call_with_status(status: str) -> str:
    from callwrap_api.db import repository
    from callwrap_api.db.session import SessionLocal
    from callwrap_api.state import CallStatus

    with SessionLocal() as db:
        call = repository.create_call(db, audio_path="/tmp/list.wav")
        # UPLOADED가 기본값이라, 다른 상태로 테스트하려면 FSM 허용 전이만 가능
        if status != CallStatus.UPLOADED.value:
            repository.set_status(db, call, CallStatus(status))
        return str(call.id)


def test_list_returns_all_calls_without_filter(client):
    make_call_with_status("UPLOADED")
    make_call_with_status("UPLOADED")
    resp = client.get("/api/calls")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) >= 2


def test_list_filters_by_status(client):
    call_id = make_call_with_status("FAILED")
    resp = client.get("/api/calls", params={"status": "FAILED"})
    assert resp.status_code == 200
    ids = [item["call_id"] for item in resp.json()["items"]]
    assert call_id in ids


def test_unknown_status_returns_400(client):
    resp = client.get("/api/calls", params={"status": "NOT_A_REAL_STATUS"})
    assert resp.status_code == 400


def test_limit_is_respected(client):
    for _ in range(5):
        make_call_with_status("UPLOADED")
    resp = client.get("/api/calls", params={"limit": 2})
    assert len(resp.json()["items"]) <= 2