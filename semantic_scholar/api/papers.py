"""
Paper-related API endpoints for the Semantic Scholar API.
"""

from typing import Dict, List, Optional
from fastmcp import Context
import httpx

# Import mcp from centralized location instead of server
from ..mcp import mcp
from ..config import PaperFields, CitationReferenceFields, AuthorDetailFields, Config, ErrorType
from ..utils.http import make_request, get_api_key
from ..utils.logger import logger
from ..utils.errors import create_error_response

@mcp.tool()
async def paper_relevance_search(
    context: Context,
    query: str,
    fields: Optional[List[str]] = None,
    publication_types: Optional[List[str]] = None,
    open_access_pdf: bool = False,
    min_citation_count: Optional[int] = None,
    year: Optional[str] = None,
    venue: Optional[List[str]] = None,
    fields_of_study: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = 10
) -> Dict:
    """
    Search for papers on Semantic Scholar using relevance-based ranking.
    This endpoint is optimized for finding the most relevant papers matching a text query.
    Results are sorted by relevance score.

    Args:
        query (str): A text query to search for. The query will be matched against paper titles,
            abstracts, venue names, and author names.

        fields (Optional[List[str]]): List of fields to return for each paper.
            paperId and title are always returned.

        publication_types (Optional[List[str]]): Filter by publication types.

        open_access_pdf (bool): If True, only include papers with a public PDF.
            Default: False

        min_citation_count (Optional[int]): Minimum number of citations required.

        year (Optional[str]): Filter by publication year. Supports several formats:
            - Single year: "2019"
            - Year range: "2016-2020"
            - Since year: "2010-"
            - Until year: "-2015"

        venue (Optional[List[str]]): Filter by publication venues.
            Accepts full venue names or ISO4 abbreviations.

        fields_of_study (Optional[List[str]]): Filter by fields of study.

        offset (int): Number of results to skip for pagination.
            Default: 0

        limit (int): Maximum number of results to return.
            Default: 10
            Maximum: 100

    Returns:
        Dict: {
            "total": int,      # Total number of papers matching the query
            "offset": int,     # Current offset in the results
            "next": int,       # Offset for the next page of results (if available)
            "data": List[Dict] # List of papers with requested fields
        }
    """
    if not query.strip():
        return create_error_response(
            ErrorType.VALIDATION,
            "Query string cannot be empty"
        )

    # Validate and prepare fields
    if fields is None:
        fields = PaperFields.DEFAULT
    else:
        invalid_fields = set(fields) - PaperFields.VALID_FIELDS
        if invalid_fields:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid fields: {', '.join(invalid_fields)}",
                {"valid_fields": list(PaperFields.VALID_FIELDS)}
            )

    # Validate and prepare parameters
    limit = min(limit, 100)
    params = {
        "query": query,
        "offset": offset,
        "limit": limit,
        "fields": ",".join(fields)
    }

    # Add optional filters
    if publication_types:
        params["publicationTypes"] = ",".join(publication_types)
    if open_access_pdf:
        params["openAccessPdf"] = "true"
    if min_citation_count is not None:
        params["minCitationCount"] = min_citation_count
    if year:
        params["year"] = year
    if venue:
        params["venue"] = ",".join(venue)
    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)

    return await make_request("/paper/search", params)

