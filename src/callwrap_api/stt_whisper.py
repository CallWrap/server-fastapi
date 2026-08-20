"""Whisper STT + pyannote 화자분리 → Transcript. ★ STT 교체 지점(이노하이로 통째 교체될 자리).

**발화는 단어 단위로 만든다.** Whisper 세그먼트를 그대로 발화로 쓰면 안 된다 — 세그먼트는
Whisper가 자기 편의대로 자른 덩어리라 화자가 바뀌는 지점을 모른다. 실제 통화에서 이렇게 나왔다:

    [1] 고객   "…아직 처리가 안 됐다고"      ← 문장이 중간에 잘리고
    [2] 상담사 "나와서요. 네, 확인해드리겠습니다"  ← 고객 말꼬리가 상담사 발화에 붙었다

`evidence_indices`가 가리키는 근거 발화가 엉뚱해지고, 요약도 화자를 헷갈릴 수 있다.
그래서 `word_timestamps=True`로 단어별 시각을 받아, **화자가 바뀌는 단어에서 발화를 끊는다.**

같은 이유로 confidence도 단어 확률의 평균을 쓴다. 세그먼트의 `avg_logprob`은 실은 30초
디코딩 창 단위라(같은 창의 세그먼트가 전부 같은 값을 갖는다) 특정 발화 하나가 뭉개진 것을
품질 게이트가 잡아낼 수 없었다.

무거운 ML 의존성(faster-whisper·pyannote)은 함수 안에서 지연 임포트한다 — 기본 워커
설치(stt 그룹 미설치)에서도 이 모듈 import와 병합 로직 테스트가 돈다. 모델은 프로세스당
한 번만 로드한다(lru_cache).
"""

import importlib.util
import math
import os
from functools import lru_cache
from pathlib import Path

from callwrap_api.settings import get_settings

from callwrap_ai.schemas import Speaker, Transcript, Utterance


# os.add_dll_directory 핸들이 GC되면 검색 경로가 다시 제거되므로 프로세스 수명 동안 보관한다.
_WINDOWS_DLL_HANDLES: list[object] = []


def _compute_type(device: str) -> str:
    """CTranslate2 장치별 안정적인 연산 형식."""
    return "float16" if device == "cuda" else "int8"


@lru_cache(maxsize=1)
def _configure_windows_cuda_dlls() -> None:
    """NVIDIA Windows wheels의 DLL 디렉터리를 현재 프로세스 검색 경로에 등록한다."""
    if os.name != "nt" or get_settings().callwrap_device != "cuda":
        return

    missing: list[str] = []
    for package in ("nvidia.cublas", "nvidia.cudnn"):
        spec = importlib.util.find_spec(package)
        locations = list(spec.submodule_search_locations or ()) if spec else []
        dll_dir = Path(locations[0]) / "bin" if locations else None
        if dll_dir is None or not dll_dir.is_dir():
            missing.append(package)
            continue

        # PATH는 CTranslate2의 동적 LoadLibrary 검색에, add_dll_directory는 Python 확장 DLL 검색에 쓴다.
        os.environ["PATH"] = f"{dll_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        _WINDOWS_DLL_HANDLES.append(os.add_dll_directory(str(dll_dir)))

    if missing:
        raise RuntimeError(
            "CALLWRAP_DEVICE=cuda requires Windows CUDA runtime wheels: " + ", ".join(missing)
        )


@lru_cache(maxsize=1)
def _whisper():
    from faster_whisper import WhisperModel

    settings = get_settings()
    _configure_windows_cuda_dlls()
    return WhisperModel(
        settings.whisper_model,
        device=settings.callwrap_device,
        compute_type=_compute_type(settings.callwrap_device),
    )


