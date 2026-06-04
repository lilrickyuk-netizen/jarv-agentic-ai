"""
JARV Backend - Safe Internet Access

Controlled outbound internet for research/build/launch/operate/scale. NOT
unrestricted:
  * only http/https; file://, internal/loopback/private IPs blocked (SSRF guard),
  * GET-only fetch with timeout + response size cap; never executes downloads,
  * secrets are never sent; payload previews are redacted,
  * package metadata (npm/PyPI/GitHub) and CVE (OSV) use public read-only APIs,
  * assets only from an approved-source allowlist with licence records,
  * live external sends (email/post/form/API-write) are NOT here — they go
    through the approval-gated integrations layer.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import socket
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 12.0
MAX_BYTES = 200_000

APPROVED_ASSET_SOURCES = {
    "pixabay.com", "pexels.com", "unsplash.com", "freesound.org",
    "opengameart.org", "fonts.google.com", "fontshare.com", "lucide.dev",
    "heroicons.com", "svgrepo.com", "lottiefiles.com",
}

_BLOCKED_HOST_FRAGMENTS = ("localhost", "metadata.google", "169.254.169.254")


def _ssrf_ok(url: str) -> tuple[bool, Optional[str]]:
    """Block non-http(s), internal/loopback/private targets, and metadata IPs."""
    try:
        p = urllib.parse.urlparse(url)
    except Exception:  # noqa: BLE001
        return False, "unparseable URL"
    if p.scheme not in ("http", "https"):
        return False, f"scheme '{p.scheme}' not allowed (http/https only)"
    host = p.hostname or ""
    if not host:
        return False, "missing host"
    low = host.lower()
    if any(frag in low for frag in _BLOCKED_HOST_FRAGMENTS):
        return False, "internal/metadata host blocked"
    try:
        for fam, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, f"resolves to non-public IP {ip} (SSRF blocked)"
    except Exception:
        # DNS failure -> let the request attempt fail normally (not an SSRF bypass).
        pass
    return True, None


def _redact(text: str) -> str:
    low = text.lower()
    for h in ("api_key", "apikey", "secret", "token", "password", "authorization", "bearer", "private key"):
        if h in low:
            return "[REDACTED — may contain secrets]"
    return text


async def fetch_url(url: str) -> Dict[str, Any]:
    """GET a public URL (read-only, size-capped, SSRF-guarded). Never executes."""
    ok, reason = _ssrf_ok(url)
    if not ok:
        return {"ok": False, "blocked": True, "url": url, "reason": reason}
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "JARV-Research/1.0"})
            body = r.text[:MAX_BYTES]
            return {"ok": r.status_code < 400, "url": str(r.url), "status": r.status_code,
                    "content_type": r.headers.get("content-type", ""),
                    "title": _extract_title(body), "text": _redact(_strip_html(body))[:8000],
                    "bytes": len(r.content)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "reason": str(exc)}


def _extract_title(html: str) -> str:
    import re
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip()[:200] if m else "")


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


async def check_package_registry(name: str, ecosystem: str = "npm") -> Dict[str, Any]:
    """Read public package metadata (npm or PyPI). Read-only; no install."""
    eco = ecosystem.lower()
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as c:
            if eco in ("npm", "node", "js"):
                r = await c.get(f"https://registry.npmjs.org/{urllib.parse.quote(name)}")
                if r.status_code >= 400:
                    return {"ok": False, "name": name, "ecosystem": "npm", "reason": f"HTTP {r.status_code}"}
                d = r.json()
                latest = d.get("dist-tags", {}).get("latest")
                meta = d.get("versions", {}).get(latest, {})
                return {"ok": True, "name": name, "ecosystem": "npm", "latest": latest,
                        "license": meta.get("license") or d.get("license"),
                        "homepage": d.get("homepage"), "deprecated": bool(meta.get("deprecated"))}
            if eco in ("pypi", "python", "pip"):
                r = await c.get(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json")
                if r.status_code >= 400:
                    return {"ok": False, "name": name, "ecosystem": "pypi", "reason": f"HTTP {r.status_code}"}
                info = r.json().get("info", {})
                return {"ok": True, "name": name, "ecosystem": "pypi",
                        "latest": info.get("version"), "license": info.get("license"),
                        "homepage": info.get("home_page") or info.get("project_url")}
            return {"ok": False, "name": name, "ecosystem": eco, "reason": "unsupported ecosystem"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "name": name, "ecosystem": eco, "reason": str(exc)}


async def check_cve(name: str, ecosystem: str = "npm", version: Optional[str] = None) -> Dict[str, Any]:
    """Query the public OSV vulnerability database (read-only)."""
    eco_map = {"npm": "npm", "node": "npm", "js": "npm", "pypi": "PyPI", "python": "PyPI", "pip": "PyPI"}
    payload = {"package": {"name": name, "ecosystem": eco_map.get(ecosystem.lower(), "npm")}}
    if version:
        payload["version"] = version
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as c:
            r = await c.post("https://api.osv.dev/v1/query", content=json.dumps(payload).encode())
            if r.status_code >= 400:
                return {"ok": False, "name": name, "reason": f"HTTP {r.status_code}"}
            vulns = r.json().get("vulns", []) or []
            return {"ok": True, "name": name, "ecosystem": ecosystem,
                    "vulnerabilities": len(vulns),
                    "ids": [v.get("id") for v in vulns[:10]],
                    "risk": "vulnerable" if vulns else "clear"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "name": name, "reason": str(exc)}


def asset_licence_dry_run(query: str, source: str) -> Dict[str, Any]:
    """Dry-run asset lookup: confirm the source is approved; no file downloaded."""
    src = (source or "").lower().strip()
    approved = any(src == s or src.endswith(s) or s in src for s in APPROVED_ASSET_SOURCES)
    return {
        "ok": approved, "query": query, "source": source,
        "approved_source": approved,
        "commercial_use": "verify on source page before download",
        "downloaded": False,
        "note": ("Approved source. A real download requires an approved workspace "
                 "target + a licence record in ASSET_LICENCES.md." if approved
                 else f"Source '{source}' is not in the approved asset allowlist; blocked."),
        "approved_sources": sorted(APPROVED_ASSET_SOURCES),
    }


def internet_tools() -> List[Dict[str, Any]]:
    """Registry of internet tools (for /api/tools/internet/list)."""
    auto = "allowed_auto"
    appr = "requires_approval"
    return [
        {"name": "web_search", "status": "disabled_no_creds",
         "note": "Set a search API key to enable; fetch_url works for known URLs."},
        {"name": "fetch_url", "status": auto, "note": "GET public pages (SSRF-guarded, read-only)."},
        {"name": "fetch_docs_page", "status": auto},
        {"name": "fetch_api_docs", "status": auto},
        {"name": "check_package_registry", "status": auto, "note": "npm/PyPI metadata."},
        {"name": "check_cve_database", "status": auto, "note": "OSV vulnerability query."},
        {"name": "check_external_status_page", "status": auto},
        {"name": "download_asset_with_licence_check", "status": appr,
         "note": "Dry-run auto; real download needs approved workspace + licence record."},
        {"name": "save_web_source_record", "status": auto},
        {"name": "summarise_web_source", "status": auto},
        {"name": "create_research_record", "status": auto},
        {"name": "external_http_request_dry_run", "status": auto},
        {"name": "external_http_request_with_approval", "status": appr},
    ]
