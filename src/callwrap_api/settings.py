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

    database_url: str = "postgresql+psycopg://callwrap:callwrap@localhost:5432/callwrap"
    redis_url: str = "redis://localhost:6379/0"

    # 업로드된 음성 파일 저장 위치. 로컬 전용 — .gitignore 처리됨.
    # 실서비스에서는 오브젝트 스토리지로 교체될 지점이다.
    audio_storage_dir: Path = API_ROOT / "data" / "audio"

    # 품질 게이트 임계값 파일 (규리와 공유하는 설정)
    quality_gate_config_path: Path = API_ROOT / "config" / "quality_gate.yaml"

    # ★ STT 교체 지점. stub = 고정 더미 전사(stt_stub.py), 오디오를 읽지 않는다.
    #    stt/가 준비되면 "whisper"를 추가하고 기본값을 바꾼다.
    #    실서비스에서 stub이 켜진 채로 돌면 안 된다 — /health에 노출해 눈에 띄게 했다.
    stt_backend: str = "stub"


@lru_cache
def get_settings() -> Settings:
    return Settings()
