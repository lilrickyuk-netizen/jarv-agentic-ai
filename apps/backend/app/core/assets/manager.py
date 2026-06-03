"""
JARV Backend - Asset Manager

Core asset management system for creating, organizing, and retrieving digital assets.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
import uuid
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class AssetType(str, Enum):
    """Types of assets that can be managed"""
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    PRESENTATION = "presentation"
    DESIGN = "design"
    CODE = "code"
    TEMPLATE = "template"
    AUDIO = "audio"
    DATA = "data"
    OTHER = "other"


class AssetStatus(str, Enum):
    """Status of an asset"""
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


@dataclass
class AssetMetadata:
    """Metadata for an asset"""
    asset_id: str
    name: str
    asset_type: AssetType
    status: AssetStatus
    file_path: str
    file_size: int  # bytes
    mime_type: str
    created_at: datetime
    updated_at: datetime
    created_by: str  # user ID
    workspace_id: str
    version: int
    tags: List[str]
    description: str
    dimensions: Optional[Dict[str, Any]] = None  # For images/videos
    duration: Optional[float] = None  # For audio/video
    page_count: Optional[int] = None  # For documents
    custom_fields: Dict[str, Any] = None


@dataclass
class AssetVersion:
    """Version information for an asset"""
    version_number: int
    file_path: str
    created_at: datetime
    created_by: str
    changes: str
    file_size: int


class AssetManager:
    """
    Core asset management system.

    Handles creation, storage, organization, versioning, and retrieval
    of all digital assets in the JARV system.
    """

    def __init__(self, storage_base_path: str = "./data/assets"):
        """
        Initialize asset manager.

        Args:
            storage_base_path: Base path for asset storage
        """
        self.storage_base_path = Path(storage_base_path)
        self.storage_base_path.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)

        # In-memory storage for demo (in production: use database)
        self.assets: Dict[str, AssetMetadata] = {}
        self.versions: Dict[str, List[AssetVersion]] = {}

    def create_asset(
        self,
        name: str,
        asset_type: AssetType,
        workspace_id: str,
        created_by: str,
        file_content: bytes,
        mime_type: str,
        tags: List[str] = None,
        description: str = "",
        custom_fields: Dict[str, Any] = None,
    ) -> AssetMetadata:
        """
        Create a new asset.

        Args:
            name: Asset name
            asset_type: Type of asset
            workspace_id: Workspace ID
            created_by: User ID who created it
            file_content: File content as bytes
            mime_type: MIME type
            tags: List of tags
            description: Asset description
            custom_fields: Custom metadata fields

        Returns:
            AssetMetadata for created asset
        """
        asset_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # Determine file extension from mime_type
        extension = self._get_extension_from_mime(mime_type)

        # Create file path
        relative_path = self._generate_file_path(
            workspace_id, asset_type, asset_id, extension
        )
        full_path = self.storage_base_path / relative_path

        # Ensure directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        with open(full_path, 'wb') as f:
            f.write(file_content)

        file_size = len(file_content)

        # Extract dimensions/metadata based on type
        dimensions = self._extract_dimensions(asset_type, file_content)
        duration = self._extract_duration(asset_type, file_content)
        page_count = self._extract_page_count(asset_type, file_content)

        # Create metadata
        metadata = AssetMetadata(
            asset_id=asset_id,
            name=name,
            asset_type=asset_type,
            status=AssetStatus.DRAFT,
            file_path=str(relative_path),
            file_size=file_size,
            mime_type=mime_type,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            workspace_id=workspace_id,
            version=1,
            tags=tags or [],
            description=description,
            dimensions=dimensions,
            duration=duration,
            page_count=page_count,
            custom_fields=custom_fields or {},
        )

        # Store asset
        self.assets[asset_id] = metadata

        # Create initial version
        self.versions[asset_id] = [
            AssetVersion(
                version_number=1,
                file_path=str(relative_path),
                created_at=now,
                created_by=created_by,
                changes="Initial version",
                file_size=file_size,
            )
        ]

        self.logger.info(f"Created asset: {asset_id} ({name})")
        return metadata

    def get_asset(self, asset_id: str) -> Optional[AssetMetadata]:
        """Get asset metadata by ID"""
        return self.assets.get(asset_id)

    def update_asset(
        self,
        asset_id: str,
        updated_by: str,
        file_content: Optional[bytes] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[AssetStatus] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> Optional[AssetMetadata]:
        """
        Update an existing asset.

        Creates a new version if file_content is provided.
        """
        asset = self.assets.get(asset_id)
        if not asset:
            return None

        now = datetime.utcnow()
        changes = []

        # Update file content (creates new version)
        if file_content is not None:
            asset.version += 1
            extension = self._get_extension_from_mime(asset.mime_type)
            relative_path = self._generate_file_path(
                asset.workspace_id, asset.asset_type, asset_id, extension,
                version=asset.version
            )
            full_path = self.storage_base_path / relative_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, 'wb') as f:
                f.write(file_content)

            file_size = len(file_content)
            asset.file_path = str(relative_path)
            asset.file_size = file_size

            # Add version record
            self.versions[asset_id].append(
                AssetVersion(
                    version_number=asset.version,
                    file_path=str(relative_path),
                    created_at=now,
                    created_by=updated_by,
                    changes=f"Updated file content",
                    file_size=file_size,
                )
            )
            changes.append("file content")

        # Update metadata
        if name is not None:
            asset.name = name
            changes.append("name")

        if description is not None:
            asset.description = description
            changes.append("description")

        if tags is not None:
            asset.tags = tags
            changes.append("tags")

        if status is not None:
            asset.status = status
            changes.append("status")

        if custom_fields is not None:
            asset.custom_fields.update(custom_fields)
            changes.append("custom fields")

        asset.updated_at = now

        self.logger.info(f"Updated asset {asset_id}: {', '.join(changes)}")
        return asset

    def delete_asset(self, asset_id: str) -> bool:
        """
        Delete an asset (soft delete - archives it).
        """
        asset = self.assets.get(asset_id)
        if not asset:
            return False

        asset.status = AssetStatus.ARCHIVED
        asset.updated_at = datetime.utcnow()

        self.logger.info(f"Archived asset: {asset_id}")
        return True

    def search_assets(
        self,
        workspace_id: Optional[str] = None,
        asset_type: Optional[AssetType] = None,
        tags: Optional[List[str]] = None,
        status: Optional[AssetStatus] = None,
        search_text: Optional[str] = None,
    ) -> List[AssetMetadata]:
        """
        Search for assets based on criteria.
        """
        results = list(self.assets.values())

        # Filter by workspace
        if workspace_id:
            results = [a for a in results if a.workspace_id == workspace_id]

        # Filter by type
        if asset_type:
            results = [a for a in results if a.asset_type == asset_type]

        # Filter by status
        if status:
            results = [a for a in results if a.status == status]

        # Filter by tags
        if tags:
            results = [
                a for a in results
                if any(tag in a.tags for tag in tags)
            ]

        # Filter by search text
        if search_text:
            search_lower = search_text.lower()
            results = [
                a for a in results
                if search_lower in a.name.lower()
                or search_lower in a.description.lower()
            ]

        return results

    def get_asset_versions(self, asset_id: str) -> List[AssetVersion]:
        """Get all versions of an asset"""
        return self.versions.get(asset_id, [])

    def get_asset_content(self, asset_id: str, version: Optional[int] = None) -> Optional[bytes]:
        """
        Get asset file content.

        Args:
            asset_id: Asset ID
            version: Specific version (None = latest)

        Returns:
            File content as bytes or None if not found
        """
        asset = self.assets.get(asset_id)
        if not asset:
            return None

        # Get file path for specific version
        if version is not None:
            versions = self.versions.get(asset_id, [])
            version_data = next((v for v in versions if v.version_number == version), None)
            if not version_data:
                return None
            file_path = self.storage_base_path / version_data.file_path
        else:
            file_path = self.storage_base_path / asset.file_path

        # Read file
        if not file_path.exists():
            return None

        with open(file_path, 'rb') as f:
            return f.read()

    def get_stats(self) -> Dict[str, Any]:
        """Get asset system statistics"""
        assets = list(self.assets.values())

        total_size = sum(a.file_size for a in assets)

        type_counts = {}
        for asset_type in AssetType:
            count = sum(1 for a in assets if a.asset_type == asset_type)
            if count > 0:
                type_counts[asset_type.value] = count

        status_counts = {}
        for status in AssetStatus:
            count = sum(1 for a in assets if a.status == status)
            if count > 0:
                status_counts[status.value] = count

        return {
            "total_assets": len(assets),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "by_type": type_counts,
            "by_status": status_counts,
            "total_versions": sum(len(v) for v in self.versions.values()),
        }

    def _generate_file_path(
        self,
        workspace_id: str,
        asset_type: AssetType,
        asset_id: str,
        extension: str,
        version: int = 1,
    ) -> Path:
        """Generate file path for an asset"""
        return Path(workspace_id) / asset_type.value / f"{asset_id}_v{version}{extension}"

    def _get_extension_from_mime(self, mime_type: str) -> str:
        """Get file extension from MIME type"""
        mime_to_ext = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/svg+xml": ".svg",
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "application/pdf": ".pdf",
            "application/msword": ".doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/vnd.ms-powerpoint": ".ppt",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
            "text/plain": ".txt",
            "text/html": ".html",
            "application/json": ".json",
            "text/csv": ".csv",
        }
        return mime_to_ext.get(mime_type, ".bin")

    def _extract_dimensions(self, asset_type: AssetType, content: bytes) -> Optional[Dict[str, Any]]:
        """Extract dimensions from image/video (simplified)"""
        if asset_type in [AssetType.IMAGE, AssetType.VIDEO]:
            # In production: use PIL, opencv, ffmpeg, etc.
            return {"width": 1920, "height": 1080}
        return None

    def _extract_duration(self, asset_type: AssetType, content: bytes) -> Optional[float]:
        """Extract duration from audio/video (simplified)"""
        if asset_type in [AssetType.AUDIO, AssetType.VIDEO]:
            # In production: use ffmpeg, mutagen, etc.
            return 120.0  # 2 minutes
        return None

    def _extract_page_count(self, asset_type: AssetType, content: bytes) -> Optional[int]:
        """Extract page count from documents (simplified)"""
        if asset_type in [AssetType.DOCUMENT, AssetType.PRESENTATION]:
            # In production: use PyPDF2, python-pptx, etc.
            return 10
        return None


# Global asset manager instance
_asset_manager: Optional[AssetManager] = None


def get_asset_manager() -> AssetManager:
    """Get global asset manager instance"""
    global _asset_manager
    if _asset_manager is None:
        _asset_manager = AssetManager()
    return _asset_manager
