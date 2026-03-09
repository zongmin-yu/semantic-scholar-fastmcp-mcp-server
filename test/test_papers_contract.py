import pytest

import semantic_scholar.api.papers as papers_api


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


def assert_validation_error(result, message, details=None):
    assert result == {
        "error": {
            "type": "validation",
            "message": message,
            "details": details or {},
        }
    }


async def test_paper_relevance_search_happy_path(mock_make_request):
    payload = {"total": 1, "offset": 0, "data": [{"paperId": "p1"}]}
    mock_make_request.install(papers_api).queue_responses(payload)

    result = await papers_api.paper_relevance_search.fn(None, query="attention", limit=5)

    assert result == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/search",
        params={
            "query": "attention",
            "offset": 0,
            "limit": 5,
            "fields": "title,abstract,year,citationCount,authors,url",
        },
    )


async def test_paper_relevance_search_empty_query(mock_make_request):
    result = await papers_api.paper_relevance_search.fn(None, query="   ")

    assert_validation_error(result, "Query string cannot be empty")
    assert mock_make_request.calls == []


async def test_paper_relevance_search_rate_limit_passthrough(mock_make_request, mock_error_response):
    error = mock_error_response(status_code=429)
    mock_make_request.install(papers_api).queue_responses(error)

    result = await papers_api.paper_relevance_search.fn(None, query="attention", limit=5)

    assert result == error
    assert_single_call(
        mock_make_request,
        endpoint="/paper/search",
        params={
            "query": "attention",
            "offset": 0,
            "limit": 5,
            "fields": "title,abstract,year,citationCount,authors,url",
        },
    )


async def test_paper_bulk_search_happy_path(mock_make_request):
    payload = {"total": 1, "token": "next-2", "data": [{"paperId": "p1"}]}
    mock_make_request.install(papers_api).queue_responses(payload)

    result = await papers_api.paper_bulk_search.fn(
        None,
        query=" transformer ",
        token="next-1",
        fields=["paperId", "title"],
        sort="citationCount:desc",
        publication_types=["Conference"],
        open_access_pdf=True,
        min_citation_count=10,
        publication_date_or_year="2020-01-01:2024-12-31",
        venue=["NeurIPS"],
        fields_of_study=["Computer Science"],
    )

    assert result == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/search/bulk",
        params={
            "query": "transformer",
            "token": "next-1",
            "fields": "paperId,title",
            "sort": "citationCount:desc",
            "publicationTypes": "Conference",
            "openAccessPdf": "true",
            "minCitationCount": "10",
            "publicationDateOrYear": "2020-01-01:2024-12-31",
            "venue": "NeurIPS",
            "fieldsOfStudy": "Computer Science",
        },
    )


async def test_paper_bulk_search_invalid_sort_field(mock_make_request):
    result = await papers_api.paper_bulk_search.fn(None, sort="year:desc")

    assert_validation_error(
        result,
        "Invalid sort field. Must be one of: paperId, publicationDate, citationCount",
    )
    assert mock_make_request.calls == []


async def test_paper_bulk_search_rate_limit_passthrough(mock_make_request, mock_error_response):
    error = mock_error_response(status_code=429)
    mock_make_request.install(papers_api).queue_responses(error)

    result = await papers_api.paper_bulk_search.fn(
        None,
        query=" transformer ",
        token="next-1",
        fields=["paperId", "title"],
        sort="citationCount:desc",
        publication_types=["Conference"],
        open_access_pdf=True,
        min_citation_count=10,
        publication_date_or_year="2020-01-01:2024-12-31",
        venue=["NeurIPS"],
        fields_of_study=["Computer Science"],
    )

    assert result == error
    assert_single_call(
        mock_make_request,
        endpoint="/paper/search/bulk",
        params={
            "query": "transformer",
            "token": "next-1",
            "fields": "paperId,title",
            "sort": "citationCount:desc",
            "publicationTypes": "Conference",
            "openAccessPdf": "true",
            "minCitationCount": "10",
            "publicationDateOrYear": "2020-01-01:2024-12-31",
            "venue": "NeurIPS",
            "fieldsOfStudy": "Computer Science",
        },
    )


async def test_paper_title_search_happy_path(mock_make_request):
    payload = {"paperId": "p1", "title": "Attention is All You Need"}
    mock_make_request.install(papers_api).queue_responses(payload)

    result = await papers_api.paper_title_search.fn(None, query="Attention is All You Need")

    assert result == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/search/match",
        params={
            "query": "Attention is All You Need",
            "fields": "title,abstract,year,citationCount,authors,url",
        },
    )


async def test_paper_title_search_empty_query(mock_make_request):
    result = await papers_api.paper_title_search.fn(None, query="   ")

    assert_validation_error(result, "Query string cannot be empty")
    assert mock_make_request.calls == []


