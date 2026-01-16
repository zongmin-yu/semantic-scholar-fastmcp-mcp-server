import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

import semantic_scholar.bridge as bridge
import semantic_scholar.utils.http as utils_http

# Reuse sample IDs from other tests for consistency
SAMPLE_PAPER_ID = "649def34f8be52c8b66281af98ae884c09aef38b"
SAMPLE_PAPER_IDS = [
    SAMPLE_PAPER_ID,
    "ARXIV:2106.15928"
]
SAMPLE_AUTHOR_ID = "1741101"
SAMPLE_AUTHOR_IDS = [SAMPLE_AUTHOR_ID, "2061296"]


@pytest.mark.asyncio
async def test_paper_search_endpoint(monkeypatch):
    async def fake_make_request(*args, **kwargs):
        endpoint = args[0] if args else kwargs.get('endpoint')
        assert endpoint == "/paper/search"
        return {"data": [], "total": 0}

    monkeypatch.setattr(bridge, "make_request", fake_make_request)

    transport = ASGITransport(app=bridge.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/v1/paper/search", params={"q": "test", "limit": 1})
        assert r.status_code == 200
        body = r.json()
        assert "data" in body and body["total"] == 0


@pytest.mark.asyncio
async def test_paper_details_endpoint(monkeypatch):
    async def fake_make_request(*args, **kwargs):
        endpoint = args[0] if args else kwargs.get('endpoint')
        assert endpoint.startswith("/paper/")
        return {"paperId": SAMPLE_PAPER_ID, "title": "Test Paper"}

    monkeypatch.setattr(bridge, "make_request", fake_make_request)

    transport = ASGITransport(app=bridge.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(f"/v1/paper/{SAMPLE_PAPER_ID}")
        assert r.status_code == 200
        body = r.json()
        assert body.get("paperId") == SAMPLE_PAPER_ID


@pytest.mark.asyncio
async def test_paper_batch_endpoint(monkeypatch):
    # fake http client with a post method
    class FakeResp:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data
            self.text = str(data)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise Exception("HTTP error")

        def json(self):
            return self._data

    class FakeClient:
        async def post(self, url, json=None, params=None, headers=None):
            assert isinstance(json, dict) and "ids" in json
            return FakeResp(200, [{"paperId": pid} for pid in json["ids"]])

    # set the http_client in the utils module used by the bridge
    monkeypatch.setattr(utils_http, "http_client", FakeClient())
    transport = ASGITransport(app=bridge.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/v1/paper/batch", json={"ids": SAMPLE_PAPER_IDS})
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list) and len(body) == 2


@pytest.mark.asyncio
async def test_author_endpoints_and_recommendations(monkeypatch):
    async def fake_make_request(*args, **kwargs):
        endpoint = args[0] if args else kwargs.get('endpoint')
        if endpoint.startswith("/author/search"):
            return {"data": [], "total": 0}
        if endpoint.startswith("/author/") and "batch" not in endpoint:
            return {"authorId": SAMPLE_AUTHOR_ID, "name": "A. Author"}
        if endpoint.startswith("/paper/") and endpoint.endswith("/recommendations"):
            return {"recommendations": []}
        return {}

    monkeypatch.setattr(bridge, "make_request", fake_make_request)

    transport = ASGITransport(app=bridge.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/v1/author/search", params={"q": "Andrew Ng"})
        assert r.status_code == 200
        r = await ac.get(f"/v1/author/{SAMPLE_AUTHOR_ID}")
        assert r.status_code == 200 and r.json().get("authorId") == SAMPLE_AUTHOR_ID
        r = await ac.get("/v1/recommendations", params={"paper_id": SAMPLE_PAPER_ID})
        assert r.status_code == 200 and "recommendations" in r.json()
