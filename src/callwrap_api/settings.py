"""환경 설정. 실제 값은 저장소 루트의 .env에서 읽는다 (.env.example 참고, 커밋 금지)."""

from functools import lru_cache
from pathlib import Path

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
