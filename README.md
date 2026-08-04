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

```bash
uv sync
docker run -d --name callwrap-rabbit --user root -p 5672:5672 -p 15672:15672 rabbitmq:3-management

uv run celery -A callwrap_api.tasks.app.celery_app worker --loglevel=info   # 워커
uv run python -m callwrap_api.messaging.consumer                            # 컨슈머(브리지)
```

전체 컨테이너로: `docker compose up -d`. 테스트: `uv run pytest` (DB·브로커 불필요, 상시 실행).

> `callwrap-ai`는 예시(stub) 패키지(`stubs/callwrap-ai`)를 물린다. 실제 모델(AI-model 레포)
> 완성 시 `pyproject.toml`의 `[tool.uv.sources]` 한 줄만 교체하면 된다.

## 구조

```
config/quality_gate.yaml     품질 게이트 임계값
docs/message_contract.md     Spring↔FastAPI 메시지 계약
stubs/callwrap-ai/           예시(stub) AI 패키지
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