@mcp.tool()
async def paper_bulk_search(
    context: Context,
    query: Optional[str] = None,
    token: Optional[str] = None,
    fields: Optional[List[str]] = None,
    sort: Optional[str] = None,
    publication_types: Optional[List[str]] = None,
    open_access_pdf: bool = False,
    min_citation_count: Optional[int] = None,
    publication_date_or_year: Optional[str] = None,
    year: Optional[str] = None,
    venue: Optional[List[str]] = None,
    fields_of_study: Optional[List[str]] = None
) -> Dict:
    """
    Bulk search for papers with advanced filtering and sorting options.
    Intended for retrieving large sets of papers efficiently.
    
    Args:
        query (Optional[str]): Text query to match against paper title and abstract.
            Supports boolean logic with +, |, -, ", *, (), and ~N.
            
        token (Optional[str]): Continuation token for pagination
        
        fields (Optional[List[str]]): Fields to return for each paper
            paperId is always returned
            Default: paperId and title only
            
        sort (Optional[str]): Sort order in format 'field:order'
            Fields: paperId, publicationDate, citationCount
            Order: asc (default), desc
            Default: 'paperId:asc'
            
        publication_types (Optional[List[str]]): Filter by publication types
            
        open_access_pdf (bool): Only include papers with public PDF
        
        min_citation_count (Optional[int]): Minimum citation threshold
        
        publication_date_or_year (Optional[str]): Date/year range filter
            Format: <startDate>:<endDate> in YYYY-MM-DD
            
        year (Optional[str]): Publication year filter
            Examples: '2019', '2016-2020', '2010-', '-2015'
            
        venue (Optional[List[str]]): Filter by publication venues
            
        fields_of_study (Optional[List[str]]): Filter by fields of study
    
    Returns:
        Dict: {
            'total': int,      # Total matching papers
            'token': str,      # Continuation token for next batch
            'data': List[Dict] # Papers with requested fields
        }
    """
    # Build request parameters
    params = {}
    
    # Add query if provided
    if query:
        params["query"] = query.strip()
        
    # Add continuation token if provided
    if token:
        params["token"] = token
        
    # Add fields if provided
    if fields:
        # Validate fields
        invalid_fields = set(fields) - PaperFields.VALID_FIELDS
        if invalid_fields:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid fields: {', '.join(invalid_fields)}",
                {"valid_fields": list(PaperFields.VALID_FIELDS)}
            )
        params["fields"] = ",".join(fields)
        
    # Add sort if provided
    if sort:
        # Validate sort format
        valid_sort_fields = ["paperId", "publicationDate", "citationCount"]
        valid_sort_orders = ["asc", "desc"]
        
        try:
            field, order = sort.split(":")
            if field not in valid_sort_fields:
                return create_error_response(
                    ErrorType.VALIDATION,
                    f"Invalid sort field. Must be one of: {', '.join(valid_sort_fields)}"
                )
            if order not in valid_sort_orders:
                return create_error_response(
                    ErrorType.VALIDATION,
                    f"Invalid sort order. Must be one of: {', '.join(valid_sort_orders)}"
                )
            params["sort"] = sort
        except ValueError:
            return create_error_response(
                ErrorType.VALIDATION,
                "Sort must be in format 'field:order'"
            )
            
    # Add publication types if provided
    if publication_types:
        valid_types = {
            "Review", "JournalArticle", "CaseReport", "ClinicalTrial",
            "Conference", "Dataset", "Editorial", "LettersAndComments",
            "MetaAnalysis", "News", "Study", "Book", "BookSection"
        }
        invalid_types = set(publication_types) - valid_types
        if invalid_types:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid publication types: {', '.join(invalid_types)}",
                {"valid_types": list(valid_types)}
            )
        params["publicationTypes"] = ",".join(publication_types)
        
    # Add open access PDF filter
    if open_access_pdf:
        params["openAccessPdf"] = "true"
        
    # Add minimum citation count if provided
    if min_citation_count is not None:
        if min_citation_count < 0:
            return create_error_response(
                ErrorType.VALIDATION,
                "Minimum citation count cannot be negative"
            )
        params["minCitationCount"] = str(min_citation_count)
        
    # Add publication date/year if provided
    if publication_date_or_year:
        params["publicationDateOrYear"] = publication_date_or_year
    elif year:
        params["year"] = year
        
    # Add venue filter if provided
    if venue:
        params["venue"] = ",".join(venue)
        
    # Add fields of study filter if provided
    if fields_of_study:
        valid_fields = {
            "Computer Science", "Medicine", "Chemistry", "Biology",
            "Materials Science", "Physics", "Geology", "Psychology",
            "Art", "History", "Geography", "Sociology", "Business",
            "Political Science", "Economics", "Philosophy", "Mathematics",
            "Engineering", "Environmental Science", "Agricultural and Food Sciences",
            "Education", "Law", "Linguistics"
        }
        invalid_fields = set(fields_of_study) - valid_fields
        if invalid_fields:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid fields of study: {', '.join(invalid_fields)}",
                {"valid_fields": list(valid_fields)}
            )
        params["fieldsOfStudy"] = ",".join(fields_of_study)
    
    # Make the API request
    result = await make_request("/paper/search/bulk", params)
    
    # Handle potential errors
    if isinstance(result, Dict) and "error" in result:
        return result
        
    return result

