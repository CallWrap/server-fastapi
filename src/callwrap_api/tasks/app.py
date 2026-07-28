"""Celery 앱. 브로커·백엔드 모두 Redis."""

from celery import Celery

from callwrap_api.settings import get_settings

_settings = get_settings()

celery_app = Celery(
    "callwrap",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
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
    # 워커가 죽어도 태스크가 사라지지 않게. 전사는 비싼 작업이라 유실되면 손해가 크다.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 태스크는 서로를 직접 부르지 않고 다음 태스크를 큐에 넣는다.
    # 단계별로 독립 재시도가 가능해야 하기 때문 (핵심 원칙).
    task_track_started=True,
)
