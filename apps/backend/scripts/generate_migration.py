#!/usr/bin/env python
"""
JARV Backend - Generate Alembic Migration

Generates Alembic migration from all SQLAlchemy models using autogenerate.

Usage:
    python scripts/generate_migration.py
    python scripts/generate_migration.py --message "migration description"
"""
import sys
import subprocess
from pathlib import Path
import argparse

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def generate_migration(message: str = "auto-generated migration") -> None:
    """
    Generate Alembic migration using autogenerate.

    Args:
        message: Migration message
    """
    print("=" * 60)
    print("JARV Backend - Generate Alembic Migration")
    print("=" * 60)
    print(f"Message: {message}")
    print("=" * 60)

    # Import models to ensure they're registered
    print("\nImporting models...")
    try:
        import app.models  # noqa: F401
        print("[OK] Models imported successfully")
    except Exception as e:
        print(f"[ERROR] Failed to import models: {e}")
        sys.exit(1)

    # Generate migration
    print("\nGenerating migration...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", message],
            capture_output=True,
            text=True,
            check=True
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        print("\n" + "=" * 60)
        print("[OK] Migration generated successfully!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Review the generated migration in alembic/versions/")
        print("2. Run: python scripts/db.py migrate")
        print("=" * 60)

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to generate migration: {e}")
        print(e.stdout)
        print(e.stderr, file=sys.stderr)
        sys.exit(1)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Generate Alembic migration from SQLAlchemy models"
    )
    parser.add_argument(
        "--message",
        "-m",
        default="auto-generated migration",
        help="Migration message"
    )

    args = parser.parse_args()

    generate_migration(args.message)


if __name__ == "__main__":
    main()
