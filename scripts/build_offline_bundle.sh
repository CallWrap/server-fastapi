#!/usr/bin/env bash
# 망분리(사보원) 반입용 오프라인 번들을 만든다. 온라인 환경에서 1회 실행.
#
#   ./scripts/build_offline_bundle.sh
#
# 산출물: bundle/ 한 폴더 — 코드·의존성 wheel·모델 가중치·실행 안내.
# 반입 후 밖에서 아무것도 받지 않는다(PyPI·GitHub·HuggingFace·ollama.com 전부 불필요).
# ※ ollama(F3 감정판정용 온디바이스 LLM)는 이 스크립트를 "ollama가 설치되고
#   exaone3.5:7.8b를 pull해둔 머신"에서 돌려야 같이 담긴다. 없으면 5단계가 안내만 하고 넘어간다.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/bundle"
rm -rf "$OUT"
mkdir -p "$OUT"/{code,wheels,models/checkpoints,hf-cache,pyannote-cache,ollama}

echo "[1/6] 코드 아카이브"
git -C "$ROOT" archive --format=tar HEAD | (mkdir -p "$OUT/code/server-fastapi" && tar -x -C "$OUT/code/server-fastapi")

echo "[2/6] AI-model 코드 (callwrap-ai) — 오프라인에선 git이 아니라 로컬 경로로 물린다"
if [ -d "$ROOT/../AI-model" ]; then
  git -C "$ROOT/../AI-model" archive --format=tar HEAD | (mkdir -p "$OUT/code/AI-model" && tar -x -C "$OUT/code/AI-model")
else
  git clone --depth 1 https://github.com/CallWrap/AI-model.git "$OUT/code/AI-model" >/dev/null 2>&1
  rm -rf "$OUT/code/AI-model/.git"
fi

echo "[3/6] 의존성 wheel (server-fastapi 기본+stt그룹 + AI-model train extra, transitive 포함)"
# uv export로 잠긴 버전을 뽑아 wheel만 내려받는다. 사보원에선 --no-index로 설치.
uv export --no-hashes --group stt --format requirements-txt > "$OUT/wheels/requirements.txt" 2>/dev/null
# PyPI에 없는 것 두 줄을 뺀다 — 둘 다 코드로 반입해 로컬 설치한다.
#   "-e ."                : 이 서비스 자신
#   "callwrap-ai @ git+..": AI-model 레포
grep -vE "^-e |^callwrap-ai @|^callwrap-api" "$OUT/wheels/requirements.txt" > "$OUT/wheels/requirements.pypi.txt"

# AI-model의 train extra(torch/transformers/scikit-learn) — F2·F3 실제 추론에 필요하다.
# "train"이라는 이름과 달리 classify.py의 추론 경로도 이 extra에 의존한다(팀에 공유 필요).
if [ -d "$ROOT/../AI-model" ]; then
  AI_DIR="$ROOT/../AI-model"
else
  AI_DIR="$OUT/code/AI-model"
fi
( cd "$AI_DIR" && uv export --no-hashes --extra train --format requirements-txt 2>/dev/null || true ) \
  | grep -vE "^-e |^callwrap-ai" >> "$OUT/wheels/requirements.pypi.txt" || true
# 두 레포가 독립적으로 잠근 버전이라 같은 패키지가 다른 버전으로 중복/충돌할 수 있다
# (예: certifi 중복, transformers 최신판이 huggingface_hub>=0.28을 요구해 pyannote의
#  huggingface_hub<0.28 핀과 충돌). server-fastapi(stt그룹) 쪽 버전을 우선해 중복을 지우고,
# transformers 생태계 3종은 hub<0.28과 맞는 범위로 강제해 pip가 서로 맞는 버전을 고르게 한다.
python3 - "$OUT/wheels/requirements.pypi.txt" <<'PY'
import re, sys
path = sys.argv[1]
FORCE_RANGE = {
    "transformers": "transformers>=4.40,<4.47",
    "tokenizers": "tokenizers>=0.20,<0.21",
    "huggingface-hub": "huggingface-hub<0.28",
}
seen, out = set(), []
for line in open(path):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    name = re.split(r"[=<>; ]", line, 1)[0].lower()
    if name in FORCE_RANGE:
        if name in seen:
            continue
        seen.add(name)
        out.append(FORCE_RANGE[name])
        continue
    if name in seen:
        continue
    seen.add(name)
    out.append(line)
