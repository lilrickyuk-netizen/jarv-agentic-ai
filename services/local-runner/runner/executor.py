"""
JARV Local Runner - Executors

Command and file execution with safety validation.
"""
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
import glob
import logging
import time

from runner.config import settings

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Security validation failed"""
    pass


class CommandExecutor:
    """
    Executes commands on local system.

    Validates commands against banned list and security rules.
    """

    def __init__(self):
        """Initialize command executor"""
        self.logger = logging.getLogger("runner.command")

    def _validate_command(self, command: str):
        """
        Validate command against security rules.

        Args:
            command: Command to validate

        Raises:
            SecurityError: If command is not allowed
        """
        # Check banned commands
        for banned in settings.BANNED_COMMANDS:
            if banned in command.lower():
                raise SecurityError(f"Banned command detected: {banned}")

        # Check for dangerous patterns
        dangerous_patterns = [
            "rm -rf /",
            ":(){ :|:& };:",  # Fork bomb
            "dd if=/dev/zero",  # Disk wipe
            "mkfs.",  # Format filesystem
        ]

        for pattern in dangerous_patterns:
            if pattern in command:
                raise SecurityError(f"Dangerous command pattern detected")

        self.logger.info(f"Command validated: {command[:50]}...")

    def _validate_cwd(self, cwd: Optional[str]) -> Path:
        """
        Validate and resolve working directory.

        Args:
            cwd: Working directory path

        Returns:
            Resolved Path object

        Raises:
            SecurityError: If directory not allowed
        """
        if cwd:
            path = Path(cwd).resolve()
        else:
            path = Path.cwd()

        # Check if path is within allowed folders
        is_allowed = False
        for allowed_folder in settings.ALLOWED_FOLDERS:
            allowed_path = Path(allowed_folder).resolve()
            try:
                path.relative_to(allowed_path)
                is_allowed = True
                break
            except ValueError:
                continue

        if not is_allowed:
            raise SecurityError(f"Working directory not in allowed folders: {path}")

        if not path.exists():
            raise SecurityError(f"Working directory does not exist: {path}")

        return path

    async def execute_command(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        Execute command synchronously.

        Args:
            command: Command to execute
            cwd: Working directory
            timeout: Timeout in seconds

        Returns:
            Execution result with stdout, stderr, exit_code
        """
        start_time = time.time()

        try:
            # Validate
            self._validate_command(command)
            cwd_path = self._validate_cwd(cwd)

            self.logger.info(f"Executing command: {command}")

            # Execute
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd_path),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                raise TimeoutError(f"Command timed out after {timeout} seconds")

            duration = time.time() - start_time

            result = {
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "exit_code": process.returncode,
                "duration": duration,
            }

            self.logger.info(f"Command completed: exit_code={process.returncode}, duration={duration:.2f}s")
            return result

        except Exception as e:
            self.logger.error(f"Command execution failed: {e}")
            raise

    async def execute_command_background(
        self,
        task_id: str,
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 3600,
        task_manager=None,
    ):
        """
        Execute command in background with task tracking.

        Args:
            task_id: Task ID for tracking
            command: Command to execute
            cwd: Working directory
            timeout: Timeout in seconds
            task_manager: Task manager instance
        """
        try:
            result = await self.execute_command(command, cwd, timeout)

            if task_manager:
                await task_manager.complete_task(task_id, result)

        except Exception as e:
            if task_manager:
                await task_manager.fail_task(task_id, str(e))


class FileExecutor:
    """
    Executes file operations on local system.

    Validates paths against allowed folders.
    """

    def __init__(self):
        """Initialize file executor"""
        self.logger = logging.getLogger("runner.file")

    def _validate_path(self, path: str) -> Path:
        """
        Validate file path against allowed folders.

        Args:
            path: File path to validate

        Returns:
            Resolved Path object

        Raises:
            SecurityError: If path not allowed
        """
        file_path = Path(path).resolve()

        # Check if path is within allowed folders
        is_allowed = False
        for allowed_folder in settings.ALLOWED_FOLDERS:
            allowed_path = Path(allowed_folder).resolve()
            try:
                file_path.relative_to(allowed_path)
                is_allowed = True
                break
            except ValueError:
                continue

        if not is_allowed:
            raise SecurityError(f"Path not in allowed folders: {file_path}")

        return file_path

    async def read_file(self, path: str) -> str:
        """
        Read file from local filesystem.

        Args:
            path: File path

        Returns:
            File content
        """
        try:
            file_path = self._validate_path(path)

            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            if not file_path.is_file():
                raise ValueError(f"Path is not a file: {file_path}")

            # Check file size
            if file_path.stat().st_size > settings.MAX_FILE_SIZE:
                raise ValueError(f"File too large: {file_path.stat().st_size} bytes")

            self.logger.info(f"Reading file: {file_path}")

            # Read file
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            return content

        except Exception as e:
            self.logger.error(f"File read failed: {e}")
            raise

    async def write_file(self, path: str, content: str):
        """
        Write file to local filesystem.

        Args:
            path: File path
            content: File content
        """
        try:
            file_path = self._validate_path(path)

            # Check content size
            if len(content) > settings.MAX_FILE_SIZE:
                raise ValueError(f"Content too large: {len(content)} bytes")

            self.logger.info(f"Writing file: {file_path}")

            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

        except Exception as e:
            self.logger.error(f"File write failed: {e}")
            raise

    async def list_files(
        self,
        path: str,
        pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List files in directory.

        Args:
            path: Directory path
            pattern: Glob pattern (optional)

        Returns:
            List of file information
        """
        try:
            dir_path = self._validate_path(path)

            if not dir_path.exists():
                raise FileNotFoundError(f"Directory not found: {dir_path}")

            if not dir_path.is_dir():
                raise ValueError(f"Path is not a directory: {dir_path}")

            self.logger.info(f"Listing files: {dir_path}")

            # List files
            if pattern:
                file_paths = glob.glob(str(dir_path / pattern))
            else:
                file_paths = [str(p) for p in dir_path.iterdir()]

            # Get file info
            files = []
            for file_path in file_paths:
                p = Path(file_path)
                if p.exists():
                    stat = p.stat()
                    files.append({
                        "path": str(p),
                        "name": p.name,
                        "is_file": p.is_file(),
                        "is_dir": p.is_dir(),
                        "size": stat.st_size if p.is_file() else 0,
                        "modified": stat.st_mtime,
                    })

            return files

        except Exception as e:
            self.logger.error(f"File list failed: {e}")
            raise