@mcp.tool()
async def paper_title_search(
    context: Context,
    query: str,
    fields: Optional[List[str]] = None,
    publication_types: Optional[List[str]] = None,
    open_access_pdf: bool = False,
    min_citation_count: Optional[int] = None,
    year: Optional[str] = None,
    venue: Optional[List[str]] = None,
    fields_of_study: Optional[List[str]] = None
) -> Dict:
    """
    Find a single paper by title match. This endpoint is optimized for finding a specific paper
    by its title and returns the best matching paper based on title similarity.

    Args:
        query (str): The title text to search for. The query will be matched against paper titles
            to find the closest match.

        fields (Optional[List[str]]): List of fields to return for the paper.
            paperId and title are always returned.

        publication_types (Optional[List[str]]): Filter by publication types.

        open_access_pdf (bool): If True, only include papers with a public PDF.
            Default: False

        min_citation_count (Optional[int]): Minimum number of citations required.

        year (Optional[str]): Filter by publication year. Supports several formats:
            - Single year: "2019"
            - Year range: "2016-2020"
            - Since year: "2010-"
            - Until year: "-2015"

        venue (Optional[List[str]]): Filter by publication venues.
            Accepts full venue names or ISO4 abbreviations.

        fields_of_study (Optional[List[str]]): Filter by fields of study.

    Returns:
        Dict: {
            "paperId": str,      # Semantic Scholar Paper ID
            "title": str,        # Paper title
            "matchScore": float, # Similarity score between query and matched title
            ...                  # Additional requested fields
        }
        
        Returns error response if no matching paper is found.
    """
    if not query.strip():
        return create_error_response(
            ErrorType.VALIDATION,
            "Query string cannot be empty"
        )

    # Validate and prepare fields
    if fields is None:
        fields = PaperFields.DEFAULT
    else:
        invalid_fields = set(fields) - PaperFields.VALID_FIELDS
        if invalid_fields:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid fields: {', '.join(invalid_fields)}",
                {"valid_fields": list(PaperFields.VALID_FIELDS)}
            )

    # Build base parameters
    params = {"query": query}

    # Add optional parameters
    if fields:
        params["fields"] = ",".join(fields)
    if publication_types:
        params["publicationTypes"] = ",".join(publication_types)
    if open_access_pdf:
        params["openAccessPdf"] = "true"
    if min_citation_count is not None:
        params["minCitationCount"] = str(min_citation_count)
    if year:
        params["year"] = year
    if venue:
        params["venue"] = ",".join(venue)
    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)

    result = await make_request("/paper/search/match", params)
    
    # Handle specific error cases
    if isinstance(result, Dict):
        if "error" in result:
            error_msg = result["error"].get("message", "")
            if "404" in error_msg:
                return create_error_response(
                    ErrorType.VALIDATION,
                    "No matching paper found",
                    {"original_query": query}
                )
            return result
    
    return result

@mcp.tool()
async def paper_details(
    context: Context,
    paper_id: str,
    fields: Optional[List[str]] = None
) -> Dict:
    """
    Get details about a paper using various types of identifiers.
    This endpoint provides comprehensive metadata about a paper.

    Args:
        paper_id (str): Paper identifier in one of the following formats:
            - Semantic Scholar ID (e.g., "649def34f8be52c8b66281af98ae884c09aef38b")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")
        
        fields (Optional[List[str]]): List of fields to return.
            paperId is always returned.

    Returns:
        Dict: Paper details with requested fields.
            Always includes paperId.
            Returns error response if paper not found.
    """
    if not paper_id.strip():
        return create_error_response(
            ErrorType.VALIDATION,
            "Paper ID cannot be empty"
        )

    # Build request parameters
    params = {}
    if fields:
        params["fields"] = ",".join(fields)

    # Make the API request
    result = await make_request(f"/paper/{paper_id}", params)
    
    # Handle potential errors
    if isinstance(result, Dict) and "error" in result:
        error_msg = result["error"].get("message", "")
        if "404" in error_msg:
            return create_error_response(
                ErrorType.VALIDATION,
                "Paper not found",
                {"paper_id": paper_id}
            )
        return result

    return result

