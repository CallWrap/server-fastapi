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
