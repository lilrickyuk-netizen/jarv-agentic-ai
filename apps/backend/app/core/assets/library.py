"""
JARV Backend - Asset library with licence records

Downloading an asset is only allowed when its licence is known and permits the
use: the licence is taken from the caller or inferred from the provider
(Pixabay, Pexels, Unsplash, Google Fonts, Lucide, Heroicons, ...); an unknown
or non-commercial licence is refused for a commercial product. Downloads are
SSRF-guarded, size-capped, restricted to media/font/data types (never
executables or archives), written into the workspace folder, hashed, and
recorded as an Asset with its source, author and licence (AssetLicence).
The manifest (ASSETS.json) and the credits file (ASSET-LICENCES.md) are
generated from those records.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assets import Asset, AssetLicence

MAX_BYTES = 25 * 1024 * 1024
ALLOWED = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".webp": "image", ".svg": "image",
    ".avif": "image", ".ico": "image", ".mp3": "audio", ".wav": "audio", ".ogg": "audio", ".m4a": "audio",
    ".mp4": "video", ".webm": "video", ".woff": "font", ".woff2": "font", ".ttf": "font", ".otf": "font",
    ".json": "animation", ".lottie": "animation", ".glb": "model", ".gltf": "model",
}
_TYPE_PREFIX = {"image": ("image/",), "audio": ("audio/",), "video": ("video/",),
                "font": ("font/", "application/font", "application/x-font", "application/octet-stream", "application/vnd.ms-fontobject"),
                "animation": ("application/json", "text/json", "application/zip", "application/octet-stream"),
                "model": ("model/", "application/octet-stream", "application/json")}

LICENCES: Dict[str, Dict[str, Any]] = {
    "cc0-1.0": {"name": "CC0 1.0 (public domain)", "commercial": True, "attribution": False, "share_alike": False},
    "cc-by-4.0": {"name": "CC BY 4.0", "commercial": True, "attribution": True, "share_alike": False},
    "cc-by-3.0": {"name": "CC BY 3.0", "commercial": True, "attribution": True, "share_alike": False},
    "cc-by-sa-4.0": {"name": "CC BY-SA 4.0", "commercial": True, "attribution": True, "share_alike": True},
    "cc-by-sa-3.0": {"name": "CC BY-SA 3.0", "commercial": True, "attribution": True, "share_alike": True},
    "cc-by-nc-4.0": {"name": "CC BY-NC 4.0", "commercial": False, "attribution": True, "share_alike": False},
    "cc-by-nc-sa-4.0": {"name": "CC BY-NC-SA 4.0", "commercial": False, "attribution": True, "share_alike": True},
    "mit": {"name": "MIT", "commercial": True, "attribution": True, "share_alike": False},
    "isc": {"name": "ISC", "commercial": True, "attribution": True, "share_alike": False},
    "apache-2.0": {"name": "Apache 2.0", "commercial": True, "attribution": True, "share_alike": False},
    "ofl-1.1": {"name": "SIL Open Font License 1.1", "commercial": True, "attribution": False, "share_alike": False,
                "notes": "Fonts may be bundled and used; the font itself may not be sold on its own."},
    "gpl-3.0": {"name": "GPL 3.0", "commercial": True, "attribution": True, "share_alike": True,
                "notes": "Copyleft: shipping it can require releasing the combined work under the GPL."},
    "pixabay": {"name": "Pixabay Content License", "commercial": True, "attribution": False, "share_alike": False,
                "notes": "No selling unaltered copies; no use implying endorsement."},
    "pexels": {"name": "Pexels License", "commercial": True, "attribution": False, "share_alike": False,
               "notes": "No selling unaltered copies; identifiable people may not be shown in a bad light."},
    "unsplash": {"name": "Unsplash License", "commercial": True, "attribution": False, "share_alike": False,
                 "notes": "No compiling photos into a competing service."},
    "lottiefiles-simple": {"name": "Lottie Simple License", "commercial": True, "attribution": False, "share_alike": False},
    "all-rights-reserved": {"name": "All rights reserved", "commercial": False, "attribution": True, "share_alike": False},
}
ALIASES = {"cc0": "cc0-1.0", "public domain": "cc0-1.0", "cc-by": "cc-by-4.0", "cc by 4.0": "cc-by-4.0",
           "cc by": "cc-by-4.0", "cc-by-sa": "cc-by-sa-4.0", "cc by-sa 4.0": "cc-by-sa-4.0", "cc-by-nc": "cc-by-nc-4.0",
           "ofl": "ofl-1.1", "sil ofl": "ofl-1.1", "sil open font license": "ofl-1.1", "apache": "apache-2.0",
           "apache 2.0": "apache-2.0", "gpl": "gpl-3.0", "gplv3": "gpl-3.0", "pixabay license": "pixabay",
           "pixabay content license": "pixabay", "pexels license": "pexels", "unsplash license": "unsplash",
           "lottie simple license": "lottiefiles-simple", "copyright": "all-rights-reserved"}
PROVIDERS = {"pixabay.com": "pixabay", "cdn.pixabay.com": "pixabay", "pexels.com": "pexels", "images.pexels.com": "pexels",
             "unsplash.com": "unsplash", "images.unsplash.com": "unsplash", "fonts.google.com": "ofl-1.1",
             "fonts.gstatic.com": "ofl-1.1", "lucide.dev": "isc", "unpkg.com/lucide-static": "isc",
             "heroicons.com": "mit", "unpkg.com/heroicons": "mit"}
PROVIDER_NAMES = {"pixabay": "Pixabay", "pexels": "Pexels", "unsplash": "Unsplash", "ofl-1.1": "Google Fonts",
                  "isc": "Lucide", "mit": "Heroicons"}


def _norm(name: str) -> str:
    """'CC BY-NC 4.0', 'cc_by_nc_4.0' and 'cc-by-nc-4.0' are the same licence."""
    return re.sub(r"[\s_]+", "-", name.strip().lower())


_ALIAS_KEYS = {_norm(k): v for k, v in ALIASES.items()}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_licence(licence: Optional[str], url: Optional[str] = None) -> Tuple[Optional[str], str]:
    """(licence id, how it was determined)."""
    if licence:
        key = _norm(licence)
        key = _ALIAS_KEYS.get(key, key)
        if key in LICENCES:
            return key, "stated"
        return None, f"'{licence}' is not a licence JARV recognises"
    if url:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        for domain, lic in PROVIDERS.items():
            if "/" in domain:
                d_host, d_path = domain.split("/", 1)
                if host == d_host and parsed.path.lstrip("/").startswith(d_path):
                    return lic, f"provider {domain}"
            elif host == domain or host.endswith("." + domain):
                return lic, f"provider {domain}"
    return None, "no licence stated and the provider does not have a single standard licence"


def check_licence(licence: Optional[str], url: Optional[str] = None, *, commercial: bool = True,
                  modify: bool = True) -> Dict[str, Any]:
    lic_id, how = resolve_licence(licence, url)
    if lic_id is None:
        return {"allowed": False, "licence": None, "determined_by": how,
                "reason": "Unknown licence: the asset may not be used until its licence is confirmed"}
    terms = LICENCES[lic_id]
    conditions = []
    if terms["attribution"]:
        conditions.append("credit the author and licence")
    if terms["share_alike"]:
        conditions.append("derivatives must use the same licence")
    if terms.get("notes"):
        conditions.append(terms["notes"])
    allowed = (terms["commercial"] or not commercial)
    reason = None if allowed else f"{terms['name']} does not allow commercial use"
    return {"allowed": allowed, "licence": lic_id, "name": terms["name"], "determined_by": how,
            "commercial_use": terms["commercial"], "attribution_required": terms["attribution"],
            "share_alike": terms["share_alike"], "modification_allowed": modify, "conditions": conditions,
            "reason": reason}


async def fetch(url: str) -> Tuple[bytes, str]:
    """GET a public URL with a size cap (indirection kept small so tests can replace the network)."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise RuntimeError(f"{url} returned {response.status_code}")
            declared = int(response.headers.get("content-length") or 0)
            if declared > MAX_BYTES:
                raise ValueError(f"The file is {declared} bytes; the limit is {MAX_BYTES}")
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError(f"The file is larger than {MAX_BYTES} bytes")
                chunks.append(chunk)
            return b"".join(chunks), response.headers.get("content-type", "").split(";")[0].strip().lower()


