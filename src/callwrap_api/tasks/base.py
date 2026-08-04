"""파이프라인 태스크 공통 베이스.

Week 1 검증에서 발견: 태스크가 예외로 죽으면 콜이 어중간하게 끝나 상담사 화면에서
죽은 건지 도는 중인지 알 수 없었다. 각 태스크가 try/except를 각자 쓰면 언젠가 하나가
빠진다. 베이스 클래스에 한 번 걸어둔다.

무상태 워커: 실패를 DB에 기록하지 않고 Spring에 FAILED를 발행한다(단일 발행 지점).
"""

import logging
import uuid
from typing import Any

from celery import Task

logger = logging.getLogger(__name__)


class PipelineTask(Task):
    """실패하면 Spring에 FAILED를 발행하는 태스크.

    모든 파이프라인 태스크의 첫 인자는 call_id(str)여야 한다 — on_failure가 그걸로
    콜을 식별한다. 이 규칙을 어기면 실패 시 발행이 조용히 안 되므로 _call_id_from()에서 방어한다.
    """

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        call_id = self._call_id_from(args, kwargs)
        if call_id is None:
            logger.error(
                "태스크 %s 실패했으나 call_id를 못 찾아 FAILED 발행을 건너뛴다. args=%r",
                self.name,
                args,
            )
            return

        logger.error("태스크 %s 실패 → 콜 %s FAILED 발행. 원인: %r", self.name, call_id, exc)
        # 지연 임포트 — publisher가 settings·kombu를 물어와 임포트 그래프가 커진다.
        from callwrap_api.messaging import publisher
        from callwrap_api.messaging.contracts import build_failed

        publisher.publish_result(build_failed(call_id, repr(exc)))

    @staticmethod
    def _call_id_from(args: tuple[Any, ...], kwargs: dict[str, Any]) -> uuid.UUID | None:
        raw = kwargs.get("call_id") or (args[0] if args else None)
        if not isinstance(raw, str):
            return None
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None
