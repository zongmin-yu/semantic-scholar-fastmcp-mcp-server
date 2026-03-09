import pytest

import semantic_scholar.bridge as bridge
from semantic_scholar.config import AuthorDetailFields, Config, PaperFields


pytestmark = pytest.mark.asyncio


def assert_single_call(
    mock_make_request,
    *,
    endpoint,
    params,
    api_key_override=None,
    method="GET",
    json=None,
    base_url=None,
):
    assert mock_make_request.calls == [
        {
            "endpoint": endpoint,
            "params": params,
            "api_key_override": api_key_override,
            "method": method,
            "json": json,
            "base_url": base_url,
        }
    ]


async def test_bridge_paper_search_contract(mock_make_request, bridge_client, auth_headers):
    payload = {"total": 1, "data": [{"paperId": "p1"}]}
    mock_make_request.install(bridge).queue_responses(payload)

    response = await bridge_client.get("/v1/paper/search", params={"q": "attention"}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/search",
        params={
            "query": "attention",
            "offset": 0,
            "limit": 10,
            "fields": "title,abstract,year,citationCount,authors,url",
        },
        api_key_override="bridge-token",
    )


async def test_bridge_paper_details_contract(mock_make_request, bridge_client, auth_headers):
    payload = {"paperId": "paper-123", "title": "Attention"}
    mock_make_request.install(bridge).queue_responses(payload)

    response = await bridge_client.get("/v1/paper/paper-123", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/paper-123",
        params={"fields": ",".join(Config.DEFAULT_FIELDS)},
        api_key_override="bridge-token",
    )


async def test_bridge_paper_batch_contract(mock_make_request, bridge_client, auth_headers):
    payload = [{"paperId": "p1"}, {"paperId": "p2"}]
    mock_make_request.install(bridge).queue_responses(payload)

    response = await bridge_client.post("/v1/paper/batch", json={"ids": ["p1", "p2"]}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/batch",
        params={"fields": ",".join(Config.DEFAULT_FIELDS)},
        api_key_override="bridge-token",
        method="POST",
        json={"ids": ["p1", "p2"]},
    )


async def test_bridge_author_search_contract(mock_make_request, bridge_client, auth_headers):
    payload = {"total": 1, "data": [{"authorId": "1741101"}]}
    mock_make_request.install(bridge).queue_responses(payload)

    response = await bridge_client.get("/v1/author/search", params={"q": "Andrew Ng"}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == payload
    assert_single_call(
        mock_make_request,
        endpoint="/author/search",
        params={
            "query": "Andrew Ng",
            "offset": 0,
            "limit": 10,
            "fields": ",".join(AuthorDetailFields.BASIC),
        },
        api_key_override="bridge-token",
    )


async def test_bridge_author_details_contract(mock_make_request, bridge_client, auth_headers):
    payload = {"authorId": "1741101", "name": "Andrew Ng"}
    mock_make_request.install(bridge).queue_responses(payload)

    response = await bridge_client.get("/v1/author/1741101", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == payload
    assert_single_call(
        mock_make_request,
        endpoint="/author/1741101",
        params={"fields": ",".join(AuthorDetailFields.BASIC)},
        api_key_override="bridge-token",
    )


async def test_bridge_author_batch_contract(mock_make_request, bridge_client, auth_headers):
    payload = [{"authorId": "1741101"}, {"authorId": "2061296"}]
    mock_make_request.install(bridge).queue_responses(payload)

    response = await bridge_client.post(
        "/v1/author/batch",
        json={"ids": ["1741101", "2061296"]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == payload
    assert_single_call(
        mock_make_request,
        endpoint="/author/batch",
        params={"fields": ",".join(AuthorDetailFields.BASIC)},
        api_key_override="bridge-token",
        method="POST",
        json={"ids": ["1741101", "2061296"]},
    )


async def test_bridge_recommendations_contract(mock_make_request, bridge_client, auth_headers):
    payload = {"recommendedPapers": [{"paperId": "p9"}]}
    mock_make_request.install(bridge).queue_responses(payload)

    response = await bridge_client.get("/v1/recommendations", params={"paper_id": "paper-123"}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == payload
    assert_single_call(
        mock_make_request,
        endpoint="/papers/forpaper/paper-123",
        params={"fields": ",".join(PaperFields.DEFAULT)},
        api_key_override="bridge-token",
        base_url=Config.RECOMMENDATIONS_BASE_URL,
    )


async def test_bridge_recommendations_requires_paper_id(mock_make_request, bridge_client, auth_headers):
    response = await bridge_client.get("/v1/recommendations", headers=auth_headers)

    assert response.status_code == 400
    assert response.json() == {"detail": "paper_id is required"}
    assert mock_make_request.calls == []


async def test_bridge_error_payload_passthrough(mock_make_request, mock_error_response, bridge_client, auth_headers):
    error = mock_error_response(status_code=404)
    mock_make_request.install(bridge).queue_responses(error)

    response = await bridge_client.get("/v1/paper/search", params={"q": "attention"}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == error
    assert_single_call(
        mock_make_request,
        endpoint="/paper/search",
        params={
            "query": "attention",
            "offset": 0,
            "limit": 10,
            "fields": "title,abstract,year,citationCount,authors,url",
        },
        api_key_override="bridge-token",
    )
