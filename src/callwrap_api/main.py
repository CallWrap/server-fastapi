"""FastAPI 앱. 실행: uv run uvicorn callwrap_api.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from callwrap_api.quality.config import load_quality_gate_config
from callwrap_api.routers import calls, health
from callwrap_api.settings import get_settings
from callwrap_api.state import InvalidTransition


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 품질 게이트 설정을 기동 시점에 한 번 읽는다.
    # 오타 난 임계값을 첫 콜이 아니라 기동 실패로 알게 하려는 것.
    settings = get_settings()
    load_quality_gate_config(settings.quality_gate_config_path)
    yield


app = FastAPI(
    title="CallWrap API",
    description="상담이 끝나면, 기록은 AI가 — 상담 후처리 자동화 백엔드",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(calls.router)


@app.exception_handler(InvalidTransition)
async def invalid_transition_handler(request: Request, exc: InvalidTransition) -> JSONResponse:
    """상태 전이 위반은 클라이언트 잘못이 아니라 우리 파이프라인의 버그다. 409로 드러낸다."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})
