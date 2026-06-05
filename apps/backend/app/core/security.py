"""
JARV Backend - Security Utilities

Password hashing, JWT token generation and validation.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
import bcrypt

from app.core.config import settings

logger = logging.getLogger(__name__)


# ===== Secret Redaction =====
#
# Central redaction used before writing tool input/output and audit/ToolRun
# records, so raw secrets are never persisted to logs. Redacts by value pattern
# (API keys, bearer tokens, JWTs, private keys, DB URLs with passwords, etc.)
# and by sensitive key name (password/secret/token/...). Non-secret context is
# preserved.

REDACTED = "[REDACTED]"

# Dict/JSON keys whose VALUE must always be redacted regardless of content.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|apikey|authorization|auth|"
    r"private[_-]?key|access[_-]?key|secret[_-]?key|refresh[_-]?token|"
    r"client[_-]?secret|webhook[_-]?secret|credential|session[_-]?key)"
)

# Value patterns that look like secrets even under a non-sensitive key.
_VALUE_PATTERNS = [
    # JWT (header.payload.signature)
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    # PEM private key blocks
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    # Bearer / token auth headers
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{10,}"),
    # OpenAI-style and generic prefixed keys
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    # AWS access key id + secret
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Database / broker URLs that embed credentials: scheme://user:pass@host
    re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]+@[^\s]+"),
    # key=secret / key: secret style assignments (.env-ish), value >= 8 chars
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|refresh[_-]?token|client[_-]?secret|webhook[_-]?secret)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
]


def redact_text(value: str) -> str:
    """Redact secret-looking substrings from a single string."""
    if not isinstance(value, str) or not value:
        return value
    redacted = value
    for pat in _VALUE_PATTERNS:
        redacted = pat.sub(REDACTED, redacted)
    return redacted


def redact_value(value: Any, _key: Optional[str] = None, _depth: int = 0) -> Any:
    """Recursively redact secrets from a value (str/dict/list/scalars).

    If the value is under a sensitive key name, it is fully redacted. Otherwise
    secret-looking substrings are masked. Recursion is depth-limited to stay safe
    on deeply-nested structures.
    """
    if _key is not None and isinstance(_key, str) and _SENSITIVE_KEY_RE.search(_key):
        # Whole value is sensitive by key name — never store it raw.
        return REDACTED
    if _depth > 12:
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(v, _key=str(k), _depth=_depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v, _key=_key, _depth=_depth + 1) for v in value]
    return value


def redact_secrets(data: Any) -> Any:
    """Public entry point: return a redacted copy of arbitrary data (no mutation)."""
    try:
        return redact_value(data)
    except Exception:  # noqa: BLE001 - redaction must never break the caller
        # Fail safe: if anything goes wrong, return a coarse marker rather than
        # leaking the raw value.
        return REDACTED


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.

    Args:
        plain_password: Plain text password
        hashed_password: Hashed password (bcrypt hash)

    Returns:
        True if password matches, False otherwise

    Note:
        bcrypt has a 72-byte limit. Passwords longer than 72 bytes
        are truncated to maintain compatibility.
    """
    # Truncate to 72 bytes to comply with bcrypt limit
    password_bytes = plain_password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]

    # bcrypt.checkpw requires bytes
    return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password (as string)

    Note:
        bcrypt has a 72-byte limit. Passwords longer than 72 bytes
        are truncated to maintain compatibility.
    """
    # Truncate to 72 bytes to comply with bcrypt limit
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]

    # Generate salt and hash
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)

    # Return as string
    return hashed.decode('utf-8')


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Data to encode in the token
        expires_delta: Optional expiration time delta

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire, "iat": datetime.utcnow()})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY or settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )

    return encoded_jwt


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT refresh token.

    Args:
        data: Data to encode in the token
        expires_delta: Optional expiration time delta

    Returns:
        Encoded JWT refresh token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh"
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY or settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )

    return encoded_jwt


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode and validate a JWT token.

    Args:
        token: JWT token to decode

    Returns:
        Decoded token payload or None if invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY or settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        return None


def verify_token(token: str, token_type: str = "access") -> Optional[Dict[str, Any]]:
    """
    Verify a JWT token and check its type.

    Args:
        token: JWT token to verify
        token_type: Expected token type ("access" or "refresh")

    Returns:
        Decoded token payload or None if invalid
    """
    payload = decode_token(token)

    if payload is None:
        return None

    # Check token type for refresh tokens
    if token_type == "refresh":
        if payload.get("type") != "refresh":
            logger.warning("Token type mismatch: expected refresh token")
            return None

    return payload
