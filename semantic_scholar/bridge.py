"""
HTTP Bridge for the Semantic Scholar MCP Server.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import AuthorDetailFields, Config, PaperFields
from .core.client import S2Client, make_compat_client
from .core.exceptions import S2Error
from .core.requests import (
    AuthorBatchDetailsRequest,
    AuthorDetailsRequest,
    AuthorSearchRequest,
    PaperBatchDetailsRequest,
    PaperDetailsRequest,
    PaperRelevanceSearchRequest,
    RequestModel,
)
from .utils.errors import s2_exception_to_error_response
from .utils.http import cleanup_client, initialize_client, make_request


class IdList(BaseModel):
    ids: List[str]


@dataclass(slots=True)
class _BridgeRecommendationsRequest(RequestModel):
    paper_id: str
    fields: Optional[str] = None
    base_url: str = Config.RECOMMENDATIONS_BASE_URL

    @property
    def endpoint(self) -> str:
        return f"/papers/forpaper/{self.paper_id}"

    def to_params(self) -> dict[str, str]:
        params = {}
        if self.fields:
            params["fields"] = self.fields
        return params


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_client()
    try:
        yield
    finally:
        await cleanup_client()


app = FastAPI(title="Semantic Scholar Bridge", version="0.1", lifespan=lifespan)


def _client() -> S2Client:
    return make_compat_client(make_request)


def _bearer_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1]
    return None


def _bridge_error_response(exc: S2Error) -> JSONResponse:
    return JSONResponse(s2_exception_to_error_response(exc), status_code=200)


@app.get("/v1/paper/search")
async def paper_search(
    request: Request,
    q: str,
    fields: Optional[str] = None,
    offset: int = 0,
    limit: int = 10,
):
    token = _bearer_token(request)
    try:
        request_model = PaperRelevanceSearchRequest(
            query=q,
            fields=fields.split(",") if fields else Config.DEFAULT_FIELDS,
            offset=offset,
            limit=limit,
        )
        return await _client().search_papers(request_model, api_key_override=token)
    except S2Error as exc:
        return _bridge_error_response(exc)


@app.get("/v1/paper/{paper_id}")
async def paper_details(request: Request, paper_id: str, fields: Optional[str] = None):
    token = _bearer_token(request)
    try:
        request_model = PaperDetailsRequest(
            paper_id=paper_id,
            fields=fields.split(",") if fields else Config.DEFAULT_FIELDS,
        )
        return await _client().get_paper(request_model, api_key_override=token)
    except S2Error as exc:
        return _bridge_error_response(exc)


@app.post("/v1/paper/batch")
async def paper_batch(request: Request, batch: IdList, fields: Optional[str] = None):
    token = _bearer_token(request)
    try:
        request_model = PaperBatchDetailsRequest(
            paper_ids=batch.ids,
            fields=fields if fields else ",".join(Config.DEFAULT_FIELDS),
        )
        return await _client().batch_papers(request_model, api_key_override=token)
    except S2Error as exc:
        return _bridge_error_response(exc)


@app.get("/v1/author/search")
async def author_search(
    request: Request,
    q: str,
    fields: Optional[str] = None,
    offset: int = 0,
    limit: int = 10,
):
    token = _bearer_token(request)
    try:
        request_model = AuthorSearchRequest(
            query=q,
            fields=fields.split(",") if fields else AuthorDetailFields.BASIC,
            offset=offset,
            limit=limit,
        )
        return await _client().search_authors(request_model, api_key_override=token)
    except S2Error as exc:
        return _bridge_error_response(exc)


@app.get("/v1/author/{author_id}")
async def author_details(request: Request, author_id: str, fields: Optional[str] = None):
    token = _bearer_token(request)
    try:
        request_model = AuthorDetailsRequest(
            author_id=author_id,
            fields=fields.split(",") if fields else AuthorDetailFields.BASIC,
        )
        return await _client().get_author(request_model, api_key_override=token)
    except S2Error as exc:
        return _bridge_error_response(exc)


@app.post("/v1/author/batch")
async def author_batch(request: Request, batch: IdList, fields: Optional[str] = None):
    token = _bearer_token(request)
    try:
        request_model = AuthorBatchDetailsRequest(
            author_ids=batch.ids,
            fields=fields if fields else ",".join(AuthorDetailFields.BASIC),
        )
        return await _client().batch_authors(request_model, api_key_override=token)
    except S2Error as exc:
        return _bridge_error_response(exc)


@app.get("/v1/recommendations")
async def recommendations(request: Request, paper_id: Optional[str] = None, fields: Optional[str] = None):
    if not paper_id:
        raise HTTPException(status_code=400, detail="paper_id is required")

    token = _bearer_token(request)
    try:
        request_model = _BridgeRecommendationsRequest(
            paper_id=paper_id,
            fields=fields if fields else ",".join(PaperFields.DEFAULT),
        )
        return await _client().recommend_for_paper(request_model, api_key_override=token)
    except S2Error as exc:
        return _bridge_error_response(exc)
