"""
api/는 callwrap_ai.analyze() 하나만 부른다 (계약). analyze()는 무상태다 — DB도 Celery도
모른다. 그 경계를 여기서 지킨다.

무상태 워커: 결과를 DB에 저장하지 않고 RabbitMQ로 Spring에 발행한다. 저장은 Spring이 한다.
"""

import logging
import uuid

from callwrap_api.messaging import publisher
from callwrap_api.messaging.contracts import build_done
from callwrap_api.tasks.app import celery_app
from callwrap_api.tasks.base import PipelineTask

from callwrap_ai import analyze
from callwrap_ai.schemas import Transcript
from callwrap_ai.transcript_sanitizer import sanitize_transcript

logger = logging.getLogger(__name__)


@celery_app.task(base=PipelineTask, bind=True, name="callwrap.analyze")
def analyze_task(self, call_id: str, transcript_json: str) -> str:
    """품질 게이트를 통과한 전사를 분석하고 결과를 Spring에 발행한다."""
    transcript = Transcript.model_validate_json(transcript_json)
    safe_transcript = sanitize_transcript(transcript)

    # analyze()는 부분 실패를 예외로 던지지 않는다 — result.failures에 담아 돌려준다.
    # 일부 모듈이 실패해도 나머지 결과는 상담사에게 보여줘야 하므로 여기서 막지 않는다.
    result = analyze(transcript, summary_transcript=safe_transcript)

    # 결과를 Spring에 발행(DONE). 화면·DB에는 비속어를 마스킹한 전사만 보낸다.
    publisher.publish_result(build_done(uuid.UUID(call_id), result, safe_transcript))

    if result.failures:
        logger.warning("콜 %s 부분 실패: %s", call_id, result.failures)
    return f"failures={result.failures}"
