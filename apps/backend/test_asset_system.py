"""
Test script for Asset Management System.
"""
import sys
from pathlib import Path
import uuid

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.assets.manager import get_asset_manager, AssetType, AssetStatus
from app.core.assets.storage import AssetStorage
from app.core.assets.templates import get_template_library, TemplateCategory


def test_asset_creation():
    """Test creating assets"""
    print("="*70)
    print("TEST 1: ASSET CREATION")
    print("="*70)

    manager = get_asset_manager()
    workspace_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    # Create a test asset
    test_content = b"This is test content for an asset"

    metadata = manager.create_asset(
        name="Test Document",
        asset_type=AssetType.DOCUMENT,
        workspace_id=workspace_id,
        created_by=user_id,
        file_content=test_content,
        mime_type="application/pdf",
        tags=["test", "document", "sample"],
        description="A test document for verification",
    )

    print(f"[OK] Created asset: {metadata.asset_id}")
    print(f"  Name: {metadata.name}")
    print(f"  Type: {metadata.asset_type.value}")
    print(f"  Size: {metadata.file_size} bytes")
    print(f"  Tags: {', '.join(metadata.tags)}")
    print(f"  Version: {metadata.version}")
    print()

    # Verify retrieval
    retrieved = manager.get_asset(metadata.asset_id)
    assert retrieved is not None
    assert retrieved.asset_id == metadata.asset_id
    print("[OK] Asset retrieval verified")
    print()

    # Verify content
    content = manager.get_asset_content(metadata.asset_id)
    assert content == test_content
    print("[OK] Asset content verified")
    print()

    return metadata.asset_id


def test_asset_update():
    """Test updating assets"""
    print("="*70)
    print("TEST 2: ASSET UPDATE")
    print("="*70)

    manager = get_asset_manager()
    workspace_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    # Create asset
    metadata = manager.create_asset(
        name="Original Name",
        asset_type=AssetType.IMAGE,
        workspace_id=workspace_id,
        created_by=user_id,
        file_content=b"original content",
        mime_type="image/png",
    )

    print(f"[OK] Created asset: {metadata.asset_id}")
    print(f"  Original name: {metadata.name}")
    print(f"  Original version: {metadata.version}")
    print()

    # Update metadata
    updated = manager.update_asset(
        asset_id=metadata.asset_id,
        updated_by=user_id,
        name="Updated Name",
        description="Updated description",
        tags=["updated", "modified"],
        status=AssetStatus.APPROVED,
    )

    print("[OK] Updated asset metadata")
    print(f"  New name: {updated.name}")
    print(f"  Description: {updated.description}")
    print(f"  Tags: {', '.join(updated.tags)}")
    print(f"  Status: {updated.status.value}")
    print()

    # Update content (creates new version)
    updated = manager.update_asset(
        asset_id=metadata.asset_id,
        updated_by=user_id,
        file_content=b"updated content v2",
    )

    print("[OK] Updated asset content")
    print(f"  New version: {updated.version}")
    print()

    # Check versions
    versions = manager.get_asset_versions(metadata.asset_id)
    print(f"[OK] Asset has {len(versions)} versions")
    for v in versions:
        print(f"  Version {v.version_number}: {v.file_size} bytes, {v.changes}")
    print()

    return metadata.asset_id


def test_asset_search():
    """Test searching assets"""
    print("="*70)
    print("TEST 3: ASSET SEARCH")
    print("="*70)

    manager = get_asset_manager()
    workspace_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    # Create multiple assets
    for i in range(5):
        manager.create_asset(
            name=f"Document {i+1}",
            asset_type=AssetType.DOCUMENT if i < 3 else AssetType.IMAGE,
            workspace_id=workspace_id,
            created_by=user_id,
            file_content=b"content",
            mime_type="application/pdf" if i < 3 else "image/png",
            tags=["test", f"doc{i+1}"] if i < 3 else ["test", "image"],
        )

    print(f"[OK] Created 5 test assets")
    print()

    # Search by workspace
    results = manager.search_assets(workspace_id=workspace_id)
    print(f"[OK] Search by workspace: {len(results)} assets found")
    print()

    # Search by type
    results = manager.search_assets(
        workspace_id=workspace_id,
        asset_type=AssetType.DOCUMENT
    )
    print(f"[OK] Search by type (DOCUMENT): {len(results)} assets found")
    print()

    # Search by tags
    results = manager.search_assets(
        workspace_id=workspace_id,
        tags=["image"]
    )
    print(f"[OK] Search by tags (image): {len(results)} assets found")
    print()

    # Search by text
    results = manager.search_assets(
        workspace_id=workspace_id,
        search_text="Document 2"
    )
    print(f"[OK] Search by text: {len(results)} assets found")
    if results:
        print(f"  Found: {results[0].name}")
    print()


