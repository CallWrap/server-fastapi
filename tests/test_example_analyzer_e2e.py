"""예시(stub) AI 모델 경로 end-to-end 검증 (무상태).

가짜 체크를 쓰지 않는다 — STT stub이 만든 전사를 실제 품질 게이트(실제 checks +
config/quality_gate.yaml)에 통과시키고, 예시 analyzer(analyze())의 결과가 Spring으로
발행되는 DONE 메시지에 그대로 실리는지 확인한다.

실제 모델(AI-model)로 교체돼도 이 테스트의 '경로'는 동일하다 — 바뀌는 건 analyze()가
내는 값뿐이라, 값에 대한 단언은 예시 모델 기준으로 둔다(교체 시 이 파일만 갱신).

DB도 브로커도 없다. 발행은 captured_results가 가로챈다.
"""

import uuid

import pytest


@pytest.fixture(autouse=True)
def eager_celery():
    from callwrap_api.tasks.app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False


def test_stub_transcript_passes_real_gate_and_publishes_example_done(captured_results, tmp_path):
    """실제 게이트 통과 → 예시 analyzer 결과가 DONE 메시지로 발행되는지."""
    from callwrap_api.messaging.contracts import ResultStatus
    from callwrap_api.tasks.transcribe import transcribe_task

    audio = tmp_path / "call.wav"
    audio.write_bytes(b"dummy-audio")
    cid = uuid.uuid4()

    transcribe_task.apply(args=(str(cid), str(audio))).get()

    done = [m for m in captured_results if m.status is ResultStatus.DONE]
    assert len(done) == 1, "stub 전사는 실제 게이트를 통과해 DONE 발행까지 가야 한다"
    msg = done[0]
    assert msg.call_id == cid

    a = msg.analysis
    assert a["consultation_type"]["value"] == "사용법문의"
    assert a["consultation_type"]["confidence"] == 0.95
    assert a["grade"]["value"] == "일반"
    assert a["summary"]["value"]["title"]  # 요약 제목 비어있지 않음
    assert a["failures"] == []
    assert msg.failures == []

    # evidence_indices가 실존 발화 index만 가리키는지 (stub 전사는 index 0~3)
    valid = {0, 1, 2, 3}
    for field in ("summary", "consultation_type", "needs_followup"):
        assert set(a[field]["evidence_indices"]) <= valid
