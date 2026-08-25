# Spring ↔ FastAPI 메시지 계약

RabbitMQ topic exchange `callwrap` 하나를 라우팅키로 방향을 가른다. 실제 정의는
`server-spring/src/main/resources/schema/*.schema.json`(JSON Schema, 발행측 검증)과
`server-fastapi/src/callwrap_api/messaging/contracts.py`(pydantic 모델)에 있고, 이 문서는
그 둘을 사람이 읽기 좋게 요약한 것이다 — **필드를 바꿀 땐 세 파일(JSON Schema 2개 + contracts.py)을
같이 고치고, 이 문서도 갱신한다.**

```
Spring ──(call.analyze.request)──▶ [callwrap exchange] ──▶ callwrap.jobs 큐 ──▶ FastAPI consumer
FastAPI ──(call.analyze.result)──▶ [callwrap exchange] ──▶ Spring이 바인딩한 큐(callwrap.spring.result-queue)
```

## 1. JobRequest (Spring → FastAPI)

라우팅키 `call.analyze.request`, 큐 `callwrap.jobs`.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `schema_version` | string (`"1.0"`) | ✅ | 계약 버전 |
| `call_id` | UUID | ✅ | Spring의 `calls.id` |
| `audio_uri` | string | ✅ | 오디오 위치. `AUDIO_SOURCE=local`이면 로컬 파일 경로, `s3`면 `s3://bucket/key` |
| `audio_format` | string \| null | | 참고용, 현재 로직에서 강제하지 않음 |
| `metadata` | object \| null | | 예약 필드 |
| `requested_at` | date-time | | 요청 발행 시각 |

`additionalProperties: true` — 모르는 필드가 와도 검증 실패하지 않는다.

## 2. ResultMessage (FastAPI → Spring)

라우팅키 `call.analyze.result`.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `schema_version` | string (`"1.0"`) | ✅ | |
| `call_id` | UUID | ✅ | |
| `status` | `"DONE"` \| `"NEEDS_HUMAN_REVIEW"` \| `"FAILED"` | ✅ | |
| `analysis` | object \| null | `status=DONE`일 때 필수 | `AnalysisResult`(AI-model `schemas.py`) 그대로 |
| `quality` | `{passed: bool, failed_checks: string[]}` | `status=NEEDS_HUMAN_REVIEW`일 때 필수 | 품질 게이트가 왜 사람 확인으로 보냈는지 |
| `failures` | string[] | | 부분 실패한 AI 모듈명 (`classify_category` 등) |
| `error` | string \| null | `status=FAILED`일 때 필수 | 예외 메시지 요약 |
| `completed_at` | date-time | ✅ | |

`status`별로 `analysis`/`quality`/`error` 중 정확히 그 필드만 채워진다 — 나머지는 `null`.
Spring `ResultMessageListener`가 `call_id`를 못 찾으면(예: Call insert가 실패했는데 job은 이미
발행된 경우) 재시도 후 DLQ로 격리한다 — 이 자체는 정상 동작이다.

## 3. AnalysisResult (analysis 필드 안의 실제 내용)

출처: `AI-model/src/callwrap_ai/schemas.py` — **4개 레포 공용, 여기 바꾸면 전원 리뷰**.

| 필드 | 채우는 모듈 | 실패 시 `failures`에 들어가는 값 |
|---|---|---|
| `consultation_type` (SR유형 8종) | `sr_type.py` (klue-roberta-base + 화자임베딩) | `classify_type` |
| `consultation_category` (중분류 6종) | `classify.py` | `classify_category` |
| `consultation_subcategory` (소분류 29종) | `classify.py` (중분류로 후보 마스킹) | `classify_subcategory` / `subcategory_hierarchy` |
| `grade` (칭찬콜/악성콜/일반) | `grade.py` — Ollama(EXAONE) 감정점수 + 2축 규칙 | `grade` |
| `summary` (제목/문의내용/처리내용) | `summary.py` — Ollama(EXAONE) 1회 호출 | `summarize` |
| `needs_followup`, `needs_faq` | `summary.py`와 같은 호출에서 함께 산출 | `needs_followup`, `needs_faq` |

각 필드는 `Judgment[T]` (`value` + `confidence` + `evidence_indices`)로 오고, 모델이 없거나
호출이 실패하면 그 필드만 `null` + `failures`에 모듈명이 남는다 — 나머지 필드는 정상 반환된다
(부분 실패 허용, 명세 4.1).

## 4. 필요한 로컬/오프라인 자산

이 계약 자체와는 별개로, FastAPI가 실제로 위 필드를 채우려면 다음이 로컬에 있어야 한다
(전부 인터넷 없이 캐시 파일만 복사해서 반입 가능 — `scripts/OFFLINE_README.md` 참고):

- Whisper(`large-v3`) — HuggingFace 캐시
- pyannote 3종(segmentation-3.0, speaker-diarization-3.1, wespeaker) — 별도 캐시 경로
- 중분류·소분류·SR유형 체크포인트 3종 — `AI-model/data/models/`
- Ollama `exaone3.5:7.8b` — 등급판정·요약·후속처리·FAQ필요 전부 이 모델 하나가 담당
