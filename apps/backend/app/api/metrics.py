"""
JARV Backend - Metrics endpoint

``GET /metrics`` in the Prometheus text format. When ``METRICS_TOKEN`` is set,
scrapers must send ``Authorization: Bearer <token>``. The production nginx
configuration does not route ``/metrics`` to the public internet; Prometheus
scrapes the backend directly on the private network.
"""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.observability.metrics import render

router = APIRouter(tags=["observability"])

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _authorise(authorization: str | None) -> None:
    token = (getattr(settings, "METRICS_TOKEN", "") or "").strip()
    if not token:
        return
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail="Metrics token required")


@router.get("/metrics", include_in_schema=False)
async def metrics(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    _authorise(authorization)
    return PlainTextResponse(await render(db), media_type=CONTENT_TYPE)
