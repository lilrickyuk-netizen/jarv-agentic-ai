"""
JARV Workers Configuration
"""
from typing import Optional
from pydantic import Field, PostgresDsn, RedisDsn, validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkersSettings(BaseSettings):
    """Workers settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Database
    POSTGRES_USER: str = "jarv"
    POSTGRES_PASSWORD: str = "jarv_password"
    POSTGRES_DB: str = "jarv"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: Optional[PostgresDsn] = None

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

    @validator("REDIS_URL", pre=True)
    def assemble_redis_connection(cls, v: Optional[str], values: dict) -> str:
        if isinstance(v, str) and v:
            return v
        return f"redis://{values.get('REDIS_HOST')}:{values.get('REDIS_PORT')}/{values.get('REDIS_DB')}"

    # Celery
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    CELERY_WORKER_CONCURRENCY: int = 4
    CELERY_TASK_ALWAYS_EAGER: bool = False  # Set to True for synchronous testing
    CELERY_TASK_EAGER_PROPAGATES: bool = True

    @validator("CELERY_BROKER_URL", pre=True)
    def set_celery_broker(cls, v: Optional[str], values: dict) -> str:
        if v:
            return v
        return values.get("REDIS_URL", "redis://localhost:6379/0")

    @validator("CELERY_RESULT_BACKEND", pre=True)
    def set_celery_backend(cls, v: Optional[str], values: dict) -> str:
        if v:
            return v
        return values.get("REDIS_URL", "redis://localhost:6379/0")

    # Worker Configuration
    LOG_LEVEL: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    # Task Timeouts
    DEFAULT_TASK_TIMEOUT: int = 3600  # 1 hour
    LONG_TASK_TIMEOUT: int = 7200  # 2 hours
    SWARM_TASK_TIMEOUT: int = 3600  # 1 hour

    # Task Retry
    DEFAULT_MAX_RETRIES: int = 3
    DEFAULT_RETRY_DELAY: int = 60  # seconds

    # Company Operator
    COMPANY_OPERATOR_ENABLED: bool = True
    DAILY_LOOP_SCHEDULE: str = "0 9 * * *"  # 9 AM daily
    WEEKLY_PLAN_SCHEDULE: str = "0 9 * * 1"  # 9 AM Monday

    # Self-Evolution
    SELF_EVOLUTION_ENABLED: bool = True
    EVOLUTION_REVIEW_SCHEDULE: str = "0 2 * * *"  # 2 AM daily

    # Self-Healing
    SELF_HEALING_ENABLED: bool = True
    HEALTH_CHECK_INTERVAL: int = 300  # 5 minutes

    # Swarm
    SWARM_ENABLED: bool = True
    MAX_SUBAGENTS_PER_WORKSPACE: int = 10
    MAX_SUBAGENTS_GLOBAL: int = 50
    SUBAGENT_TIMEOUT: int = 3600

    # Monitoring
    MONITORING_INTERVAL: int = 60  # 1 minute

    # LLM Providers
    CLAUDE_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None

    # Feature Flags
    EXPERIMENTAL_FEATURES: bool = False


# Global settings instance
workers_settings = WorkersSettings()


# Export for convenience
__all__ = ["workers_settings", "WorkersSettings"]