def _root(workspace) -> Tuple[str, Path]:
    from app.core.workspaces import fs_inspector

    host = (workspace.config or {}).get("root_path")
    container = fs_inspector.host_to_container(host) if host else None
    if not host or container is None or not container.is_dir():
        raise ValueError("This workspace has no folder to store assets in")
    return host, container.resolve()


async def _licence_row(db: AsyncSession, workspace_id: UUID, lic_id: str, provider: Optional[str]) -> AssetLicence:
    row = (await db.execute(select(AssetLicence).where(AssetLicence.workspace_id == workspace_id,
                                                       AssetLicence.licence_type == lic_id))).scalar_one_or_none()
    if row is None:
        terms = LICENCES[lic_id]
        now = _now()
        row = AssetLicence(id=uuid4(), workspace_id=workspace_id, licence_name=terms["name"], licence_type=lic_id,
                           provider=provider, terms=terms.get("notes"),
                           permitted_uses=["commercial" if terms["commercial"] else "non-commercial"]
                           + (["requires attribution"] if terms["attribution"] else []),
                           restrictions=["share-alike"] if terms["share_alike"] else [], is_active=True,
                           is_expired=False, current_uses=0, meta_data={}, created_at=now, updated_at=now)
        db.add(row)
        await db.flush()
    row.current_uses = int(row.current_uses or 0) + 1
    return row


