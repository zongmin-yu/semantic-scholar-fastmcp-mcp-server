"""
Author-related API endpoints for the Semantic Scholar API.
"""

from typing import Dict, List, Optional
from fastmcp import Context

# Import mcp from centralized location instead of server
from ..mcp import mcp
from ..config import AuthorDetailFields, ErrorType
from ..utils.http import make_request
from ..utils.errors import create_error_response
from ..utils.logger import logger

@mcp.tool()
async def author_search(
    context: Context,
    query: str,
    fields: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = 100
) -> Dict:
    """
    Search for authors by name on Semantic Scholar.
    This endpoint is optimized for finding authors based on their name.
    Results are sorted by relevance to the query.
    
    Args:
        query (str): The name text to search for. The query will be matched against author names
            and their known aliases.

        fields (Optional[List[str]]): List of fields to return for each author.
            authorId is always returned.

        offset (int): Number of authors to skip for pagination.
            Default: 0

        limit (int): Maximum number of authors to return.
            Default: 100
            Maximum: 1000

    Returns:
        Dict: {
            "total": int,      # Total number of authors matching the query
            "offset": int,     # Current offset in the results
            "next": int,       # Next offset (if more results available)
            "data": List[Dict] # List of authors with requested fields
        }
    """
    if not query.strip():
        return create_error_response(
            ErrorType.VALIDATION,
            "Query string cannot be empty"
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
        "query": query,
        "offset": offset,
        "limit": limit
    }
    if fields:
        params["fields"] = ",".join(fields)

    # Make the API request
    return await make_request("/author/search", params)

@mcp.tool()
async def author_details(
    context: Context,
    author_id: str,
    fields: Optional[List[str]] = None
) -> Dict:
    """
    Get detailed information about an author by their ID.
    This endpoint provides comprehensive metadata about an author.

    Args:
        author_id (str): Semantic Scholar author ID.
            This is a unique identifier assigned by Semantic Scholar.
            Example: "1741101" (Albert Einstein)

        fields (Optional[List[str]]): List of fields to return.
            authorId is always returned.
            Available fields include name, papers, citationCount, etc.

    Returns:
        Dict: Author details with requested fields.
            Always includes authorId.
            Returns error response if author not found.
    """
    if not author_id.strip():
        return create_error_response(
            ErrorType.VALIDATION,
            "Author ID cannot be empty"
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
    params = {}
    if fields:
        params["fields"] = ",".join(fields)

    # Make the API request
    result = await make_request(f"/author/{author_id}", params)
    
    if isinstance(result, Dict) and "error" in result:
        error_msg = result["error"].get("message", "")
        if "404" in error_msg:
            return create_error_response(
                ErrorType.VALIDATION,
                "Author not found",
                {"author_id": author_id}
            )
        return result

    return result

@mcp.tool()
async def author_papers(
    context: Context,
    author_id: str,
    fields: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = 100
) -> Dict:
    """
    Get papers written by an author with pagination support.
    This endpoint provides detailed information about an author's publications.

    Args:
        author_id (str): Semantic Scholar author ID.
            This is a unique identifier assigned by Semantic Scholar.
            Example: "1741101" (Albert Einstein)

        fields (Optional[List[str]]): List of fields to return for each paper.
            paperId is always returned.

        offset (int): Number of papers to skip for pagination.
            Default: 0

        limit (int): Maximum number of papers to return.
            Default: 100
            Maximum: 1000

    Returns:
        Dict: {
            "offset": int,     # Current offset in the results
            "next": int,       # Next offset (if more results available)
            "data": List[Dict] # List of papers with requested fields
        }
    """
    if not author_id.strip():
        return create_error_response(
            ErrorType.VALIDATION,
            "Author ID cannot be empty"
        )

    # Validate limit
    if limit > 1000:
        return create_error_response(
            ErrorType.VALIDATION,
            "Limit cannot exceed 1000",
            {"max_limit": 1000}
        )

    # Build request parameters
    params = {
        "offset": offset,
        "limit": limit
    }
    if fields:
        params["fields"] = ",".join(fields)

    # Make the API request
    result = await make_request(f"/author/{author_id}/papers", params)
    
    if isinstance(result, Dict) and "error" in result:
        error_msg = result["error"].get("message", "")
        if "404" in error_msg:
            return create_error_response(
                ErrorType.VALIDATION,
                "Author not found",
                {"author_id": author_id}
            )
        return result

    return result

@mcp.tool()
async def author_batch_details(
    context: Context,
    author_ids: List[str],
    fields: Optional[str] = None
) -> Dict:
    """
    Get details for multiple authors in a single batch request.
    This endpoint is optimized for efficiently retrieving details about known authors.

    Args:
        author_ids (List[str]): List of Semantic Scholar author IDs.
            These are unique identifiers assigned by Semantic Scholar.
            Example: ["1741101", "1741102"]
            Maximum: 1000 IDs per request

        fields (Optional[str]): Comma-separated list of fields to return for each author.
            authorId is always returned.

    Returns:
        List[Dict]: List of author details with requested fields.
            - Results maintain the same order as input author_ids
            - Invalid or not found author IDs return null in the results
            - Each author object contains the requested fields
            - authorId is always included in each author object
    """
    # Validate inputs
    if not author_ids:
        return create_error_response(
            ErrorType.VALIDATION,
            "Author IDs list cannot be empty"
        )
        
    if len(author_ids) > 1000:
        return create_error_response(
            ErrorType.VALIDATION,
            "Cannot process more than 1000 author IDs at once",
            {"max_authors": 1000, "received": len(author_ids)}
        )

    # Validate fields if provided
    if fields:
        field_list = fields.split(",")
        invalid_fields = set(field_list) - AuthorDetailFields.VALID_FIELDS
        if invalid_fields:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid fields: {', '.join(invalid_fields)}",
                {"valid_fields": list(AuthorDetailFields.VALID_FIELDS)}
            )

    # Build request parameters
    params = {}
    if fields:
        params["fields"] = fields

    return await make_request("/author/batch", params=params, method="POST", json={"ids": author_ids})
