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

# venv 레이아웃이 OS마다 다르다 (Linux/macOS: bin/, Windows: Scripts/).
VENV_PY="$ROOT/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$ROOT/.venv/Scripts/python.exe"
rm -rf "$OUT"
mkdir -p "$OUT"/{code,wheels,models/checkpoints,hf-cache,pyannote-cache,ollama}

echo "[1/7] 코드 아카이브"
git -C "$ROOT" archive --format=tar HEAD | (mkdir -p "$OUT/code/server-fastapi" && tar -x -C "$OUT/code/server-fastapi")

echo "[2/7] AI-model 코드 (callwrap-ai) — 오프라인에선 git이 아니라 로컬 경로로 물린다"
if [ -d "$ROOT/../AI-model" ]; then
  git -C "$ROOT/../AI-model" archive --format=tar HEAD | (mkdir -p "$OUT/code/AI-model" && tar -x -C "$OUT/code/AI-model")
else
  git clone --depth 1 https://github.com/CallWrap/AI-model.git "$OUT/code/AI-model" >/dev/null 2>&1
  rm -rf "$OUT/code/AI-model/.git"
fi

echo "[3/7] 의존성 wheel (server-fastapi 기본+stt그룹 + AI-model train extra, transitive 포함)"
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
  | grep -vE "^-e |^callwrap-ai" > "$OUT/wheels/requirements.aimodel.txt" || true
# 두 레포가 독립적으로 잠근 버전이라 같은 패키지가 다른 버전으로 중복/충돌할 수 있다
# (예: numpy — server-fastapi는 torch 2.2 호환 위해 <2로 고정했는데 AI-model 쪽은 2.x를
#  요구, 또는 huggingface_hub 상한 충돌). server-fastapi(stt그룹) 쪽을 항상 우선한다:
# AI-model 줄 중 이름이 server-fastapi 쪽에 이미 있는 건 통째로 버리고, 없는 이름만 얹는다.
# 마커 유무로 판단하면 안 되는 이유 — torch/torchaudio는 server-fastapi 쪽 "같은 소스" 안에서
# `sys_platform == 'win32'`/`!= 'win32'` 두 줄로 정상적으로 갈라져 있다(pyproject.toml의
# [tool.uv.sources] 인덱스 오버라이드로 win32는 cu121 wheel을 쓴다). 이걸 서로 충돌하는
# 중복으로 오인해 지우면 cu121 줄이 사라지고 사보원 PC에서 CPU wheel이 잡힌다(GPU가 논다).
# 그래서 "같은 소스 내부의 마커 분기"는 그대로 두고, "다른 소스가 같은 이름을 다시 정의"한
# 경우만 이름 기준으로 걸러낸다 — 소스(파일) 단위로 먼저 나누면 이 둘이 자연히 구분된다.
python3 - "$OUT/wheels/requirements.pypi.txt" "$OUT/wheels/requirements.aimodel.txt" <<'PY'
import re, sys
primary_path, secondary_path = sys.argv[1], sys.argv[2]
FORCE_RANGE = {
    "transformers": "transformers>=4.40,<4.47",
    "tokenizers": "tokenizers>=0.20,<0.21",
    "huggingface-hub": "huggingface-hub<0.28",
}


def pkg_name(line: str) -> str:
    head = line.split(";", 1)[0]
    return re.split(r"[=<>\[\s]", head, maxsplit=1)[0].strip().lower()


def load(path):
    try:
        return [l.strip() for l in open(path) if l.strip() and not l.strip().startswith("#")]
    except FileNotFoundError:
        return []


primary = load(primary_path)
secondary = load(secondary_path)

primary_names = {pkg_name(l) for l in primary}
# 부차 소스(AI-model)는 주 소스(server-fastapi)가 이미 정한 패키지를 절대 재정의하지 않는다.
secondary = [l for l in secondary if pkg_name(l) not in primary_names]

