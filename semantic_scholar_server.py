#!/usr/bin/env python3
from fastmcp import FastMCP, Context
import httpx
import logging
import os
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from enum import Enum
import asyncio
import time
import signal
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global HTTP client for connection pooling
http_client = None
# Event to keep process alive when FastMCP detaches
stop_event = None

# Rate Limiting Configuration
@dataclass
class RateLimitConfig:
    # Define rate limits (requests, seconds)
    SEARCH_LIMIT = (1, 1)  # 1 request per 1 second
    BATCH_LIMIT = (1, 1)   # 1 request per 1 second
    DEFAULT_LIMIT = (10, 1)  # 10 requests per 1 second
    
    # Endpoints categorization
    # These endpoints have stricter rate limits due to their computational intensity
    # and to prevent abuse of the recommendation system
    RESTRICTED_ENDPOINTS = [
        "/paper/batch",     # Batch operations are expensive
        "/paper/search",    # Search operations are computationally intensive
        "/recommendations"  # Recommendation generation is resource-intensive
    ]

# Error Types
class ErrorType(Enum):
    RATE_LIMIT = "rate_limit"
    API_ERROR = "api_error"
    VALIDATION = "validation"
    TIMEOUT = "timeout"

# Field Constants
class PaperFields:
    DEFAULT = ["title", "abstract", "year", "citationCount", "authors", "url"]
    DETAILED = DEFAULT + ["references", "citations", "venue", "influentialCitationCount"]
    MINIMAL = ["title", "year", "authors"]
    SEARCH = ["paperId", "title", "year", "citationCount"]
    
    # Valid fields from API documentation
    VALID_FIELDS = {
        "abstract",
        "authors",
        "citationCount",
        "citations",
        "corpusId",
        "embedding",
        "externalIds",
        "fieldsOfStudy",
        "influentialCitationCount",
        "isOpenAccess",
        "openAccessPdf",
        "paperId",
        "publicationDate",
        "publicationTypes",
        "publicationVenue",
        "references",
        "s2FieldsOfStudy",
        "title",
        "tldr",
        "url",
        "venue",
        "year"
    }

class AuthorDetailFields:
    """Common field combinations for author details"""
    
    # Basic author information
    BASIC = ["name", "url", "affiliations"]
    
    # Author's papers information
    PAPERS_BASIC = ["papers"]  # Returns paperId and title
    PAPERS_DETAILED = [
        "papers.year",
        "papers.authors",
        "papers.abstract",
        "papers.venue",
        "papers.url"
    ]
    
    # Complete author profile
    COMPLETE = BASIC + ["papers", "papers.year", "papers.authors", "papers.venue"]
    
    # Citation metrics
    METRICS = ["citationCount", "hIndex", "paperCount"]

    # Valid fields for author details
    VALID_FIELDS = {
        "authorId",
        "name",
        "url",
        "affiliations",
        "papers",
        "papers.year",
        "papers.authors",
        "papers.abstract",
        "papers.venue",
        "papers.url",
        "citationCount",
        "hIndex",
        "paperCount"
    }

class PaperDetailFields:
    """Common field combinations for paper details"""
    
    # Basic paper information
    BASIC = ["title", "abstract", "year", "venue"]
    
    # Author information
    AUTHOR_BASIC = ["authors"]
    AUTHOR_DETAILED = ["authors.url", "authors.paperCount", "authors.citationCount"]
    
    # Citation information
    CITATION_BASIC = ["citations", "references"]
    CITATION_DETAILED = ["citations.title", "citations.abstract", "citations.year",
                        "references.title", "references.abstract", "references.year"]
    
    # Full paper details
    COMPLETE = BASIC + AUTHOR_BASIC + CITATION_BASIC + ["url", "fieldsOfStudy", 
                                                       "publicationVenue", "publicationTypes"]

class CitationReferenceFields:
    """Common field combinations for citation and reference queries"""
    
    # Basic information
    BASIC = ["title"]
    
    # Citation/Reference context
    CONTEXT = ["contexts", "intents", "isInfluential"]
    
    # Paper details
    DETAILED = ["title", "abstract", "authors", "year", "venue"]
    
    # Full information
    COMPLETE = CONTEXT + DETAILED

    # Valid fields for citation/reference queries
    VALID_FIELDS = {
        "contexts",
        "intents",
        "isInfluential",
        "title",
        "abstract",
        "authors",
        "year",
        "venue",
        "paperId",
        "url",
        "citationCount",
        "influentialCitationCount"
    }

# Configuration
class Config:
    # API Configuration
    API_VERSION = "v1"
    BASE_URL = f"https://api.semanticscholar.org/graph/{API_VERSION}"
    TIMEOUT = int(os.getenv("SEMANTIC_SCHOLAR_TIMEOUT", "30"))  # seconds
    
    # Request Limits
    MAX_BATCH_SIZE = 100
    MAX_RESULTS_PER_PAGE = 100
    DEFAULT_PAGE_SIZE = 10
    MAX_BATCHES = 5
    
    # Fields Configuration
    DEFAULT_FIELDS = PaperFields.DEFAULT
    
    # Feature Flags
    ENABLE_CACHING = False
    DEBUG_MODE = False
    
    # Search Configuration
    SEARCH_TYPES = {
        "comprehensive": {
            "description": "Balanced search considering relevance and impact",
            "min_citations": None,
            "ranking_strategy": "balanced"
        },
        "influential": {
            "description": "Focus on highly-cited and influential papers",
            "min_citations": 50,
            "ranking_strategy": "citations"
        },
        "latest": {
            "description": "Focus on recent papers with impact",
            "min_citations": None,
            "ranking_strategy": "recency"
        }
    }

