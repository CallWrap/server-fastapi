# 빌드 컨텍스트는 저장소 루트다 (api/가 ../ai를 로컬 경로로 물기 때문).
#   docker build -f api/Dockerfile .
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 의존성 해석에 필요한 파일만 먼저 복사한다 — 소스만 바뀌었을 때 캐시가 살아있게.
COPY api/pyproject.toml api/uv.lock* /app/api/
COPY ai/pyproject.toml ai/uv.lock* /app/ai/
COPY ai/README.md /app/ai/
COPY ai/src /app/ai/src

WORKDIR /app/api
RUN uv sync --no-install-project

COPY api/ /app/api/
RUN uv sync

ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "uvicorn", "callwrap_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