seen_force, seen_key, out = set(), set(), []
for line in primary + secondary:
    name = pkg_name(line)
    if name in FORCE_RANGE:
        if name in seen_force:
            continue
        seen_force.add(name)
        out.append(FORCE_RANGE[name])
        continue
    # (이름, 마커)로 dedup — 같은 소스 내부에서 sys_platform 등으로 갈린 줄은 서로 다르게 남는다.
    key = (name, line.split(";", 1)[1].strip() if ";" in line else "")
    if key in seen_key:
        continue
    seen_key.add(key)
    out.append(line)
open(primary_path, "w").write("\n".join(out) + "\n")
PY
rm -f "$OUT/wheels/requirements.aimodel.txt"

# uv엔 download가 없어 venv의 pip을 쓴다. 사보원 머신과 OS/파이썬이 다르면
# 그 환경에서 다시 받아야 하므로, 플랫폼이 다르면 --platform/--python-version을 추가한다.
# torch/torchaudio의 +cu121 로컬 버전은 PyPI엔 없고 파이토치 전용 인덱스(pyproject.toml의
# [[tool.uv.index]] pytorch-cu121)에만 있다 — --extra-index-url 없이는 "No matching
# distribution" 에러로 그냥 실패한다.
"$VENV_PY" -m pip download -q \
  --extra-index-url https://download.pytorch.org/whl/cu121 \
  -r "$OUT/wheels/requirements.pypi.txt" -d "$OUT/wheels"
# callwrap-ai(AI-model)·callwrap-api(이 서비스) 둘 다 여기 온라인 머신에서 wheel로 미리 빌드해
# 담는다 — editable(-e) 설치는 hatchling의 editable 백엔드가 추가로 'editables' 패키지 등을
# 요구해 오프라인에서 계속 깨진다. 빌드된 wheel을 그냥 pip install하면 그 체인이 필요 없어진다.
"$VENV_PY" -m pip wheel -q --no-deps -w "$OUT/wheels" "$AI_DIR"
"$VENV_PY" -m pip wheel -q --no-deps -w "$OUT/wheels" "$ROOT"

