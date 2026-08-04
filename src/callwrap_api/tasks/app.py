"""Celery 앱. broker는 RabbitMQ. result backend는 없다.

무상태 워커: 결과는 messaging/publisher가 RabbitMQ로 Spring에 발행하고, 파이프라인
상태는 태스크 인자로 흐른다 — Celery result backend를 읽는 코드가 없어 두지 않는다.

Spring Job은 messaging/consumer(kombu)가 callwrap.jobs 큐에서 받아 transcribe로 넘긴다.
그래서 Celery worker는 자기 기본 큐만 소비하면 되고, 여기서 큐 라우팅을 손댈 필요가 없다.
"""

from celery import Celery

from callwrap_api.settings import get_settings

_settings = get_settings()

celery_app = Celery(
    "callwrap",
    broker=_settings.rabbitmq_url,
    include=[
        "callwrap_api.tasks.transcribe",
        "callwrap_api.tasks.quality_gate",
        "callwrap_api.tasks.analyze",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Seoul",
    enable_utc=True,
    # result backend가 없다. 결과는 RabbitMQ로 Spring에 발행한다.
    task_ignore_result=True,
    # 워커가 죽어도 태스크가 사라지지 않게. 전사는 비싼 작업이라 유실되면 손해가 크다.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
