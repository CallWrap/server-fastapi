"""파이프라인 ② — 품질 게이트 태스크. 담당: 이정민.

판정 로직은 quality/orchestrator.py에 있다. 이 파일은 DB·상태 전이·다음 큐만 다룬다.
"""

import logging
import uuid

from callwrap_api.db import repository
from callwrap_api.db.session import SessionLocal
from callwrap_api.quality.config import load_quality_gate_config
from callwrap_api.quality.orchestrator import run_quality_gate
from callwrap_api.settings import get_settings
from callwrap_api.state import CallStatus
from callwrap_api.tasks.app import celery_app
from callwrap_api.tasks.base import PipelineTask

from callwrap_ai.schemas import Transcript

logger = logging.getLogger(__name__)


@celery_app.task(base=PipelineTask, bind=True, name="callwrap.quality_gate")
def run_quality_gate_task(self, call_id: str, transcript_json: str) -> str:
    """전사를 판정하고 다음 단계를 큐에 넣는다. 반환값은 결정된 액션.

    transcript를 인자로 넘기는 이유: 태스크가 자기 입력을 스스로 갖고 있어야
    단계 단위 재시도가 가능하다. (전사 본문 DB 저장은 Week 5 — 지금은 큐로만 넘긴다.)
    """
    from callwrap_api.tasks.analyze import analyze_task
    from callwrap_api.tasks.transcribe import transcribe_task

    settings = get_settings()
    transcript = Transcript.model_validate_json(transcript_json)
    config = load_quality_gate_config(settings.quality_gate_config_path)

    with SessionLocal() as db:
        call = repository.get_call(db, uuid.UUID(call_id))
        if call is None:
            raise ValueError(f"콜을 찾을 수 없다: {call_id}")

        # 중복 배달 방어. 게이트는 TRANSCRIBING에서만 들어온다.
        # 그 외 상태면 이미 판정을 지나간 콜이다 — 여기서 막지 않으면 set_status가
        # InvalidTransition을 던지고, on_failure가 그걸 받아 정상 콜을 FAILED로 뒤집는다.
        # (transcribe·analyze와 같은 가드. 셋 다 있어야 acks_late 중복이 안전하다.)
        if call.call_status is not CallStatus.TRANSCRIBING:
            logger.warning(
                "콜 %s는 %s 상태다 (TRANSCRIBING 아님). 중복 배달로 보고 건너뛴다.",
                call_id,
                call.status,
            )
            return "skipped"

        repository.set_status(db, call, CallStatus.QUALITY_CHECK)

        report = run_quality_gate(transcript, config, retry_count=call.retry_count)
        repository.save_gate_report(db, call, report)
        logger.info(
            "콜 %s 게이트 판정: %s (실패 %d/%d)",
            call_id,
            report.action,
            len(report.failed_checks),
            len(report.results),
        )

        if report.action == "pass":
            repository.set_status(db, call, CallStatus.PASSED)
            analyze_task.delay(call_id, transcript_json)
            return "pass"

        if report.action == "retry":
            # 재시도 카운터를 먼저 올린다. 올리기 전에 큐에 넣으면 워커가 옛 카운터로
            # 판정해서 상한을 넘겨 도는 경우가 생긴다.
            repository.set_status(db, call, CallStatus.RETRYING)
            repository.increment_retry(db, call)
            # 상태는 RETRYING인 채로 넘긴다. 여기서 TRANSCRIBING까지 올려버리면
            # transcribe의 중복 방어(이미 TRANSCRIBING이면 skip)에 걸려 재시도가 통째로
            # 무시된다. RETRYING → TRANSCRIBING 전이는 transcribe가 한다.
            transcribe_task.delay(call_id)
            return "retry"

        repository.set_status(db, call, CallStatus.NEEDS_HUMAN_REVIEW)
        return "human_review"
