"""Spring Job 컨슈머 — RabbitMQ의 깔끔한 JSON을 받아 Celery 파이프라인으로 넘긴다.

이 프로세스가 브리지다: Spring은 Celery 규격을 몰라도 되고(JobRequest JSON만 발행),
여기서 검증한 뒤 ingest_job.delay()로 Celery에 위임한다. 무거운 일(오디오 취득·전사·
분석)은 Celery worker가 한다 — 컨슈머는 파싱과 위임만.

실행:  python -m callwrap_api.messaging.consumer
(Celery worker와 함께 떠 있어야 한다. worker가 실제 파이프라인을 돌린다.)
"""

import logging

from kombu import Connection, Exchange, Queue
from kombu.mixins import ConsumerMixin

from callwrap_api.messaging import topology as topo
from callwrap_api.messaging.contracts import JobRequest
from callwrap_api.settings import get_settings

logger = logging.getLogger(__name__)


def dispatch_job(body: dict) -> None:
    """JSON Job 하나를 검증하고 Celery 파이프라인(transcribe)으로 넘긴다.

    Spring은 깔끔한 JobRequest JSON만 발행하면 된다(Celery 규격 불필요). 여기서 검증한 뒤
    transcribe_task.delay로 파이프라인을 시작한다. 컨슈머 콜백에서 분리해 둔 이유:
    브로커 없이 이 함수만 단위 테스트하기 위해서.
    """
    from callwrap_api.tasks.transcribe import transcribe_task

    job = JobRequest.model_validate(body)
    transcribe_task.delay(str(job.call_id), job.audio_uri)
    logger.info("Job 수신 call=%s → 파이프라인 시작", job.call_id)


class JobConsumer(ConsumerMixin):
    def __init__(self, connection: Connection):
        self.connection = connection
        exchange = Exchange(topo.EXCHANGE, type="topic", durable=True)
        self.queue = Queue(
            topo.QUEUE_JOBS,
            exchange=exchange,
            routing_key=topo.ROUTING_JOB_REQUEST,
            durable=True,
        )

    def get_consumers(self, Consumer, channel):
        return [Consumer(queues=[self.queue], callbacks=[self.on_message], accept=["json"])]

    def on_message(self, body, message):
        try:
            dispatch_job(body)
            message.ack()
        except Exception as exc:  # noqa: BLE001
            # 파싱 불능 등 — 재큐하면 무한 루프다. 거부해서 DLQ로 보낸다.
            logger.error("Job 처리 실패, DLQ로: %r body=%r", exc, body)
            message.reject(requeue=False)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with Connection(get_settings().rabbitmq_url) as conn:
        logger.info("JobConsumer 시작 — %s 큐 대기", topo.QUEUE_JOBS)
        JobConsumer(conn).run()


if __name__ == "__main__":
    main()