def asset_view(a: Asset) -> Dict[str, Any]:
    meta = a.meta_data or {}
    return {"id": str(a.id), "name": a.asset_name, "type": a.asset_type, "path": a.file_path, "url": a.url,
            "size": a.file_size, "mime": a.mime_type, "sha256": a.file_hash, "licence": a.license_type,
            "author": meta.get("author"), "source_page": meta.get("source_page"), "provider": meta.get("provider"),
            "attribution": meta.get("attribution")}


def attribution(name: str, author: Optional[str], source: Optional[str], lic_id: str) -> str:
    who = f" by {author}" if author else ""
    where = f" ({source})" if source else ""
    return f"\"{name}\"{who}{where}, licensed under {LICENCES[lic_id]['name']}"


async def download(db: AsyncSession, workspace, url: str, *, folder: str = "assets", filename: Optional[str] = None,
                   licence: Optional[str] = None, author: Optional[str] = None, source_page: Optional[str] = None,
                   commercial: bool = True, created_by: Optional[UUID] = None) -> Asset:
    from app.core.internet import _ssrf_ok
    from app.core.workspaces import fs_inspector
    from app.core.workspaces.lifecycle import join_host

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise PermissionError("Assets are downloaded over https only")
    allowed, reason = _ssrf_ok(url)
    if not allowed:
        raise PermissionError(f"URL refused: {reason}")
    name = filename or PurePosixPath(parsed.path).name or "asset"
    name = re.sub(r"[^A-Za-z0-9._-]", "-", name)[:120]
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in ALLOWED:
        raise PermissionError(f"'{suffix or name}' files are not downloadable assets (allowed: "
                              f"{', '.join(sorted(ALLOWED))}); executables and archives are never downloaded")
    if not re.match(r"^[A-Za-z0-9._/-]{1,120}$", folder) or ".." in folder or folder.startswith("/"):
        raise ValueError("folder must be a relative path inside the workspace")
    verdict = check_licence(licence, url, commercial=commercial)
    if not verdict["allowed"]:
        raise PermissionError(verdict["reason"])
    data, content_type = await fetch(url)
    kind = ALLOWED[suffix]
    if content_type and not content_type.startswith(_TYPE_PREFIX[kind]) and not (suffix == ".svg" and "svg" in content_type):
        raise PermissionError(f"The server sent '{content_type}', not a {kind} file")
    if suffix == ".svg" and re.search(rb"<script|on\w+\s*=", data[:200000], re.I):
        raise PermissionError("The SVG contains script; refused")
    host, container = _root(workspace)
    target = container.joinpath(*folder.split("/"), name)
    if target.exists():
        target = target.with_name(f"{target.stem}-{uuid4().hex[:6]}{target.suffix}")
    if fs_inspector._is_banned(str(target)):
        raise PermissionError("Target is a protected location")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    rel = target.relative_to(container).as_posix()
    lic_id = verdict["licence"]
    provider = PROVIDER_NAMES.get(lic_id) if verdict["determined_by"].startswith("provider") else None
    await _licence_row(db, workspace.id, lic_id, provider)
    now = _now()
    row = Asset(id=uuid4(), workspace_id=workspace.id, asset_name=target.name, asset_type=kind, category=folder,
                file_path=rel, storage_location=join_host(host, rel.replace("/", "\\" if "\\" in host else "/")),
                url=url, file_size=len(data), mime_type=content_type or None,
                file_hash=hashlib.sha256(data).hexdigest(), created_by=created_by, is_active=True, is_public=False,
                license_type=lic_id, download_count=1, view_count=0, tags=[kind, lic_id],
                meta_data={"author": author, "source_page": source_page or url, "provider": provider,
                           "licence_determined_by": verdict["determined_by"], "conditions": verdict["conditions"],
                           "attribution": attribution(target.name, author, source_page or url, lic_id)},
                created_at=now, updated_at=now)
    db.add(row)
    await db.flush()
    return row


