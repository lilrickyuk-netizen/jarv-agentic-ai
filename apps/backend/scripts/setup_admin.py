#!/usr/bin/env python
"""
JARV Backend - Setup Admin User

Creates initial admin user in Redis for local authentication.
This is a temporary solution for Phase 1. In Phase 2, users will be stored in PostgreSQL.

Usage:
    python scripts/setup_admin.py
    python scripts/setup_admin.py --username admin --password <password>
"""
import sys
import asyncio
from pathlib import Path
from datetime import datetime
import argparse
import getpass

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.redis import init_redis, close_redis
from app.core.security import get_password_hash
from app.core.config import settings


async def create_admin_user(username: str, password: str) -> None:
    """
    Create admin user in Redis.

    Args:
        username: Admin username
        password: Admin password
    """
    try:
        # Initialize Redis
        redis = await init_redis()

        # Check if user already exists
        existing_user = await redis.hgetall(f"user:{username}")
        if existing_user:
            print(f"User '{username}' already exists!")
            overwrite = input("Overwrite existing user? (yes/no): ")
            if overwrite.lower() != "yes":
                print("Aborted")
                return

        # Hash password
        password_hash = get_password_hash(password)

        # Create user ID
        user_id = f"admin_{username}"

        # Store user in Redis
        user_data = {
            "user_id": user_id,
            "username": username,
            "password_hash": password_hash,
            "created_at": datetime.utcnow().isoformat(),
        }

        await redis.hset(f"user:{username}", mapping=user_data)

        # Mark user as admin
        await redis.set(f"user:{user_id}:admin", "true")

        print(f"\n{'=' * 60}")
        print(f"Admin user created successfully!")
        print(f"{'=' * 60}")
        print(f"Username: {username}")
        print(f"User ID:  {user_id}")
        print(f"Admin:    Yes")
        print(f"{'=' * 60}\n")

        # Close Redis connection
        await close_redis()

    except Exception as e:
        print(f"Error creating admin user: {e}")
        sys.exit(1)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Create admin user for JARV backend"
    )
    parser.add_argument(
        "--username",
        default="admin",
        help="Admin username (default: admin)"
    )
    parser.add_argument(
        "--password",
        help="Admin password (will prompt if not provided)"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("JARV Backend - Admin User Setup")
    print("=" * 60)
    print(f"Environment: {settings.ENVIRONMENT}")
    print(f"Redis URL:   {settings.REDIS_URL}")
    print("=" * 60)

    username = args.username
    password = args.password

    # Prompt for password if not provided
    if not password:
        password = getpass.getpass(f"Enter password for '{username}': ")
        password_confirm = getpass.getpass("Confirm password: ")

        if password != password_confirm:
            print("Passwords do not match!")
            sys.exit(1)

    # Validate password
    if len(password) < 8:
        print("Password must be at least 8 characters long!")
        sys.exit(1)

    # Create admin user
    asyncio.run(create_admin_user(username, password))


if __name__ == "__main__":
    main()
