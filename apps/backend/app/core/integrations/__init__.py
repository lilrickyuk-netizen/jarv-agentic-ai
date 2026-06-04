"""
JARV Backend - External I/O Integration Registry

Safe outbound-integration foundation that works WITHOUT live credentials.

  * Integration registry with per-integration status (enabled / disabled_no_creds).
  * Dry-run mode is the default: payloads are validated and logged (secret-safe,
    never echoing tokens) but nothing leaves the machine.
  * Live sends require credentials AND explicit allow; otherwise they degrade to a
    disabled state instead of crashing.
  * A local mock webhook target is always available for verification.

This is the secret-safe seam JARV uses to notify, post, or call out — gated so
nothing is sent externally without configuration + approval.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.core.config import settings

logger = logging.getLogger(__name__)

# Fragments that must be redacted if they ever appear in a payload preview.
_REDACT_HINTS = ("key", "token", "secret", "password", "authorization", "bearer")


def _redact(text: str) -> str:
    out = text
    for hint in _REDACT_HINTS:
        if hint in out.lower():
            return "[REDACTED — payload may contain secrets]"
    return out[:500]


class IntegrationRegistry:
    """Registry of outbound integrations and their live readiness."""

    def list(self) -> List[Dict[str, Any]]:
        """Return each integration with a real, credential-derived status."""
        items: List[Dict[str, Any]] = []

        # Email (SMTP) — enabled only when SMTP host + user configured.
        smtp_ready = bool(getattr(settings, "SMTP_HOST", None) and getattr(settings, "SMTP_USER", None))
        items.append({
            "name": "email_smtp",
            "type": "notification",
            "status": "enabled" if smtp_ready else "disabled_no_creds",
            "requires_approval": True,
            "message": None if smtp_ready else "Set SMTP_HOST/SMTP_USER/SMTP_PASSWORD to enable.",
        })

        # Generic outbound webhook — always available in dry-run; live posts need a URL + approval.
        items.append({
            "name": "webhook",
            "type": "webhook",
            "status": "enabled",  # dry-run always available
            "requires_approval": True,
            "message": "Dry-run available now; live POST requires a target URL and approval.",
        })

        # Local mock target — always available for verification.
        items.append({
            "name": "local_mock",
            "type": "mock",
            "status": "enabled",
            "requires_approval": False,
            "message": "Local dry-run sink for safe verification (no external send).",
        })
        return items

    async def send(self, target: str, message: str, dry_run: bool = True) -> Dict[str, Any]:
        """
        Send (or dry-run) a notification. Default is dry-run: the payload is logged
        secret-safe and nothing leaves the machine. Live sends require credentials;
        missing credentials degrade to a safe disabled response (never crash).
        """
        preview = _redact(message or "")
        if dry_run or target == "local_mock":
            logger.info(f"[integrations] DRY-RUN send to '{target}': {preview}")
            return {
                "ok": True,
                "mode": "dry_run",
                "target": target,
                "payload_preview": preview,
                "summary": f"dry-run notification to '{target}' logged (not sent)",
                "sent": False,
            }

        # Live send path: only proceed if the integration is actually configured.
        configured = {i["name"]: i for i in self.list()}
        info = configured.get(target)
        if not info or info["status"] != "enabled" or target in ("webhook",):
            return {
                "ok": False,
                "mode": "disabled",
                "target": target,
                "summary": (f"live send to '{target}' is disabled "
                            f"({(info or {}).get('message') or 'not configured'})"),
                "sent": False,
            }
        # If we reach here a real adapter would perform the send; we never fabricate success.
        return {
            "ok": False,
            "mode": "requires_adapter",
            "target": target,
            "summary": f"live adapter for '{target}' not configured; refusing to fake a send",
            "sent": False,
        }


integrations = IntegrationRegistry()
