"""파이프라인 태스크 공통 베이스.

Week 1 검증에서 발견: 태스크가 예외로 죽으면 콜이 중간 상태(TRANSCRIBING 등)에
영원히 갇혔다. 상담사 화면엔 "전사 중"으로 계속 떠 있고 죽은 건지 도는 중인지 알 수 없다.

각 태스크가 try/except를 각자 쓰면 언젠가 하나가 빠진다. 베이스 클래스에 한 번 걸어둔다.
"""

import logging
import uuid
from typing import Any

from celery import Task

from callwrap_api.db import repository

logger = logging.getLogger(__name__)


class PipelineTask(Task):
    """실패하면 콜을 FAILED로 떨어뜨리는 태스크.

    모든 파이프라인 태스크의 첫 인자는 call_id(str)여야 한다 — on_failure가 그걸로
    콜을 찾는다. 이 규칙을 어기면 실패 시 상태 기록이 조용히 안 되므로
    _call_id_from()에서 방어한다.
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
                "태스크 %s 실패했으나 call_id를 못 찾아 FAILED 기록을 건너뛴다. args=%r",
                self.name,
                args,
            )
            return

        logger.error("태스크 %s 실패 → 콜 %s를 FAILED로. 원인: %r", self.name, call_id, exc)
        repository.mark_failed(call_id)

    @staticmethod
    def _call_id_from(args: tuple[Any, ...], kwargs: dict[str, Any]) -> uuid.UUID | None:
        raw = kwargs.get("call_id") or (args[0] if args else None)
        if not isinstance(raw, str):
            return None
        try:
            return uuid.UUID(raw)
        except ValueError:
            return None
