# CallWrap — server-fastapi

상담 후처리 자동화 파이프라인의 **백엔드 서버**. 음성 업로드부터 STT, 데이터 품질 게이트,
AI 분석 결과 저장까지를 담당한다. FastAPI(동기 API) + Celery(비동기 워커) 구성.

전체 파이프라인 중 ② 데이터 품질 게이트, ④ AI 분석 결과 저장, ⑥ 상담사 확정 데이터 축적을 맡는다.

## 아키텍처

```
업로드(wav/mp3/…) ─▶ [transcribe] ─▶ [quality_gate] ─▶ [analyze] ─▶ 결과 저장
      FastAPI            Celery           Celery          Celery        Postgres
                          STT           품질 임계값       callwrap_ai
                                         통과 판정         .analyze()
```

- **FastAPI** — 업로드·조회 API. 업로드는 `202 Accepted`로 즉시 반환하고 처리는 큐로 넘긴다.
- **Celery + Redis** — `transcribe → quality_gate → analyze` 태스크 체인.
- **품질 게이트** — 4개 체크(`config/quality_gate.yaml` 임계값)를 통과한 `Transcript`만 분석 단계로 넘긴다.
- **상태 관리** — `state.py`의 FSM이 콜 상태 전이의 유일한 진실. 허용되지 않은 전이는 예외.
- **AI 분석** — `callwrap_ai.analyze()` 하나만 호출한다(분석 로직은 별도 `ai` 패키지 소유).


## 콜 상태(FSM)

```
UPLOADED → TRANSCRIBING → QUALITY_CHECK ┬─ PASSED → ANALYZING → DONE
                                        ├─ RETRYING → (재시도)
                                        └─ NEEDS_HUMAN_REVIEW
(모든 단계에서 실패 시 → FAILED)
```

## 실행

> **의존성 참고:** `callwrap-ai`를 로컬 경로(`../ai`)로 물린다(`pyproject.toml`의 `[tool.uv.sources]`).
> 이 레포를 단독으로 클론하면 `../ai`가 없어 `uv sync`가 실패한다. `ai` 패키지를 형제 디렉터리에
> 두거나, 소스 지정을 배포용(레지스트리/깃)으로 바꿔야 한다.

```bash
uv sync                                  # 의존성 설치
docker compose up -d postgres redis      # DB·큐만 로컬로
uv run alembic upgrade head              # 스키마 생성

uv run uvicorn callwrap_api.main:app --reload                              # API 서버
uv run celery -A callwrap_api.tasks.app.celery_app worker --loglevel=info  # 워커
```

전체를 컨테이너로: `docker compose up -d`. API 문서(Swagger): http://localhost:8000/docs

### 테스트

```bash
uv run pytest                            # DB 없이 도는 테스트만 (DB 붙는 건 자동 skip)

# 파이프라인 흐름 테스트까지 (DB 필요)
createdb callwrap_test
CALLWRAP_TEST_DATABASE_URL="postgresql+psycopg://$(whoami)@localhost:5432/callwrap_test" \
  DATABASE_URL="postgresql+psycopg://$(whoami)@localhost:5432/callwrap_test" \
  uv run alembic upgrade head
CALLWRAP_TEST_DATABASE_URL=... DATABASE_URL=... uv run pytest
```

## 구조

```
.
├── config/quality_gate.yaml        품질 게이트 임계값
├── migrations/                     Alembic 마이그레이션
├── src/callwrap_api/
│   ├── main.py                     FastAPI 앱 엔트리
│   ├── settings.py                 .env 로딩 (pydantic-settings)
│   ├── state.py                    콜 상태 FSM — status의 진실
│   ├── stt_stub.py                 STT 스텁 (연동 전 임시)
│   ├── db/                         models · session · repository
│   ├── routers/                    calls(업로드·조회) · health
│   ├── schemas/quality.py          GateResult 계약
│   ├── quality/
│   │   ├── config.py               yaml 로더
│   │   ├── checks/                 체크 4개 — 한 파일에 하나
│   │   │   ├── stt_confidence.py
│   │   │   ├── repetition_and_gaps.py
│   │   │   ├── speaker_overlap.py
│   │   │   └── segment_length.py
│   │   └── orchestrator.py         실행 · 예외 통합 · 액션 종합
│   └── tasks/                      Celery — transcribe · quality_gate · analyze
└── tests/                          테스트 13종
```

## 기술 스택

Python ≥3.11 · FastAPI · Celery(Redis) · SQLAlchemy 2.0 + Alembic · PostgreSQL(psycopg 3) ·
Pydantic v2 · uv(패키지 관리) · Docker Compose
