"""환경 설정. 실제 값은 저장소 루트의 .env에서 읽는다 (.env.example 참고, 커밋 금지)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# api/src/callwrap_api/settings.py → api/
API_ROOT = Path(__file__).resolve().parents[2]
# api/ → 저장소 루트
REPO_ROOT = API_ROOT.parent


class Settings(BaseSettings):
    # .env는 저장소 루트에 하나만 둔다. api/.env도 있으면 그쪽이 우선.
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Celery broker 겸 Spring↔FastAPI 메시징 브로커. result backend는 쓰지 않는다
    # (결과는 RabbitMQ로 Spring에 발행하고, DB·상태 저장은 Spring이 소유한다).
    # 무상태 워커라 DATABASE_URL은 없다 — FastAPI는 DB를 건드리지 않는다.
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672//"

    # 오디오 취득 지점. local = 로컬/공유볼륨 경로. s3 = MinIO/S3(audio_uri가 s3://bucket/key).
    audio_source: str = "local"

    # audio_source="s3"일 때만 쓰인다. MinIO는 S3 API 호환이라 endpoint_url만 바꾸면 됩니다~
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    quality_gate_config_path: Path = API_ROOT / "config" / "quality_gate.yaml"
    stt_backend: str = "stub"

    # stt_backend="whisper"일 때만 쓰인다.
    whisper_model: str = "large-v3"      # faster-whisper 모델 크기 (tiny/base/small/medium/large-v3) — 정확도 우선
    hf_token: str | None = None          # pyannote 게이트 모델 다운로드용 (HuggingFace 토큰)
    # callwrap-ai와 STT가 함께 쓰는 추론 장치. 명시값만 허용해 CUDA DLL 문제를 CPU로 조용히 숨기지 않는다.
    callwrap_device: Literal["cpu", "cuda"] = "cpu"

    # FAQ 배치 생성기(routers/faq.py)가 Spring 내부 API(/api/internal/faq/*)를 호출할 때 쓴다.
    # 컨테이너 안에서 localhost는 컨테이너 자신을 가리키므로 host.docker.internal이 기본값.
    spring_api_base_url: str = "http://host.docker.internal:8080"
    #: Spring의 /api/internal/faq/** 를 부를 때 X-API-Key로 보낼 값.
    #: SecurityConfig의 ApiKeyAuthFilter.SCOPE_INTERNAL과 짝을 맞춘 값이어야 한다.
    spring_internal_api_key: str = ""
    #: 소분류 하나에 이 건수 이상 후보가 모여야 FAQ 생성을 시도한다. 너무 적으면 대표성이 없다.
    faq_min_group_size: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
