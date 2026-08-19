# 독립 레포 빌드. 컨텍스트는 api/ 자신이다.
#   docker build -f Dockerfile .
# (callwrap-ai는 pyproject.toml의 [tool.uv.sources]에서 AI-model git 레포를 직접 물기 때문에
#  로컬 stubs/ 복사가 더 이상 필요 없다.)
FROM python:3.11-slim

# callwrap-ai가 pyproject.toml에서 git 소스(AI-model 레포)로 물려있어서, uv sync가 내부적으로
# git clone을 한다. python:3.11-slim엔 git이 안 깔려있어서 이게 없으면 "Git executable not found"로 죽는다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 의존성 해석에 필요한 파일만 먼저 복사한다 — 소스만 바뀌었을 때 캐시가 살아있게.
# --group stt: faster-whisper/pyannote/torch — STT_BACKEND=whisper가 기본값이 됐으므로
# 이걸 빼면 컨테이너가 뜨자마자 ModuleNotFoundError로 죽는다.
#
# callwrap-ai가 AI-model(비공개 레포)을 git 소스로 물고 있어서 uv sync가 내부적으로 그걸
# 클론해야 하는데, 비공개 레포라 인증이 필요하다. --mount=type=secret로 빌드 시점에만
# GitHub PAT을 꺼내 쓰고, 같은 RUN(레이어) 안에서 바로 지운다 — 이미지 레이어에 토큰이 남지 않는다.
COPY pyproject.toml uv.lock* /app/
RUN --mount=type=secret,id=github_token \
    git config --global url."https://$(cat /run/secrets/github_token)@github.com/".insteadOf "https://github.com/" && \
    uv sync --no-install-project --group stt && \
    git config --global --unset-all url."https://$(cat /run/secrets/github_token)@github.com/".insteadOf

COPY . /app/
RUN --mount=type=secret,id=github_token \
    git config --global url."https://$(cat /run/secrets/github_token)@github.com/".insteadOf "https://github.com/" && \
    uv sync --group stt && \
    git config --global --unset-all url."https://$(cat /run/secrets/github_token)@github.com/".insteadOf

ENV PYTHONUNBUFFERED=1

# 기본은 헬스체크 API. worker/consumer는 compose에서 command로 각각 띄운다.
CMD ["uv", "run", "uvicorn", "callwrap_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
