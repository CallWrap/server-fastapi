"""오디오 취득 — Spring이 업로드한 오디오를 FastAPI가 받아온다.

★ 교체 지점. 지금은 로컬/공유 볼륨 경로만 지원한다. 오브젝트 스토리지(S3/MinIO)가
   정해지면 여기에 백엔드 분기를 추가한다 (settings.audio_source). stt_stub과 같은 패턴.

이 함수 밖의 코드는 audio_uri가 어디서 왔는지(로컬/S3) 몰라도 된다 — 항상 로컬 경로를 돌려준다.
"""

from pathlib import Path
from urllib.parse import urlparse

from callwrap_api.settings import get_settings


class UnknownAudioSource(Exception):
    """settings.audio_source가 모르는 값일 때."""


class AudioNotFound(Exception):
    """audio_uri가 가리키는 오디오를 못 찾았을 때."""


def fetch_audio(audio_uri: str) -> str:
    """audio_uri를 로컬 파일 경로로 해석해 돌려준다. ★ 여기가 스토리지 교체 지점.

    'local' 백엔드: file:// 스킴 또는 맨 경로를 그대로 로컬 파일로 본다.
    (오브젝트 스토리지 백엔드는 스토리지 확정 후 추가 — 다운로드해서 로컬 경로 반환.)
    """
    source = get_settings().audio_source
    if source == "local":
        return _resolve_local(audio_uri)
    raise UnknownAudioSource(
        f"모르는 오디오 소스: {source!r}. 현재 지원: 'local' (오브젝트 스토리지 연동 대기)"
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
