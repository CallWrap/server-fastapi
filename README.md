# CallWrap — server-fastapi

상담 후처리 파이프라인의 **무상태 워커**. Spring이 RabbitMQ로 보낸 요청을 받아
**STT → 품질 게이트 → AI 분석**을 수행하고 결과를 RabbitMQ로 회신한다.
DB는 건드리지 않는다(저장·조회는 Spring 소유).

```
Spring ─Job─▶ RabbitMQ ─▶ consumer ─▶ transcribe ─▶ quality_gate ─▶ analyze ─▶ 결과 발행 ─▶ Spring
```

결과는 셋 중 하나로 발행된다: `DONE`(분석 완료) · `NEEDS_HUMAN_REVIEW`(품질 미달) · `FAILED`(처리 실패).
Spring과의 메시지 계약은 **[docs/message_contract.md](docs/message_contract.md)** 참고.

## 실행

> RabbitMQ는 이 레포에서 안 띄웁니다. `server-spring`의 docker-compose가 먼저 떠 있어야 함.
> 추가 사항 : RABBITMQ_URL은 host.docker.internal:5672로 바꿔뒀습니다.

```bash
# 1. server-spring 레포에서 먼저
docker compose up -d

# 2. 그 다음 이 레포에서
docker compose up -d
```

```bash
uv sync
docker run -d --name callwrap-rabbit --user root -p 5672:5672 -p 15672:15672 rabbitmq:3-management

uv run celery -A callwrap_api.tasks.app.celery_app worker --loglevel=info   # 워커
uv run python -m callwrap_api.messaging.consumer                            # 컨슈머(브리지)
```

전체 컨테이너로: `docker compose up -d`. 테스트: `uv run pytest` (DB·브로커 불필요, 상시 실행).

> `callwrap-ai`는 실제 모델 라이브러리(`CallWrap/AI-model` 레포)를 git 소스로 물고 있다.
> AI-model에 변경이 머지되면 `uv lock --upgrade-package callwrap-ai`로 다시 잠가야 반영된다.
> (`stubs/callwrap-ai`는 전환 이전에 쓰던 예시 패키지로, 지금은 아무도 참조하지 않는다.)

### Docker 없이 네이티브로 실행 (오프라인/사보원 환경)

`docker compose build`는 `callwrap-ai`(비공개 `AI-model` 레포)를 git으로 클론하기 때문에
GitHub PAT(`.github_token`)이 필요하다. `AI-model`을 이미 형제 디렉토리로 갖고 있다면,
`pyproject.toml`의 `[tool.uv.sources]`를 `{ path = "../AI-model", editable = true }`로
바꿔서 로컬 경로로 물리면 PAT 없이도 `uv sync`가 된다.

```bash
uv sync --group stt        # faster-whisper·pyannote·torch까지 (기본 sync엔 안 들어감)
```

venv에 pip이 없다고 나오면(`uv`가 만든 venv는 기본적으로 pip을 안 깐다) 한 번만:
```bash
.venv/Scripts/python.exe -m ensurepip --upgrade   # Windows
.venv/bin/python -m ensurepip --upgrade           # Linux/macOS
```

Windows에서 Celery는 prefork를 못 쓰므로 `--pool=solo`가 필요하다:
```bash
export CALLWRAP_MODEL_DIR="<AI-model 레포>/data/models"   # 체크포인트 3종이 있는 경로
export STT_BACKEND=whisper
export WHISPER_MODEL=large-v3
celery -A callwrap_api.tasks.app.celery_app worker --loglevel=info --pool=solo
python -m callwrap_api.messaging.consumer
```

이 경로로 RabbitMQ(`server-spring`의 docker-compose) + Postgres/MinIO만 띄우고 Spring/FastAPI를
전부 호스트에서 직접 실행하는 구성을 실제로 검증했다 — 오디오 1건을 `POST /api/reviews`로
넣어 Whisper(large-v3) 전사 → pyannote 화자분리 → quality_gate → 결과가 Spring까지
정상 왕복하는 것까지 확인됨.

## 환경변수

| 변수 | 설명 |
|---|---|
| `SPRING_API_BASE_URL` | Spring 내부 API 베이스 URL (기본 `http://host.docker.internal:8080`) |
| `SPRING_INTERNAL_API_KEY` | Spring `/api/internal/faq/**` 호출 시 `X-API-Key`로 보낼 값. Spring의 `CALLWRAP_API_KEY_INTERNAL`과 동일해야 함 |

## FAQ 배치 생성

`POST /internal/faq/generate-batch`가 needs_faq 후보를 소분류별로 모아 EXAONE으로 FAQ 문항을 합성하고
Spring에 DRAFT로 저장한다. 이 레포 자체에는 스케줄러가 없다 — 호출 주체는 두 곳이다.

- **수동:** 상담사가 web 관리자 화면에서 트리거(`server-spring`의 `FaqController` → 이 엔드포인트)
- **자동:** `server-spring`의 `FaqBatchScheduler`가 매일 새벽 4시(KST)에 같은 엔드포인트를 호출

소분류당 후보가 `faq_min_group_size`(기본 3) 미만이면 그 그룹은 건너뛰고 다음 배치에서 다시 시도된다.

## 구조

```
config/quality_gate.yaml     품질 게이트 임계값
docs/message_contract.md     Spring↔FastAPI 메시지 계약
stubs/callwrap-ai/           미사용(과거 전환 이전 예시)
src/callwrap_api/
├── main.py                  FastAPI — /health 전용
├── settings.py
├── stt_stub.py              STT 스텁
├── messaging/               consumer · publisher · contracts · topology · audio
├── quality/                 orchestrator + checks 4종
└── tasks/                   Celery — app · transcribe · quality_gate · analyze
```

## 기술 스택

Python ≥3.11 · Celery(RabbitMQ) · FastAPI(헬스체크) · Pydantic v2 · uv · Docker Compose
