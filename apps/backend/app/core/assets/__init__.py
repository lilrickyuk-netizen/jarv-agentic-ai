"""
JARV Backend - Asset Management System

Comprehensive system for creating, storing, managing, and retrieving digital assets.
"""
from app.core.assets.manager import AssetManager, AssetType, AssetStatus
from app.core.assets.storage import AssetStorage
from app.core.assets.templates import AssetTemplateLibrary

__all__ = [
    "AssetManager",
    "AssetType",
    "AssetStatus",
    "AssetStorage",
    "AssetTemplateLibrary",
]