async def test_paper_title_search_404_maps_to_no_match(mock_make_request, mock_error_response):
    mock_make_request.install(papers_api).queue_responses(mock_error_response(status_code=404))

    result = await papers_api.paper_title_search.fn(None, query="Attention is All You Need")

    assert_validation_error(
        result,
        "No matching paper found",
        {"original_query": "Attention is All You Need"},
    )
    assert_single_call(
        mock_make_request,
        endpoint="/paper/search/match",
        params={
            "query": "Attention is All You Need",
            "fields": "title,abstract,year,citationCount,authors,url",
        },
    )


async def test_paper_details_happy_path(mock_make_request):
    payload = {"paperId": "CorpusId:215416146", "title": "Attention"}
    mock_make_request.install(papers_api).queue_responses(payload)

    result = await papers_api.paper_details.fn(None, paper_id="CorpusId:215416146", fields=["title", "year"])

    assert result == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/CorpusId:215416146",
        params={"fields": "title,year"},
    )


async def test_paper_details_empty_paper_id(mock_make_request):
    result = await papers_api.paper_details.fn(None, paper_id="   ")

    assert_validation_error(result, "Paper ID cannot be empty")
    assert mock_make_request.calls == []


async def test_paper_details_404_maps_to_paper_not_found(mock_make_request, mock_error_response):
    mock_make_request.install(papers_api).queue_responses(mock_error_response(status_code=404))

    result = await papers_api.paper_details.fn(None, paper_id="CorpusId:215416146", fields=["title", "year"])

    assert_validation_error(result, "Paper not found", {"paper_id": "CorpusId:215416146"})
    assert_single_call(
        mock_make_request,
        endpoint="/paper/CorpusId:215416146",
        params={"fields": "title,year"},
    )


async def test_paper_batch_details_happy_path(mock_make_request):
    payload = [{"paperId": "649def34f8be52c8b66281af98ae884c09aef38b"}, {"paperId": "ARXIV:2106.15928"}]
    mock_make_request.install(papers_api).queue_responses(payload)

    result = await papers_api.paper_batch_details.fn(
        None,
        paper_ids=["649def34f8be52c8b66281af98ae884c09aef38b", "ARXIV:2106.15928"],
        fields="title,year",
    )

    assert result == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/batch",
        params={"fields": "title,year"},
        method="POST",
        json={"ids": ["649def34f8be52c8b66281af98ae884c09aef38b", "ARXIV:2106.15928"]},
    )


async def test_paper_batch_details_empty_ids_validation(mock_make_request):
    result = await papers_api.paper_batch_details.fn(None, paper_ids=[], fields="title,year")

    assert_validation_error(result, "Paper IDs list cannot be empty")
    assert mock_make_request.calls == []


async def test_paper_batch_details_rate_limit_passthrough(mock_make_request, mock_error_response):
    error = mock_error_response(status_code=429)
    mock_make_request.install(papers_api).queue_responses(error)

    result = await papers_api.paper_batch_details.fn(
        None,
        paper_ids=["649def34f8be52c8b66281af98ae884c09aef38b", "ARXIV:2106.15928"],
        fields="title,year",
    )

    assert result == error
    assert_single_call(
        mock_make_request,
        endpoint="/paper/batch",
        params={"fields": "title,year"},
        method="POST",
        json={"ids": ["649def34f8be52c8b66281af98ae884c09aef38b", "ARXIV:2106.15928"]},
    )


async def test_paper_authors_happy_path(mock_make_request):
    payload = {"offset": 5, "next": 30, "data": [{"authorId": "a1"}]}
    mock_make_request.install(papers_api).queue_responses(payload)

    result = await papers_api.paper_authors.fn(
        None,
        paper_id="paper-123",
        fields=["name", "affiliations"],
        offset=5,
        limit=25,
    )

    assert result == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/paper-123/authors",
        params={"offset": 5, "limit": 25, "fields": "name,affiliations"},
    )


async def test_paper_authors_limit_validation(mock_make_request):
    result = await papers_api.paper_authors.fn(None, paper_id="paper-123", limit=1001)

    assert_validation_error(result, "Limit cannot exceed 1000", {"max_limit": 1000})
    assert mock_make_request.calls == []


async def test_paper_authors_404_maps_to_paper_not_found(mock_make_request, mock_error_response):
    mock_make_request.install(papers_api).queue_responses(mock_error_response(status_code=404))

    result = await papers_api.paper_authors.fn(
        None,
        paper_id="paper-123",
        fields=["name", "affiliations"],
        offset=5,
        limit=25,
    )

    assert_validation_error(result, "Paper not found", {"paper_id": "paper-123"})
    assert_single_call(
        mock_make_request,
        endpoint="/paper/paper-123/authors",
        params={"offset": 5, "limit": 25, "fields": "name,affiliations"},
    )


