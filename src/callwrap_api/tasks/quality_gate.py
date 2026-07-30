"""

무상태 워커: DB를 건드리지 않는다. retry_count는 인자로 받아 판정에 쓰고, 재시도할 땐
retry_count+1을 실어 transcribe로 되보낸다. 상한(max_retry) 도달 시 사람 검토로 넘어간다.
품질 체크 이력 저장(Week 7 튜닝용)은 Spring이 결과를 보관한다 — 여기서 저장하지 않는다.
"""

import logging

from callwrap_api.messaging import publisher
from callwrap_api.messaging.contracts import build_human_review
from callwrap_api.quality.config import load_quality_gate_config
from callwrap_api.quality.orchestrator import run_quality_gate
from callwrap_api.settings import get_settings
from callwrap_api.tasks.app import celery_app
from callwrap_api.tasks.base import PipelineTask

from callwrap_ai.schemas import Transcript

logger = logging.getLogger(__name__)


@celery_app.task(base=PipelineTask, bind=True, name="callwrap.quality_gate")
def run_quality_gate_task(
    self, call_id: str, transcript_json: str, audio_uri: str, retry_count: int = 0
) -> str:
    """전사를 판정하고 다음 단계를 큐에 넣는다. 반환값은 결정된 액션.

    transcript를 인자로 받는 이유: 태스크가 자기 입력을 스스로 갖고 있어야 단계 단위
    재시도가 가능하다. audio_uri도 함께 받는다 — 재시도 시 transcribe로 되보내야 하므로.
    """
    from callwrap_api.tasks.analyze import analyze_task
    from callwrap_api.tasks.transcribe import transcribe_task

    settings = get_settings()
    transcript = Transcript.model_validate_json(transcript_json)
    config = load_quality_gate_config(settings.quality_gate_config_path)

    report = run_quality_gate(transcript, config, retry_count=retry_count)
    logger.info(
        "콜 %s 게이트 판정: %s (실패 %d/%d, retry=%d)",
        call_id,
        report.action,
        len(report.failed_checks),
        len(report.results),
        retry_count,
    )

    if report.action == "pass":
        analyze_task.delay(call_id, transcript_json)
        return "pass"

    if report.action == "retry":
        # retry_count를 올려 되보낸다. 상한 판정은 다음 회차 게이트가 한다.
        transcribe_task.delay(call_id, audio_uri, retry_count + 1)
        return "retry"

    # human_review — 사람 검토로 넘어감을 Spring에 발행(실패한 체크명으로 사유 전달).
    failed = [r.check_name for r in report.failed_checks]
    publisher.publish_result(build_human_review(_as_uuid(call_id), failed))
    return "human_review"


def _as_uuid(call_id: str):
    import uuid

    return uuid.UUID(call_id)
