"""
JARV Backend - External Integrations API

Surfaces the notification targets and sends to the signed-in operator: a dry
run by default, a live email or webhook when configured, and the disabled
state with its setup line when not.
"""
import logging
from typing import Any, Dict, List, Optional

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.database import get_db
from app.core.integrations import integrations
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


class NotifyRequest(BaseModel):
    target: str = "local_mock"
    message: str = "JARV test notification (dry-run)."
    dry_run: bool = True


@router.get("/list")
async def list_integrations(_operator: CurrentUserId) -> List[Dict[str, Any]]:
    """List registered outbound integrations and their live readiness."""
    return integrations.list()


@router.post("/notify")
async def notify(req: NotifyRequest, operator: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Notify the signed-in operator (dry-run by default). Pressing send here is the operator's own approval."""
    address = (await db.execute(select(User.email).where(User.id == UUID(str(operator))))).scalar_one_or_none()
    return await integrations.send(req.target, req.message, dry_run=req.dry_run, operator_email=address)
