#!/usr/bin/env python
"""
JARV Backend Database Management Script

Usage:
    python scripts/db.py migrate      # Run migrations
    python scripts/db.py rollback     # Rollback last migration
    python scripts/db.py reset        # Reset database (DEV ONLY)
    python scripts/db.py seed         # Seed with test data (DEV ONLY)
"""
import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.database import init_db, engine
from app.models.base import Base
import subprocess


def run_alembic(command: list[str]) -> None:
    """Run Alembic command"""
    result = subprocess.run(
        ["alembic"] + command,
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        sys.exit(result.returncode)


async def reset_database() -> None:
    """Reset database - DROP and CREATE all tables (DEV ONLY)"""
    if settings.ENVIRONMENT == "production":
        print("ERROR: Cannot reset database in production!")
        sys.exit(1)

    print("WARNING: This will delete all data!")
    confirm = input("Type 'RESET' to confirm: ")
    if confirm != "RESET":
        print("Aborted")
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        print("Dropped all tables")
        await conn.run_sync(Base.metadata.create_all)
        print("Created all tables")


async def seed_database() -> None:
    """Seed database with test data (DEV ONLY)"""
    if settings.ENVIRONMENT == "production":
        print("ERROR: Cannot seed database in production!")
        sys.exit(1)

    # Import and run seed data script
    from scripts.seed_data import seed_all
    await seed_all()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "migrate":
        print("Running database migrations...")
        run_alembic(["upgrade", "head"])
        print("Migrations complete")

    elif command == "rollback":
        print("Rolling back last migration...")
        run_alembic(["downgrade", "-1"])
        print("Rollback complete")

    elif command == "reset":
        print("Resetting database...")
        asyncio.run(reset_database())
        print("Database reset complete")

    elif command == "seed":
        print("Seeding database...")
        asyncio.run(seed_database())
        print("Seed complete")

    elif command == "current":
        print("Current migration:")
        run_alembic(["current"])

    elif command == "history":
        print("Migration history:")
        run_alembic(["history"])

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
