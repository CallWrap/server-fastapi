from pathlib import Path

from callwrap_api.messaging.audio import _resolve_local


def test_resolve_local_accepts_native_absolute_path(tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"audio")

    assert Path(_resolve_local(str(audio))) == audio


def test_resolve_local_accepts_file_uri(tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"audio")

    assert Path(_resolve_local(audio.as_uri())) == audio
