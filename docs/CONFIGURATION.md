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

### Memory Embedding Configuration

Every memory is embedded on write and searched by semantic similarity plus
keyword overlap. No key is needed: by default JARV uses its built-in local
embedder (`jarv-hash-v1`), which runs offline and matches word, phrase, and
sub-word overlap. Set a provider for neural embeddings that also match
synonyms.

```env
# auto (default): openai when OPENAI_API_KEY is set, otherwise local
EMBEDDING_PROVIDER=auto        # auto | local | openai | ollama | custom
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536      # must stay 1536 (the memories.embedding column size)
CUSTOM_EMBEDDING_ENDPOINT=     # only for EMBEDDING_PROVIDER=custom
```

Vectors from different models are never compared. Each row records the model
that produced it; after changing provider, existing rows stay keyword-searchable
and can be re-embedded with `memory_service.backfill_embeddings`.

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
VOICEBOX_BASE_URL=http://voicebox:17493
VOICEBOX_PROFILE_ID=
VOICEBOX_CONNECT_TIMEOUT_SECONDS=3
VOICEBOX_READ_TIMEOUT_SECONDS=180
VOICEBOX_MAX_AUDIO_BYTES=26214400
WAKEWORD_MODEL_DIR=/data/voice-models/sherpa-kws-gigaspeech
```

Voicebox is an optional CPU service in the private Compose network. Start it with
`docker compose --profile voice up -d --build voicebox`; do not publish its port,
because the upstream API has no authentication. JARV proxies authenticated
transcription, speech generation, status, cancellation, and audio requests.

After the backend and Voicebox are healthy, sign in as an administrator and use
the cockpit's **Set up JARV voice** action to create the persistent Kokoro
American-male profile. Use **Install wake model** to download and checksum-verify
the Apache-2.0 English sherpa-onnx model into `WAKEWORD_MODEL_DIR`. Browser
hands-free operation is opt-in: microphone access is requested explicitly and
16 kHz audio frames are sent to the self-hosted JARV detector while enabled. Use
**Update wake phrase** to regenerate and runtime-validate the installed keyword
file as “Talk to me”; disable hands-free before updating it. The local detector
and Voicebox Whisper recognizer accept “Talk to me” without a JARV prefix. After
the phrase, the captured instruction is sent through the normal authenticated
command/authority pipeline. Voicebox spoken replies can be interrupted by wake
detection or the explicit interrupt control.

Voicebox CPU inference is supported but can be slow, and the first speech
generation downloads the selected TTS model. Real microphone accuracy,
false-trigger rate, generated audio quality, and barge-in behavior still require
hands-on acceptance on the target browser and hardware.

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

Sending (support replies, the agents' `email_send` after approval, notifications to you) uses SMTP;
reading (the support inbox, `email_read`, `email_search`) uses IMAP, opened read-only. Leave them blank
to keep email off: messages are then saved as drafts. The older `EMAIL_SMTP_*` / `EMAIL_IMAP_*` names
are still read when these are unset.

```env
SMTP_HOST=smtp.your-provider.com
SMTP_PORT=587
SMTP_USER=you@your-domain.com
SMTP_PASSWORD=app-password-from-your-provider
SMTP_FROM=you@your-domain.com
IMAP_HOST=imap.your-provider.com
IMAP_PORT=993
IMAP_USER=you@your-domain.com
IMAP_PASSWORD=app-password-from-your-provider
IMAP_FOLDER=INBOX
NOTIFY_EMAIL=you@your-domain.com        # where JARV notifies you (defaults to your login email)
NOTIFY_WEBHOOK_URL=https://ntfy.sh/your-topic   # optional: Slack, Discord or ntfy webhook
```

The dashboard's Settings page shows which services are configured (never their values) and has a
Check button per service that tests the connection without sending or spending anything.

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
