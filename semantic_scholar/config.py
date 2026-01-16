"""
Configuration for the Semantic Scholar API Server.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Tuple, Any
import os

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