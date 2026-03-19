"""Test utilities and core functionality without MCP dependencies"""

import httpx
import logging
import os
from typing import Dict, Optional
import asyncio
from enum import Enum
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Basic setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ErrorType(Enum):
    RATE_LIMIT = "rate_limit"
    API_ERROR = "api_error"
    VALIDATION = "validation"
    TIMEOUT = "timeout"

class Config:
    API_VERSION = "v1"
    GRAPH_BASE_URL = f"https://api.semanticscholar.org/graph/{API_VERSION}"
    RECOMMENDATIONS_BASE_URL = "https://api.semanticscholar.org/recommendations/v1"
    TIMEOUT = 30  # seconds

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

def get_api_key() -> Optional[str]:
    """Get the Semantic Scholar API key from environment variables."""
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    logger.info(f"API Key found: {'Yes' if api_key else 'No'}")
    return api_key

async def make_request(endpoint: str, params: Dict = None, method: str = "GET", json: Dict = None) -> Dict:
    """Make a request to the Semantic Scholar API."""
    try:
        api_key = get_api_key()
        headers = {"x-api-key": api_key} if api_key else {}
        params = params or {}
        
        # Choose base URL based on endpoint
        is_recommendations = endpoint.startswith("recommendations") or endpoint.startswith("papers/forpaper")
        base_url = Config.RECOMMENDATIONS_BASE_URL if is_recommendations else Config.GRAPH_BASE_URL
        
        # Clean up endpoint
        if endpoint.startswith("/"):
            endpoint = endpoint[1:]
        if is_recommendations and endpoint.startswith("recommendations/"):
            endpoint = endpoint[len("recommendations/"):]  # Remove "recommendations/" prefix

        url = f"{base_url}/{endpoint}"
        logger.info(f"Making {method} request to {url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Params: {params}")
        if json:
            logger.info(f"JSON body: {json}")

        async with httpx.AsyncClient(timeout=Config.TIMEOUT, follow_redirects=True) as client:
            if method == "GET":
                response = await client.get(url, params=params, headers=headers)
            else:  # POST
                response = await client.post(url, params=params, json=json, headers=headers)
            
            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text}")
            
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