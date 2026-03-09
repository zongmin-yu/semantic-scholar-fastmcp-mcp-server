import pytest
from httpx import ASGITransport, AsyncClient

import semantic_scholar.bridge as bridge
import semantic_scholar.api.papers as papers_api
from semantic_scholar.config import Config


@pytest.mark.asyncio
async def test_paper_autocomplete_basic_call(monkeypatch):
    async def fake_make_request(endpoint, params=None, **kwargs):
        assert endpoint == "/paper/autocomplete"
        assert params == {"query": "graph neural"}
        return {"matches": [{"paperId": "123", "title": "Graph Neural Networks"}]}

    monkeypatch.setattr(papers_api, "make_request", fake_make_request)

    result = await papers_api.paper_autocomplete.fn(None, query="graph neural")

    assert "matches" in result
    assert result["matches"][0]["paperId"] == "123"


@pytest.mark.asyncio
async def test_paper_autocomplete_empty_query_validation():
    result = await papers_api.paper_autocomplete.fn(None, query="   ")

    assert result["error"]["type"] == "validation"
    assert result["error"]["message"] == "Query string cannot be empty"


@pytest.mark.asyncio
async def test_paper_autocomplete_truncates_query(monkeypatch):
    long_query = "a" * 150

    async def fake_make_request(endpoint, params=None, **kwargs):
        assert endpoint == "/paper/autocomplete"
        assert params == {"query": "a" * 100}
        return {"matches": []}

    monkeypatch.setattr(papers_api, "make_request", fake_make_request)

    result = await papers_api.paper_autocomplete.fn(None, query=long_query)

    assert result == {"matches": []}


@pytest.mark.asyncio
async def test_snippet_search_basic_call(monkeypatch):
    async def fake_make_request(endpoint, params=None, **kwargs):
        assert endpoint == "/snippet/search"
        assert params == {
            "query": "transformer attention",
            "limit": 5,
            "fields": "snippet.text,paper.title",
            "paperIds": "p1,p2",
            "authors": "Author One,Author Two",
            "minCitationCount": 50,
            "insertedBefore": "2025-01-01",
            "publicationDateOrYear": "2020-01-01:2024-12-31",
            "year": "2020-2024",
            "venue": "NeurIPS,ICML",
            "fieldsOfStudy": "Computer Science,Mathematics",
        }
        return {"data": [{"text": "attention is all you need"}]}

    monkeypatch.setattr(papers_api, "make_request", fake_make_request)

    result = await papers_api.snippet_search.fn(
        None,
        query="transformer attention",
        fields=["snippet.text", "paper.title"],
        limit=5,
        paper_ids=["p1", "p2"],
        authors=["Author One", "Author Two"],
        min_citation_count=50,
        inserted_before="2025-01-01",
        publication_date_or_year="2020-01-01:2024-12-31",
        year="2020-2024",
        venue=["NeurIPS", "ICML"],
        fields_of_study=["Computer Science", "Mathematics"],
    )

    assert result["data"][0]["text"] == "attention is all you need"


@pytest.mark.asyncio
async def test_snippet_search_empty_query_validation():
    result = await papers_api.snippet_search.fn(None, query="  ")

    assert result["error"]["type"] == "validation"
    assert result["error"]["message"] == "Query string cannot be empty"


@pytest.mark.asyncio
async def test_snippet_search_limit_validation():
    result = await papers_api.snippet_search.fn(None, query="test", limit=0)

    assert result["error"]["type"] == "validation"
    assert result["error"]["message"] == "Limit must be at least 1"
    assert result["error"]["details"] == {"min_limit": 1}


@pytest.mark.asyncio
async def test_snippet_search_author_count_validation():
    result = await papers_api.snippet_search.fn(
        None,
        query="test",
        authors=[f"Author {i}" for i in range(11)],
    )

    assert result["error"]["type"] == "validation"
    assert result["error"]["message"] == "Cannot filter by more than 10 authors"
    assert result["error"]["details"] == {"max_authors": 10}


@pytest.mark.asyncio
async def test_snippet_search_paper_id_count_validation():
    result = await papers_api.snippet_search.fn(
        None,
        query="test",
        paper_ids=[f"paper-{i}" for i in range(101)],
    )

    assert result["error"]["type"] == "validation"
    assert result["error"]["message"] == "Cannot filter by more than 100 paper IDs"
    assert result["error"]["details"] == {"max_paper_ids": 100}


@pytest.mark.asyncio
async def test_bridge_recommendations_uses_recommendations_base_url(monkeypatch):
    async def fake_make_request(endpoint, params=None, api_key_override=None, method="GET", json=None, base_url=None):
        assert endpoint == "/papers/forpaper/paper-123"
        assert params == {"fields": "title,year"}
        assert method == "GET"
        assert json is None
        assert api_key_override is None
        assert base_url == Config.RECOMMENDATIONS_BASE_URL
        return {"recommendedPapers": []}

    monkeypatch.setattr(bridge, "make_request", fake_make_request)

    transport = ASGITransport(app=bridge.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/v1/recommendations",
            params={"paper_id": "paper-123", "fields": "title,year"},
        )

    assert response.status_code == 200
    assert response.json() == {"recommendedPapers": []}
