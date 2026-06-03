# JARV Backend

FastAPI backend for the JARV Agentic AI System.

## Tech Stack

- Python 3.11+
- FastAPI
- Pydantic v2
- SQLAlchemy 2.0
- Alembic
- PostgreSQL with pgvector
- Redis
- Celery workers
- WebSockets
- JWT authentication

## Development

```bash
# Install dependencies
poetry install

# Run development server
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run database migrations
poetry run alembic upgrade head

# Create new migration
poetry run alembic revision --autogenerate -m "description"

# Run tests
poetry run pytest

# Format code
poetry run black .
poetry run ruff check .
```

## Environment Variables

Create a `.env` file (see `.env.example` for all options):

```
DATABASE_URL=postgresql://user:password@localhost:5432/jarv
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key-here-min-32-chars
JWT_SECRET_KEY=your-jwt-secret-key
CLAUDE_API_KEY=your-claude-api-key
OPENAI_API_KEY=your-openai-api-key (optional)
GEMINI_API_KEY=your-gemini-api-key (optional)
```

## Authentication Setup

After setting up the database and Redis, create an admin user:

```bash
# Interactive mode (will prompt for password)
poetry run python scripts/setup_admin.py

# Or with arguments
poetry run python scripts/setup_admin.py --username admin --password YourSecurePassword123!
```

## Project Structure

```
app/
├── api/           # API endpoints
│   ├── auth.py    # Authentication
│   └── health.py  # Health checks
├── core/          # Core functionality
│   ├── auth.py    # Auth dependencies
│   ├── celery.py  # Celery config
│   ├── config.py  # Settings
│   ├── database.py # Database
│   ├── redis.py   # Redis
│   └── security.py # JWT & passwords
├── models/        # SQLAlchemy models (Phase 2)
├── schemas/       # Pydantic schemas
│   └── auth.py    # Auth schemas
├── workers/       # Background workers
│   └── tasks.py   # Celery tasks
└── main.py        # FastAPI application

scripts/
├── db.py          # Database management
├── setup_admin.py # Admin user creation
├── test_worker.py # Worker testing
├── worker.sh      # Worker startup
└── scheduler.sh   # Scheduler startup
```

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