open(path, "w").write("\n".join(out) + "\n")
PY

# uv엔 download가 없어 venv의 pip을 쓴다. 사보원 머신과 OS/파이썬이 다르면
# 그 환경에서 다시 받아야 하므로, 플랫폼이 다르면 --platform/--python-version을 추가한다.
"$ROOT/.venv/bin/python" -m pip download -q -r "$OUT/wheels/requirements.pypi.txt" -d "$OUT/wheels"
# callwrap-ai(AI-model)·callwrap-api(이 서비스) 둘 다 여기 온라인 머신에서 wheel로 미리 빌드해
# 담는다 — editable(-e) 설치는 hatchling의 editable 백엔드가 추가로 'editables' 패키지 등을
# 요구해 오프라인에서 계속 깨진다. 빌드된 wheel을 그냥 pip install하면 그 체인이 필요 없어진다.
"$ROOT/.venv/bin/python" -m pip wheel -q --no-deps -w "$OUT/wheels" "$AI_DIR"
"$ROOT/.venv/bin/python" -m pip wheel -q --no-deps -w "$OUT/wheels" "$ROOT"

echo "[4/6] STT 모델 가중치 (whisper·pyannote)"
# HuggingFace 허브 캐시 — faster-whisper만 여기를 쓴다.
HF="${HF_HOME:-$HOME/.cache/huggingface}/hub"
for m in models--Systran--faster-whisper-base; do
  [ -d "$HF/$m" ] && cp -R "$HF/$m" "$OUT/hf-cache/" && echo "     + (hf-cache) $m"
done
# pyannote는 Pipeline.from_pretrained()의 cache_dir 기본값이 PYANNOTE_CACHE(기본
# ~/.cache/torch/pyannote)라 파이프라인 설정(config.yaml)·segmentation·화자임베딩 전부
# 이 경로만 본다. HuggingFace 허브 캐시(~/.cache/huggingface/hub)에 같은 폴더가 있어도
# pyannote는 절대 거기를 안 본다 — 셋 다 빠짐없이 여기서 담아야 오프라인에서 실제로 동작한다.
PYCACHE="${PYANNOTE_CACHE:-$HOME/.cache/torch/pyannote}"
for m in models--pyannote--segmentation-3.0 models--pyannote--speaker-diarization-3.1 models--pyannote--wespeaker-voxceleb-resnet34-LM; do
  [ -d "$PYCACHE/$m" ] && cp -R "$PYCACHE/$m" "$OUT/pyannote-cache/" && echo "     + (pyannote-cache) $m"
done
for m in models--pyannote--segmentation-3.0 models--pyannote--speaker-diarization-3.1 models--pyannote--wespeaker-voxceleb-resnet34-LM; do
  [ -d "$OUT/pyannote-cache/$m" ] || echo "     ! 경고: $m 이(가) PYANNOTE_CACHE에 없다. 실제 오디오로 transcribe_whisper()를 한 번 돌려 캐시를 채운 뒤 재실행하라."
done

echo "[5/6] F2/F3 자리 표시 (checkpoint·ollama)"
echo "AI 모델 checkpoint(SR·중분류)를 여기 넣으세요 — 성진에게 수령" > "$OUT/models/checkpoints/README.txt"
if command -v ollama >/dev/null 2>&1 && ollama list 2>/dev/null | grep -q "exaone3.5:7.8b"; then
  echo "     ollama 모델 발견 — 파일 복사(용량 큼, 수 GB)"
  cp -R "$HOME/.ollama/models" "$OUT/ollama/" 2>/dev/null && echo "     + ~/.ollama/models"
else
  cat > "$OUT/ollama/README.txt" <<'EOF'
ollama(F3 감정판정용, exaone3.5:7.8b)가 이 머신엔 없어 자동으로 못 담았다.
ollama가 설치되고 `ollama pull exaone3.5:7.8b`를 실행해둔 머신에서
이 스크립트를 다시 돌리거나, 그 머신의 ~/.ollama/models 를 통째로 이 폴더에 복사해서 가져가라.
EOF
  echo "     ! ollama 없음 — README만 남김 (수동 반입 필요)"
fi

echo "[6/6] 실행 안내"
cp "$ROOT/scripts/OFFLINE_README.md" "$OUT/README.md"

du -sh "$OUT" 2>/dev/null || true
echo "완료: $OUT"
