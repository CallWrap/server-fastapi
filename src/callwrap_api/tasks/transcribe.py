"""파이프라인 ① — STT + 화자분리 태스크. 담당: 김규리, 이정민 (세부 분담 미정).

실제 전사는 stt/가 맡는다. 이 태스크는 stt/를 부르고 결과를 ②로 넘기기만 한다.
★ Whisper → 이노하이 교체 지점이 _transcribe() 아래로 숨는다.
"""

import logging
import uuid

from callwrap_api.db import repository
from callwrap_api.db.session import SessionLocal
from callwrap_api.settings import get_settings
from callwrap_api.state import CallStatus
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
    raise UnknownSTTBackend(
        f"모르는 STT 백엔드: {backend!r}. 현재 지원: 'stub' (stt/ 연동 대기)"
    )


@celery_app.task(base=PipelineTask, bind=True, name="callwrap.transcribe")
def transcribe_task(self, call_id: str) -> str:
    """음성 파일을 전사하고 품질 게이트 큐에 넣는다.

    재시도로 다시 들어올 수도 있다 (RETRYING → TRANSCRIBING). 그때도 같은 경로다.
    """
    # 순환 임포트를 피해 함수 안에서 임포트한다 (quality_gate가 이 모듈을 되부른다).
    from callwrap_api.tasks.quality_gate import run_quality_gate_task

    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        if call is None:
            raise ValueError(f"콜을 찾을 수 없다: {call_id}")

        if call.call_status is CallStatus.TRANSCRIBING:
            # 이미 전사 중 — 중복 배달이다. 다시 돌리면 큐에 두 번 들어간다.
            logger.warning("콜 %s는 이미 TRANSCRIBING이다. 중복 실행으로 보고 건너뛴다.", call_id)
            return "skipped"

        repository.set_status(db, call, CallStatus.TRANSCRIBING)
        audio_path = call.audio_path

    transcript = _transcribe(audio_path)
    run_quality_gate_task.delay(call_id, transcript.model_dump_json())
    return f"utterances={len(transcript.utterances)}"