@lru_cache(maxsize=1)
def _diarizer():
    from pyannote.audio import Pipeline
    import torch

    # 인자로 토큰을 넘기지 않는다 — pyannote/hf_hub 버전마다 인자명이 use_auth_token↔token으로
    # 달라 깨진다. HF_TOKEN을 env에 두면 huggingface_hub이 알아서 읽는다(버전 무관).
    token = get_settings().hf_token
    if token:
        os.environ.setdefault("HF_TOKEN", token)
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
    if get_settings().callwrap_device == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CALLWRAP_DEVICE=cuda but CUDA-enabled PyTorch is not available for pyannote"
            )
        pipeline.to(torch.device("cuda"))
    return pipeline


def transcribe_whisper(audio_path: str) -> Transcript:
    """오디오를 전사(Whisper)하고 화자를 배정(pyannote)해 Transcript로 돌려준다."""
    segments, _info = _whisper().transcribe(audio_path, word_timestamps=True)
    spans = _to_spans(segments)

    turns = _diarize(audio_path)
    return Transcript(utterances=_assign_speakers(spans, turns))


def _to_spans(segments) -> list[tuple[float, float, str, float | None]]:
    """세그먼트 목록 -> 단어 단위 (start, end, text, probability) 목록.

    단어 시각이 없는 세그먼트(모델이 못 내주는 경우)는 세그먼트 하나를 통째로 한 조각으로 둔다 —
    그 조각만 예전처럼 화자 경계가 뭉툭해질 뿐, 나머지는 단어 단위로 정확히 갈린다.
    """
    spans: list[tuple[float, float, str, float | None]] = []
    for segment in segments:
        words = getattr(segment, "words", None)
        if words:
            spans += [(w.start, w.end, w.word, w.probability) for w in words]
        else:
            spans.append((segment.start, segment.end, segment.text, _confidence(segment.avg_logprob)))
    return spans


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


def _assign_speakers(spans, turns) -> list[Utterance]:
    """단어 조각들을 화자별로 묶어 발화 목록을 만든다.

    spans: (start, end, text, probability) 목록 — 단어 단위가 기본이다.
    turns: (start, end, label) 화자 구간 목록 (pyannote 출력)

    화자가 바뀌는 조각에서 발화를 끊는다. 화자 구간이 안 잡히는 조각(구간 사이 빈틈, 숨소리
    구간 등)은 **직전 화자를 이어간다** — 거기서 끊으면 한 문장이 쓸데없이 조각난다.
    """
    roles = _role_map(turns)
    utterances: list[Utterance] = []
    texts: list[str] = []
    probabilities: list[float] = []
    speaker: Speaker | None = None
    start = end = 0.0

    def flush() -> None:
        text = "".join(texts).strip()
        if not text or speaker is None:
            return
        scored = [p for p in probabilities if p is not None]
        utterances.append(
            Utterance(
                index=len(utterances),
                speaker=speaker,
                text=text,
                start=start,
                end=end,
                confidence=round(sum(scored) / len(scored), 4) if scored else None,
            )
        )

    for span_start, span_end, text, probability in spans:
        label = _speaker_at((span_start + span_end) / 2, turns)
        # 화자를 못 찾으면 직전 화자를 잇는다. 통화 맨 앞이라 직전도 없으면 상담사로 둔다
        # (인바운드 콜은 상담사가 먼저 받는다 — _role_map과 같은 전제).
        current = roles.get(label) or speaker or Speaker.COUNSELOR
        if current is not speaker:
            flush()
            texts, probabilities = [], []
            speaker, start = current, span_start
        texts.append(text)
        probabilities.append(probability)
        end = span_end

    flush()
    return utterances


def _speaker_at(when: float, turns) -> str | None:
    """그 시각을 품는 화자 구간의 라벨. 겹치는 구간이 여럿이면 더 늦게 시작한 쪽(교대 직후)을 쓴다."""
    best, best_start = None, float("-inf")
    for t_start, t_end, label in turns:
        if t_start <= when < t_end and t_start > best_start:
            best, best_start = label, t_start
    return best


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


def _confidence(avg_logprob) -> float | None:
    """faster-whisper avg_logprob(≈-1~0) → 0~1. 정규화 책임은 stt/에 있다(합의)."""
    if avg_logprob is None:
        return None
    return min(1.0, math.exp(avg_logprob))