async def save_source(db: AsyncSession, workspace_id: UUID, asset_id: Any, *, source_page: Optional[str],
                      author: Optional[str], licence: Optional[str]) -> Asset:
    row = (await db.execute(select(Asset).where(Asset.id == UUID(str(asset_id)), Asset.workspace_id == workspace_id))
           ).scalar_one_or_none()
    if row is None:
        raise LookupError("Asset not found in this workspace")
    meta = dict(row.meta_data or {})
    if licence:
        lic_id, how = resolve_licence(licence)
        if lic_id is None:
            raise ValueError(how)
        row.license_type = lic_id
        meta["licence_determined_by"] = "stated"
        await _licence_row(db, workspace_id, lic_id, meta.get("provider"))
    if source_page:
        meta["source_page"] = source_page
    if author:
        meta["author"] = author
    if row.license_type in LICENCES:
        meta["attribution"] = attribution(row.asset_name, meta.get("author"), meta.get("source_page"), row.license_type)
    row.meta_data = meta
    row.updated_at = _now()
    await db.flush()
    return row


async def list_assets(db: AsyncSession, workspace_id: UUID) -> List[Asset]:
    return list((await db.execute(select(Asset).where(Asset.workspace_id == workspace_id, Asset.is_active.is_(True))
                                  .order_by(Asset.asset_name))).scalars().all())


async def write_manifest(db: AsyncSession, workspace) -> Dict[str, Any]:
    assets = await list_assets(db, workspace.id)
    _host, container = _root(workspace)
    manifest = {"generated_at": _now().isoformat(), "generator": "JARV", "assets": [asset_view(a) for a in assets]}
    (container / "ASSETS.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    unlicensed = [a.asset_name for a in assets if a.license_type not in LICENCES]
    return {"file": "ASSETS.json", "assets": len(assets), "unlicensed": unlicensed}


async def write_licence_file(db: AsyncSession, workspace) -> Dict[str, Any]:
    assets = await list_assets(db, workspace.id)
    _host, container = _root(workspace)
    groups: Dict[str, List[Asset]] = {}
    for a in assets:
        groups.setdefault(a.license_type or "unknown", []).append(a)
    lines = ["# Third-party assets", "", f"Generated by JARV on {_now().date().isoformat()} from the asset records.", ""]
    for lic_id in sorted(groups):
        terms = LICENCES.get(lic_id)
        lines.append(f"## {terms['name'] if terms else 'Licence not confirmed'}")
        if terms and terms.get("notes"):
            lines.append(f"\n{terms['notes']}")
        lines.append("")
        for a in groups[lic_id]:
            lines.append(f"- `{a.file_path}`: {(a.meta_data or {}).get('attribution') or a.asset_name}")
        lines.append("")
    (container / "ASSET-LICENCES.md").write_text("\n".join(lines), encoding="utf-8")
    needs_credit = [a.asset_name for a in assets if LICENCES.get(a.license_type or "", {}).get("attribution")]
    return {"file": "ASSET-LICENCES.md", "assets": len(assets), "licences": sorted(groups),
            "attribution_required": needs_credit}
