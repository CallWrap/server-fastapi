import os

# 테스트는 개발자 .env에 의존하지 않는다 — STT_BACKEND=whisper인 .env를 둔 개발자도
# base 테스트가 stub 경로로 돌게 강제한다. (env가 .env보다 우선하고, get_settings 캐시 전에 세팅)
os.environ["STT_BACKEND"] = "stub"

import pytest
from fastapi.testclient import TestClient

from callwrap_api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def captured_results(monkeypatch):
    """결과 발행을 가로채 실제 RabbitMQ 연결을 막고, 발행된 메시지를 수집한다.

    모든 테스트에 적용(autouse) — 파이프라인이 DONE/검토/실패에 닿을 때 publisher가
    브로커에 붙으려다 지연·실패하는 걸 막는다. 발행 내용을 검증할 테스트는 이 fixture를
    인자로 받아 리스트를 들여다본다.
    """
    from callwrap_api.messaging import publisher

    box: list = []
    monkeypatch.setattr(publisher, "publish_result", box.append)
    return box


@pytest.fixture
def fixed_analysis(monkeypatch):
    """analyze()를 고정 결과로 갈아끼운다. 반환한 AnalysisResult가 곧 기대값이다.

    이 레포가 검증할 것은 **경로**다 — 전사→게이트→분석→발행이 이어지는지, 결과가 계약
    형태 그대로 실리는지. 실제 판정값은 AI-model의 책임이고 검증도 그쪽 테스트에 있다.
    진짜 analyze()를 부르면 ollama가 떠 있고 체크포인트가 마운트된 머신에서만 통과하는
    테스트가 된다 — "DB·브로커 불필요, 상시 실행" 원칙과 어긋난다.
    (예전엔 stubs/callwrap-ai가 이 역할을 했는데, 실제 AI-model을 git 소스로 물면서
     그 자리가 비었다.)
    """
    from callwrap_ai.schemas import (
        AnalysisResult,
        ConsultationCategory,
        ConsultationGrade,
        ConsultationSubcategory,
        ConsultationType,
        Judgment,
        Summary,
    )
    from callwrap_api.tasks import analyze as analyze_task_module

    evidence = [0, 1]
    result = AnalysisResult(
        summary=Judgment(
            value=Summary(
                title="(고정) 바우처 결제 오류 확인 요청",
                inquiry="제공기관 담당자가 바우처 결제 처리 중 오류가 반복된다고 문의함.",
                resolution="상담원이 결제 메뉴 경로와 재시도 방법을 안내하고 처리 완료를 확인함.",
            ),
            confidence=0.88,
            evidence_indices=evidence,
        ),
        consultation_type=Judgment(
            value=ConsultationType.USAGE, confidence=0.95, evidence_indices=evidence
        ),
        consultation_category=Judgment(
            value=ConsultationCategory.PAYMENT, confidence=0.47, evidence_indices=evidence
        ),
        consultation_subcategory=Judgment(
            value=ConsultationSubcategory.PAYMENT_METHOD_ERROR,
            confidence=0.31,
            evidence_indices=evidence,
        ),
        grade=Judgment(
            value=ConsultationGrade.NORMAL, confidence=0.6, evidence_indices=evidence
        ),
        needs_followup=Judgment(value=False, confidence=0.98, evidence_indices=evidence),
        needs_faq=Judgment(value=True, confidence=0.94, evidence_indices=evidence),
        failures=[],
    )
    monkeypatch.setattr(analyze_task_module, "analyze", lambda _transcript: result)
    return result
