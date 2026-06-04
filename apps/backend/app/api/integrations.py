"""
JARV Backend - External Integrations API

Surfaces the outbound-integration registry and a safe dry-run send path. Live
sends require credentials and approval; missing credentials show a disabled
state instead of failing.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import CurrentUserId
from app.core.integrations import integrations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


class NotifyRequest(BaseModel):
    target: str = "local_mock"
    message: str = "JARV test notification (dry-run)."
    dry_run: bool = True


@router.get("/list")
async def list_integrations() -> List[Dict[str, Any]]:
    """List registered outbound integrations and their live readiness."""
    return integrations.list()


@router.post("/notify")
async def notify(req: NotifyRequest, operator: CurrentUserId) -> Dict[str, Any]:
    """Send a notification (dry-run by default; live send requires config + approval)."""
    return await integrations.send(req.target, req.message, dry_run=req.dry_run)
