"""Whisper STT + pyannote 화자분리 → Transcript. ★ STT 교체 지점(이노하이로 통째 교체될 자리).

무거운 ML 의존성(faster-whisper·pyannote)은 함수 안에서 지연 임포트한다 — 기본 워커
설치(stt 그룹 미설치)에서도 이 모듈 import와 병합 로직 테스트가 돈다. 모델은 프로세스당
한 번만 로드한다(lru_cache).
"""

import math
from functools import lru_cache

from callwrap_api.settings import get_settings

from callwrap_ai.schemas import Speaker, Transcript, Utterance


@lru_cache(maxsize=1)
def _whisper():
    from faster_whisper import WhisperModel

    return WhisperModel(get_settings().whisper_model)


@lru_cache(maxsize=1)
def _diarizer():
    import os

    from pyannote.audio import Pipeline

    # 인자로 토큰을 넘기지 않는다 — pyannote/hf_hub 버전마다 인자명이 use_auth_token↔token으로
    # 달라 깨진다. HF_TOKEN을 env에 두면 huggingface_hub이 알아서 읽는다(버전 무관).
    token = get_settings().hf_token
    if token:
        os.environ.setdefault("HF_TOKEN", token)
    return Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")


def transcribe_whisper(audio_path: str) -> Transcript:
    """오디오를 전사(Whisper)하고 화자를 배정(pyannote)해 Transcript로 돌려준다."""
    segments, _info = _whisper().transcribe(audio_path)
    whisper_segments = [(s.start, s.end, s.text, s.avg_logprob) for s in segments]

    turns = _diarize(audio_path)
    return Transcript(utterances=_assign_speakers(whisper_segments, turns))


def _diarize(audio_path: str) -> list[tuple[float, float, str]]:
    """pyannote로 화자 구간 (start, end, label) 리스트를 뽑는다.

    파일 경로 대신 soundfile로 직접 읽어 waveform을 넘긴다 — torchaudio/torchcodec의
    ffmpeg 의존(libavutil 버전 지옥)을 우회. soundfile은 libsndfile로 wav/aiff/flac를 읽는다.
    """
    import soundfile as sf
    import torch

    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)  # (frames, channels)
    waveform = torch.from_numpy(data).T  # pyannote는 (channel, time) 기대
    diarization = _diarizer()({"waveform": waveform, "sample_rate": sr})
    return [(t.start, t.end, label) for t, _, label in diarization.itertracks(yield_label=True)]


# ── 순수 병합 로직 (모델 없이 테스트 가능) ─────────────────────────────


def _assign_speakers(whisper_segments, turns) -> list[Utterance]:
    """Whisper 세그먼트에 화자를 배정해 Utterance 리스트를 만든다.

    whisper_segments: (start, end, text, avg_logprob) 리스트
    turns:            (start, end, label) 화자 구간 리스트 (pyannote 출력)
    """
    roles = _role_map(turns)
    out = []
    for i, (start, end, text, avg_logprob) in enumerate(whisper_segments):
        label = _dominant_speaker(start, end, turns)
        out.append(
            Utterance(
                index=i,
                # 겹치는 화자구간이 없으면 상담사로 둔다(대개 시작/끝의 짧은 세그먼트).
                speaker=roles.get(label, Speaker.COUNSELOR),
                text=text.strip(),
                start=start,
                end=end,
                confidence=_confidence(avg_logprob),
            )
        )
    return out


def _role_map(turns) -> dict[str, Speaker]:
    """화자 라벨 → 역할. 먼저 발화한 라벨을 상담사로 본다.

    ponytail: 인바운드 콜 관례 기반 휴리스틱(먼저 말한 쪽=상담사). 틀리는 콜이 나오면
              화자별 총 발화시간/톤 기반으로 교체. 화자 2명 가정 — 셋째부터는 고객으로 뭉뚱그림.
    """
    order: list[str] = []
    for _start, _end, label in sorted(turns):
        if label not in order:
            order.append(label)
    return {
        label: (Speaker.COUNSELOR if i == 0 else Speaker.CUSTOMER)
        for i, label in enumerate(order)
    }


def _dominant_speaker(start, end, turns) -> str | None:
    """세그먼트와 시간상 가장 많이 겹치는 화자 라벨. 겹침 없으면 None."""
    best, best_overlap = None, 0.0
    for t_start, t_end, label in turns:
        overlap = min(end, t_end) - max(start, t_start)
        if overlap > best_overlap:
            best, best_overlap = label, overlap
    return best


def _confidence(avg_logprob) -> float | None:
    """faster-whisper avg_logprob(≈-1~0) → 0~1. 정규화 책임은 stt/에 있다(합의)."""
    if avg_logprob is None:
        return None
    return min(1.0, math.exp(avg_logprob))
