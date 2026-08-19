"""FAQ 배치 생성 트리거. 관리자가 수동으로 호출한다 (POST /internal/faq/generate-batch).

Spring의 후보 조회 → 소분류별 그룹핑 → EXAONE 합성(callwrap_ai.faq_generate) → Spring에 저장,
네 단계를 동기로 순서대로 실행한다. main.py 독스트링의 "무상태 워커라 업무 API가 없다" 원칙에
대한 유일한 예외인데, 이 작업 자체는 상태를 안 갖는다 — 후보도 결과도 전부 Spring이 저장하고,
이 엔드포인트는 그 사이를 잇는 배치 트리거일 뿐이라 무상태성은 깨지 않는다고 판단했다.

지금은 관리자가 수동으로 누르는 트리거로 시작한다 (데모 가능성 우선). 나중에 자동화하려면
Celery beat로 주기 실행하도록 바꾸면 된다 — 이 함수 본체는 그대로 재사용 가능.
"""

import logging
from collections import defaultdict

import httpx
from fastapi import APIRouter, HTTPException

from callwrap_ai.faq_generate import generate_faq
from callwrap_api.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/faq", tags=["faq"])


@router.post("/generate-batch")
def generate_batch() -> dict:
    """needs_faq=true 후보를 소분류별로 모아 EXAONE으로 FAQ 문항을 합성하고 Spring에 DRAFT로 저장한다."""
    settings = get_settings()
    base = settings.spring_api_base_url.rstrip("/")

    with httpx.Client(timeout=30) as client:
        try:
            resp = client.get(f"{base}/api/internal/faq/candidates")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Spring 후보 조회 실패: {exc}") from None

        candidates = resp.json().get("candidates", [])
        if not candidates:
            return {"groups_processed": 0, "entries_created": 0, "skipped_groups": []}

        groups: dict[str, list[dict]] = defaultdict(list)
        for c in candidates:
            groups[c["subcategory"]].append(c)

        entries_created = 0
        groups_processed = 0
        skipped_groups: list[dict] = []

        for subcategory, cases in groups.items():
            # 대표성 없는 소분류(후보 1~2건)는 건너뛴다 — 다음 배치 때 더 쌓이면 다시 시도됨
            # (아직 faq_processed_at으로 마킹 안 됐으므로 후보 목록에 계속 남는다).
            if len(cases) < settings.faq_min_group_size:
                skipped_groups.append({"subcategory": subcategory, "count": len(cases)})
                continue

            groups_processed += 1
            faq_items = generate_faq(subcategory, cases)
            if not faq_items:
                logger.warning("[faq] EXAONE 생성 실패 또는 빈 결과 — 소분류=%s 건수=%d", subcategory, len(cases))
                continue

            for item in faq_items:
                raw_indices = item.get("source_indices") or []
                sample_call_ids = [cases[i]["callId"] for i in raw_indices if 0 <= i < len(cases)]
                if not sample_call_ids:
                    # 근거 인덱스가 비었거나 못 믿을 값이면, 이번 그룹 전체를 근거로 보수적으로 잡는다.
                    sample_call_ids = [c["callId"] for c in cases]

                try:
                    create_resp = client.post(
                        f"{base}/api/internal/faq/entries",
                        json={
                            "subcategory": subcategory,
                            "question": item["question"],
                            "answer": item["answer"],
                            "sourceCallCount": len(sample_call_ids),
                            "sampleCallIds": sample_call_ids,
                        },
                    )
                    create_resp.raise_for_status()
                    entries_created += 1
                except httpx.HTTPError as exc:
                    logger.error("[faq] Spring 저장 실패 — 소분류=%s: %r", subcategory, exc)

        return {
            "groups_processed": groups_processed,
            "entries_created": entries_created,
            "skipped_groups": skipped_groups,
        }
