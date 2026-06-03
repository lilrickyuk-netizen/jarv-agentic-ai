#!/usr/bin/env python3
"""
JARV Local Runner - Installer

Sets up local runner with secure token generation.
"""
import sys
import subprocess
from pathlib import Path

# Add runner to path
sys.path.insert(0, str(Path(__file__).parent))

from runner.auth import generate_token
from runner.config import settings


def install():
    """Install local runner"""
    print("=" * 60)
    print("JARV Local Runner - Installation")
    print("=" * 60)
    print()

    # Check Python version
    if sys.version_info < (3, 8):
        print("ERROR: Python 3.8 or higher is required")
        sys.exit(1)

    print("✓ Python version check passed")

    # Install dependencies
    print("\nInstalling dependencies...")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-e", "."
        ])
        print("✓ Dependencies installed")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to install dependencies: {e}")
        sys.exit(1)

    # Generate authentication token
    print("\nGenerating authentication token...")
    token = generate_token()
    print("✓ Token generated")

    # Save token
    token_file = Path.home() / ".jarv" / "runner_token.txt"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    with open(token_file, 'w') as f:
        f.write(token)
    token_file.chmod(0o600)

    print(f"✓ Token saved to: {token_file}")

    # Show configuration
    print("\n" + "=" * 60)
    print("Installation Complete!")
    print("=" * 60)
    print()
    print("Configuration:")
    print(f"  Host: {settings.HOST}")
    print(f"  Port: {settings.PORT}")
    print(f"  Allowed Folders: {len(settings.ALLOWED_FOLDERS)}")
    for folder in settings.ALLOWED_FOLDERS[:3]:
        print(f"    - {folder}")
    if len(settings.ALLOWED_FOLDERS) > 3:
        print(f"    ... and {len(settings.ALLOWED_FOLDERS) - 3} more")
    print()
    print("Authentication Token:")
    print(f"  {token}")
    print()
    print("IMPORTANT: Add this token to your JARV backend configuration:")
    print(f"  RUNNER_TOKEN={token}")
    print()
    print("To start the local runner:")
    print("  python start.py")
    print()


if __name__ == "__main__":
    install()
