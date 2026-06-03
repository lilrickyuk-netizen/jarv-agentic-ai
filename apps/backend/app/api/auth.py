"""
JARV Backend - Authentication Endpoints

Login, logout, token refresh, and password management.
"""
import logging
from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis

from app.core.redis import get_redis
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    verify_token,
)
from app.core.auth import CurrentUserId
from app.core.config import settings
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    LogoutRequest,
    PasswordChangeRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Login",
    description="Authenticate user and return access and refresh tokens"
)
async def login(
    credentials: LoginRequest,
    redis: Annotated[Redis, Depends(get_redis)]
) -> TokenResponse:
    """
    Login endpoint for admin authentication.

    For this initial phase, we use a simple Redis-based user store.
    In Phase 2, this will be replaced with database models.

    Args:
        credentials: Login credentials (username and password)
        redis: Redis client

    Returns:
        Access and refresh tokens

    Raises:
        HTTPException: If credentials are invalid
    """
    # Get user from Redis (temporary solution for Phase 1)
    user_data = await redis.hgetall(f"user:{credentials.username}")

    if not user_data:
        logger.warning(f"Login attempt for non-existent user: {credentials.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Verify password
    stored_password_hash = user_data.get("password_hash", "")
    if not verify_password(credentials.password, stored_password_hash):
        logger.warning(f"Failed login attempt for user: {credentials.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    user_id = user_data.get("user_id", credentials.username)

    # Create tokens
    token_data = {"sub": user_id, "username": credentials.username}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Store refresh token in Redis with expiration
    await redis.setex(
        f"refresh_token:{user_id}",
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        refresh_token
    )

    logger.info(f"User logged in: {credentials.username}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh Token",
    description="Get new access token using refresh token"
)
async def refresh_token(
    request: RefreshTokenRequest,
    redis: Annotated[Redis, Depends(get_redis)]
) -> TokenResponse:
    """
    Refresh access token using a valid refresh token.

    Args:
        request: Refresh token request
        redis: Redis client

    Returns:
        New access and refresh tokens

    Raises:
        HTTPException: If refresh token is invalid
    """
    # Verify refresh token
    payload = verify_token(request.refresh_token, token_type="refresh")
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user_id = payload.get("sub")
    username = payload.get("username")

    # Verify refresh token is still valid in Redis
    stored_token = await redis.get(f"refresh_token:{user_id}")
    if stored_token != request.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Create new tokens
    token_data = {"sub": user_id, "username": username}
    access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(token_data)

    # Update refresh token in Redis
    await redis.setex(
        f"refresh_token:{user_id}",
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        new_refresh_token
    )

    logger.info(f"Token refreshed for user: {username}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout",
    description="Logout user and revoke tokens"
)
async def logout(
    user_id: CurrentUserId,
    request: LogoutRequest,
    redis: Annotated[Redis, Depends(get_redis)]
) -> dict:
    """
    Logout endpoint to revoke access and refresh tokens.

    Args:
        user_id: Current authenticated user ID
        request: Logout request with access token
        redis: Redis client

    Returns:
        Success message
    """
    # Blacklist the access token
    await redis.setex(
        f"blacklist:token:{request.access_token}",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "true"
    )

    # Delete refresh token
    await redis.delete(f"refresh_token:{user_id}")

    logger.info(f"User logged out: {user_id}")

    return {"message": "Successfully logged out"}


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Current User",
    description="Get current authenticated user information"
)
async def get_current_user(
    user_id: CurrentUserId,
    redis: Annotated[Redis, Depends(get_redis)]
) -> UserResponse:
    """
    Get current authenticated user information.

    Args:
        user_id: Current authenticated user ID
        redis: Redis client

    Returns:
        User information
    """
    # Get user data from Redis
    user_key = None

    # Find user by user_id
    for key in await redis.keys("user:*"):
        data = await redis.hgetall(key)
        if data.get("user_id") == user_id:
            user_key = key
            break

    if not user_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user_data = await redis.hgetall(user_key)
    is_admin = await redis.get(f"user:{user_id}:admin")

    return UserResponse(
        user_id=user_id,
        username=user_data.get("username", user_id),
        is_admin=is_admin == "true" if is_admin else False,
        created_at=user_data.get("created_at"),
    )


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change Password",
    description="Change user password"
)
async def change_password(
    user_id: CurrentUserId,
    request: PasswordChangeRequest,
    redis: Annotated[Redis, Depends(get_redis)]
) -> dict:
    """
    Change user password.

    Args:
        user_id: Current authenticated user ID
        request: Password change request
        redis: Redis client

    Returns:
        Success message

    Raises:
        HTTPException: If current password is incorrect
    """
    # Find user by user_id
    user_key = None
    for key in await redis.keys("user:*"):
        data = await redis.hgetall(key)
        if data.get("user_id") == user_id:
            user_key = key
            break

    if not user_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user_data = await redis.hgetall(user_key)

    # Verify current password
    stored_password_hash = user_data.get("password_hash", "")
    if not verify_password(request.current_password, stored_password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect current password",
        )

    # Update password
    new_password_hash = get_password_hash(request.new_password)
    await redis.hset(user_key, "password_hash", new_password_hash)

    logger.info(f"Password changed for user: {user_id}")

    return {"message": "Password changed successfully"}
