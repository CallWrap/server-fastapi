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
    # 하트비트를 끈다. --pool=solo에서는 전사(Whisper+pyannote)가 도는 동안 메인 프로세스가
    # CPU에 묶여 AMQP 하트비트를 못 보낸다. 3분짜리 통화 하나가 187초 걸리는데 기본 하트비트는
    # 60초라, 브로커가 연결을 끊고("Server unexpectedly closed connection") 그 순간
    # acks_late 태스크는 ack을 못 한 채 큐로 되돌아간다 — 전사에 성공하고도 같은 콜을
    # 영원히 다시 처리하는 루프가 된다.
    # 연결이 진짜 죽는 건 TCP가 알려주므로 하트비트 없이도 감지된다.
    broker_heartbeat=0,
)