async def test_paper_citations_happy_path(mock_make_request):
    payload = {"offset": 0, "next": 10, "data": [{"paperId": "c1"}]}
    mock_make_request.install(papers_api).queue_responses(payload)

    result = await papers_api.paper_citations.fn(
        None,
        paper_id="paper-123",
        fields=["title", "contexts"],
        offset=0,
        limit=10,
    )

    assert result == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/paper-123/citations",
        params={"offset": 0, "limit": 10, "fields": "title,contexts"},
    )


async def test_paper_citations_invalid_field_validation(mock_make_request):
    result = await papers_api.paper_citations.fn(None, paper_id="paper-123", fields=["badField"])

    assert result["error"]["type"] == "validation"
    assert result["error"]["message"] == "Invalid fields: badField"
    assert mock_make_request.calls == []


async def test_paper_citations_404_maps_to_paper_not_found(mock_make_request, mock_error_response):
    mock_make_request.install(papers_api).queue_responses(mock_error_response(status_code=404))

    result = await papers_api.paper_citations.fn(
        None,
        paper_id="paper-123",
        fields=["title", "contexts"],
        offset=0,
        limit=10,
    )

    assert_validation_error(result, "Paper not found", {"paper_id": "paper-123"})
    assert_single_call(
        mock_make_request,
        endpoint="/paper/paper-123/citations",
        params={"offset": 0, "limit": 10, "fields": "title,contexts"},
    )


async def test_paper_references_happy_path(mock_make_request):
    payload = {"offset": 0, "next": 10, "data": [{"paperId": "r1"}]}
    mock_make_request.install(papers_api).queue_responses(payload)

    result = await papers_api.paper_references.fn(
        None,
        paper_id="paper-123",
        fields=["title", "contexts"],
        offset=0,
        limit=10,
    )

    assert result == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/paper-123/references",
        params={"offset": 0, "limit": 10, "fields": "title,contexts"},
    )


async def test_paper_references_limit_validation(mock_make_request):
    result = await papers_api.paper_references.fn(None, paper_id="paper-123", limit=1001)

    assert_validation_error(result, "Limit cannot exceed 1000", {"max_limit": 1000})
    assert mock_make_request.calls == []


async def test_paper_references_404_maps_to_paper_not_found(mock_make_request, mock_error_response):
    mock_make_request.install(papers_api).queue_responses(mock_error_response(status_code=404))

    result = await papers_api.paper_references.fn(
        None,
        paper_id="paper-123",
        fields=["title", "contexts"],
        offset=0,
        limit=10,
    )

    assert_validation_error(result, "Paper not found", {"paper_id": "paper-123"})
    assert_single_call(
        mock_make_request,
        endpoint="/paper/paper-123/references",
        params={"offset": 0, "limit": 10, "fields": "title,contexts"},
    )


async def test_paper_autocomplete_happy_path(mock_make_request):
    long_query = "a" * 150
    payload = {"matches": [{"paperId": "p1"}]}
    mock_make_request.install(papers_api).queue_responses(payload)

    result = await papers_api.paper_autocomplete.fn(None, query=long_query)

    assert result == payload
    assert_single_call(
        mock_make_request,
        endpoint="/paper/autocomplete",
        params={"query": "a" * 100},
    )


async def test_paper_autocomplete_empty_query_validation(mock_make_request):
    result = await papers_api.paper_autocomplete.fn(None, query="   ")

    assert_validation_error(result, "Query string cannot be empty")
    assert mock_make_request.calls == []


async def test_paper_autocomplete_rate_limit_passthrough(mock_make_request, mock_error_response):
    error = mock_error_response(status_code=429)
    mock_make_request.install(papers_api).queue_responses(error)

    result = await papers_api.paper_autocomplete.fn(None, query="graph neural")

    assert result == error
    assert_single_call(
        mock_make_request,
        endpoint="/paper/autocomplete",
        params={"query": "graph neural"},
    )


async def test_snippet_search_happy_path(mock_make_request):
    payload = {"data": [{"snippet": {"text": "attention is all you need"}}]}
    mock_make_request.install(papers_api).queue_responses(payload)

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

    assert result == payload
    assert_single_call(
        mock_make_request,
        endpoint="/snippet/search",
        params={
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
        },
    )


async def test_snippet_search_author_count_validation(mock_make_request):
    result = await papers_api.snippet_search.fn(
        None,
        query="transformer attention",
        authors=[f"Author {index}" for index in range(11)],
    )

    assert_validation_error(result, "Cannot filter by more than 10 authors", {"max_authors": 10})
    assert mock_make_request.calls == []


async def test_snippet_search_timeout_passthrough(mock_make_request, mock_error_response):
    error = mock_error_response(timeout=True)
    mock_make_request.install(papers_api).queue_responses(error)

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

    assert result == error
    assert_single_call(
        mock_make_request,
        endpoint="/snippet/search",
        params={
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
        },
    )