@mcp.tool()
async def paper_batch_details(
    context: Context,
    paper_ids: List[str],
    fields: Optional[str] = None
) -> Dict:
    """
    Get details for multiple papers in a single batch request.
    This endpoint is optimized for efficiently retrieving details about known papers.
    
    Args:
        paper_ids (List[str]): List of paper identifiers. Each ID can be in any of these formats:
            - Semantic Scholar ID (e.g., "649def34f8be52c8b66281af98ae884c09aef38b")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")
            Maximum: 500 IDs per request

        fields (Optional[str]): Comma-separated list of fields to return for each paper.
            paperId is always returned.
    
    Returns:
        List[Dict]: List of paper details with requested fields.
            - Results maintain the same order as input paper_ids
            - Invalid or not found paper IDs return null in the results
            - Each paper object contains the requested fields
            - paperId is always included in each paper object
    """
    # Validate inputs
    if not paper_ids:
        return create_error_response(
            ErrorType.VALIDATION,
            "Paper IDs list cannot be empty"
        )
        
    if len(paper_ids) > 500:
        return create_error_response(
            ErrorType.VALIDATION,
            "Cannot process more than 500 paper IDs at once",
            {"max_papers": 500, "received": len(paper_ids)}
        )

    # Validate fields if provided
    if fields:
        field_list = fields.split(",")
        invalid_fields = set(field_list) - PaperFields.VALID_FIELDS
        if invalid_fields:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid fields: {', '.join(invalid_fields)}",
                {"valid_fields": list(PaperFields.VALID_FIELDS)}
            )

    # Build request parameters
    params = {}
    if fields:
        params["fields"] = fields

    # Make POST request with proper structure
    try:
        async with httpx.AsyncClient(timeout=Config.TIMEOUT) as client:
            api_key = get_api_key()
            headers = {"x-api-key": api_key} if api_key else {}

            url = f"{Config.BASE_URL}/paper/batch"
            logger.debug(
                "Semantic Scholar request: method=%s url=%s params=%s headers=%s",
                "POST",
                url,
                params,
                headers
            )
            logger.debug("Semantic Scholar request body: %s", {"ids": paper_ids})
            response = await client.post(
                url,
                params=params,
                json={"ids": paper_ids},
                headers=headers
            )
            response.raise_for_status()
            return response.json()
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return create_error_response(
                ErrorType.RATE_LIMIT,
                "Rate limit exceeded",
                {"retry_after": e.response.headers.get("retry-after")}
            )
        return create_error_response(
            ErrorType.API_ERROR,
            f"HTTP error: {e.response.status_code}",
            {"response": e.response.text}
        )
    except httpx.TimeoutException:
        return create_error_response(
            ErrorType.TIMEOUT,
            f"Request timed out after {Config.TIMEOUT} seconds"
        )
    except Exception as e:
        return create_error_response(
            ErrorType.API_ERROR,
            str(e)
        )

@mcp.tool()
async def paper_authors(
    context: Context,
    paper_id: str,
    fields: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = 100
) -> Dict:
    """
    Get details about the authors of a paper with pagination support.
    This endpoint provides author information and their contributions.

    Args:
        paper_id (str): Paper identifier in one of the following formats:
            - Semantic Scholar ID (e.g., "649def34f8be52c8b66281af98ae884c09aef38b")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")

        fields (Optional[List[str]]): List of fields to return for each author.
            authorId is always returned.

        offset (int): Number of authors to skip for pagination.
            Default: 0

        limit (int): Maximum number of authors to return.
            Default: 100
            Maximum: 1000

    Returns:
        Dict: {
            "offset": int,     # Current offset in the results
            "next": int,       # Next offset (if more results available)
            "data": List[Dict] # List of authors with requested fields
        }
    """
    if not paper_id.strip():
        return create_error_response(
            ErrorType.VALIDATION,
            "Paper ID cannot be empty"
        )

    # Validate limit
    if limit > 1000:
        return create_error_response(
            ErrorType.VALIDATION,
            "Limit cannot exceed 1000",
            {"max_limit": 1000}
        )
    
    # Validate fields
    if fields:
        invalid_fields = set(fields) - AuthorDetailFields.VALID_FIELDS
        if invalid_fields:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid fields: {', '.join(invalid_fields)}",
                {"valid_fields": list(AuthorDetailFields.VALID_FIELDS)}
            )

    # Build request parameters
    params = {
        "offset": offset,
        "limit": limit
    }
    if fields:
        params["fields"] = ",".join(fields)

    # Make the API request
    result = await make_request(f"/paper/{paper_id}/authors", params)
    
    # Handle potential errors
    if isinstance(result, Dict) and "error" in result:
        error_msg = result["error"].get("message", "")
        if "404" in error_msg:
            return create_error_response(
                ErrorType.VALIDATION,
                "Paper not found",
                {"paper_id": paper_id}
            )
        return result

    return result

