# CallWrap — server-fastapi

상담 후처리 자동화 파이프라인의 **FastAPI 백엔드**. 음성 업로드부터 STT, 데이터 품질 게이트,
AI 분석 결과 저장까지를 담당한다. FastAPI(동기 API) + Celery(비동기 워커) 구성.

전체 시스템은 두 개의 백엔드로 나뉜다.

- **server-fastapi** — 음성 처리·AI 추론·파이프라인 오케스트레이션
- **server-spring** (담당: 김규리) — 사용자·인증·검토(review) 도메인 API

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
