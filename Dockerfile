# 독립 레포 빌드. 컨텍스트는 api/ 자신이다.
#   docker build -f Dockerfile .
# (callwrap-ai는 pyproject.toml의 [tool.uv.sources]에서 AI-model git 레포를 직접 물기 때문에
#  로컬 stubs/ 복사가 더 이상 필요 없다.)
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 의존성 해석에 필요한 파일만 먼저 복사한다 — 소스만 바뀌었을 때 캐시가 살아있게.
# --group stt: faster-whisper/pyannote/torch — STT_BACKEND=whisper가 기본값이 됐으므로
# 이걸 빼면 컨테이너가 뜨자마자 ModuleNotFoundError로 죽는다.
COPY pyproject.toml uv.lock* /app/
RUN uv sync --no-install-project --group stt

COPY . /app/
RUN uv sync --group stt

ENV PYTHONUNBUFFERED=1

# 기본은 헬스체크 API. worker/consumer는 compose에서 command로 각각 띄운다.
CMD ["uv", "run", "uvicorn", "callwrap_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