# Rate Limiter
class RateLimiter:
    def __init__(self):
        self._last_call_time = {}
        self._locks = {}

    def _get_rate_limit(self, endpoint: str) -> Tuple[int, int]:
        if any(restricted in endpoint for restricted in RateLimitConfig.RESTRICTED_ENDPOINTS):
            return RateLimitConfig.SEARCH_LIMIT
        return RateLimitConfig.DEFAULT_LIMIT

    async def acquire(self, endpoint: str):
        if endpoint not in self._locks:
            self._locks[endpoint] = asyncio.Lock()
            self._last_call_time[endpoint] = 0

        async with self._locks[endpoint]:
            rate_limit = self._get_rate_limit(endpoint)
            current_time = time.time()
            time_since_last_call = current_time - self._last_call_time[endpoint]
            
            if time_since_last_call < rate_limit[1]:
                delay = rate_limit[1] - time_since_last_call
                await asyncio.sleep(delay)
            
            self._last_call_time[endpoint] = time.time()

def create_error_response(
    error_type: ErrorType,
    message: str,
    details: Optional[Dict] = None
) -> Dict:
    return {
        "error": {
            "type": error_type.value,
            "message": message,
            "details": details or {}
        }
    }

mcp = FastMCP("Semantic Scholar Server")
rate_limiter = RateLimiter()


# Basic functions

def get_api_key() -> Optional[str]:
    """
    Get the Semantic Scholar API key from environment variables.
    Returns None if no API key is set, enabling unauthenticated access.
    """
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    if not api_key:
        logger.warning("No SEMANTIC_SCHOLAR_API_KEY set. Using unauthenticated access with lower rate limits.")
    return api_key

async def handle_exception(loop, context):
    """Global exception handler for the event loop."""
    msg = context.get("exception", context["message"])
    logger.error(f"Caught exception: {msg}")
    asyncio.create_task(shutdown())

async def initialize_client():
    """Initialize the global HTTP client."""
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(
            timeout=Config.TIMEOUT,
            limits=httpx.Limits(max_keepalive_connections=10)
        )
    return http_client

async def cleanup_client():
    """Cleanup the global HTTP client."""
    global http_client
    if http_client is not None:
        await http_client.aclose()
        http_client = None

async def make_request(endpoint: str, params: Dict = None) -> Dict:
    """Make a rate-limited request to the Semantic Scholar API."""
    try:
        # Apply rate limiting
        await rate_limiter.acquire(endpoint)

        # Get API key if available
        api_key = get_api_key()
        headers = {"x-api-key": api_key} if api_key else {}
        url = f"{Config.BASE_URL}{endpoint}"

        # Use global client
        client = await initialize_client()
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error {e.response.status_code} for {endpoint}: {e.response.text}")
        if e.response.status_code == 429:
            return create_error_response(
                ErrorType.RATE_LIMIT,
                "Rate limit exceeded. Consider using an API key for higher limits.",
                {
                    "retry_after": e.response.headers.get("retry-after"),
                    "authenticated": bool(get_api_key())
                }
            )
        return create_error_response(
            ErrorType.API_ERROR,
            f"HTTP error: {e.response.status_code}",
            {"response": e.response.text}
        )
    except httpx.TimeoutException as e:
        logger.error(f"Request timeout for {endpoint}: {str(e)}")
        return create_error_response(
            ErrorType.TIMEOUT,
            f"Request timed out after {Config.TIMEOUT} seconds"
        )
    except Exception as e:
        logger.error(f"Unexpected error for {endpoint}: {str(e)}")
        return create_error_response(
            ErrorType.API_ERROR,
            str(e)
        )




# 1. Paper Data Tools

