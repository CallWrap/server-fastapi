"""analyze() — 예시(stub) 구현.

★ 이것은 실제 AI 모델이 아니다. AI-model 레포가 완성되기 전까지 파이프라인 전 구간이
  실제 형태의 결과로 흐르도록 하는 예시 응답을 돌려준다.
  
  실제 모델로 교체 시 api/의 코드는 바뀌지 않는다 — analyze() 시그니처와
  AnalysisResult 계약이 동일하기 때문. 교체는 pyproject의 소스 경로만 바꾸면 된다.

  더미도 실존하는 발화 index만 가리킨다 — web/이 하이라이트를 바로 테스트할 수 있게.
  confidence는 3-tier(High/Medium/Low)가 전부 등장하도록 일부러 흩어놓았다.
"""

from callwrap_ai.schemas import (
    AnalysisResult,
    ConsultationCategory,
    ConsultationGrade,
    ConsultationSubcategory,
    ConsultationType,
    Judgment,
    Summary,
    Transcript,
)


def analyze(transcript: Transcript) -> AnalysisResult:
    indices = [u.index for u in transcript.utterances]
    head, tail = indices[:2], indices[-2:]

    return AnalysisResult(
        summary=Judgment(
            value=Summary(
                title="(예시) 바우처 결제 오류 확인 요청",
                inquiry="(예시) 제공기관 담당자가 바우처 결제 처리 중 오류가 반복된다고 문의함.",
                resolution="(예시) 상담원이 결제 메뉴 경로와 재시도 방법을 안내하고 처리 완료를 확인함.",
            ),
            confidence=0.92,
            evidence_indices=head,
        ),
        consultation_type=Judgment(
            value=ConsultationType.USAGE, confidence=0.95, evidence_indices=head
        ),
        consultation_category=Judgment(
            value=ConsultationCategory.PAYMENT, confidence=0.72, evidence_indices=head
        ),
        consultation_subcategory=Judgment(
            value=ConsultationSubcategory.PAYMENT_METHOD_ERROR,
            confidence=0.58,
            evidence_indices=head,
        ),
        grade=Judgment(value=ConsultationGrade.NORMAL, confidence=0.55),
        needs_followup=Judgment(value=False, confidence=0.88, evidence_indices=tail),
        needs_faq=Judgment(value=True, confidence=0.66, evidence_indices=head),
        failures=[],
    )
