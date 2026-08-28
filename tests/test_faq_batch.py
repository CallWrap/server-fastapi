from types import SimpleNamespace

import callwrap_api.routers.faq as faq_router


CANDIDATES = [
    {"callId": "call-1", "subcategory": "본인부담금입금", "inquiry": "납부 방법 문의", "resolution": "가상계좌 안내"},
    {"callId": "call-2", "subcategory": "본인부담금입금", "inquiry": "입금 계좌 문의", "resolution": "가상계좌 안내"},
]
FAQ_ITEMS = [
    {"question": "어떻게 납부하나요?", "answer": "가상계좌로 납부합니다.", "source_indices": [0, 1]}
]


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class FakeClient:
    def __init__(self):
        self.posts = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get(self, *_):
        return FakeResponse({"candidates": CANDIDATES})

    def post(self, url, json):
        self.posts.append((url, json))
        return FakeResponse()


def install(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(faq_router.httpx, "Client", lambda **_: client)
    monkeypatch.setattr(
        faq_router,
        "get_settings",
        lambda: SimpleNamespace(
            spring_api_base_url="http://spring",
            spring_internal_api_key="key",
            faq_min_group_size=2,
        ),
    )
    monkeypatch.setattr(faq_router, "generate_faq", lambda *_: FAQ_ITEMS)
    return client


def test_batch_stores_only_gemma_validated_faq(monkeypatch):
    client = install(monkeypatch)
    monkeypatch.setattr(faq_router, "validate_faq", lambda *_: FAQ_ITEMS)

    result = faq_router.generate_batch()

    assert result["entries_created"] == 1
    assert client.posts[0][1]["question"] == "어떻게 납부하나요?"


def test_batch_does_not_store_when_gemma_rejects_draft(monkeypatch):
    client = install(monkeypatch)
    monkeypatch.setattr(faq_router, "validate_faq", lambda *_: [])

    result = faq_router.generate_batch()

    assert result["entries_created"] == 0
    assert client.posts == []
