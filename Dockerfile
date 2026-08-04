# 독립 레포 빌드. 컨텍스트는 api/ 자신이다.
#   docker build -f Dockerfile .
# (callwrap-ai는 stubs/callwrap-ai 예시 패키지를 로컬 경로로 물기 때문에 함께 복사한다.)
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 의존성 해석에 필요한 파일만 먼저 복사한다 — 소스만 바뀌었을 때 캐시가 살아있게.
# 예시 패키지(stubs/)는 path 의존이라 lock 해석 시점에 있어야 한다.
COPY pyproject.toml uv.lock* /app/
COPY stubs /app/stubs
RUN uv sync --no-install-project

COPY . /app/
RUN uv sync

ENV PYTHONUNBUFFERED=1

# 기본은 헬스체크 API. worker/consumer는 compose에서 command로 각각 띄운다.
CMD ["uv", "run", "uvicorn", "callwrap_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
