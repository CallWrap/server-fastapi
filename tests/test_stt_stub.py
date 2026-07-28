"""stub 전사기 검증. ★ stt/가 붙으면 이 파일은 버린다."""

import pytest

from callwrap_api.quality.config import load_quality_gate_config
from callwrap_api.quality.orchestrator import run_quality_gate
from callwrap_api.settings import get_settings
from callwrap_api.stt_stub import make_bad_transcript, transcribe_stub
from callwrap_api.tasks.transcribe import UnknownSTTBackend, _transcribe

from callwrap_ai.schemas import Transcript


def test_stub_returns_valid_transcript():
    t = transcribe_stub("/tmp/whatever.wav")
    assert isinstance(t, Transcript)
    assert len(t.utterances) == 4


def test_stub_indices_are_contiguous_from_zero():
    """evidence_indices가 이걸 가리키므로 순번이 어긋나면 web/ 하이라이트가 깨진다."""
    t = transcribe_stub("/tmp/x.wav")
    assert [u.index for u in t.utterances] == [0, 1, 2, 3]


def test_stub_utterances_are_time_ordered_and_non_overlapping():
    """좋은 전사여야 게이트를 통과한다 — happy path 테스트의 전제."""
    t = transcribe_stub("/tmp/x.wav")
    for prev, cur in zip(t.utterances, t.utterances[1:]):
        assert prev.end <= cur.start, f"{prev.index} → {cur.index} 겹침"


def test_stub_segment_lengths_are_sane():
    """quality_gate.yaml의 min 0.5초 / max 60초 안에 있어야 한다."""
    for u in transcribe_stub("/tmp/x.wav").utterances:
        assert 0.5 <= (u.end - u.start) <= 60.0


def test_bad_transcript_actually_overlaps():
    """실패 경로 테스트용 데이터가 실제로 겹치는지."""
    u = make_bad_transcript().utterances
    assert u[0].speaker != u[1].speaker
    assert u[1].start < u[0].end  # 겹침


def test_bad_transcript_has_an_extreme_segment():
    lengths = [u.end - u.start for u in make_bad_transcript().utterances]
    assert any(length < 0.5 for length in lengths)


def test_transcribe_dispatches_to_stub():
    assert len(_transcribe("/tmp/x.wav").utterances) == 4


def test_unknown_backend_raises(monkeypatch):
    """오타 난 STT_BACKEND가 조용히 넘어가면 안 된다."""
    import callwrap_api.tasks.transcribe as mod

    class FakeSettings:
        stt_backend = "whipser"  # 오타

    monkeypatch.setattr(mod, "get_settings", lambda: FakeSettings())
    with pytest.raises(UnknownSTTBackend, match="whipser"):
        _transcribe("/tmp/x.wav")

def test_stub_transcript_passes_the_gate_once_checks_exist():
    """체크 4개(①②③④)가 전부 구현된 뒤엔 정상 stub 데이터가 게이트를 통과해야 한다.

    Week 3 이전엔 체크가 미구현이라 human_review로 떨어졌다(과거 동작).
    체크 4개가 전부 구현된 지금은 pass를 기대한다 — stub 데이터가 "정상적인"
    콜 표본으로 잘 만들어져 있는지 검증하는 자리표시자.
    """
    config = load_quality_gate_config(get_settings().quality_gate_config_path)
    report = run_quality_gate(transcribe_stub("/tmp/x.wav"), config)
    assert report.action == "pass"
    assert all(r.passed for r in report.results)
