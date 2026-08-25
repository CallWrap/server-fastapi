# 오프라인(망분리) 실행 안내

이 번들만으로 실행한다. **밖에서 아무것도 받지 않는다** — PyPI·GitHub·HuggingFace·ollama.com 전부 불필요.

```
code/server-fastapi/   파이프라인 (이 서비스)
code/AI-model/         callwrap-ai (analyze + F2 중분류/소분류/SR유형 + F3 상담등급 모델 코드)
wheels/                파이썬 의존성 (server-fastapi + AI-model train extra, transitive 포함)
hf-cache/               whisper 가중치 (HuggingFace 캐시 — faster-whisper 전용)
pyannote-cache/         pyannote 전체(파이프라인 설정+segmentation+화자임베딩) — HF 캐시 아님, 별도 경로
models/checkpoints/     중분류·소분류·SR유형 체크포인트 3종 — 스크립트가 AI-model/data/models/에서 자동 복사
ollama/                 등급판정·요약·후속처리·FAQ필요 전부 담당하는 온디바이스 LLM(exaone3.5:7.8b) — 있으면 자동 포함
vc_redist.x64.exe       Windows용 Microsoft Visual C++ 재배포 패키지 — torch/ctranslate2/numpy 등
                        C-extension wheel이 DLL 로드에 필요. 사보원 PC에 없으면 먼저 설치한다.
```

## -1. (Windows) VC++ 런타임부터 설치

`torch`·`ctranslate2`·`numpy` 같은 C-extension wheel은 Visual C++ 2015-2022 x64 런타임
DLL(`vcruntime140.dll` 등)이 있어야 로드된다. 이미 깔려있으면 건너뛰어도 되지만,
확실치 않으면 먼저 실행해둔다 (관리자 권한 필요할 수 있음, 조용히 설치):
```bash
./vc_redist.x64.exe /install /quiet /norestart
```

## 0. 지금 뭐가 실제로 동작하는지 (analyze() 현황, 2026-08-22 기준)

| 항목 | 상태 | 필요한 것 |
|---|---|---|
| F1 요약·후속처리 필요·FAQ 필요 | 실제 모델 (Ollama EXAONE 1회 호출) | `ollama/`에 exaone3.5:7.8b |
| F2 중분류(6종)·소분류(29종) | 실제 모델 | `wheels`의 torch/transformers + `models/checkpoints/` |
| 상담유형/SR유형(8종) | 실제 모델 (화자임베딩 포함 커스텀 헤드) | `models/checkpoints/`의 `sr-type-klue-roberta-base-v2` + `hf-cache/`의 klue/roberta-base config(가중치는 불필요 — fine-tuned state_dict로 바로 덮어씀) |
| F3 상담등급 | 실제 모델 (Ollama 감정점수 + 2축 규칙) | `ollama/`에 exaone3.5:7.8b |
| STT(전사) | 실제 모델, 한국어 콜센터 음성으로 실측 확인함 | `hf-cache/`(large-v3) |
| 화자분리 | 실제 모델, **wav/flac 등만 지원 — m4a/AAC는 안 됨**(pyannote가 soundfile/libsndfile로 직접 읽어서) | `pyannote-cache/` + 오디오를 wav로 사전 변환 |

checkpoint나 ollama 모델이 없으면 해당 항목만 `None`으로 부분 실패 처리되고 나머지는 정상 동작한다(파이프라인 전체가 죽지 않음).

## 1. 설치

```bash
cd code/server-fastapi
python -m venv .venv && . .venv/bin/activate
pip install --no-index --find-links ../../wheels -r ../../wheels/requirements.pypi.txt
pip install --no-index --no-deps --find-links ../../wheels callwrap-ai callwrap-api   # 미리 빌드된 wheel 2개
```

> `pyproject.toml`의 `[tool.uv.sources]`는 개발용 git 소스다. 오프라인에선 위처럼
> 로컬 경로로 설치하므로 그 줄을 쓰지 않는다.

## 2. 모델 가중치 배치

```bash
mkdir -p ~/.cache/huggingface/hub ~/.cache/torch/pyannote
cp -R ../../hf-cache/* ~/.cache/huggingface/hub/          # whisper
cp -R ../../pyannote-cache/* ~/.cache/torch/pyannote/     # pyannote 전체 — HF 캐시가 아니라 이 경로다
cp -R ../../models/checkpoints/* code/AI-model/data/models/   # F2 checkpoint (있으면)
```

ollama가 없으면 설치 파일을 별도 반입해 설치 후:
```bash
ollama serve &
cp -R ../../ollama/models/* ~/.ollama/models/
```

## 3. 환경변수 (핵심 — 이게 없으면 다운로드를 시도하다 실패한다)

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export STT_BACKEND=whisper          # 실 전사. 파이프라인만 볼 땐 stub
export WHISPER_MODEL=large-v3        # hf-cache에 담아온 크기와 일치해야 함
export AUDIO_SOURCE=local
export RABBITMQ_URL=amqp://guest:guest@localhost:5672//
# F2/F3 — checkpoint·ollama를 기본 경로가 아닌 곳에 뒀다면만 필요
# export CALLWRAP_MODEL_DIR=/path/to/models/checkpoints
# export OLLAMA_URL=http://127.0.0.1:11434
```

## 4. 동작 확인 (실데이터 넣기 전에)

```bash
pytest -q                                   # 파이프라인 회귀 (stub, 모델 불필요)
python - <<'PY'
from callwrap_api.stt_whisper import transcribe_whisper
t = transcribe_whisper("샘플.wav")
print(len(t.utterances), "utterances"); print(t.utterances[0])
PY
python - <<'PY'
from callwrap_ai import classify
print(classify.predict_category("테스트 상담 대본입니다"))  # checkpoint 있으면 (라벨, 확률), 없으면 None
PY
```

전사 결과가 나오면 오프라인 STT 정상. 그다음 실데이터를 투입한다.

## 5. 파이프라인 실행

```bash
celery -A callwrap_api.tasks.app.celery_app worker --loglevel=info   # 워커
python -m callwrap_api.messaging.consumer                            # Spring Job 브리지
```

## 주의

- **whisper 모델 크기**를 바꾸려면 그 가중치도 미리 담아와야 한다(`WHISPER_MODEL`과 `hf-cache` 일치).
- **pyannote는 whisper와 캐시 경로가 다르다** — `Pipeline.from_pretrained()`의 cache_dir 기본값이
  `PYANNOTE_CACHE`(`~/.cache/torch/pyannote`)라, 파이프라인 설정·segmentation·화자 임베딩 셋 다
  `pyannote-cache/`로 온다. `~/.cache/huggingface/hub`에 pyannote 폴더가 있어도 pyannote는 그걸
  보지 않는다 — 2단계를 그대로 따라야 화자분리가 동작한다.
- **ollama 모델(exaone3.5:7.8b)은 수 GB다.** 이 스크립트를 ollama가 설치된 머신에서 돌려야
  자동으로 담긴다. 안 그러면 `ollama/README.txt`만 생기니, 그 머신에서 따로 반입해야 한다.
- **실데이터·전사 결과는 반출 금지.** 반출은 지표(정확도 등)만.
