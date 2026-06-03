"""
JARV Local Runner Configuration
"""
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class LocalRunnerSettings(BaseSettings):
    """Local Runner settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Service Configuration
    HOST: str = "127.0.0.1"
    PORT: int = 8001
    LOG_LEVEL: str = "INFO"

    # Backend Connection
    BACKEND_URL: str = "http://localhost:8000"

    # Authentication
    DEV_MODE: bool = False
    DEV_TOKEN: str = "dev-token-for-testing-only"

    # File System Access
    ALLOWED_FOLDERS: List[str] = Field(
        default_factory=lambda: [
            str(Path.home() / "Documents"),
            str(Path.home() / "Desktop"),
            str(Path.home() / "Downloads"),
            str(Path.cwd()),
        ]
    )

    # Command Execution
    BANNED_COMMANDS: List[str] = Field(
        default_factory=lambda: [
            "rm -rf",
            "del /f /s /q",
            "format",
            "shutdown",
            "reboot",
            "halt",
            "poweroff",
            "mkfs",
            "dd if=/dev/zero",
        ]
    )

    # Execution Limits
    COMMAND_TIMEOUT: int = 300  # 5 minutes
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100 MB

    # Security
    AUDIT_ENABLED: bool = True


# Global settings instance
settings = LocalRunnerSettings()
