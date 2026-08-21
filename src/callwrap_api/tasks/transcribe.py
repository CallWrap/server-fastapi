"""
실제 전사는 stt/가 맡는다. 이 태스크는 오디오를 받아와 stt/를 부르고 결과를 ②로 넘긴다.
★ Whisper → 이노하이 교체 지점이 _transcribe() 아래로 숨는다.

무상태 워커: DB를 건드리지 않는다. 상태(call_id·audio_uri·retry_count)는 전부 인자로
흐른다. audio_uri를 계속 들고 다니는 이유 — 게이트가 retry를 걸면 여기로 다시 와서
같은 오디오를 재전사해야 하기 때문.
"""

import logging

from callwrap_api.messaging.audio import (
    TransientAudioError,
    cleanup_fetched_audio,
    fetch_audio,
)
from callwrap_api.settings import get_settings
from callwrap_api.stt_stub import transcribe_stub
from callwrap_api.tasks.app import celery_app
from callwrap_api.tasks.base import PipelineTask

from callwrap_ai.schemas import Transcript

logger = logging.getLogger(__name__)


class UnknownSTTBackend(Exception):
    """settings.stt_backend가 모르는 값일 때."""


def _transcribe(audio_path: str) -> Transcript:
    """설정된 백엔드로 전사한다. ★ 여기가 STT 교체 지점.

    stt/가 준비되면 "whisper" 분기를 추가하고 settings 기본값을 바꾼다.
    이 함수 밖의 코드는 어떤 백엔드인지 몰라도 된다.
    """
    backend = get_settings().stt_backend
    if backend == "stub":
        return transcribe_stub(audio_path)
    if backend == "whisper":
        from callwrap_api.stt_whisper import transcribe_whisper

        return transcribe_whisper(audio_path)
    raise UnknownSTTBackend(
        f"모르는 STT 백엔드: {backend!r}. 현재 지원: 'stub', 'whisper'"
    )


@celery_app.task(
    base=PipelineTask,
    bind=True,
    name="callwrap.transcribe",
    autoretry_for=(TransientAudioError,),
    retry_backoff=2,       # 2초, 4초, 8초 ...
    retry_backoff_max=30,
    retry_jitter=True,
    max_retries=3,
)
def transcribe_task(self, call_id: str, audio_uri: str, retry_count: int = 0) -> str:
    """오디오를 받아와 전사하고 품질 게이트 큐에 넣는다.

    재시도로 다시 들어올 수도 있다(게이트가 retry_count를 올려 되보낸다). 같은 경로다.
    실패하면 PipelineTask.on_failure가 Spring에 FAILED를 발행한다.
    """
    # 순환 임포트를 피해 함수 안에서 임포트한다.
    from callwrap_api.tasks.quality_gate import run_quality_gate_task

    audio_path = fetch_audio(audio_uri)
    try:
        transcript = _transcribe(audio_path)
    finally:
        cleanup_fetched_audio(audio_path)
    run_quality_gate_task.delay(
        call_id, transcript.model_dump_json(), audio_uri, retry_count
    )
    return f"utterances={len(transcript.utterances)} retry={retry_count}"
