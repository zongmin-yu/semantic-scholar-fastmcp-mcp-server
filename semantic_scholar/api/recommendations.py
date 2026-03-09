"""
Recommendation-related API endpoints for the Semantic Scholar API.
"""

from typing import Dict, List, Optional

from fastmcp import Context

from ..config import ErrorType
from ..core.client import S2Client, make_compat_client
from ..core.exceptions import S2ApiError, S2Error, S2ValidationError
from ..core.requests import PaperRecommendationsMultiRequest, PaperRecommendationsSingleRequest
from ..mcp import mcp
from ..utils.errors import create_error_response, s2_exception_to_error_response
from ..utils.http import make_request
from ..utils.logger import logger


def _client() -> S2Client:
    return make_compat_client(make_request)


@mcp.tool()
async def get_paper_recommendations_single(
    context: Context,
    paper_id: str,
    fields: Optional[str] = None,
    limit: int = 100,
    from_pool: str = "recent",
) -> Dict:
    try:
        request = PaperRecommendationsSingleRequest(
            paper_id=paper_id,
            fields=fields,
            limit=limit,
            from_pool=from_pool,
        )
        return await _client().recommend_for_paper(request)
    except S2ValidationError as exc:
        return s2_exception_to_error_response(exc)
    except S2ApiError as exc:
        if exc.status_code == 404:
            return create_error_response(
                ErrorType.VALIDATION,
                "Paper not found",
                {"paper_id": paper_id},
            )
        return s2_exception_to_error_response(exc)
    except S2Error as exc:
        return s2_exception_to_error_response(exc)
    except Exception as exc:
        logger.error("Unexpected error in recommendations: %s", str(exc))
        return create_error_response(
            ErrorType.API_ERROR,
            "Failed to get recommendations",
            {"error": str(exc)},
        )


@mcp.tool()
async def get_paper_recommendations_multi(
    context: Context,
    positive_paper_ids: List[str],
    negative_paper_ids: Optional[List[str]] = None,
    fields: Optional[str] = None,
    limit: int = 100,
) -> Dict:
    try:
        request = PaperRecommendationsMultiRequest(
            positive_paper_ids=positive_paper_ids,
            negative_paper_ids=negative_paper_ids,
            fields=fields,
            limit=limit,
        )
        return await _client().recommend_from_papers(request)
    except S2ValidationError as exc:
        return s2_exception_to_error_response(exc)
    except S2ApiError as exc:
        if exc.status_code == 404:
            return create_error_response(
                ErrorType.VALIDATION,
                "One or more input papers not found",
                {
                    "positive_ids": positive_paper_ids,
                    "negative_ids": negative_paper_ids,
                },
            )
        return s2_exception_to_error_response(exc)
    except S2Error as exc:
        return s2_exception_to_error_response(exc)
    except Exception as exc:
        logger.error("Unexpected error in recommendations: %s", str(exc))
        return create_error_response(
            ErrorType.API_ERROR,
            "Failed to get recommendations",
            {"error": str(exc)},
        )
