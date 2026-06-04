"""
JARV Backend Configuration
Uses Pydantic Settings for environment variable management
"""
from typing import List, Optional
from pydantic import Field, PostgresDsn, RedisDsn, validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    PROJECT_NAME: str = "JARV Agentic AI System"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="development", pattern="^(development|staging|production)$")
    DEBUG: bool = False
    LOG_LEVEL: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    # Server
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    # Database
    POSTGRES_USER: str = "jarv"
    POSTGRES_PASSWORD: str = "jarv_password"
    POSTGRES_DB: str = "jarv"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: Optional[PostgresDsn] = None
    DATABASE_POOL_SIZE: int = 20

    @validator("DATABASE_URL", pre=True)
    def assemble_db_connection(cls, v: Optional[str], values: dict) -> str:
        if isinstance(v, str) and v:
            return v
        return f"postgresql://{values.get('POSTGRES_USER')}:{values.get('POSTGRES_PASSWORD')}@{values.get('POSTGRES_HOST')}:{values.get('POSTGRES_PORT')}/{values.get('POSTGRES_DB')}"

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_URL: Optional[RedisDsn] = None
    REDIS_MAX_CONNECTIONS: int = 50

    @validator("REDIS_URL", pre=True)
    def assemble_redis_connection(cls, v: Optional[str], values: dict) -> str:
        if isinstance(v, str) and v:
            return v
        return f"redis://{values.get('REDIS_HOST')}:{values.get('REDIS_PORT')}/{values.get('REDIS_DB')}"

    # Security
    SECRET_KEY: str = Field(..., min_length=32)  # Required, minimum 32 characters
    JWT_SECRET_KEY: str = Field(default_factory=lambda: "")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    SESSION_TIMEOUT_MINUTES: int = 60

    @validator("JWT_SECRET_KEY", pre=True)
    def set_jwt_secret(cls, v: Optional[str], values: dict) -> str:
        if v:
            return v
        return values.get("SECRET_KEY", "")

    # CORS
    CORS_ENABLED: bool = True

    # Rate Limiting
    RATE_LIMITING_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60

    # LLM Providers
    # ANTHROPIC_API_KEY is the canonical Anthropic env var name; declared before
    # CLAUDE_API_KEY so the fallback validator below can read it from `values`.
    ANTHROPIC_API_KEY: Optional[str] = None
    CLAUDE_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    @validator("CLAUDE_API_KEY", pre=True)
    def claude_key_from_anthropic(cls, v: Optional[str], values: dict) -> Optional[str]:
        # Honor the standard ANTHROPIC_API_KEY when CLAUDE_API_KEY is unset/empty,
        # so either environment variable name configures the Claude provider.
        if v:
            return v
        return values.get("ANTHROPIC_API_KEY") or None

    # Local Runner
    RUNNER_TOKEN: str = Field(default="dev-runner-token")
    APPROVED_FOLDERS: List[str] = Field(default_factory=list)
    BANNED_FOLDERS: List[str] = Field(default_factory=list)

    @validator("APPROVED_FOLDERS", pre=True)
    def parse_folders(cls, v):
        if isinstance(v, str):
            return [f.strip() for f in v.split(",") if f.strip()]
        return v or []

    @validator("BANNED_FOLDERS", pre=True)
    def parse_banned_folders(cls, v):
        if isinstance(v, str):
            return [f.strip() for f in v.split(",") if f.strip()]
        return v or []

    # Authority
    DEFAULT_AUTHORITY_LEVEL: int = Field(default=3, ge=1, le=7)
    AUTO_STAGING_DEPLOY: bool = False
    AUTO_PRODUCTION_REPAIR: bool = False

    # Swarm
    SWARM_ENABLED: bool = True
    MAX_SUBAGENTS_PER_WORKSPACE: int = 10
    MAX_SUBAGENTS_GLOBAL: int = 50
    SUBAGENT_TIMEOUT: int = 3600

    # Self-Evolution
    SELF_EVOLUTION_ENABLED: bool = True
    AUTO_APPROVE_SAFE_EVOLUTION: bool = False

    # Company Operator
    COMPANY_OPERATOR_ENABLED: bool = True

    # Self-Healing
    SELF_HEALING_ENABLED: bool = True

    # Logging and Monitoring
    AUDIT_LOGGING_ENABLED: bool = True
    BOUNDARY_REPORTING_ENABLED: bool = True
    LOG_RETENTION_DAYS: int = 90

    # Celery
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    CELERY_WORKER_CONCURRENCY: int = 4

    @validator("CELERY_BROKER_URL", pre=True)
    def set_celery_broker(cls, v: Optional[str], values: dict) -> str:
        # Follow REDIS_URL so the broker stays consistent with the cache
        # connection and is Docker-safe when REDIS_URL is overridden via env.
        # Always coerce to a plain string — Celery/Kombu cannot consume a
        # RedisDsn object. An explicit value is only used if REDIS_URL is unset.
        redis_url = values.get("REDIS_URL")
        if redis_url:
            return str(redis_url)
        if v:
            return str(v)
        return "redis://localhost:6379/0"

    @validator("CELERY_RESULT_BACKEND", pre=True)
    def set_celery_backend(cls, v: Optional[str], values: dict) -> str:
        # Follow REDIS_URL so the result backend stays consistent with the
        # cache connection and is Docker-safe when REDIS_URL is overridden via
        # env. Always coerce to a plain string — Celery/Kombu cannot consume a
        # RedisDsn object. An explicit value is only used if REDIS_URL is unset.
        redis_url = values.get("REDIS_URL")
        if redis_url:
            return str(redis_url)
        if v:
            return str(v)
        return "redis://localhost:6379/0"

    # Voice
    VOICE_ENABLED: bool = False
    STT_PROVIDER: str = "whisper"
    TTS_PROVIDER: str = "elevenlabs"
    ELEVENLABS_API_KEY: Optional[str] = None
    GOOGLE_CLOUD_API_KEY: Optional[str] = None
    AZURE_SPEECH_KEY: Optional[str] = None

    # Email
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: Optional[str] = None

    # External Services
    SENTRY_DSN: Optional[str] = None
    GITHUB_TOKEN: Optional[str] = None
    UNSPLASH_ACCESS_KEY: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None

    # Backup
    AUTO_BACKUP_ENABLED: bool = True
    BACKUP_SCHEDULE: str = "0 2 * * *"
    BACKUP_RETENTION_DAYS: int = 30

    # Feature Flags
    EXPERIMENTAL_FEATURES: bool = False

    # Development
    HOT_RELOAD: bool = False
    DEBUG_TOOLBAR: bool = False
    SEED_TEST_DATA: bool = False

    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development"""
        return self.ENVIRONMENT == "development"

    @property
    def is_staging(self) -> bool:
        """Check if running in staging"""
        return self.ENVIRONMENT == "staging"


# Global settings instance
settings = Settings()


# Export for convenience
__all__ = ["settings", "Settings"]
