# api/

FastAPI 서버와 비동기 큐. 파이프라인의 ② ④ ⑥.

**담당:** 김규리, 이정민 (세부 분담 미정)

## 할 일

- 음성 업로드 → STT → AI 분석으로 이어지는 분석 API와 Celery 큐
- ② 데이터 품질 게이트 — 품질 기준을 통과한 `Transcript`만 `ai/`로 전달
- ④ AI 분석 결과 저장 (DB)
- ⑥ 상담사 확정 데이터 축적
- 모델 서빙·MLflow 연동, Docker 배포, 모니터링·부하테스트

Celery 태스크에서 `callwrap_ai.analyze()` 하나만 호출한다.

## 실행

```bash
cd api
uv sync                                  # 의존성 (../ai를 로컬 경로로 같이 물린다)
docker compose up -d postgres redis      # DB·큐만 로컬로
uv run alembic upgrade head              # 스키마 생성
uv run uvicorn callwrap_api.main:app --reload
uv run celery -A callwrap_api.tasks.app.celery_app worker --loglevel=info
uv run pytest                            # DB 붙는 테스트는 자동 skip

# 파이프라인 흐름 테스트까지 돌리려면 (DB 필요)
createdb callwrap_test
CALLWRAP_TEST_DATABASE_URL="postgresql+psycopg://$(whoami)@localhost:5432/callwrap_test" \
  DATABASE_URL="postgresql+psycopg://$(whoami)@localhost:5432/callwrap_test" \
  uv run alembic upgrade head
CALLWRAP_TEST_DATABASE_URL=... DATABASE_URL=... uv run pytest
```

전체를 컨테이너로: `docker compose up -d`. API 문서: http://localhost:8000/docs

## 구조

```
api/
├── config/quality_gate.yaml        ★ 임계값 (규리 공유)
├── migrations/                     ★ Alembic (규리 공유)
├── src/callwrap_api/
│   ├── main.py                     FastAPI 앱
│   ├── settings.py                 .env 로딩
│   ├── state.py                    콜 상태 FSM — status의 진실
│   ├── db/                         models · session · repository
│   ├── routers/                    calls (업로드·조회) · health
│   ├── schemas/quality.py          ★ GateResult 계약 (규리 공유)
│   ├── quality/
│   │   ├── config.py               yaml 로더
│   │   ├── checks/                 체크 4개 — 한 파일에 하나
│   │   └── orchestrator.py         실행·예외 통합·액션 종합
│   └── tasks/                      Celery — transcribe · quality_gate · analyze
└── tests/
```

## 분담

| 파트 | 담당 | 상태 |
|---|---|---|
| `checks/stt_confidence.py` | 규리 | 시그니처만 (Week 3) |
| `checks/repetition_and_gaps.py` | 규리 | 시그니처만 (Week 3) |
| `checks/speaker_overlap.py` | 정민 | 시그니처만 (Week 3) |
| `checks/segment_length.py` | 정민 | 시그니처만 (Week 3) |
| `orchestrator.py` · `state.py` · `db/` · `routers/` | 정민 | Week 1 골격 |
| `tasks/transcribe.py` | 미정 | `stt/` 연동 대기 |

★ 표시된 파일은 둘 다 건드리는 곳이다. 고치기 전에 공유할 것.

컨벤션과 열린 질문은 [`docs/backend_conventions.md`](../docs/backend_conventions.md),
설계 결정 근거는 [`docs/decisions.md`](../docs/decisions.md).