# PyPI에 wheel이 아예 없는 패키지(예: antlr4-python3-runtime, docopt)는 pip download가
# sdist(.tar.gz/.zip)를 그대로 받아온다. 오프라인에서 --no-index로 이걸 설치하면 pip가
# PEP517 build isolation을 하려고 setuptools/wheel을 다시 받으러 가는데, 이건 바깥의
# --no-index가 안 먹는 pip의 잘 알려진 함정이라 네트워크 없는 사보원에서 그냥 멈춘다.
# 그래서 인터넷 있는 지금 미리 wheel로 빌드해 sdist를 대체한다.
shopt -s nullglob
sdists=("$OUT"/wheels/*.tar.gz "$OUT"/wheels/*.zip)
shopt -u nullglob
if [ "${#sdists[@]}" -gt 0 ]; then
  echo "     sdist ${#sdists[@]}개를 wheel로 재빌드 (오프라인 install의 build isolation 회피)"
  for sdist in "${sdists[@]}"; do
    echo "     - $(basename "$sdist")"
    "$VENV_PY" -m pip wheel -q --no-deps -w "$OUT/wheels" "$sdist" && rm -f "$sdist"
  done
fi

echo "[4/7] STT 모델 가중치 (whisper·pyannote)"
# HuggingFace 허브 캐시 — faster-whisper만 여기를 쓴다. .env의 WHISPER_MODEL과 일치해야 한다.
WHISPER_SIZE="$(grep -oE '^WHISPER_MODEL=.*' "$ROOT/.env" 2>/dev/null | cut -d= -f2)"
WHISPER_SIZE="${WHISPER_SIZE:-large-v3}"
HF="${HF_HOME:-$HOME/.cache/huggingface}/hub"
for m in "models--Systran--faster-whisper-$WHISPER_SIZE"; do
  [ -d "$HF/$m" ] && cp -R "$HF/$m" "$OUT/hf-cache/" && echo "     + (hf-cache) $m"
  [ -d "$HF/$m" ] || echo "     ! 경고: $m 이(가) 캐시에 없다. WHISPER_MODEL=$WHISPER_SIZE 로 한 번 전사를 돌려 캐시를 채운 뒤 재실행하라."
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
# SR유형(sr_type.py)의 백본(klue/roberta-base)은 AutoConfig.from_pretrained()로 config만
# 읽는다 — 사전학습 가중치는 fine-tuned state_dict로 바로 덮어써서 안 쓰이므로(model.py의
# pretrained=False 경로) config.json만 있으면 오프라인에서도 안 터진다. 442MB짜리
# model.safetensors는 필요 없어 안 담는다(dereference해서 config만 복사).
KLUE_BACKBONE="models--klue--roberta-base"
if [ -d "$HF/$KLUE_BACKBONE" ]; then
  mkdir -p "$OUT/hf-cache/$KLUE_BACKBONE/refs"
  cp -L "$HF/$KLUE_BACKBONE/refs/main" "$OUT/hf-cache/$KLUE_BACKBONE/refs/main" 2>/dev/null || true
  for snap in "$HF/$KLUE_BACKBONE"/snapshots/*/; do
    [ -e "$snap/config.json" ] || continue
    hash="$(basename "$snap")"
    mkdir -p "$OUT/hf-cache/$KLUE_BACKBONE/snapshots/$hash"
    cp -L "$snap/config.json" "$OUT/hf-cache/$KLUE_BACKBONE/snapshots/$hash/config.json"
  done
  echo "     + (hf-cache, config만) $KLUE_BACKBONE"
else
  echo "     ! 경고: $KLUE_BACKBONE 이(가) 캐시에 없다. SR유형 모델을 한 번 로드해 캐시를 채운 뒤 재실행하라(안 채우면 SR유형이 오프라인에서 빠짐 — failures에 기록되고 나머지는 정상 진행)."
fi

echo "[5/7] F2/F3 체크포인트(SR·중분류·소분류)·ollama"
CKPT_SRC="$AI_DIR/data/models"
CKPTS_FOUND=0
for m in category-klue-roberta-base-seed42 subcategory-klue-roberta-base-seed42 sr-type-klue-roberta-base-v2; do
  if [ -d "$CKPT_SRC/$m" ]; then
    cp -R "$CKPT_SRC/$m" "$OUT/models/checkpoints/" && echo "     + (checkpoint) $m"
    CKPTS_FOUND=$((CKPTS_FOUND + 1))
  else
    echo "     ! 경고: $m 이(가) $CKPT_SRC 에 없다. 담당자에게 받아 배치한 뒤 재실행하라."
  fi
done
[ "$CKPTS_FOUND" -eq 0 ] && echo "AI 모델 checkpoint(SR·중분류·소분류)를 여기 넣으세요 — 담당자에게 수령" > "$OUT/models/checkpoints/README.txt"
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

echo "[6/7] Windows 런타임 (VC++ Redistributable)"
# torch(cu121)·ctranslate2·numpy 같은 C-extension wheel은 VC++ 2015-2022 x64 런타임
# DLL(vcruntime140.dll 등)이 없으면 로드가 실패한다("DLL load failed while importing ...").
# 사보원 PC에 이미 있을 수도 있지만 보장이 없어 마이크로소프트 공식 재배포 설치파일을
# 온라인에서 미리 받아 같이 담는다.
if [ ! -f "$OUT/vc_redist.x64.exe" ]; then
  if curl -fsSL --max-time 60 -o "$OUT/vc_redist.x64.exe" "https://aka.ms/vs/17/release/vc_redist.x64.exe"; then
    echo "     + vc_redist.x64.exe ($(du -h "$OUT/vc_redist.x64.exe" 2>/dev/null | cut -f1))"
  else
    rm -f "$OUT/vc_redist.x64.exe"
    echo "     ! 다운로드 실패 — https://aka.ms/vs/17/release/vc_redist.x64.exe 를 수동으로 받아 bundle/에 넣어라."
  fi
fi

echo "[7/7] 실행 안내"
cp "$ROOT/scripts/OFFLINE_README.md" "$OUT/README.md"

du -sh "$OUT" 2>/dev/null || true
echo "완료: $OUT"
