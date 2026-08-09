"""오디오 취득 — Spring이 업로드한 오디오를 FastAPI가 받아온다.

지원 백엔드: local(로컬/공유볼륨), s3(MinIO/S3 — audio_uri가 s3://bucket/key 형태).
"""

import tempfile
from pathlib import Path
from urllib.parse import urlparse

from callwrap_api.settings import get_settings


class UnknownAudioSource(Exception):
    """settings.audio_source가 모르는 값일 때."""


class AudioNotFound(Exception):
    """audio_uri가 가리키는 오디오를 못 찾았을 때."""


def fetch_audio(audio_uri: str) -> str:
    """audio_uri를 로컬 파일 경로로 해석해 돌려준다."""
    source = get_settings().audio_source
    if source == "local":
        return _resolve_local(audio_uri)
    if source == "s3":
        return _resolve_s3(audio_uri)
    raise UnknownAudioSource(
        f"모르는 오디오 소스: {source!r}. 현재 지원: 'local', 's3'"
    )


def _resolve_local(audio_uri: str) -> str:
    parsed = urlparse(audio_uri)
    if parsed.scheme in ("", "file"):
        path = Path(parsed.path if parsed.scheme == "file" else audio_uri)
        if not path.exists():
            raise AudioNotFound(f"오디오 파일이 없다: {path}")
        return str(path)
    raise UnknownAudioSource(
        f"'local' 백엔드는 {parsed.scheme!r} 스킴을 다루지 못한다: {audio_uri!r}"
    )

def _resolve_s3(audio_uri: str) -> str:

    """s3://bucket/key를 MinIO/S3에서 내려받아 로컬 임시 경로로 반환한다.

    진짜 AWS S3로 옮길 때도 이 함수는 그대로 — endpoint_url만 빠지면 된다.
    다운로드한 임시파일은 여기서 지우지 않는다. 파이프라인 태스크가 다 쓴 뒤 정리하는
       로직이 아직 없어서, 워커가 오래 떠 있으면 /tmp가 쌓인다 — todo..
    """
    import boto3

    parsed = urlparse(audio_uri)
    if parsed.scheme != "s3":
        raise UnknownAudioSource(
            f"'s3' 백엔드는 {parsed.scheme!r} 스킴을 다루지 못한다: {audio_uri!r}"
        )

    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    settings = get_settings()

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )

    suffix = Path(key).suffix or ".wav"
    tmp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = Path(tmp_file.name)
    tmp_file.close()

    try:
        client.download_file(bucket, key, str(tmp_path))
    except Exception as exc:  # noqa: BLE001 — boto3 예외 계층이 커서 넓게 잡고 우리 예외로 감쌈
        raise AudioNotFound(f"오디오 파일을 못 찾음: {audio_uri}") from exc

    return str(tmp_path)
