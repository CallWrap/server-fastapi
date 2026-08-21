from pathlib import Path
from types import SimpleNamespace

from callwrap_api.messaging import audio as audio_module
from callwrap_api.messaging.audio import _resolve_local, cleanup_fetched_audio


def test_resolve_local_accepts_native_absolute_path(tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"audio")

    assert Path(_resolve_local(str(audio))) == audio


def test_resolve_local_accepts_file_uri(tmp_path):
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"audio")

    assert Path(_resolve_local(audio.as_uri())) == audio


def test_cleanup_fetched_audio_removes_s3_temp_file(tmp_path, monkeypatch):
    downloaded = tmp_path / "downloaded.wav"
    downloaded.write_bytes(b"audio")
    monkeypatch.setattr(
        audio_module, "get_settings", lambda: SimpleNamespace(audio_source="s3")
    )

    cleanup_fetched_audio(str(downloaded))

    assert not downloaded.exists()


def test_cleanup_fetched_audio_preserves_local_file(tmp_path, monkeypatch):
    original = tmp_path / "original.wav"
    original.write_bytes(b"audio")
    monkeypatch.setattr(
        audio_module, "get_settings", lambda: SimpleNamespace(audio_source="local")
    )

    cleanup_fetched_audio(str(original))

    assert original.exists()
