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


async def get_current_user_id(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
    redis: Annotated[Redis, Depends(get_redis)]
) -> str:
    """
    Get current authenticated user ID from JWT token.

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


async def get_current_admin_user(
    user_id: Annotated[str, Depends(get_current_user_id)],
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
    # Check if user is admin (stored in Redis for now, will use DB in Phase 2)
    is_admin = await redis.get(f"user:{user_id}:admin")

    if not is_admin or is_admin != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )

    return user_id


# Type aliases for dependency injection
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
CurrentAdminUserId = Annotated[str, Depends(get_current_admin_user)]


# Simple User model for API dependencies
from pydantic import BaseModel
from uuid import UUID


class User(BaseModel):
    """Simple user model for API dependencies"""
    id: UUID
    email: str
    username: str
    workspace_id: Optional[UUID] = None


async def get_current_user(
    user_id: Annotated[str, Depends(get_current_user_id)],
) -> User:
    """
    Get current authenticated user object.

    Args:
        user_id: Current user ID from token

    Returns:
        User object with basic info

    Note:
        In production, this would fetch user from database.
        For now, returns a simple user object with ID.
    """
    from uuid import UUID, uuid5, NAMESPACE_DNS

    # Operators authenticate via the Redis user store, where the token subject is
    # a username-derived id (e.g. "admin_richard"), not a UUID. Coerce it to a
    # stable UUID (uuid5) so endpoints that type user.id as UUID work for any
    # authenticated operator instead of 500-ing.
    try:
        uid = UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        uid = uuid5(NAMESPACE_DNS, f"jarv-user-{user_id}")

    return User(
        id=uid,
        email=f"user-{str(user_id)[:8]}@jarv.ai",
        username=f"user-{str(user_id)[:8]}",
        workspace_id=None,
    )
