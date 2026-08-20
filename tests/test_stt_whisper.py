"""stt_whisper 병합 로직 검증 — 모델 없이 순수 함수만 (faster-whisper·pyannote 미설치에서도 돈다)."""

from callwrap_api.stt_whisper import (
    _assign_speakers,
    _confidence,
    _role_map,
    _speaker_at,
    _to_spans,
)

from callwrap_ai.schemas import Speaker


def test_role_map_first_speaker_is_counselor():
    turns = [(2.0, 5.0, "B"), (0.0, 2.0, "A")]  # A가 먼저 발화
    roles = _role_map(turns)
    assert roles["A"] == Speaker.COUNSELOR
    assert roles["B"] == Speaker.CUSTOMER


def test_speaker_at_finds_covering_turn():
    turns = [(0.0, 3.0, "A"), (2.5, 6.0, "B")]
    assert _speaker_at(1.0, turns) == "A"
    assert _speaker_at(5.0, turns) == "B"
    assert _speaker_at(2.7, turns) == "B"  # 겹치면 늦게 시작한 쪽(교대 직후)
    assert _speaker_at(10.0, turns) is None


def test_words_split_at_speaker_change():
    """한 Whisper 세그먼트가 두 화자에 걸쳐도 화자 전환 지점에서 발화가 갈린다.

    실제 통화에서 "…안 됐다고 / 나와서요. 네 확인해드리겠습니다"가 한 세그먼트로 묶여
    고객 말꼬리가 상담사 발화에 붙었던 문제 — 그 상황을 그대로 재현한다.
    """
    words = [
        (0.0, 0.5, " 안", 0.9), (0.5, 1.0, "됐다고", 0.9),   # 고객 구간
        (1.0, 1.5, " 나와서요", 0.8),                          # 아직 고객
        (2.0, 2.5, " 네", 0.7), (2.5, 3.0, " 확인해드리겠습니다", 0.7),  # 상담사
    ]
    turns = [(0.0, 1.8, "B"), (1.9, 3.0, "A"), (0.0, 0.0, "A")]
    utts = _assign_speakers(words, turns)

    assert len(utts) == 2
    assert utts[0].text == "안됐다고 나와서요"
    assert utts[1].text == "네 확인해드리겠습니다"
    assert utts[0].start == 0.0 and utts[0].end == 1.5
    assert [u.index for u in utts] == [0, 1]


def test_confidence_is_word_probability_mean():
    words = [(0.0, 0.5, "가", 0.9), (0.5, 1.0, "나", 0.7)]
    utts = _assign_speakers(words, [(0.0, 1.0, "A")])
    assert utts[0].confidence == 0.8  # 창 단위가 아니라 이 발화의 단어 평균


def test_unmatched_word_continues_previous_speaker():
    """화자 구간 사이 빈틈에 떨어진 단어는 직전 화자를 잇는다 — 거기서 끊으면 문장이 조각난다."""
    words = [(0.0, 0.5, "네", 0.9), (0.6, 0.9, " 그렇군요", 0.9)]
    turns = [(0.0, 0.55, "A")]  # 두 번째 단어는 어떤 구간에도 안 들어간다
    utts = _assign_speakers(words, turns)
    assert len(utts) == 1
    assert utts[0].text == "네 그렇군요"


def test_leading_word_without_turn_defaults_counselor():
    utts = _assign_speakers([(10.0, 11.0, "음", 0.5)], [(0.0, 2.0, "A")])
    assert utts[0].speaker == Speaker.COUNSELOR


def test_to_spans_falls_back_to_segment_when_no_words():
    class Segment:
        def __init__(self, start, end, text, avg_logprob, words=None):
            self.start, self.end, self.text = start, end, text
            self.avg_logprob, self.words = avg_logprob, words

    class Word:
        def __init__(self, start, end, word, probability):
            self.start, self.end, self.word, self.probability = start, end, word, probability

    spans = _to_spans([
        Segment(0.0, 1.0, "안녕", -0.1, [Word(0.0, 0.5, "안", 0.9), Word(0.5, 1.0, "녕", 0.8)]),
        Segment(1.0, 2.0, " 세그먼트뿐", -0.2),  # 단어 시각 없음 → 통째로 한 조각
    ])

    assert len(spans) == 3
    assert spans[0] == (0.0, 0.5, "안", 0.9)
    assert spans[2][2] == " 세그먼트뿐"
    assert 0.0 < spans[2][3] < 1.0  # avg_logprob을 확률로 정규화해서 넣는다


def test_confidence_normalizes_logprob():
    assert _confidence(0.0) == 1.0
    assert _confidence(None) is None
    assert 0.0 < _confidence(-1.0) < 1.0
