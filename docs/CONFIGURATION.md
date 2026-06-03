# JARV Configuration Guide

Complete configuration guide for JARV Agentic AI System.

## Environment Files

JARV uses environment variables for configuration. Several example files are provided:

- `.env.example` - Development configuration template
- `.env.production.example` - Production configuration template
- `apps/dashboard/.env.local.example` - Frontend-specific configuration

## Setup

### Development

```bash
# Copy example file
cp .env.example .env

# Edit with your values
nano .env

# Required minimum configuration
POSTGRES_PASSWORD=secure_password
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET_KEY=$(openssl rand -hex 32)
RUNNER_TOKEN=$(openssl rand -hex 32)
CLAUDE_API_KEY=your_claude_key
```

### Production

```bash
# Copy production example
cp .env.production.example .env

# Generate secure keys
openssl rand -hex 32  # Use for SECRET_KEY
openssl rand -hex 32  # Use for JWT_SECRET_KEY
openssl rand -hex 32  # Use for RUNNER_TOKEN

# Configure production values
# See .env.production.example for all required settings
```

## Configuration Categories

### Database Configuration

```env
POSTGRES_USER=jarv
POSTGRES_PASSWORD=secure_password
POSTGRES_DB=jarv
DATABASE_URL=postgresql://user:pass@host:5432/db
DATABASE_POOL_SIZE=20
```

### Redis Configuration

```env
REDIS_URL=redis://localhost:6379/0
REDIS_MAX_CONNECTIONS=50
```

### Security Configuration

```env
SECRET_KEY=your-32-char-secret-key
JWT_SECRET_KEY=your-jwt-secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

### LLM Provider Configuration

```env
# Claude (Primary - Required)
CLAUDE_API_KEY=your_claude_api_key

# Optional providers
OPENAI_API_KEY=your_openai_key
GEMINI_API_KEY=your_gemini_key
OLLAMA_BASE_URL=http://localhost:11434
```

### Authority Configuration

```env
DEFAULT_AUTHORITY_LEVEL=3  # 1-7
AUTO_STAGING_DEPLOY=false
AUTO_PRODUCTION_REPAIR=false
```

Authority levels:
1. Read Only
2. Edit Workspace Files
3. Build and Test
4. Install Approved Tools
5. Staging Deploy
6. Production Repair
7. Live Release

### Swarm Configuration

```env
SWARM_ENABLED=true
MAX_SUBAGENTS_PER_WORKSPACE=10
MAX_SUBAGENTS_GLOBAL=50
SUBAGENT_TIMEOUT=3600
```

### Self-Evolution Configuration

```env
SELF_EVOLUTION_ENABLED=true
AUTO_APPROVE_SAFE_EVOLUTION=false
```

### Local Runner Configuration

```env
LOCAL_RUNNER_PORT=8001
RUNNER_TOKEN=secure_token
APPROVED_FOLDERS=/path/to/projects,/path/to/workspaces
BANNED_FOLDERS=/path/to/banking,/path/to/crypto
```

### Voice Configuration

```env
VOICE_ENABLED=false
STT_PROVIDER=whisper
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your_key
```

### Monitoring and Logging

```env
AUDIT_LOGGING_ENABLED=true
BOUNDARY_REPORTING_ENABLED=true
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_RETENTION_DAYS=90
```

### Backup Configuration

```env
AUTO_BACKUP_ENABLED=true
BACKUP_SCHEDULE=0 2 * * *
BACKUP_RETENTION_DAYS=30
```

### Email Configuration

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email
SMTP_PASSWORD=your_password
SMTP_FROM=noreply@your-domain.com
```

## Backend Configuration

The backend uses Pydantic Settings for type-safe configuration.

**Location**: `apps/backend/app/core/config.py`

**Usage**:
```python
from app.core.config import settings

# Access settings
database_url = settings.DATABASE_URL
is_production = settings.is_production
```

**Features**:
- Automatic environment variable loading
- Type validation with Pydantic
- Default values
- Computed properties
- Environment-specific helpers

## Frontend Configuration

The frontend uses type-safe environment access.

**Location**: `apps/dashboard/src/lib/env.ts`

**Usage**:
```typescript
import { env } from '@/lib/env';

// Access settings
const apiUrl = env.apiUrl;
const isDevelopment = env.isDevelopment;
```

**Features**:
- Type-safe environment variables
- Runtime validation
- Default values
- Environment helpers

## Local Runner Configuration

**Location**: `services/local-runner/runner/config.py`

**Features**:
- File system access control
- Command execution limits
- Security boundaries
- Audit logging

## Workers Configuration

**Location**: `services/workers/workers/config.py`

**Features**:
- Celery configuration
- Task timeouts and retries
- Worker-specific settings
- Schedule configuration

## Security Best Practices

### Secret Generation

```bash
# Generate secure random keys
openssl rand -hex 32

# Or use Python
python -c "import secrets; print(secrets.token_hex(32))"
```

### Environment-Specific Secrets

Use different secrets for each environment:
- Development: Simple keys for testing
- Staging: Separate keys from production
- Production: Strong, unique keys

### Secret Management

For production, consider using:
- AWS Secrets Manager
- HashiCorp Vault
- Azure Key Vault
- Environment variables in hosting platform

### Never Commit Secrets

Ensure `.env` files are in `.gitignore`:
```gitignore
.env
.env.local
.env.*.local
```

## Configuration Validation

### Backend

Configuration is validated on startup:
```python
from app.core.config import settings

# This will raise validation errors if configuration is invalid
settings.validate()
```

### Frontend

Environment variables are validated when accessed:
```typescript
import { env } from '@/lib/env';

// Throws error if NEXT_PUBLIC_API_URL is not set
const apiUrl = env.apiUrl;
```

## Environment-Specific Configuration

### Development

```env
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG
HOT_RELOAD=true
```

### Staging

```env
ENVIRONMENT=staging
DEBUG=false
LOG_LEVEL=INFO
AUTO_STAGING_DEPLOY=true
```

### Production

```env
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=WARNING
AUTO_PRODUCTION_REPAIR=false
```

## Configuration Override Order

Configuration is loaded in this order (later overrides earlier):

1. Default values in code
2. `.env` file
3. Environment-specific `.env.{ENVIRONMENT}` file
4. System environment variables
5. Command-line arguments (where applicable)

## Troubleshooting

### Missing Environment Variables

If you see "Missing environment variable" errors:

1. Check `.env` file exists
2. Verify variable name matches exactly (case-sensitive)
3. Ensure no extra spaces around `=`
4. Check file is in correct location

### Invalid Configuration

If configuration validation fails:

1. Check value types match expected types
2. Verify URLs are properly formatted
3. Ensure numeric values are in valid ranges
4. Check boolean values are "true" or "false"

### Database Connection Issues

If database connection fails:

1. Verify DATABASE_URL format
2. Check database is running
3. Confirm credentials are correct
4. Test connection with psql or database client

## Docker Environment Variables

When using Docker, environment variables can be set in:

1. `.env` file (loaded by docker-compose)
2. `docker-compose.yml` environment section
3. `docker-compose.override.yml` for local overrides
4. Command line: `docker-compose run -e VAR=value`

See `DOCKER.md` for more details on Docker configuration.

## Further Reading

- [Docker Configuration](../DOCKER.md)
- [Backend README](../apps/backend/README.md)
- [Dashboard README](../apps/dashboard/README.md)
- [Local Runner README](../services/local-runner/README.md)
- [Workers README](../services/workers/README.md)
