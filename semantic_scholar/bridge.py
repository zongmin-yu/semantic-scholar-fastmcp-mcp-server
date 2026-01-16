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
from .config import Config, AuthorDetailFields, PaperFields, PaperDetailFields, CitationReferenceFields

app = FastAPI(title="Semantic Scholar Bridge", version="0.1")


class IdList(BaseModel):
    ids: List[str]


@app.on_event("startup")
async def _startup():
    # ensure the shared http client is initialized
    await initialize_client()

def _bearer_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1]
    return None


@app.get("/v1/paper/search")
async def paper_search(request: Request, q: str, fields: Optional[str] = None, offset: int = 0, limit: int = 10):
    params = {"query": q, "offset": offset, "limit": limit}
    # If caller didn't request specific fields, use server default fields
    params["fields"] = fields if fields else ",".join(Config.DEFAULT_FIELDS)
    token = _bearer_token(request)
    result = await make_request("/paper/search", params=params, api_key_override=token)
    return result


@app.get("/v1/paper/{paper_id}")
async def paper_details(request: Request, paper_id: str, fields: Optional[str] = None):
    params = {"fields": fields} if fields else {"fields": ",".join(Config.DEFAULT_FIELDS)}
    token = _bearer_token(request)
    result = await make_request(f"/paper/{paper_id}", params=params, api_key_override=token)
    return result


@app.post("/v1/paper/batch")
async def paper_batch(request: Request, batch: IdList, fields: Optional[str] = None):
    params = {"fields": fields} if fields else {"fields": ",".join(Config.DEFAULT_FIELDS)}
    token = _bearer_token(request)
    return await make_request(
        "/paper/batch",
        params=params,
        api_key_override=token,
        method="POST",
        json={"ids": batch.ids},
    )


@app.get("/v1/author/search")
async def author_search(request: Request, q: str, fields: Optional[str] = None, offset: int = 0, limit: int = 10):
    params = {"query": q, "offset": offset, "limit": limit}
    params["fields"] = fields if fields else ",".join(AuthorDetailFields.BASIC)
    token = _bearer_token(request)
    result = await make_request("/author/search", params=params, api_key_override=token)
    return result


@app.get("/v1/author/{author_id}")
async def author_details(request: Request, author_id: str, fields: Optional[str] = None):
    params = {"fields": fields} if fields else {"fields": ",".join(AuthorDetailFields.BASIC)}
    token = _bearer_token(request)
    result = await make_request(f"/author/{author_id}", params=params, api_key_override=token)
    return result


@app.post("/v1/author/batch")
async def author_batch(request: Request, batch: IdList, fields: Optional[str] = None):
    params = {"fields": fields} if fields else {"fields": ",".join(AuthorDetailFields.BASIC)}
    token = _bearer_token(request)
    return await make_request(
        "/author/batch",
        params=params,
        api_key_override=token,
        method="POST",
        json={"ids": batch.ids},
    )


@app.get("/v1/recommendations")
async def recommendations(request: Request, paper_id: Optional[str] = None, fields: Optional[str] = None):
    if not paper_id:
        raise HTTPException(status_code=400, detail="paper_id is required")
    params = {"fields": fields} if fields else {"fields": ",".join(PaperFields.DEFAULT)}
    token = _bearer_token(request)
    result = await make_request(f"/paper/{paper_id}/recommendations", params=params, api_key_override=token)
    return result