@mcp.tool()
async def paper_citations(
    context: Context,
    paper_id: str,
    fields: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = 100
) -> Dict:
    """
    Get papers that cite the specified paper (papers where this paper appears in their bibliography).
    This endpoint provides detailed citation information including citation contexts.

    Args:
        paper_id (str): Paper identifier in one of the following formats:
            - Semantic Scholar ID (e.g., "649def34f8be52c8b66281af98ae884c09aef38b")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")

        fields (Optional[List[str]]): List of fields to return for each citing paper.
            paperId is always returned.

        offset (int): Number of citations to skip for pagination.
            Default: 0

        limit (int): Maximum number of citations to return.
            Default: 100
            Maximum: 1000

    Returns:
        Dict: {
            "offset": int,     # Current offset in the results
            "next": int,       # Next offset (if more results available)
            "data": List[Dict] # List of citing papers with requested fields
        }
    """
    if not paper_id.strip():
        return create_error_response(
            ErrorType.VALIDATION,
            "Paper ID cannot be empty"
        )

    # Validate limit
    if limit > 1000:
        return create_error_response(
            ErrorType.VALIDATION,
            "Limit cannot exceed 1000",
            {"max_limit": 1000}
        )

    # Validate fields
    if fields:
        invalid_fields = set(fields) - CitationReferenceFields.VALID_FIELDS
        if invalid_fields:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid fields: {', '.join(invalid_fields)}",
                {"valid_fields": list(CitationReferenceFields.VALID_FIELDS)}
            )

    # Build request parameters
    params = {
        "offset": offset,
        "limit": limit
    }
    if fields:
        params["fields"] = ",".join(fields)

    # Make the API request
    result = await make_request(f"/paper/{paper_id}/citations", params)
    
    # Handle potential errors
    if isinstance(result, Dict) and "error" in result:
        error_msg = result["error"].get("message", "")
        if "404" in error_msg:
            return create_error_response(
                ErrorType.VALIDATION,
                "Paper not found",
                {"paper_id": paper_id}
            )
        return result

    return result

@mcp.tool()
async def paper_references(
    context: Context,
    paper_id: str,
    fields: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = 100
) -> Dict:
    """
    Get papers cited by the specified paper (papers appearing in this paper's bibliography).
    This endpoint provides detailed reference information including citation contexts.

    Args:
        paper_id (str): Paper identifier in one of the following formats:
            - Semantic Scholar ID (e.g., "649def34f8be52c8b66281af98ae884c09aef38b")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")

        fields (Optional[List[str]]): List of fields to return for each referenced paper.
            paperId is always returned.

        offset (int): Number of references to skip for pagination.
            Default: 0

        limit (int): Maximum number of references to return.
            Default: 100
            Maximum: 1000

    Returns:
        Dict: {
            "offset": int,     # Current offset in the results
            "next": int,       # Next offset (if more results available)
            "data": List[Dict] # List of referenced papers with requested fields
        }
    """
    if not paper_id.strip():
        return create_error_response(
            ErrorType.VALIDATION,
            "Paper ID cannot be empty"
        )

    # Validate limit
    if limit > 1000:
        return create_error_response(
            ErrorType.VALIDATION,
            "Limit cannot exceed 1000",
            {"max_limit": 1000}
        )

    # Validate fields
    if fields:
        invalid_fields = set(fields) - CitationReferenceFields.VALID_FIELDS
        if invalid_fields:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid fields: {', '.join(invalid_fields)}",
                {"valid_fields": list(CitationReferenceFields.VALID_FIELDS)}
            )

    # Build request parameters
    params = {
        "offset": offset,
        "limit": limit
    }
    if fields:
        params["fields"] = ",".join(fields)

    # Make the API request
    result = await make_request(f"/paper/{paper_id}/references", params)
    
    # Handle potential errors
    if isinstance(result, Dict) and "error" in result:
        error_msg = result["error"].get("message", "")
        if "404" in error_msg:
            return create_error_response(
                ErrorType.VALIDATION,
                "Paper not found",
                {"paper_id": paper_id}
            )
        return result

    return result 
