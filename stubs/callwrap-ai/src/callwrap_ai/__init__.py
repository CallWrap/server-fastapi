"""callwrap_ai — Transcript를 받아 후처리 폼을 채운다. 외부 API는 analyze() 하나.

    from callwrap_ai import analyze
    result = analyze(transcript)   # Transcript -> AnalysisResult

※ 예시(stub) 패키지. 실제 모델은 AI-model 레포가 소유하며, 완성 시 이 패키지를 대체한다.
  공개 심볼·시그니처는 실제와 동일하게 유지한다 (api/ import 무변경 보장).
"""

from callwrap_ai.pipeline import analyze
from callwrap_ai.schemas import (
    SUBCATEGORIES_BY_CATEGORY,
    AnalysisResult,
    ConsultationCategory,
    ConsultationGrade,
    ConsultationSubcategory,
    ConsultationType,
    Judgment,
    Speaker,
    Summary,
    Transcript,
    Utterance,
)

__all__ = [
    "analyze",
    "AnalysisResult",
    "ConsultationCategory",
    "ConsultationGrade",
    "ConsultationSubcategory",
    "ConsultationType",
    "Judgment",
    "Speaker",
    "Summary",
    "SUBCATEGORIES_BY_CATEGORY",
    "Transcript",
    "Utterance",
]
