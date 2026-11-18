"""
JAI Backend - What JAI has: its skill packs and skills, each department's skills, its tools and agents, the models
and workers missions use, and the upgrades installed, read live from its code (identity.inventory) for the
dashboard's Capabilities page. Reads only; nothing is spent.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from app.core.auth import CurrentUserId
from app.core.identity import inventory

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])


@router.get("")
async def capabilities(user_id: CurrentUserId) -> Dict[str, Any]:
    """Everything JAI has, as the Capabilities page shows it."""
    return await inventory.inventory()
