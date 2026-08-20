"""게이트 통과 → DONE 발행 end-to-end 검증 (무상태).

가짜 체크를 쓰지 않는다 — STT stub이 만든 전사를 실제 품질 게이트(실제 checks +
config/quality_gate.yaml)에 통과시키고, analyze()의 결과가 Spring으로 발행되는 DONE
메시지에 그대로 실리는지 확인한다.

**analyze() 자체는 fixed_analysis로 고정한다.** 예전엔 stubs/callwrap-ai가 고정값을
내줘서 그 값을 그대로 단언했는데, 실제 AI-model을 git 소스로 물면서 그 단언이 깨졌다
(consultation_type은 SR 모델 미연동이라 "기타" 고정, 분류는 체크포인트가 있어야 값이 난다).
여기서 검증할 것은 값이 아니라 경로다 — 판정값 검증은 AI-model 쪽 테스트가 한다.

DB도 브로커도 모델도 없다. 발행은 captured_results가 가로챈다.
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


def test_stub_transcript_passes_real_gate_and_publishes_done(
    captured_results, fixed_analysis, tmp_path
):
    """실제 게이트 통과 → analyze() 결과가 DONE 메시지로 발행되는지."""
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
    # AnalysisResult가 계약 형태 그대로(Judgment = value+confidence+evidence_indices) 실렸는지
    assert a["consultation_type"]["value"] == fixed_analysis.consultation_type.value.value
    assert a["consultation_type"]["confidence"] == fixed_analysis.consultation_type.confidence
    assert a["grade"]["value"] == fixed_analysis.grade.value.value
    assert a["summary"]["value"]["title"]  # 요약 제목 비어있지 않음
    assert a["failures"] == []
    assert msg.failures == []

    # 전사 원본도 함께 실린다 (web 전사 패널용)
    assert msg.transcript is not None and msg.transcript["utterances"]

    # evidence_indices가 실존 발화 index만 가리키는지 (stub 전사는 index 0~3)
    valid = {u["index"] for u in msg.transcript["utterances"]}
    for field in ("summary", "consultation_type", "needs_followup"):
        assert set(a[field]["evidence_indices"]) <= valid
