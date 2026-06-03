"""
JARV Local Runner - Authentication

Secure token authentication between backend and local runner.
"""
import secrets
import hashlib
from typing import Optional
from pathlib import Path
import json
import logging

from runner.config import settings

logger = logging.getLogger(__name__)


class TokenManager:
    """
    Manages authentication tokens.

    Stores and validates secure tokens for backend-runner communication.
    """

    def __init__(self):
        """Initialize token manager"""
        self.token_file = Path.home() / ".jarv" / "runner_token.json"
        self.token_file.parent.mkdir(parents=True, exist_ok=True)

    def generate_token(self) -> str:
        """
        Generate secure authentication token.

        Returns:
            Secure token string
        """
        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)

        # Store token hash
        self._store_token_hash(token_hash)

        logger.info("Generated new authentication token")
        return token

    def _hash_token(self, token: str) -> str:
        """
        Hash token for secure storage.

        Args:
            token: Raw token

        Returns:
            Token hash
        """
        return hashlib.sha256(token.encode()).hexdigest()

    def _store_token_hash(self, token_hash: str):
        """
        Store token hash to file.

        Args:
            token_hash: Hashed token
        """
        data = {
            "token_hash": token_hash,
            "created_at": None,  # Add timestamp if needed
        }

        with open(self.token_file, 'w') as f:
            json.dump(data, f, indent=2)

        # Set restrictive permissions (owner read/write only)
        self.token_file.chmod(0o600)

    def _load_token_hash(self) -> Optional[str]:
        """
        Load token hash from file.

        Returns:
            Token hash or None
        """
        if not self.token_file.exists():
            return None

        try:
            with open(self.token_file, 'r') as f:
                data = json.load(f)
                return data.get("token_hash")
        except Exception as e:
            logger.error(f"Failed to load token: {e}")
            return None

    def verify_token(self, token: str) -> bool:
        """
        Verify authentication token.

        Args:
            token: Token to verify

        Returns:
            True if valid, False otherwise
        """
        stored_hash = self._load_token_hash()
        if not stored_hash:
            logger.warning("No stored token found")
            return False

        token_hash = self._hash_token(token)
        return secrets.compare_digest(token_hash, stored_hash)


# Global token manager
_token_manager = TokenManager()


def verify_token(token: str) -> bool:
    """
    Verify authentication token.

    Args:
        token: Token to verify

    Returns:
        True if valid, False otherwise
    """
    # Check if using development mode with fixed token
    if settings.DEV_MODE and token == settings.DEV_TOKEN:
        return True

    return _token_manager.verify_token(token)


def generate_token() -> str:
    """
    Generate new authentication token.

    Returns:
        Secure token string
    """
    return _token_manager.generate_token()
