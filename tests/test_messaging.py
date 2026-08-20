"""Spring ↔ FastAPI 메시징 검증 (무상태 P2).

- 계약(build_*)·JobRequest 검증·컨슈머 dispatch: 순수 검증(브로커·DB 불필요).
- dispatch → 파이프라인 → DONE 발행: Celery eager로 전 구간 확인.

발행은 conftest의 captured_results(autouse)가 가로채므로 실제 RabbitMQ 없이
"무엇이 발행됐는가"를 그대로 검증한다.
"""

import uuid

import pytest

from callwrap_api.messaging.contracts import (
    JobRequest,
    ResultStatus,
    build_done,
    build_failed,
    build_human_review,
)


def _transcript():
    from callwrap_ai.schemas import Speaker, Transcript, Utterance

    return Transcript(
        utterances=[
            Utterance(index=0, speaker=Speaker.CUSTOMER, text="x", start=0, end=1, confidence=0.9)
        ]
    )


# ── 계약 ────────────────────────────────────────────────


def test_build_done_carries_analysis_and_transcript(fixed_analysis):
    cid = uuid.uuid4()
    msg = build_done(cid, fixed_analysis, _transcript())
    assert msg.status is ResultStatus.DONE
    assert msg.call_id == cid
    assert msg.analysis["consultation_type"]["value"] == fixed_analysis.consultation_type.value.value
    # 전사도 같이 실린다 — 상담사 화면의 전사 패널은 이 필드가 없으면 원문을 못 그린다.
    assert msg.transcript["utterances"][0]["speaker"] == "고객"
    assert msg.failures == []


def test_build_human_review_carries_failed_checks():
    cid = uuid.uuid4()
    msg = build_human_review(cid, ["check_speaker_overlap"])
    assert msg.status is ResultStatus.NEEDS_HUMAN_REVIEW
    assert msg.analysis is None
    assert msg.quality.failed_checks == ["check_speaker_overlap"]


def test_build_failed_carries_error():
    cid = uuid.uuid4()
    msg = build_failed(cid, "boom")
    assert msg.status is ResultStatus.FAILED
    assert msg.error == "boom"


def test_job_request_rejects_bad_uuid():
    with pytest.raises(ValueError):
        JobRequest.model_validate({"call_id": "not-a-uuid", "audio_uri": "/x.wav"})


# ── 컨슈머 브리지 ────────────────────────────────────────


def test_dispatch_job_validates_and_starts_pipeline(monkeypatch):
    """깔끔한 JSON Job → 검증 → transcribe로 파이프라인 시작. (Spring은 Celery 규격 몰라도 됨)"""
    from callwrap_api.messaging import consumer
    from callwrap_api.tasks import transcribe

    sent = []
    monkeypatch.setattr(transcribe.transcribe_task, "delay", lambda *a, **k: sent.append((a, k)))

    cid = uuid.uuid4()
    consumer.dispatch_job({"call_id": str(cid), "audio_uri": "/tmp/x.wav"})

    assert sent == [((str(cid), "/tmp/x.wav"), {})]


# ── dispatch → 파이프라인 end-to-end ────────────────────


@pytest.fixture
def eager_celery():
    from callwrap_api.tasks.app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False


def test_dispatch_runs_full_pipeline_and_publishes_done(
    eager_celery, captured_results, fixed_analysis, tmp_path
):
    """Spring Job(JSON) → dispatch → transcribe→gate→analyze → DONE 발행."""
    from callwrap_api.messaging import consumer

    audio = tmp_path / "call.wav"
    audio.write_bytes(b"dummy-audio")
    cid = uuid.uuid4()

    consumer.dispatch_job({"call_id": str(cid), "audio_uri": str(audio)})

    done = [m for m in captured_results if m.status is ResultStatus.DONE]
    assert len(done) == 1
    assert done[0].call_id == cid
    assert done[0].analysis["grade"]["value"] == fixed_analysis.grade.value.value
