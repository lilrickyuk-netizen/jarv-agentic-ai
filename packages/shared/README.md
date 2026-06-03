# JARV Shared

Shared packages and utilities for JARV Agentic AI System.

## Purpose

This package contains shared code used across multiple JARV services:
- Common data models and schemas
- Shared utilities and helpers
- Constants and enums
- Type definitions
- Validation logic

## Structure

```
jarv_shared/
├── models/        # Shared Pydantic models
├── schemas/       # Shared schemas
├── utils/         # Shared utilities
├── constants.py   # System constants
└── types.py       # Type definitions
```

## Usage

Install as a dependency in other JARV services:

```bash
# In backend, workers, or local-runner
poetry add ../../../packages/shared
```

## Development

```bash
# Install dependencies
poetry install

# Run tests
poetry run pytest

# Format code
poetry run black .
poetry run ruff check .

# Type checking
poetry run mypy .
```
