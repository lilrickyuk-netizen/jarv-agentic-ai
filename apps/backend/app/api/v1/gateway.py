"""
JAI Backend - JAI's model gateway endpoint (Wave 6)

POST /api/gateway/v1/chat/completions, /responses and /embeddings, in the OpenAI API's own shape, for the services
JAI runs on its private networks. Authorised by JAI's gateway token (JAI_GATEWAY_TOKEN), never by a provider key;
see app.core.gateway for the spending limit and pricing.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.core import gateway

router = APIRouter(prefix="/gateway/v1", tags=["gateway"])


@router.post("/{path:path}")
async def forward(path: str, request: Request, authorization: str | None = Header(default=None),
                  x_jai_caller: str | None = Header(default=None)) -> JSONResponse:
    # Without JAI's gateway token nothing is answered: 401 whether the gateway is turned off or the token is wrong.
    if not gateway.token():
        return JSONResponse(gateway.GatewayRefused(401, "JAI's gateway is turned off (no JAI_GATEWAY_TOKEN).",
                                                   "not_configured").body(), status_code=401)
    if not gateway.authorised(authorization):
        return JSONResponse(gateway.GatewayRefused(401, "Not JAI's gateway token.", "invalid_api_key").body(),
                            status_code=401)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(gateway.GatewayRefused(400, "The request body must be JSON.").body(), status_code=400)
    try:
        status, answer = await gateway.forward(path.strip("/"), body, caller=(x_jai_caller or "service")[:40])
    except gateway.GatewayRefused as refused:
        return JSONResponse(refused.body(), status_code=refused.status)
    return JSONResponse(answer, status_code=status)


# Anthropic's Messages API, for JAI's engineering sandbox (OpenHands thinking with Claude Opus 5.5). LiteLLM sends
# JAI's gateway token as x-api-key, the way it sends an Anthropic key.
anthropic_router = APIRouter(prefix="/gateway/anthropic/v1", tags=["gateway"])


@anthropic_router.post("/messages")
async def anthropic_messages(request: Request, x_api_key: str | None = Header(default=None),
                             authorization: str | None = Header(default=None),
                             anthropic_version: str | None = Header(default=None),
                             anthropic_beta: str | None = Header(default=None),
                             x_jai_caller: str | None = Header(default=None)) -> JSONResponse:
    if not gateway.token():
        return JSONResponse(gateway.GatewayRefused(401, "JAI's gateway is turned off (no JAI_GATEWAY_TOKEN).",
                                                   "not_configured").body(), status_code=401)
    if not (gateway.authorised(x_api_key) or gateway.authorised(authorization)):
        return JSONResponse(gateway.GatewayRefused(401, "Not JAI's gateway token.", "authentication_error").body(),
                            status_code=401)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(gateway.GatewayRefused(400, "The request body must be JSON.").body(), status_code=400)
    try:
        status, answer = await gateway.forward_anthropic(body, anthropic_version, anthropic_beta,
                                                         caller=(x_jai_caller or "sandbox")[:40])
    except gateway.GatewayRefused as refused:
        return JSONResponse(refused.body(), status_code=refused.status)
    return JSONResponse(answer, status_code=status)
