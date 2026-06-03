# JARV Local Runner

Local laptop runner service for JARV Agentic AI System.

## Purpose

The Local Runner executes file operations, terminal commands, builds, and tests on Richard's laptop. It provides secure, controlled access to the local file system and command execution.

## Features

- Approved folder access control
- File read/write/edit operations
- Terminal command execution
- Build and test command execution
- Package installation from approved sources
- Local project scanning
- Log streaming
- Task cancellation
- Timeouts
- Audit logging
- Voice command routing

## Security

The local runner does NOT have full unrestricted laptop access by default.

**Blocked by default:**
- Banking folders
- Crypto wallet folders
- Private keys
- Password managers
- Unknown EXE execution
- Security setting changes
- Full disk deletion
- Unapproved admin actions

## Development

```bash
# Install dependencies
poetry install

# Run local runner
poetry run python -m runner.main

# Run tests
poetry run pytest
```

## Environment Variables

Create a `.env` file:

```
BACKEND_URL=http://localhost:8000
RUNNER_TOKEN=secure-token-here
APPROVED_FOLDERS=/path/to/projects,/path/to/workspaces
BANNED_FOLDERS=/path/to/bank,/path/to/crypto
LOG_LEVEL=INFO
```

## Connection to Backend

The local runner connects to the backend API using secure token authentication. All operations are logged to the backend audit log.
