"""FastAPI 앱 — liveness/헬스체크 전용. 실행: uv run uvicorn callwrap_api.main:app --reload

무상태 워커라 업무 API(업로드·조회)는 없다 — 그건 Spring이 소유한다. 이 앱은 컨테이너
liveness와 STT 백엔드 노출용 /health 하나만 제공한다. 실제 일은 Celery worker와
messaging/consumer가 한다.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from callwrap_api.quality.config import load_quality_gate_config
from callwrap_api.routers import health
from callwrap_api.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 품질 게이트 설정을 기동 시점에 한 번 읽는다.
    # 오타 난 임계값을 첫 콜이 아니라 기동 실패로 알게 하려는 것.
    settings = get_settings()
    load_quality_gate_config(settings.quality_gate_config_path)
    yield


app = FastAPI(
    title="CallWrap API",
    description="상담이 끝나면, 기록은 AI가 — 상담 후처리 자동화 워커(헬스체크 전용 API)",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
