"""
Unit tests for security functions
"""
import pytest
from app.core.security import (
    create_access_token,
    verify_password,
    get_password_hash,
)


@pytest.mark.unit
@pytest.mark.security
def test_password_hashing():
    """Test password hashing and verification"""
    password = "test_password_123!"
    hashed = get_password_hash(password)

    # Hash should not equal plaintext
    assert hashed != password

    # Verification should succeed
    assert verify_password(password, hashed) is True

    # Wrong password should fail
    assert verify_password("wrong_password", hashed) is False


@pytest.mark.unit
@pytest.mark.security
def test_password_hash_different_each_time():
    """Test that hashing same password produces different hashes"""
    password = "same_password"
    hash1 = get_password_hash(password)
    hash2 = get_password_hash(password)

    # Hashes should be different (due to salt)
    assert hash1 != hash2

    # But both should verify correctly
    assert verify_password(password, hash1) is True
    assert verify_password(password, hash2) is True


@pytest.mark.unit
@pytest.mark.security
def test_create_access_token():
    """Test JWT token creation"""
    data = {"sub": "testuser", "role": "user"}
    token = create_access_token(data)

    assert token is not None
    assert isinstance(token, str)
    assert len(token) > 0

    # Token should have 3 parts (header.payload.signature)
    parts = token.split(".")
    assert len(parts) == 3


@pytest.mark.unit
@pytest.mark.security
def test_token_with_expiration():
    """Test token creation with custom expiration"""
    from datetime import timedelta

    data = {"sub": "testuser"}
    token = create_access_token(data, expires_delta=timedelta(minutes=15))

    assert token is not None
    assert isinstance(token, str)


@pytest.mark.unit
@pytest.mark.security
def test_empty_password_handling():
    """Test handling of empty passwords"""
    # Empty password should still hash
    hashed = get_password_hash("")
    assert hashed is not None

    # But verification should work correctly
    assert verify_password("", hashed) is True
    assert verify_password("nonempty", hashed) is False


@pytest.mark.unit
@pytest.mark.security
def test_special_characters_in_password():
    """Test passwords with special characters"""
    special_passwords = [
        "p@ssw0rd!",
        "test#password$",
        "pass%word^123",
        "unicode→password",
    ]

    for password in special_passwords:
        hashed = get_password_hash(password)
        assert verify_password(password, hashed) is True
        assert verify_password(password + "x", hashed) is False


@pytest.mark.unit
@pytest.mark.security
def test_long_password():
    """Test very long password"""
    long_password = "a" * 1000
    hashed = get_password_hash(long_password)

    assert verify_password(long_password, hashed) is True
    assert verify_password(long_password[:-1], hashed) is False
