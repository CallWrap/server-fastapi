# server-fastapi — 사보원 오프라인 셋업 가이드

## ★ 먼저 할 것: venv를 현지에서 새로 만든다 (필수)

`.venv/`에 whisper·pyannote·torch·callwrap-ai·callwrap-api가 실제 파일로 이미 설치되어
있긴 하지만, **이 `.venv`를 사보원에서 그대로 쓸 수 있다고 가정하면 안 된다.**
`.venv/pyvenv.cfg`에 이 venv를 만든 개발 머신의 절대경로(`home = C:\Users\...\Python311`)가
박혀 있고, 파이썬 표준 라이브러리 자체는 `.venv` 안에 없어서 그 경로의 베이스 파이썬을
계속 참조하는 구조다 — 사보원 PC의 사용자 계정명·설치 경로가 다르면(거의 항상 다르다)
깨진다. 개발 환경과 사보원 PC가 다른 이상, **`.venv/`를 직접 쓰지 말고 아래처럼 항상
새로 만든다:**

```bash
python -m venv .venv-onsite
.venv-onsite/Scripts/python.exe -m pip install --no-index --find-links bundle/wheels -r bundle/wheels/requirements.pypi.txt
.venv-onsite/Scripts/python.exe -m pip install --no-index --no-deps --find-links bundle/wheels callwrap-ai callwrap-api
```

- `bundle/wheels`에 필요한 패키지가 전부 `.whl`로 들어있어서 **인터넷 연결 없이** 설치된다.
- 사보원 PC에 **Python 3.11**만 설치되어 있으면 되고, 설치 경로는 어디든 상관없다.
- 아래의 모든 실행 명령에서 `.venv/Scripts/python.exe`는 전부 **`.venv-onsite/Scripts/python.exe`로 바꿔서** 쓴다.
- (기존 `.venv/`는 이 zip을 만든 개발 머신 전용이다 — 참고용으로만 남겨둔 것, 사보원에서는 무시한다.)

## ★ 반드시 해야 하는 것: 모델 가중치를 사용자 캐시로 복사

venv와 별개로, Whisper·pyannote·Ollama의 **실제 가중치 파일**은 faster-whisper/pyannote/ollama
라이브러리가 정해둔 대로 `C:\CallWrap` 바깥, **Windows 사용자 프로필 캐시**에 저장되도록
되어 있다. 이 zip에는 그 가중치를 `bundle/` 폴더에 미리 담아뒀으니, 최초 1회 아래처럼
복사해야 한다:

```bash
mkdir -p ~/.cache/huggingface/hub ~/.cache/torch/pyannote ~/.ollama/models
cp -R bundle/hf-cache/* ~/.cache/huggingface/hub/          # Whisper(large-v3)
cp -R bundle/pyannote-cache/* ~/.cache/torch/pyannote/     # 화자분리
cp -R bundle/ollama/models/* ~/.ollama/models/              # EXAONE(등급판정·요약·후속처리·FAQ)
```

이 복사를 빠뜨리면, 오프라인 환경에서 STT/화자분리/EXAONE 호출 시점에 인터넷으로
가중치를 받으려다 실패한다. **`AI-model/data/models/`(중분류·소분류·SR유형 체크포인트)는
이 복사가 필요 없다** — 그건 프로젝트 폴더 안 경로를 코드가 직접 읽는 구조라 이미 준비되어 있다.

## 실행

인프라(RabbitMQ)는 `server-spring/`에서 먼저 띄워야 한다 — [server-spring/guide.md](../server-spring/guide.md) 참고.

```bash
export RABBITMQ_URL="amqp://guest:guest@localhost:5672//"
export AUDIO_SOURCE=local
export STT_BACKEND=whisper
export WHISPER_MODEL=large-v3
export CALLWRAP_MODEL_DIR="$(pwd)/../AI-model/data/models"
export CALLWRAP_DEVICE=cpu
export OLLAMA_URL="http://127.0.0.1:11434"

# 터미널 1 — 실제 STT·품질게이트·AI분석을 수행하는 워커
.venv-onsite/Scripts/python.exe -m celery -A callwrap_api.tasks.app.celery_app worker --loglevel=info --pool=solo

# 터미널 2 — Spring이 발행한 job을 받아 celery로 넘기는 브리지
.venv-onsite/Scripts/python.exe -m callwrap_api.messaging.consumer
```

Windows에서는 Celery 기본 prefork가 안 되어 `--pool=solo`가 필수다(Linux/Mac은 빼도 됨).

## 이 컴포넌트만 빠르게 검증 (Spring·RabbitMQ 없이)

STT·분류 모델 자체가 되는지만 확인하고 싶으면:
```bash
export CALLWRAP_MODEL_DIR="$(pwd)/../AI-model/data/models"
export CALLWRAP_DEVICE=cpu

.venv-onsite/Scripts/python.exe -c "
from callwrap_api.stt_whisper import _whisper
segments, info = _whisper().transcribe('../99_archive/test_data/쇼핑_5548.wav', word_timestamps=True)
print(info.language, info.language_probability)
for seg in segments: print(seg.start, seg.end, seg.text)
"

.venv-onsite/Scripts/python.exe -c "
from callwrap_ai import classify, sr_type
print(classify.is_ready(), sr_type.is_ready())
"
```
자세한 내용은 [scripts/OFFLINE_README.md](scripts/OFFLINE_README.md) 참고 (거기 나오는 `.venv/bin/python` 표기도
같은 이유로 사보원에선 `.venv-onsite/Scripts/python.exe`로 바꿔 읽는다).

## 알려진 제한사항

- **m4a/AAC 오디오는 화자분리가 안 된다** — pyannote가 쓰는 `soundfile`이 m4a를 못 읽는다.
  `ffmpeg -i in.m4a -ar 16000 -ac 1 out.wav`로 미리 변환해서 넣는다.
- `bundle/code`는 코드 스냅샷 백업이다 — 정상 상황에서는 실제 `src/`를 쓰면 되고 안 건드려도 된다.
