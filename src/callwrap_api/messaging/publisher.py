"""분석 결과를 RabbitMQ로 발행 → Spring이 소비. (FastAPI → Spring 방향)

kombu(Celery 동봉)로 발행한다. 별도 pika 의존성 불필요.

발행은 best-effort다: 브로커가 잠깐 죽어도 파이프라인/DB는 이미 성공한 뒤이므로
여기서 예외를 위로 던져 콜을 FAILED로 뒤집지 않는다 — 실패는 로그로 남긴다.
(신뢰성 강화(outbox 패턴)는 이후 하드닝 과제.)

호출부는 `from callwrap_api.messaging import publisher` 후 `publisher.publish_result(...)`로
쓴다 — 테스트에서 이 함수를 통째로 갈아끼울 수 있게(모듈 속성 패치).
"""

import logging

from kombu import Connection, Exchange

from callwrap_api.messaging import topology as topo
from callwrap_api.messaging.contracts import ResultMessage
from callwrap_api.settings import get_settings

logger = logging.getLogger(__name__)


def publish_result(message: ResultMessage) -> None:
    """결과 메시지를 callwrap 익스체인지에 result 라우팅키로 발행한다."""
    settings = get_settings()
    payload = message.model_dump(mode="json")
    try:
        with Connection(settings.rabbitmq_url, connect_timeout=3) as conn:
            exchange = Exchange(topo.EXCHANGE, type="topic", durable=True)
            producer = conn.Producer(serializer="json")
            producer.publish(
                payload,
                exchange=exchange,
                routing_key=topo.ROUTING_JOB_RESULT,
                declare=[exchange],
                retry=False,
            )
        logger.info("결과 발행 call=%s status=%s", message.call_id, message.status.value)
    except Exception as exc:  # noqa: BLE001 — 발행 실패가 파이프라인을 죽이면 안 된다
        logger.error(
            "결과 발행 실패 call=%s status=%s: %r (파이프라인은 성공, 결과만 미전달)",
            message.call_id,
            message.status.value,
            exc,
        )
