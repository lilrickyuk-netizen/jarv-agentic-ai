"""
JARV Backend - Asset Storage

Storage management for assets with support for local and cloud storage.
"""
from typing import Optional, Dict, Any
from pathlib import Path
import logging
import shutil

logger = logging.getLogger(__name__)


class AssetStorage:
    """
    Asset storage management.

    Handles physical storage of asset files with support for:
    - Local filesystem storage
    - Cloud storage (S3, GCS, Azure) - extensible
    - Storage optimization
    - Backup and recovery
    """

    def __init__(self, storage_path: str = "./data/assets"):
        """
        Initialize asset storage.

        Args:
            storage_path: Base path for local storage
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)

    def store_file(
        self,
        file_content: bytes,
        relative_path: str,
    ) -> bool:
        """
        Store file content at relative path.

        Args:
            file_content: File content as bytes
            relative_path: Relative path within storage

        Returns:
            True if successful
        """
        full_path = self.storage_path / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(full_path, 'wb') as f:
                f.write(file_content)
            self.logger.info(f"Stored file: {relative_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to store file {relative_path}: {e}")
            return False

    def retrieve_file(self, relative_path: str) -> Optional[bytes]:
        """
        Retrieve file content.

        Args:
            relative_path: Relative path within storage

        Returns:
            File content as bytes or None if not found
        """
        full_path = self.storage_path / relative_path

        if not full_path.exists():
            self.logger.warning(f"File not found: {relative_path}")
            return None

        try:
            with open(full_path, 'rb') as f:
                return f.read()
        except Exception as e:
            self.logger.error(f"Failed to retrieve file {relative_path}: {e}")
            return None

    def delete_file(self, relative_path: str) -> bool:
        """
        Delete file from storage.

        Args:
            relative_path: Relative path within storage

        Returns:
            True if successful
        """
        full_path = self.storage_path / relative_path

        if not full_path.exists():
            return False

        try:
            full_path.unlink()
            self.logger.info(f"Deleted file: {relative_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to delete file {relative_path}: {e}")
            return False

    def file_exists(self, relative_path: str) -> bool:
        """Check if file exists"""
        full_path = self.storage_path / relative_path
        return full_path.exists()

    def get_file_size(self, relative_path: str) -> Optional[int]:
        """Get file size in bytes"""
        full_path = self.storage_path / relative_path

        if not full_path.exists():
            return None

        return full_path.stat().st_size

    def copy_file(self, source_path: str, dest_path: str) -> bool:
        """
        Copy file within storage.

        Args:
            source_path: Source relative path
            dest_path: Destination relative path

        Returns:
            True if successful
        """
        source_full = self.storage_path / source_path
        dest_full = self.storage_path / dest_path

        if not source_full.exists():
            return False

        try:
            dest_full.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_full, dest_full)
            self.logger.info(f"Copied file: {source_path} -> {dest_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to copy file: {e}")
            return False

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics"""
        total_size = 0
        file_count = 0

        for path in self.storage_path.rglob('*'):
            if path.is_file():
                file_count += 1
                total_size += path.stat().st_size

        return {
            "total_files": file_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "total_size_gb": round(total_size / (1024 * 1024 * 1024), 2),
            "storage_path": str(self.storage_path),
        }

    def cleanup_orphaned_files(self, valid_paths: list[str]) -> int:
        """
        Clean up files not in valid_paths list.

        Args:
            valid_paths: List of valid relative paths

        Returns:
            Number of files deleted
        """
        valid_set = set(valid_paths)
        deleted_count = 0

        for path in self.storage_path.rglob('*'):
            if path.is_file():
                relative = str(path.relative_to(self.storage_path))
                if relative not in valid_set:
                    try:
                        path.unlink()
                        deleted_count += 1
                        self.logger.info(f"Deleted orphaned file: {relative}")
                    except Exception as e:
                        self.logger.error(f"Failed to delete orphaned file {relative}: {e}")

        return deleted_count
