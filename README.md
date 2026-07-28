# CallWrap — server-fastapi

상담 후처리 자동화 파이프라인의 **FastAPI 백엔드**. 음성 업로드부터 STT, 데이터 품질 게이트,
AI 분석 결과 저장까지를 담당한다. FastAPI(동기 API) + Celery(비동기 워커) 구성.

전체 시스템은 두 개의 백엔드로 나뉜다.

- **server-fastapi** (이 레포, 담당: 이정민) — 음성 처리·AI 추론·파이프라인 오케스트레이션
- **Spring Boot** (담당: 김규리) — 사용자·인증·검토(review) 도메인 API

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

## API

### 현재 구현된 엔드포인트

파이프라인을 구동하는 오케스트레이션 API. `web/` 프론트가 이걸 사용한다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/api/calls/upload` | 음성 파일 업로드 → `call_id` 반환, 파이프라인 시작 |
| `GET` | `/api/calls/{call_id}` | 콜 상세 — 상태 · 품질 체크 결과 · 분석 결과(JSON) |
| `GET` | `/api/calls` | 콜 목록(페이지네이션) |
| `GET` | `/health` | 헬스체크 |
| `GET` | `/health/db` | DB 연결 확인 |

허용 업로드 확장자: `.wav`(기본) · `.mp3` · `.m4a` · `.flac`

### 계획된 기능 엔드포인트 (노션 명세, 미구현)

파이프라인 내부 단계를 개별 API로도 노출할 예정. 명세는 노션 "백엔드 자료 (API 명세, ERD)" 참고.

| 기능 | 경로 | 메서드 | 상태 |
|---|---|---|---|
| STT 전사 | `/stt` | POST | 서버 개발 전 |
| 화자 분리 | `/diarize` | POST | 서버 개발 전 |
| 상담 요약 | `/summarize` | POST | 서버 개발 전 |
| 상담등급 분류 | `/classify/grade` | POST | 서버 개발 전 |
| 상담유형 분류 | `/classify/type` | POST | 서버 개발 전 |
| 상담분류 분류 | `/classify/category` | POST | 서버 개발 전 |
| 후속처리 판정 | `/followup` | POST | 서버 개발 전 |
| 품질 게이트 | `/quality-gate` | POST | 서버 개발 전 (정민·규리) |

## 콜 상태(FSM)

```
UPLOADED → TRANSCRIBING → QUALITY_CHECK ┬─ PASSED → ANALYZING → DONE
                                        ├─ RETRYING → (재시도)
                                        └─ NEEDS_HUMAN_REVIEW
(모든 단계에서 실패 시 → FAILED)
```

## DB 구조

전체 프로젝트 ERD는 [ERDCloud — callwrap-산학협력](https://www.erdcloud.com/d/dFzhoTBQvpmBn26xB)(작성: 김규리).
이 레포(FastAPI 서비스)가 소유하는 테이블은 아래 3개다. 스키마 변경은 반드시 Alembic 마이그레이션과 함께 한다.

**`calls`** — 콜 1건. 파이프라인의 중심 엔티티.

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | UUID | PK |
| `audio_path` | String | 업로드된 음성 경로 |
| `status` | String | 콜 상태(FSM 값을 VARCHAR로 저장) |
| `retry_count` | Integer | 재시도 횟수 |
| `created_at` / `updated_at` | DateTime | |

**`quality_check_results`** — 품질 체크 1회 실행 결과. 재시도마다 새 행을 쌓는다(덮어쓰지 않음).

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | UUID | PK |
| `call_id` | UUID | FK → `calls.id` (CASCADE) |
| `check_name` | String | 체크 이름 |
| `passed` | Boolean | 통과 여부 |
| `score` / `threshold` | Float | 점수 · 임계값 |
| `higher_is_better` | Boolean | 방향 |
| `action` / `reason` | String / Text | 조치 · 사유 |
| `details` | JSONB | 체크별 상세(키 가변) |
| `retry_iteration` | Integer | 재시도 회차 |
| `checked_at` | DateTime | |

**`analysis_results`** — `analyze()` 결과. 콜당 1행(`call_id` UNIQUE).

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `id` | UUID | PK |
| `call_id` | UUID | FK → `calls.id` (CASCADE), UNIQUE |
| `result` | JSONB | 분석 결과 원본(진실의 원본) |
| `consultation_type` | String | 파생 컬럼(대시보드 필터·집계용) |
| `consultation_category` | String | 파생 컬럼 |
| `grade` | String | 파생 컬럼 |
| `created_at` | DateTime | |

인덱스: `idx_calls_status`(검토 큐 조회), `idx_analysis_grade`·`idx_analysis_type`(대시보드 집계),
`idx_check_call`(콜별 회차 결과 조회).

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
