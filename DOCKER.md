# JARV Docker Setup

Complete Docker configuration for running JARV Agentic AI System.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.0+
- 8GB+ RAM recommended
- 20GB+ disk space

## Services

The Docker Compose setup includes:

- **postgres**: PostgreSQL 15+ with pgvector extension
- **redis**: Redis 7 for caching and job queue
- **backend**: FastAPI backend (port 8000)
- **dashboard**: Next.js frontend (port 3000)
- **worker**: Celery worker for background tasks
- **scheduler**: Celery Beat for scheduled tasks
- **local-runner**: Local runner service (port 8001)
- **flower** (dev only): Celery monitoring UI (port 5555)

## Quick Start

### Production Mode

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Development Mode

```bash
# Start with hot reload
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Or use make
make dev
```

## Using Make Commands

```bash
make help      # Show all commands
make dev       # Development mode with hot reload
make up        # Production mode
make down      # Stop services
make build     # Build images
make rebuild   # Build without cache
make logs      # View logs
make clean     # Remove everything
make ps        # List running services
```

## Environment Variables

Create a `.env` file in the root directory:

```env
# Database
POSTGRES_USER=jarv
POSTGRES_PASSWORD=secure_password_here
POSTGRES_DB=jarv

# Redis
REDIS_URL=redis://redis:6379/0

# Backend
SECRET_KEY=your-secret-key-here
CLAUDE_API_KEY=your-claude-api-key
OPENAI_API_KEY=your-openai-api-key
GEMINI_API_KEY=your-gemini-api-key
ENVIRONMENT=production
LOG_LEVEL=INFO

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000

# Local Runner
RUNNER_TOKEN=secure-runner-token-here

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

## Service URLs

When running locally:

- Frontend Dashboard: http://localhost:3000
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- Local Runner: http://localhost:8001
- Flower (dev): http://localhost:5555

## Database Migrations

```bash
# Run migrations
docker-compose exec backend alembic upgrade head

# Create new migration
docker-compose exec backend alembic revision --autogenerate -m "description"
```

## Accessing Services

```bash
# Backend shell
docker-compose exec backend bash
make backend-shell

# Dashboard shell
docker-compose exec dashboard sh
make dashboard-shell

# Worker shell
docker-compose exec worker bash
make worker-shell

# Database shell
docker-compose exec postgres psql -U jarv -d jarv
make db-shell

# Redis shell
docker-compose exec redis redis-cli
make redis-shell
```

## Running Tests

```bash
# Run all tests
make test

# Run backend tests
docker-compose exec backend pytest

# Run worker tests
docker-compose exec worker pytest
```

## Monitoring

### Check Service Health

```bash
docker-compose ps
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f worker
```

### Monitor Celery Tasks (Development)

Visit http://localhost:5555 when running in development mode.

## Volumes

Persistent data is stored in Docker volumes:

- `postgres_data`: PostgreSQL database
- `redis_data`: Redis persistence

## Troubleshooting

### Services won't start

```bash
# Check service status
docker-compose ps

# View logs
docker-compose logs

# Rebuild images
docker-compose build --no-cache
```

### Database connection issues

```bash
# Check if postgres is healthy
docker-compose ps postgres

# Access database
docker-compose exec postgres psql -U jarv -d jarv
```

### Clear everything and start fresh

```bash
# WARNING: This removes all data
make clean
docker-compose up -d
```

## Production Deployment

For production deployment:

1. Set strong passwords in `.env`
2. Use proper SECRET_KEY (generate with `openssl rand -hex 32`)
3. Set ENVIRONMENT=production
4. Configure proper volumes for data persistence
5. Set up proper SSL/TLS certificates
6. Use a reverse proxy (nginx) in front of services
7. Configure proper backup strategies
8. Set up monitoring and alerting

## Network

All services communicate on the `jarv-network` bridge network.

## Health Checks

All services have health checks configured:
- Backend: HTTP check on `/health`
- Dashboard: HTTP check on `/api/health`
- Postgres: `pg_isready`
- Redis: `redis-cli ping`
- Worker: Celery inspect ping

## Resource Limits

Consider adding resource limits in production:

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M
```