# 1.1 Paper relevance search
@mcp.tool()
async def paper_relevance_search(
    context: Context,
    query: str,
    fields: Optional[List[str]] = None,
    publication_types: Optional[List[str]] = None,
    open_access_pdf: bool = False,
    min_citation_count: Optional[int] = None,
    year: Optional[str] = None,  # supports formats like "2019", "2016-2020", "2010-", "-2015"
    venue: Optional[List[str]] = None,
    fields_of_study: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = Config.DEFAULT_PAGE_SIZE
) -> Dict:
    """
    Search for papers on Semantic Scholar using relevance-based ranking.
    This endpoint is optimized for finding the most relevant papers matching a text query.
    Results are sorted by relevance score.

    Args:
        query (str): A text query to search for. The query will be matched against paper titles,
            abstracts, venue names, and author names. All terms in the query must be present
            in the paper for it to be returned. The query is case-insensitive and matches word
            prefixes (e.g. "quantum" matches "quantum" and "quantumly").

        fields (Optional[List[str]]): List of fields to return for each paper.
            paperId and title are always returned.
            Available fields:
            - abstract: The paper's abstract
            - authors: List of authors with name and authorId
            - citationCount: Total number of citations
            - citations: List of papers citing this paper
            - corpusId: Internal ID for the paper
            - embedding: Vector embedding of the paper
            - externalIds: External IDs (DOI, MAG, etc)
            - fieldsOfStudy: List of fields of study
            - influentialCitationCount: Number of influential citations
            - isOpenAccess: Whether paper is open access
            - openAccessPdf: Open access PDF URL if available
            - paperId: Semantic Scholar paper ID
            - publicationDate: Publication date in YYYY-MM-DD format
            - publicationTypes: List of publication types
            - publicationVenue: Venue information
            - references: List of papers cited by this paper
            - s2FieldsOfStudy: Semantic Scholar fields
            - title: Paper title
            - tldr: AI-generated TLDR summary
            - url: URL to Semantic Scholar paper page
            - venue: Publication venue name
            - year: Publication year

        publication_types (Optional[List[str]]): Filter by publication types.
            Available types:
            - Review
            - JournalArticle
            - CaseReport
            - ClinicalTrial
            - Conference
            - Dataset
            - Editorial
            - LettersAndComments
            - MetaAnalysis
            - News
            - Study
            - Book
            - BookSection

        open_access_pdf (bool): If True, only include papers with a public PDF.
            Default: False

        min_citation_count (Optional[int]): Minimum number of citations required.
            Papers with fewer citations will be filtered out.

        year (Optional[str]): Filter by publication year. Supports several formats:
            - Single year: "2019"
            - Year range: "2016-2020"
            - Since year: "2010-"
            - Until year: "-2015"

        venue (Optional[List[str]]): Filter by publication venues.
            Accepts full venue names or ISO4 abbreviations.
            Examples: ["Nature", "Science", "N. Engl. J. Med."]

        fields_of_study (Optional[List[str]]): Filter by fields of study.
            Available fields:
            - Computer Science
            - Medicine
            - Chemistry
            - Biology
            - Materials Science
            - Physics
            - Geology
            - Psychology
            - Art
            - History
            - Geography
            - Sociology
            - Business
            - Political Science
            - Economics
            - Philosophy
            - Mathematics
            - Engineering
            - Environmental Science
            - Agricultural and Food Sciences
            - Education
            - Law
            - Linguistics

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

    Notes:
        - Results are sorted by relevance to the query
        - All query terms must be present in the paper (AND operation)
        - Query matches are case-insensitive
        - Query matches word prefixes (e.g., "quantum" matches "quantum" and "quantumly")
        - Maximum of 100 results per request
        - Use offset parameter for pagination
        - Rate limits apply (see API documentation)
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
    limit = min(limit, Config.MAX_RESULTS_PER_PAGE)
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

# 1.2 Paper bulk search
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
            Supports boolean logic:
            - '+' for AND operation
            - '|' for OR operation
            - '-' to negate a term
            - '"' for phrase matching
            - '*' for prefix matching
            - '()' for precedence
            - '~N' for edit distance (default 2)
            Examples:
            - 'fish ladder' (contains both terms)
            - 'fish -ladder' (has fish, no ladder)
            - 'fish | ladder' (either term)
            - '"fish ladder"' (exact phrase)
            - '(fish ladder) | outflow'
            - 'fish~' (fuzzy match)
            - '"fish ladder"~3' (terms within 3 words)
            
        token (Optional[str]): Continuation token for pagination
        
        fields (Optional[List[str]]): Fields to return for each paper
            paperId is always returned
            Default: paperId and title only
            
        sort (Optional[str]): Sort order in format 'field:order'
            Fields: paperId, publicationDate, citationCount
            Order: asc (default), desc
            Default: 'paperId:asc'
            Examples:
            - 'publicationDate:asc' (oldest first)
            - 'citationCount:desc' (most cited first)
            
        publication_types (Optional[List[str]]): Filter by publication types:
            Review, JournalArticle, CaseReport, ClinicalTrial,
            Conference, Dataset, Editorial, LettersAndComments,
            MetaAnalysis, News, Study, Book, BookSection
            
        open_access_pdf (bool): Only include papers with public PDF
        
        min_citation_count (Optional[int]): Minimum citation threshold
        
        publication_date_or_year (Optional[str]): Date/year range filter
            Format: <startDate>:<endDate> in YYYY-MM-DD
            Supports partial dates and open ranges
            Examples:
            - '2019-03-05' (specific date)
            - '2019-03' (month)
            - '2019' (year)
            - '2016-03-05:2020-06-06' (range)
            - '1981-08-25:' (since date)
            - ':2015-01' (until date)
            
        year (Optional[str]): Publication year filter
            Examples: '2019', '2016-2020', '2010-', '-2015'
            
        venue (Optional[List[str]]): Filter by publication venues
            Accepts full names or ISO4 abbreviations
            Examples: ['Nature', 'N. Engl. J. Med.']
            
        fields_of_study (Optional[List[str]]): Filter by fields of study
            Available fields include: Computer Science, Medicine,
            Physics, Mathematics, etc.
    
    Returns:
        Dict: {
            'total': int,      # Total matching papers
            'token': str,      # Continuation token for next batch
            'data': List[Dict] # Papers with requested fields
        }
        
    Notes:
        - Returns up to 1,000 papers per call
        - Can fetch up to 10M papers total
        - Nested data (citations, references) not available
        - For larger datasets, use the Datasets API
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

# 1.3 Paper title search
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
            to find the closest match. The match is case-insensitive and ignores punctuation.

        fields (Optional[List[str]]): List of fields to return for the paper.
            paperId and title are always returned.
            Available fields:
            - abstract: The paper's abstract
            - authors: List of authors with name and authorId
            - citationCount: Total number of citations
            - citations: List of papers citing this paper
            - corpusId: Internal ID for the paper
            - embedding: Vector embedding of the paper
            - externalIds: External IDs (DOI, MAG, etc)
            - fieldsOfStudy: List of fields of study
            - influentialCitationCount: Number of influential citations
            - isOpenAccess: Whether paper is open access
            - openAccessPdf: Open access PDF URL if available
            - paperId: Semantic Scholar paper ID
            - publicationDate: Publication date in YYYY-MM-DD format
            - publicationTypes: List of publication types
            - publicationVenue: Venue information
            - references: List of papers cited by this paper
            - s2FieldsOfStudy: Semantic Scholar fields
            - title: Paper title
            - tldr: AI-generated TLDR summary
            - url: URL to Semantic Scholar paper page
            - venue: Publication venue name
            - year: Publication year

        publication_types (Optional[List[str]]): Filter by publication types.
            Available types:
            - Review
            - JournalArticle
            - CaseReport
            - ClinicalTrial
            - Conference
            - Dataset
            - Editorial
            - LettersAndComments
            - MetaAnalysis
            - News
            - Study
            - Book
            - BookSection

        open_access_pdf (bool): If True, only include papers with a public PDF.
            Default: False

        min_citation_count (Optional[int]): Minimum number of citations required.
            Papers with fewer citations will be filtered out.

        year (Optional[str]): Filter by publication year. Supports several formats:
            - Single year: "2019"
            - Year range: "2016-2020"
            - Since year: "2010-"
            - Until year: "-2015"

        venue (Optional[List[str]]): Filter by publication venues.
            Accepts full venue names or ISO4 abbreviations.
            Examples: ["Nature", "Science", "N. Engl. J. Med."]

        fields_of_study (Optional[List[str]]): Filter by fields of study.
            Available fields:
            - Computer Science
            - Medicine
            - Chemistry
            - Biology
            - Materials Science
            - Physics
            - Geology
            - Psychology
            - Art
            - History
            - Geography
            - Sociology
            - Business
            - Political Science
            - Economics
            - Philosophy
            - Mathematics
            - Engineering
            - Environmental Science
            - Agricultural and Food Sciences
            - Education
            - Law
            - Linguistics

    Returns:
        Dict: {
            "paperId": str,      # Semantic Scholar Paper ID
            "title": str,        # Paper title
            "matchScore": float, # Similarity score between query and matched title
            ...                  # Additional requested fields
        }
        
        Returns error response if no matching paper is found.

    Notes:
        - Returns the single best matching paper based on title similarity
        - Match score indicates how well the title matches the query
        - Case-insensitive matching
        - Ignores punctuation in matching
        - Filters are applied after finding the best title match
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

# 1.4 Details about a paper
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
            - CorpusId:<id> (e.g., "CorpusId:215416146")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")
              Supported URLs from: semanticscholar.org, arxiv.org, aclweb.org,
                                 acm.org, biorxiv.org
        
        fields (Optional[List[str]]): List of fields to return.
            paperId is always returned.
            Available fields:
            - abstract: The paper's abstract
            - authors: List of authors with name and authorId
            - citationCount: Total number of citations
            - citations: List of papers citing this paper
            - corpusId: Internal ID for the paper
            - embedding: Vector embedding of the paper
            - externalIds: External IDs (DOI, MAG, etc)
            - fieldsOfStudy: List of fields of study
            - influentialCitationCount: Number of influential citations
            - isOpenAccess: Whether paper is open access
            - openAccessPdf: Open access PDF URL if available
            - paperId: Semantic Scholar paper ID
            - publicationDate: Publication date in YYYY-MM-DD format
            - publicationTypes: List of publication types
            - publicationVenue: Venue information
            - references: List of papers cited by this paper
            - s2FieldsOfStudy: Semantic Scholar fields
            - title: Paper title
            - tldr: AI-generated TLDR summary
            - url: URL to Semantic Scholar paper page
            - venue: Publication venue name
            - year: Publication year

            Special syntax for nested fields:
            - For citations/references: citations.title, references.abstract, etc.
            - For authors: authors.name, authors.affiliations, etc.
            - For embeddings: embedding.specter_v2 for v2 embeddings

            If omitted, returns only paperId and title.

    Returns:
        Dict: Paper details with requested fields.
            Always includes paperId.
            Returns error response if paper not found.

    Notes:
        - Supports multiple identifier types for flexibility
        - Nested fields available for detailed citation/reference/author data
        - Rate limits apply (see API documentation)
        - Some fields may be null if data is not available
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

# 1.5 Get details for multiple papers at once
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
            - CorpusId:<id> (e.g., "CorpusId:215416146")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")
              Supported URLs from: semanticscholar.org, arxiv.org, aclweb.org,
                                 acm.org, biorxiv.org
            Maximum: 500 IDs per request

        fields (Optional[str]): Comma-separated list of fields to return for each paper.
            paperId is always returned.
            Available fields:
            - abstract: The paper's abstract
            - authors: List of authors with name and authorId
            - citationCount: Total number of citations
            - citations: List of papers citing this paper
            - corpusId: Internal ID for the paper
            - embedding: Vector embedding of the paper
            - externalIds: External IDs (DOI, MAG, etc)
            - fieldsOfStudy: List of fields of study
            - influentialCitationCount: Number of influential citations
            - isOpenAccess: Whether paper is open access
            - openAccessPdf: Open access PDF URL if available
            - paperId: Semantic Scholar paper ID
            - publicationDate: Publication date in YYYY-MM-DD format
            - publicationTypes: List of publication types
            - publicationVenue: Venue information
            - references: List of papers cited by this paper
            - s2FieldsOfStudy: Semantic Scholar fields
            - title: Paper title
            - tldr: AI-generated TLDR summary
            - url: URL to Semantic Scholar paper page
            - venue: Publication venue name
            - year: Publication year

            Special syntax for nested fields:
            - For citations/references: citations.title, references.abstract, etc.
            - For authors: authors.name, authors.affiliations, etc.
            - For embeddings: embedding.specter_v2 for v2 embeddings

            If omitted, returns only paperId and title.
    
    Returns:
        List[Dict]: List of paper details with requested fields.
            - Results maintain the same order as input paper_ids
            - Invalid or not found paper IDs return null in the results
            - Each paper object contains the requested fields
            - paperId is always included in each paper object

    Notes:
        - More efficient than making multiple single-paper requests
        - Maximum of 500 paper IDs per request
        - Rate limits apply (see API documentation)
        - Some fields may be null if data is not available
        - Invalid paper IDs return null instead of causing an error
        - Order of results matches order of input IDs for easy mapping
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
            
            response = await client.post(
                f"{Config.BASE_URL}/paper/batch",
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

# 1.6 Details about a paper's authors
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
            - CorpusId:<id> (e.g., "CorpusId:215416146")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")

        fields (Optional[List[str]]): List of fields to return for each author.
            authorId is always returned.
            Available fields:
            - name: Author's name
            - aliases: Alternative names for the author
            - affiliations: List of author's affiliations
            - homepage: Author's homepage URL
            - paperCount: Total number of papers by this author
            - citationCount: Total citations received by this author
            - hIndex: Author's h-index
            - papers: List of papers by this author (returns paperId and title)
            
            Special syntax for paper fields:
            - papers.year: Include year for each paper
            - papers.authors: Include authors for each paper
            - papers.abstract: Include abstract for each paper
            - papers.venue: Include venue for each paper
            - papers.citations: Include citation count for each paper

            If omitted, returns only authorId and name.

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

    Notes:
        - Authors are returned in the order they appear on the paper
        - Supports pagination for papers with many authors
        - Some fields may be null if data is not available
        - Rate limits apply (see API documentation)
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

# 1.7 Details about a paper's citations
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
            - CorpusId:<id> (e.g., "CorpusId:215416146")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")

        fields (Optional[List[str]]): List of fields to return for each citing paper.
            paperId is always returned.
            Available fields:
            - title: Paper title
            - abstract: Paper abstract
            - year: Publication year
            - venue: Publication venue
            - authors: List of authors
            - url: URL to paper page
            - citationCount: Number of citations received
            - influentialCitationCount: Number of influential citations
            
            Citation-specific fields:
            - contexts: List of citation contexts (text snippets)
            - intents: List of citation intents (Background, Method, etc.)
            - isInfluential: Whether this is an influential citation

            If omitted, returns only paperId and title.

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

    Notes:
        - Citations are sorted by citation date (newest first)
        - Includes citation context when available
        - Supports pagination for highly-cited papers
        - Some fields may be null if data is not available
        - Rate limits apply (see API documentation)
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

# 1.8 Details about a paper's references
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
            - CorpusId:<id> (e.g., "CorpusId:215416146")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")

        fields (Optional[List[str]]): List of fields to return for each referenced paper.
            paperId is always returned.
            Available fields:
            - title: Paper title
            - abstract: Paper abstract
            - year: Publication year
            - venue: Publication venue
            - authors: List of authors
            - url: URL to paper page
            - citationCount: Number of citations received
            - influentialCitationCount: Number of influential citations
            
            Reference-specific fields:
            - contexts: List of citation contexts (text snippets)
            - intents: List of citation intents (Background, Method, etc.)
            - isInfluential: Whether this is an influential citation

            If omitted, returns only paperId and title.

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

    Notes:
        - References are returned in the order they appear in the bibliography
        - Includes citation context when available
        - Supports pagination for papers with many references
        - Some fields may be null if data is not available
        - Rate limits apply (see API documentation)
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



# 2. Author Data Tools

# 2.1 Search for authors by name
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
            and their known aliases. The match is case-insensitive and matches name prefixes.
            Examples:
            - "Albert Einstein"
            - "Einstein, Albert"
            - "A Einstein"

        fields (Optional[List[str]]): List of fields to return for each author.
            authorId is always returned.
            Available fields:
            - name: Author's name
            - aliases: Alternative names for the author
            - url: URL to author's S2 profile
            - affiliations: List of author's affiliations
            - homepage: Author's homepage URL
            - paperCount: Total number of papers by this author
            - citationCount: Total citations received by this author
            - hIndex: Author's h-index
            - papers: List of papers by this author (returns paperId and title)
            
            Special syntax for paper fields:
            - papers.year: Include year for each paper
            - papers.authors: Include authors for each paper
            - papers.abstract: Include abstract for each paper
            - papers.venue: Include venue for each paper
            - papers.citations: Include citation count for each paper

            If omitted, returns only authorId and name.

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

    Notes:
        - Results are sorted by relevance to the query
        - Matches against author names and aliases
        - Case-insensitive matching
        - Matches name prefixes
        - Supports pagination for large result sets
        - Some fields may be null if data is not available
        - Rate limits apply (see API documentation)
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

# 2.2 Details about an author
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
            Available fields:
            - name: Author's name
            - aliases: Alternative names for the author
            - url: URL to author's S2 profile
            - affiliations: List of author's affiliations
            - homepage: Author's homepage URL
            - paperCount: Total number of papers by this author
            - citationCount: Total citations received by this author
            - hIndex: Author's h-index
            - papers: List of papers by this author (returns paperId and title)
            
            Special syntax for paper fields:
            - papers.year: Include year for each paper
            - papers.authors: Include authors for each paper
            - papers.abstract: Include abstract for each paper
            - papers.venue: Include venue for each paper
            - papers.citations: Include citation count for each paper

            If omitted, returns only authorId and name.

    Returns:
        Dict: Author details with requested fields.
            Always includes authorId.
            Returns error response if author not found.

    Notes:
        - Provides comprehensive author metadata
        - Papers list is limited to most recent papers
        - For complete paper list, use author_papers endpoint
        - Some fields may be null if data is not available
        - Rate limits apply (see API documentation)
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

# 2.3 Details about an author's papers
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
            Available fields:
            - title: Paper title
            - abstract: Paper abstract
            - year: Publication year
            - venue: Publication venue
            - authors: List of authors
            - url: URL to paper page
            - citationCount: Number of citations received
            - influentialCitationCount: Number of influential citations
            - isOpenAccess: Whether paper is open access
            - openAccessPdf: Open access PDF URL if available
            - fieldsOfStudy: List of fields of study
            - s2FieldsOfStudy: Semantic Scholar fields
            - publicationTypes: List of publication types
            - publicationDate: Publication date in YYYY-MM-DD format
            - journal: Journal information
            - externalIds: External IDs (DOI, MAG, etc)

            If omitted, returns only paperId and title.

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

    Notes:
        - Papers are sorted by publication date (newest first)
        - Supports pagination for authors with many papers
        - Some fields may be null if data is not available
        - Rate limits apply (see API documentation)
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

    # Validate fields
    if fields:
        invalid_fields = set(fields) - PaperFields.VALID_FIELDS
        if invalid_fields:
            return create_error_response(
                ErrorType.VALIDATION,
                f"Invalid fields: {', '.join(invalid_fields)}",
                {"valid_fields": list(PaperFields.VALID_FIELDS)}
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

# 2.4 Get details for multiple authors at once
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
            Available fields:
            - name: Author's name
            - aliases: Alternative names for the author
            - url: URL to author's S2 profile
            - affiliations: List of author's affiliations
            - homepage: Author's homepage URL
            - paperCount: Total number of papers by this author
            - citationCount: Total citations received by this author
            - hIndex: Author's h-index
            - papers: List of papers by this author (returns paperId and title)
            
            Special syntax for paper fields:
            - papers.year: Include year for each paper
            - papers.authors: Include authors for each paper
            - papers.abstract: Include abstract for each paper
            - papers.venue: Include venue for each paper
            - papers.citations: Include citation count for each paper

            If omitted, returns only authorId and name.

    Returns:
        List[Dict]: List of author details with requested fields.
            - Results maintain the same order as input author_ids
            - Invalid or not found author IDs return null in the results
            - Each author object contains the requested fields
            - authorId is always included in each author object

    Notes:
        - More efficient than making multiple single-author requests
        - Maximum of 1000 author IDs per request
        - Rate limits apply (see API documentation)
        - Some fields may be null if data is not available
        - Invalid author IDs return null instead of causing an error
        - Order of results matches order of input IDs for easy mapping
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

    # Make POST request with proper structure
    try:
        async with httpx.AsyncClient(timeout=Config.TIMEOUT) as client:
            api_key = get_api_key()
            headers = {"x-api-key": api_key} if api_key else {}
            
            response = await client.post(
                f"{Config.BASE_URL}/author/batch",
                params=params,
                json={"ids": author_ids},
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


# 3. Paper Recommendation Tools

# 3.1 Get recommendations based on a single paper
@mcp.tool()
async def get_paper_recommendations_single(
    context: Context,
    paper_id: str,
    fields: Optional[str] = None,
    limit: int = 100,
    from_pool: str = "recent"
) -> Dict:
    """
    Get paper recommendations based on a single seed paper.
    This endpoint is optimized for finding papers similar to a specific paper.

    Args:
        paper_id (str): Paper identifier in one of the following formats:
            - Semantic Scholar ID (e.g., "649def34f8be52c8b66281af98ae884c09aef38b")
            - CorpusId:<id> (e.g., "CorpusId:215416146")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")

        fields (Optional[str]): Comma-separated list of fields to return for each paper.
            paperId is always returned.
            Available fields:
            - title: Paper title
            - abstract: Paper abstract
            - year: Publication year
            - venue: Publication venue
            - authors: List of authors
            - url: URL to paper page
            - citationCount: Number of citations received
            - influentialCitationCount: Number of influential citations
            - isOpenAccess: Whether paper is open access
            - openAccessPdf: Open access PDF URL if available
            - fieldsOfStudy: List of fields of study
            - publicationTypes: List of publication types
            - publicationDate: Publication date in YYYY-MM-DD format
            - journal: Journal information
            - externalIds: External IDs (DOI, MAG, etc)

            If omitted, returns only paperId and title.

        limit (int): Maximum number of recommendations to return.
            Default: 100
            Maximum: 500

        from_pool (str): Which pool of papers to recommend from.
            Options:
            - "recent": Recent papers (default)
            - "all-cs": All computer science papers
            Default: "recent"

    Returns:
        Dict: {
            "recommendedPapers": List[Dict] # List of recommended papers with requested fields
        }

    Notes:
        - Recommendations are based on content similarity and citation patterns
        - Results are sorted by relevance to the seed paper
        - "recent" pool focuses on papers from the last few years
        - "all-cs" pool includes older computer science papers
        - Rate limits apply (see API documentation)
        - Some fields may be null if data is not available
    """
    try:
        # Apply rate limiting
        endpoint = "/recommendations"
        await rate_limiter.acquire(endpoint)

        # Validate limit
        if limit > 500:
            return create_error_response(
                ErrorType.VALIDATION,
                "Cannot request more than 500 recommendations",
                {"max_limit": 500, "requested": limit}
            )

        # Validate pool
        if from_pool not in ["recent", "all-cs"]:
            return create_error_response(
                ErrorType.VALIDATION,
                "Invalid paper pool specified",
                {"valid_pools": ["recent", "all-cs"]}
            )

        # Build request parameters
        params = {
            "limit": limit,
            "from": from_pool
        }
        if fields:
            params["fields"] = fields

        # Make the API request
        async with httpx.AsyncClient(timeout=Config.TIMEOUT) as client:
            api_key = get_api_key()
            headers = {"x-api-key": api_key} if api_key else {}
            
            url = f"https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{paper_id}"
            response = await client.get(url, params=params, headers=headers)
            
            # Handle specific error cases
            if response.status_code == 404:
                return create_error_response(
                    ErrorType.VALIDATION,
                    "Paper not found",
                    {"paper_id": paper_id}
                )
            
            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return create_error_response(
                ErrorType.RATE_LIMIT,
                "Rate limit exceeded. Consider using an API key for higher limits.",
                {
                    "retry_after": e.response.headers.get("retry-after"),
                    "authenticated": bool(get_api_key())
                }
            )
        return create_error_response(
            ErrorType.API_ERROR,
            f"HTTP error {e.response.status_code}",
            {"response": e.response.text}
        )
    except httpx.TimeoutException:
        return create_error_response(
            ErrorType.TIMEOUT,
            f"Request timed out after {Config.TIMEOUT} seconds"
        )
    except Exception as e:
        logger.error(f"Unexpected error in recommendations: {str(e)}")
        return create_error_response(
            ErrorType.API_ERROR,
            "Failed to get recommendations",
            {"error": str(e)}
        )

# 3.2 Get recommendations based on multiple papers
@mcp.tool()
async def get_paper_recommendations_multi(
    context: Context,
    positive_paper_ids: List[str],
    negative_paper_ids: Optional[List[str]] = None,
    fields: Optional[str] = None,
    limit: int = 100
) -> Dict:
    """
    Get paper recommendations based on multiple positive and optional negative examples.
    This endpoint is optimized for finding papers similar to a set of papers while
    avoiding papers similar to the negative examples.

    Args:
        positive_paper_ids (List[str]): List of paper IDs to use as positive examples.
            Papers similar to these will be recommended.
            Each ID can be in any of these formats:
            - Semantic Scholar ID (e.g., "649def34f8be52c8b66281af98ae884c09aef38b")
            - CorpusId:<id> (e.g., "CorpusId:215416146")
            - DOI:<doi> (e.g., "DOI:10.18653/v1/N18-3011")
            - ARXIV:<id> (e.g., "ARXIV:2106.15928")
            - MAG:<id> (e.g., "MAG:112218234")
            - ACL:<id> (e.g., "ACL:W12-3903")
            - PMID:<id> (e.g., "PMID:19872477")
            - PMCID:<id> (e.g., "PMCID:2323736")
            - URL:<url> (e.g., "URL:https://arxiv.org/abs/2106.15928v1")

        negative_paper_ids (Optional[List[str]]): List of paper IDs to use as negative examples.
            Papers similar to these will be avoided in recommendations.
            Uses same ID formats as positive_paper_ids.

        fields (Optional[str]): Comma-separated list of fields to return for each paper.
            paperId is always returned.
            Available fields:
            - title: Paper title
            - abstract: Paper abstract
            - year: Publication year
            - venue: Publication venue
            - authors: List of authors
            - url: URL to paper page
            - citationCount: Number of citations received
            - influentialCitationCount: Number of influential citations
            - isOpenAccess: Whether paper is open access
            - openAccessPdf: Open access PDF URL if available
            - fieldsOfStudy: List of fields of study
            - publicationTypes: List of publication types
            - publicationDate: Publication date in YYYY-MM-DD format
            - journal: Journal information
            - externalIds: External IDs (DOI, MAG, etc)

            If omitted, returns only paperId and title.

        limit (int): Maximum number of recommendations to return.
            Default: 100
            Maximum: 500

    Returns:
        Dict: {
            "recommendedPapers": List[Dict] # List of recommended papers with requested fields
        }

    Notes:
        - Recommendations balance similarity to positive examples and dissimilarity to negative examples
        - Results are sorted by relevance score
        - More positive examples can help focus recommendations
        - Negative examples help filter out unwanted topics/approaches
        - Rate limits apply (see API documentation)
        - Some fields may be null if data is not available
    """
    try:
        # Apply rate limiting
        endpoint = "/recommendations"
        await rate_limiter.acquire(endpoint)

        # Validate inputs
        if not positive_paper_ids:
            return create_error_response(
                ErrorType.VALIDATION,
                "Must provide at least one positive paper ID"
            )

        if limit > 500:
            return create_error_response(
                ErrorType.VALIDATION,
                "Cannot request more than 500 recommendations",
                {"max_limit": 500, "requested": limit}
            )

        # Build request parameters
        params = {"limit": limit}
        if fields:
            params["fields"] = fields

        request_body = {
            "positivePaperIds": positive_paper_ids,
            "negativePaperIds": negative_paper_ids or []
        }

        # Make the API request
        async with httpx.AsyncClient(timeout=Config.TIMEOUT) as client:
            api_key = get_api_key()
            headers = {"x-api-key": api_key} if api_key else {}
            
            url = "https://api.semanticscholar.org/recommendations/v1/papers"
            response = await client.post(url, params=params, json=request_body, headers=headers)
            
            # Handle specific error cases
            if response.status_code == 404:
                return create_error_response(
                    ErrorType.VALIDATION,
                    "One or more input papers not found",
                    {
                        "positive_ids": positive_paper_ids,
                        "negative_ids": negative_paper_ids
                    }
                )
            
            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return create_error_response(
                ErrorType.RATE_LIMIT,
                "Rate limit exceeded. Consider using an API key for higher limits.",
                {
                    "retry_after": e.response.headers.get("retry-after"),
                    "authenticated": bool(get_api_key())
                }
            )
        return create_error_response(
            ErrorType.API_ERROR,
            f"HTTP error {e.response.status_code}",
            {"response": e.response.text}
        )
    except httpx.TimeoutException:
        return create_error_response(
            ErrorType.TIMEOUT,
            f"Request timed out after {Config.TIMEOUT} seconds"
        )
    except Exception as e:
        logger.error(f"Unexpected error in recommendations: {str(e)}")
        return create_error_response(
            ErrorType.API_ERROR,
            "Failed to get recommendations",
            {"error": str(e)}
        )






async def shutdown():
    """Gracefully shut down the server."""
    logger.info("Initiating graceful shutdown...")
    
    # Cancel all tasks
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    # Cleanup resources
    await cleanup_client()
    try:
        cleanup_fn = getattr(mcp, "cleanup", None)
        if cleanup_fn:
            if asyncio.iscoroutinefunction(cleanup_fn):
                await cleanup_fn()
            else:
                cleanup_fn()
        else:
            # Try common alternative names on FastMCP implementations
            for name in ("shutdown", "stop", "close"):
                fn = getattr(mcp, name, None)
                if fn:
                    if asyncio.iscoroutinefunction(fn):
                        await fn()
                    else:
                        fn()
                    break
    except Exception as e:
        logger.error(f"Error during mcp cleanup: {e}")
    # Signal run_server to stop waiting
    try:
        global stop_event
        if stop_event is not None and not stop_event.is_set():
            stop_event.set()
    except Exception:
        pass
    
    logger.info(f"Cancelled {len(tasks)} tasks")
    logger.info("Shutdown complete")

def init_signal_handlers(loop):
    """Initialize signal handlers for graceful shutdown."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    logger.info("Signal handlers initialized")

async def run_server():
    """Run the server with proper async context management."""
    try:
        # Initialize HTTP client
        await initialize_client()

        # Start the server
        logger.info("Starting Semantic Scholar Server")
        # run_fastmcp; run_async may detach/return — run it as a background task
        task = asyncio.create_task(mcp.run_async())

        # Create a stop event to keep the main coroutine alive if FastMCP detaches
        global stop_event
        if stop_event is None:
            stop_event = asyncio.Event()

        # Wait until shutdown() sets the event
        await stop_event.wait()
        # Ensure server task is cancelled/awaited on shutdown
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        await shutdown()

if __name__ == "__main__":
    try:
        # Set up event loop with exception handler
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.set_exception_handler(handle_exception)
        
        # Initialize signal handlers
        init_signal_handlers(loop)
        
        # Run the server
        loop.run_until_complete(run_server())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
    finally:
        try:
            loop.run_until_complete(asyncio.sleep(0))  # Let pending tasks complete
            loop.close()
        except Exception as e:
            logger.error(f"Error during final cleanup: {str(e)}")
        logger.info("Server stopped")