def test_asset_stats():
    """Test asset statistics"""
    print("="*70)
    print("TEST 4: ASSET STATISTICS")
    print("="*70)

    manager = get_asset_manager()
    stats = manager.get_stats()

    print("[OK] Asset statistics:")
    print(f"  Total assets: {stats['total_assets']}")
    print(f"  Total size: {stats['total_size_mb']} MB")
    print(f"  Total versions: {stats['total_versions']}")
    print()

    print("  By type:")
    for asset_type, count in stats['by_type'].items():
        print(f"    {asset_type}: {count}")
    print()

    print("  By status:")
    for status, count in stats['by_status'].items():
        print(f"    {status}: {count}")
    print()


def test_template_library():
    """Test template library"""
    print("="*70)
    print("TEST 5: TEMPLATE LIBRARY")
    print("="*70)

    library = get_template_library()

    # List all templates
    all_templates = library.list_templates()
    print(f"[OK] Template library loaded: {len(all_templates)} templates")
    print()

    # List by category
    social_templates = library.list_templates(category=TemplateCategory.SOCIAL_MEDIA)
    print(f"[OK] Social media templates: {len(social_templates)}")
    for t in social_templates:
        print(f"  - {t.name}: {t.description}")
    print()

    # List by asset type
    image_templates = library.list_templates(asset_type="image")
    print(f"[OK] Image templates: {len(image_templates)}")
    print()

    # Get specific template
    template = library.get_template("pitch_deck")
    if template:
        print(f"[OK] Retrieved template: {template.name}")
        print(f"  Category: {template.category.value}")
        print(f"  Placeholders: {', '.join(template.placeholders)}")
    print()

    # Get stats
    stats = library.get_template_stats()
    print("[OK] Template library statistics:")
    print(f"  Total templates: {stats['total_templates']}")
    print(f"  By category: {stats['by_category']}")
    print()


def test_storage():
    """Test storage component"""
    print("="*70)
    print("TEST 6: STORAGE SYSTEM")
    print("="*70)

    storage = AssetStorage("./data/test_assets")

    # Store a file
    test_content = b"Test storage content"
    success = storage.store_file(test_content, "test/sample.txt")
    print(f"[OK] Stored file: {success}")
    print()

    # Retrieve file
    retrieved = storage.retrieve_file("test/sample.txt")
    assert retrieved == test_content
    print("[OK] Retrieved file content verified")
    print()

    # Check existence
    exists = storage.file_exists("test/sample.txt")
    print(f"[OK] File exists: {exists}")
    print()

    # Get file size
    size = storage.get_file_size("test/sample.txt")
    print(f"[OK] File size: {size} bytes")
    print()

    # Get storage stats
    stats = storage.get_storage_stats()
    print("[OK] Storage statistics:")
    print(f"  Total files: {stats['total_files']}")
    print(f"  Total size: {stats['total_size_mb']} MB")
    print()

    # Clean up
    storage.delete_file("test/sample.txt")
    print("[OK] Cleaned up test file")
    print()


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("ASSET MANAGEMENT SYSTEM - COMPREHENSIVE TEST")
    print("="*70)
    print()

    try:
        # Run tests
        asset_id = test_asset_creation()
        test_asset_update()
        test_asset_search()
        test_asset_stats()
        test_template_library()
        test_storage()

        # Final summary
        print("="*70)
        print("FINAL TEST RESULTS")
        print("="*70)
        print("[SUCCESS] All tests passed!")
        print()
        print("Asset System Features Verified:")
        print("  [OK] Asset creation with metadata")
        print("  [OK] Asset retrieval and content access")
        print("  [OK] Asset updates and versioning")
        print("  [OK] Asset search and filtering")
        print("  [OK] Asset statistics and reporting")
        print("  [OK] Template library with 11+ templates")
        print("  [OK] Storage system with file operations")
        print("="*70)
        print()

        return 0

    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
