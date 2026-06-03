"""
JARV Backend - Authentication Tests

Tests for authentication endpoints and utilities.
"""
import pytest
from datetime import timedelta

from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_token,
)


def test_password_hashing():
    """Test password hashing and verification"""
    password = "TestPassword123!"
    hashed = get_password_hash(password)

    # Hash should be different from original
    assert hashed != password

    # Verification should succeed
    assert verify_password(password, hashed) is True

    # Wrong password should fail
    assert verify_password("WrongPassword", hashed) is False


def test_create_access_token():
    """Test access token creation"""
    data = {"sub": "user123", "username": "testuser"}
    token = create_access_token(data)

    assert token is not None
    assert isinstance(token, str)
    assert len(token) > 0


def test_create_refresh_token():
    """Test refresh token creation"""
    data = {"sub": "user123", "username": "testuser"}
    token = create_refresh_token(data)

    assert token is not None
    assert isinstance(token, str)
    assert len(token) > 0


def test_decode_token():
    """Test token decoding"""
    data = {"sub": "user123", "username": "testuser"}
    token = create_access_token(data)

    payload = decode_token(token)

    assert payload is not None
    assert payload.get("sub") == "user123"
    assert payload.get("username") == "testuser"
    assert "exp" in payload
    assert "iat" in payload


def test_verify_access_token():
    """Test access token verification"""
    data = {"sub": "user123", "username": "testuser"}
    token = create_access_token(data)

    payload = verify_token(token, token_type="access")

    assert payload is not None
    assert payload.get("sub") == "user123"


def test_verify_refresh_token():
    """Test refresh token verification"""
    data = {"sub": "user123", "username": "testuser"}
    token = create_refresh_token(data)

    payload = verify_token(token, token_type="refresh")

    assert payload is not None
    assert payload.get("sub") == "user123"
    assert payload.get("type") == "refresh"


def test_verify_token_type_mismatch():
    """Test token type mismatch detection"""
    data = {"sub": "user123", "username": "testuser"}

    # Create access token but verify as refresh
    access_token = create_access_token(data)
    payload = verify_token(access_token, token_type="refresh")

    # Should fail because access token doesn't have type="refresh"
    assert payload is None


def test_decode_invalid_token():
    """Test decoding invalid token"""
    invalid_token = "invalid.token.here"
    payload = decode_token(invalid_token)

    assert payload is None
