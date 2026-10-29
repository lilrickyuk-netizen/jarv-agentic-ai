"""
JARV Backend - Asset tools (Repair 12e-4b)

web_search (public web search), download_asset, check_licence,
save_source_record, generate_asset_manifest and update_asset_licence_file,
all on the persisted asset library (app.core.assets.library). fetch_url is
the folder-confined runtime tool registered in Repair 12e-3a.

An asset is downloaded only when its licence is known and allows the use;
unknown licences, non-commercial licences for a commercial product,
executables and archives are refused.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.assets import library
from app.tools._scoped import ScopedTool


class _AssetTool(ScopedTool):
    _category = "assets"
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS


async def _workspace(db, context):
    from app.models.workspace import Workspace

    return (await db.execute(select(Workspace).where(Workspace.id == context.workspace_id))).scalar_one()


class _Search(BaseModel):
    query: str = Field(..., min_length=2)
    limit: int = Field(8, ge=1, le=20)


class WebSearchTool(_AssetTool):
    _name = "web_search"
    _description = "Search the public web (titles, links and snippets); read results with fetch_url."
    _input = _Search
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS
    _category = "research"

    async def act(self, db, context, owner, data):
        from app.core.internet import web_search

        result = await web_search(data["query"], data["limit"])
        if not result.get("ok"):
            raise RuntimeError(f"Search failed: {result.get('reason')}")
        return result, f"{len(result['results'])} result(s) for '{data['query']}'"


class _Licence(BaseModel):
    licence: Optional[str] = Field(None, description="Licence id or name, e.g. CC-BY-4.0, OFL, Pixabay License")
    url: Optional[str] = Field(None, description="Asset or page URL (infers the provider's licence)")
    commercial: bool = Field(True, description="Will it be used in a commercial product?")
    modify: bool = Field(True, description="Will it be edited, cropped or remixed?")


class CheckLicenceTool(_AssetTool):
    _name = "check_licence"
    _description = "Can this asset be used here? Commercial use, attribution, share-alike and conditions."
    _input = _Licence
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        verdict = library.check_licence(data.get("licence"), data.get("url"), commercial=data["commercial"],
                                        modify=data["modify"])
        text = (f"{verdict['name']}: allowed" + (f" ({'; '.join(verdict['conditions'])})" if verdict["conditions"] else "")
                if verdict["allowed"] else f"Not allowed: {verdict['reason']}")
        return verdict, text


class _Download(BaseModel):
    url: str = Field(..., description="https URL of the file")
    licence: Optional[str] = Field(None, description="Required unless the provider has one standard licence")
    author: Optional[str] = None
    source_page: Optional[str] = Field(None, description="The page the asset was found on")
    folder: str = Field("assets", description="Folder in the workspace")
    filename: Optional[str] = None
    commercial: bool = True
    modify: bool = Field(False, description="Will it be adapted? No-derivatives licences then refuse it")


class DownloadAssetTool(_AssetTool):
    _name = "download_asset"
    _description = ("Download a media, font or animation asset into the workspace after checking its licence; it is "
                    "hashed and recorded with its source, author and licence.")
    _input = _Download
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def act(self, db, context, owner, data):
        row = await library.download(db, await _workspace(db, context), data["url"], folder=data["folder"],
                                     filename=data.get("filename"), licence=data.get("licence"),
                                     author=data.get("author"), source_page=data.get("source_page"),
                                     commercial=data["commercial"], modify=data["modify"], created_by=owner)
        return library.asset_view(row), f"{row.asset_name} saved to {row.file_path} ({row.license_type})"


class _Source(BaseModel):
    asset_id: str
    source_page: Optional[str] = None
    author: Optional[str] = None
    licence: Optional[str] = None


class SaveSourceRecordTool(_AssetTool):
    _name = "save_source_record"
    _description = "Record or correct an asset's source page, author and licence (updates its attribution)."
    _input = _Source

    async def act(self, db, context, owner, data):
        row = await library.save_source(db, context.workspace_id, data["asset_id"], source_page=data.get("source_page"),
                                        author=data.get("author"), licence=data.get("licence"))
        return library.asset_view(row), f"Source recorded for {row.asset_name}"


class _Empty(BaseModel):
    pass


class GenerateAssetManifestTool(_AssetTool):
    _name = "generate_asset_manifest"
    _description = "Write ASSETS.json in the workspace: every asset with its path, hash, source, author and licence."
    _input = _Empty

    async def act(self, db, context, owner, data):
        result = await library.write_manifest(db, await _workspace(db, context))
        return result, f"ASSETS.json lists {result['assets']} asset(s)"


class UpdateAssetLicenceFileTool(_AssetTool):
    _name = "update_asset_licence_file"
    _description = "Write ASSET-LICENCES.md in the workspace: assets grouped by licence with the required credits."
    _input = _Empty

    async def act(self, db, context, owner, data):
        result = await library.write_licence_file(db, await _workspace(db, context))
        return result, f"ASSET-LICENCES.md covers {result['assets']} asset(s)"


ASSET_TOOLS = [WebSearchTool, CheckLicenceTool, DownloadAssetTool, SaveSourceRecordTool, GenerateAssetManifestTool,
               UpdateAssetLicenceFileTool]
