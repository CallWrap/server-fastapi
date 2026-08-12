"""stt_whisper 병합 로직 검증 — 모델 없이 순수 함수만 (faster-whisper·pyannote 미설치에서도 돈다)."""

from callwrap_api.stt_whisper import (
    _assign_speakers,
    _confidence,
    _dominant_speaker,
    _role_map,
)

from callwrap_ai.schemas import Speaker


def test_role_map_first_speaker_is_counselor():
    turns = [(2.0, 5.0, "B"), (0.0, 2.0, "A")]  # A가 먼저 발화
    roles = _role_map(turns)
    assert roles["A"] == Speaker.COUNSELOR
    assert roles["B"] == Speaker.CUSTOMER


def test_dominant_speaker_picks_max_overlap():
    turns = [(0.0, 3.0, "A"), (2.5, 6.0, "B")]
    assert _dominant_speaker(0.0, 2.0, turns) == "A"
    assert _dominant_speaker(3.5, 6.0, turns) == "B"
    assert _dominant_speaker(10.0, 11.0, turns) is None  # 겹침 없음


def test_assign_speakers_maps_segments_to_roles():
    whisper = [(0.0, 2.0, " 안녕하세요 ", -0.1), (2.5, 5.0, "네 말씀하세요", -0.5)]
    turns = [(0.0, 2.0, "A"), (2.5, 5.0, "B")]
    utts = _assign_speakers(whisper, turns)
    assert [u.speaker for u in utts] == [Speaker.COUNSELOR, Speaker.CUSTOMER]
    assert utts[0].text == "안녕하세요"  # strip됨
    assert [u.index for u in utts] == [0, 1]
    assert 0.0 <= utts[0].confidence <= 1.0


def test_no_overlap_segment_defaults_counselor():
    utts = _assign_speakers([(10.0, 11.0, "음", -0.2)], [(0.0, 2.0, "A")])
    assert utts[0].speaker == Speaker.COUNSELOR


def test_confidence_normalizes_logprob():
    assert _confidence(0.0) == 1.0
    assert _confidence(None) is None
    assert 0.0 < _confidence(-1.0) < 1.0
