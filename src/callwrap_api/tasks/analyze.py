"""파이프라인 ③④ — AI 분석 호출 + 결과 저장. 담당: 이정민 (저장), 성진·재혁 (분석 로직).

api/는 callwrap_ai.analyze() 하나만 부른다 (api/README.md의 계약).
analyze()는 무상태다 — DB도 Celery도 모른다. 그 경계를 여기서 지킨다.
"""

import logging
import uuid

from callwrap_api.db import repository
from callwrap_api.db.session import SessionLocal
from callwrap_api.state import CallStatus
from callwrap_api.tasks.app import celery_app
from callwrap_api.tasks.base import PipelineTask

from callwrap_ai import analyze
from callwrap_ai.schemas import Transcript

logger = logging.getLogger(__name__)


@celery_app.task(base=PipelineTask, bind=True, name="callwrap.analyze")
def analyze_task(self, call_id: str, transcript_json: str) -> str:
    """품질 게이트를 통과한 전사를 분석하고 결과를 저장한다."""
    transcript = Transcript.model_validate_json(transcript_json)

    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        if call is None:
            raise ValueError(f"콜을 찾을 수 없다: {call_id}")
        if call.call_status in (CallStatus.ANALYZING, CallStatus.DONE):
            logger.warning("콜 %s는 이미 %s다. 중복 실행으로 보고 건너뛴다.", call_id, call.status)
            return "skipped"
        repository.set_status(db, call, CallStatus.ANALYZING)

    # analyze()는 부분 실패를 예외로 던지지 않는다 — result.failures에 담아 돌려준다.
    # 일부 모듈이 실패해도 나머지 결과는 상담사에게 보여줘야 하므로 여기서 막지 않는다.
    result = analyze(transcript)

    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        # 저장을 먼저, DONE 전환을 나중에. 순서가 바뀌면 status=DONE인데 분석이 아직
        # 없는 창이 생겨 프론트가 빈 상세를 받는다.
        # (Judgment.confidence·evidence_indices를 그대로 저장 → 3-tier UI·하이라이트용.
        #  F9 개방 준비 훅도 이 저장 이벤트에 붙게 된다.)
        repository.save_analysis_result(db, call, result)
        repository.set_status(db, call, CallStatus.DONE)

    if result.failures:
        logger.warning("콜 %s 부분 실패: %s", call_id, result.failures)
    return f"failures={result.failures}"
