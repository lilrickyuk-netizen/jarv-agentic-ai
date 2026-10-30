"""
JARV Backend - Outbound notification integrations

How JARV notifies Richard: by email to his own address (NOTIFY_EMAIL, or the
SMTP_FROM account itself) through the mailer, or by an HTTPS webhook
(NOTIFY_WEBHOOK_URL: Slack, Discord, ntfy and most chat tools accept a JSON
POST). A dry run is the default and sends nothing; the local_mock target only
ever dry-runs. Each live target reports a real, credential-derived status, an
unconfigured target answers with its disabled state and setup line, and a
live send only reports success when the mail server or webhook accepted it.
Notifications go to Richard only, never to customers or lists.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Fragments that must be redacted if they ever appear in a payload preview.
_REDACT_HINTS = ("key", "token", "secret", "password", "authorization", "bearer")


def _redact(text: str) -> str:
    out = text
    for hint in _REDACT_HINTS:
        if hint in out.lower():
            return "[REDACTED — payload may contain secrets]"
    return out[:500]


def http_client(**kwargs) -> httpx.AsyncClient:
    """Indirection for the webhook request (tests replace the transport)."""
    return httpx.AsyncClient(**kwargs)


def notify_email(operator_email: Optional[str] = None) -> Optional[str]:
    from app.core.business import mailer
    from app.core.ops.connections import value

    return value("NOTIFY_EMAIL") or operator_email or mailer.smtp_settings()["sender"]


def webhook_url() -> Optional[str]:
    from app.core.ops.connections import value

    return value("NOTIFY_WEBHOOK_URL")


def _webhook_problem(url: Optional[str]) -> Optional[str]:
    if not url:
        return "Set NOTIFY_WEBHOOK_URL to an https webhook (Slack, Discord, ntfy) to enable."
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return "NOTIFY_WEBHOOK_URL must be an https URL."
    return None


class IntegrationRegistry:
    """Registry of outbound notification targets and their live readiness."""

    def list(self) -> List[Dict[str, Any]]:
        from app.core.business import mailer

        smtp_ready = mailer.smtp_configured()
        hook_problem = _webhook_problem(webhook_url())
        return [
            {"name": "email_smtp", "type": "notification", "status": "enabled" if smtp_ready else "disabled_no_creds",
             "requires_approval": True,
             "message": None if smtp_ready else "Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD and SMTP_FROM to enable."},
            {"name": "webhook", "type": "webhook", "status": "enabled" if hook_problem is None else "disabled_no_creds",
             "requires_approval": True, "message": hook_problem},
            {"name": "local_mock", "type": "mock", "status": "enabled", "requires_approval": False,
             "message": "Local dry-run sink for safe verification (no external send)."},
        ]

    async def send(self, target: str, message: str, dry_run: bool = True,
                   operator_email: Optional[str] = None) -> Dict[str, Any]:
        """Dry-run (default) or send a notification to Richard. Never reports a send that did not happen."""
        preview = _redact(message or "")
        if dry_run or target == "local_mock":
            logger.info(f"[integrations] DRY-RUN send to '{target}': {preview}")
            return {"ok": True, "mode": "dry_run", "target": target, "payload_preview": preview,
                    "summary": f"dry-run notification to '{target}' logged (not sent)", "sent": False}

        info = {i["name"]: i for i in self.list()}.get(target)
        if info is None:
            return {"ok": False, "mode": "unknown_target", "target": target, "sent": False,
                    "summary": f"'{target}' is not a notification target (email_smtp, webhook, local_mock)"}
        if info["status"] != "enabled":
            return {"ok": False, "mode": "disabled", "target": target, "sent": False,
                    "summary": f"live send to '{target}' is disabled ({info['message']})"}
        try:
            if target == "email_smtp":
                from app.core.business import mailer

                to = notify_email(operator_email)
                if not to:
                    raise ValueError("No address to notify: set NOTIFY_EMAIL")
                sent = await mailer.send_email(to, "JARV notification", message)
                return {"ok": True, "mode": "live", "target": target, "sent": True, "summary": "notification emailed",
                        "message_id": sent["message_id"]}
            async with http_client(timeout=httpx.Timeout(15.0)) as client:
                response = await client.post(webhook_url(), json={"text": message, "content": message,
                                                                  "source": "jarv"})
            if response.status_code >= 300:
                return {"ok": False, "mode": "live", "target": target, "sent": False,
                        "summary": f"the webhook answered HTTP {response.status_code}; nothing was delivered"}
            return {"ok": True, "mode": "live", "target": target, "sent": True,
                    "summary": f"webhook accepted the notification (HTTP {response.status_code})"}
        except (OSError, ValueError, RuntimeError, httpx.HTTPError) as exc:
            logger.warning(f"[integrations] live send to '{target}' failed: {type(exc).__name__}")
            return {"ok": False, "mode": "live", "target": target, "sent": False,
                    "summary": f"live send to '{target}' failed: {_redact(str(exc)) or type(exc).__name__}"}


integrations = IntegrationRegistry()
