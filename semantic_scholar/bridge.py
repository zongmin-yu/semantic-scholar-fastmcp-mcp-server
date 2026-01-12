"""
HTTP Bridge for the Semantic Scholar MCP Server

This module exposes a small FastAPI application that forwards REST
requests to the internal Semantic Scholar helper utilities. The bridge
is intended to run in the same process/container as the MCP server so
`open-webui` (or other local services) can call a plain HTTP API.

Design goals
- Minimal, well-documented HTTP surface for common workflows (search,
  paper/author details, batch lookups, recommendations).
- Reuse the existing `semantic_scholar.utils.http` helpers (rate limiting,
  API key handling, client pooling) to ensure consistent behavior.
- Run inside the same process as the MCP server (the server starts the
  Uvicorn instance programmatically).

Usage
- Import the `app` object into an ASGI/uvicorn runner or let the
  MCP server start it automatically.

Endpoints
- GET  /v1/paper/search?q=...            -> semantic scholar search
- GET  /v1/paper/{paper_id}              -> paper details
- POST /v1/paper/batch                   -> batch details (json {"ids": [...]})
- GET  /v1/author/search?q=...           -> author search
- GET  /v1/author/{author_id}            -> author details
- POST /v1/author/batch                  -> batch author details
- GET  /v1/recommendations?paper_id=...  -> recommendations (proxy)

"""
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .utils.http import make_request, initialize_client
from .utils.logger import logger
from .config import Config, AuthorDetailFields, PaperFields, PaperDetailFields, CitationReferenceFields

app = FastAPI(title="Semantic Scholar Bridge", version="0.1")


class IdList(BaseModel):
    ids: List[str]


@app.on_event("startup")
async def _startup():
    # ensure the shared http client is initialized
    await initialize_client()


@app.get("/v1/paper/search")
async def paper_search(request: Request, q: str, fields: Optional[str] = None, offset: int = 0, limit: int = 10):
    params = {"query": q, "offset": offset, "limit": limit}
    # If caller didn't request specific fields, use server default fields
    params["fields"] = fields if fields else ",".join(Config.DEFAULT_FIELDS)
    # extract bearer token if present and prefer it over env
    auth = request.headers.get("authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1]
    result = await make_request("/paper/search", params=params, api_key_override=token)
    return result


@app.get("/v1/paper/{paper_id}")
async def paper_details(request: Request, paper_id: str, fields: Optional[str] = None):
    params = {"fields": fields} if fields else {"fields": ",".join(Config.DEFAULT_FIELDS)}
    auth = request.headers.get("authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1]
    result = await make_request(f"/paper/{paper_id}", params=params, api_key_override=token)
    return result


@app.post("/v1/paper/batch")
async def paper_batch(request: Request, batch: IdList, fields: Optional[str] = None):
    params = {"fields": fields} if fields else {"fields": ",".join(Config.DEFAULT_FIELDS)}
    # Semantic Scholar batch endpoint expects POST with ids in JSON
    # The helper `make_request` currently supports GET; do a direct call here.
    # Reuse the http client from utils.http
    from .utils.http import http_client
    if http_client is None:
        await initialize_client()
        from .utils.http import http_client as _cli
        client = _cli
    else:
        client = http_client

    # extract bearer token from request to override env API key
    auth = request.headers.get("authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1]

    headers = {"x-api-key": token} if token else {}

    url = f"{Config.BASE_URL}/paper/batch"
    try:
        logger.debug(
            "Semantic Scholar request: method=%s url=%s params=%s headers=%s",
            "POST",
            url,
            params,
            headers
        )
        logger.debug("Semantic Scholar request body: %s", {"ids": batch.ids})
        resp = await client.post(url, json={"ids": batch.ids}, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Batch paper request failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/author/search")
async def author_search(request: Request, q: str, fields: Optional[str] = None, offset: int = 0, limit: int = 10):
    params = {"query": q, "offset": offset, "limit": limit}
    params["fields"] = fields if fields else ",".join(AuthorDetailFields.BASIC)
    auth = request.headers.get("authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1]
    result = await make_request("/author/search", params=params, api_key_override=token)
    return result


@app.get("/v1/author/{author_id}")
async def author_details(request: Request, author_id: str, fields: Optional[str] = None):
    params = {"fields": fields} if fields else {"fields": ",".join(AuthorDetailFields.BASIC)}
    auth = request.headers.get("authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1]
    result = await make_request(f"/author/{author_id}", params=params, api_key_override=token)
    return result


@app.post("/v1/author/batch")
async def author_batch(request: Request, batch: IdList, fields: Optional[str] = None):
    params = {"fields": fields} if fields else {"fields": ",".join(AuthorDetailFields.BASIC)}
    from .utils.http import http_client
    if http_client is None:
        await initialize_client()
        from .utils.http import http_client as _cli
        client = _cli
    else:
        client = http_client
    # extract token
    auth = request.headers.get("authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1]

    headers = {"x-api-key": token} if token else {}

    url = f"{Config.BASE_URL}/author/batch"
    try:
        logger.debug(
            "Semantic Scholar request: method=%s url=%s params=%s headers=%s",
            "POST",
            url,
            params,
            headers
        )
        logger.debug("Semantic Scholar request body: %s", {"ids": batch.ids})
        resp = await client.post(url, json={"ids": batch.ids}, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Batch author request failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/recommendations")
async def recommendations(request: Request, paper_id: Optional[str] = None, fields: Optional[str] = None):
    if not paper_id:
        raise HTTPException(status_code=400, detail="paper_id is required")
    params = {"fields": fields} if fields else {"fields": ",".join(PaperFields.DEFAULT)}
    auth = request.headers.get("authorization")
    token = None
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(None, 1)[1]
    result = await make_request(f"/paper/{paper_id}/recommendations", params=params, api_key_override=token)
    return result
