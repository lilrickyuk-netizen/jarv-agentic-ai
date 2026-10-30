"""
JARV Backend - Authentication Dependencies

FastAPI dependencies for authentication and authorization.
"""
import logging
from typing import Optional, Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_token
from app.core.redis import get_redis
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)


async def get_token_subject(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    redis: Annotated[Redis, Depends(get_redis)]
) -> str:
    """
    The verified token subject (the login store's user id, e.g. "admin_richard").

    Args:
        credentials: HTTP Bearer credentials
        redis: Redis client for token blacklist checking

    Returns:
        User ID from token

    Raises:
        HTTPException: If token is invalid or missing
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Check if token is blacklisted (logout)
    is_blacklisted = await redis.get(f"blacklist:token:{token}")
    if is_blacklisted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify and decode token
    payload = verify_token(token, token_type="access")
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_id


async def get_current_user_id(
    subject: Annotated[str, Depends(get_token_subject)],
    redis: Annotated[Redis, Depends(get_redis)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> str:
    """The caller's persisted user id (a UUID string) for ownership checks.

    Operators log in through the login store, whose ids are names such as
    "admin_richard"; workspaces, missions, memories and approvals are owned by
    rows in the users table. ``resolve_user_id`` links the two (see below)."""
    return str(await resolve_user_id(db, redis, subject))


async def resolve_user_id(db: AsyncSession, redis: Redis, subject: str) -> "UUID":
    """Map a token subject to a users-table id, creating the row on first use.

    - A UUID subject is already a users-table id.
    - An administrator is JARV's owner: the earliest persisted user, which is
      the account JARV has always assigned new workspaces to. When no user
      exists yet, the owner row is created for this administrator.
    - Any other login gets its own user row with a stable id.
    The mapping is cached in Redis.
    """
    from datetime import datetime, timezone
    from uuid import NAMESPACE_DNS, UUID, uuid5

    from sqlalchemy import select

    from app.models.user import User as UserRow

    try:
        return UUID(str(subject))
    except ValueError:
        pass
    cache_key = f"identity:{subject}"
    cached = await redis.get(cache_key)
    if cached:
        try:
            cached_id = UUID(cached)
            if (await db.execute(select(UserRow.id).where(UserRow.id == cached_id))).scalar_one_or_none():
                return cached_id
        except ValueError:
            pass
    is_admin = (await redis.get(f"user:{subject}:admin")) == "true"
    user_id = None
    if is_admin:
        user_id = (await db.execute(
            select(UserRow.id).order_by(UserRow.created_at.asc()).limit(1))).scalar_one_or_none()
    if user_id is None:
        user_id = uuid5(NAMESPACE_DNS, f"jarv-user-{subject}")
        if (await db.execute(select(UserRow.id).where(UserRow.id == user_id))).scalar_one_or_none() is None:
            now = datetime.now(timezone.utc)
            name = f"{str(subject)[:40]}-{user_id.hex[:6]}"
            db.add(UserRow(id=user_id, username=name, email=f"{user_id.hex[:12]}@operators.jarv.local",
                           password_hash="!", is_active=True, is_admin=is_admin,
                           created_at=now, updated_at=now))
            await db.commit()
            logger.info(f"Created user record for login '{name}'")
    await redis.set(cache_key, str(user_id))
    return user_id


async def get_current_admin_user(
    user_id: Annotated[str, Depends(get_token_subject)],
    redis: Annotated[Redis, Depends(get_redis)]
) -> str:
    """
    Get current authenticated admin user.

    Args:
        user_id: Current user ID
        redis: Redis client for checking admin status

    Returns:
        Admin user ID

    Raises:
        HTTPException: If user is not an admin
    """
    # The admin flag lives in the Redis user store beside the operator's credentials.
    is_admin = await redis.get(f"user:{user_id}:admin")

    if not is_admin or is_admin != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )

    return user_id


# Type aliases for dependency injection
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
TokenSubject = Annotated[str, Depends(get_token_subject)]
CurrentAdminUserId = Annotated[str, Depends(get_current_admin_user)]
