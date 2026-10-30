"""
JARV Backend - External service connections (Repair 14b)

One catalogue of every outside service JARV can use, for the Settings page:
which settings each needs, whether they are set (values are never returned,
and copied example values such as "your_..._here" count as unset), what the
service enables, how to set it up, and a live check.

A check proves the credentials work with one free, read-only call (listing
models, reading the account, a one-day stats query, an SMTP or IMAP login,
a health endpoint). It never sends a message, never generates content and
never spends credit. Responses are reduced to ok / HTTP status / reachability,
so no response body (which could echo a credential) reaches the dashboard.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings


def http_client(**kwargs) -> httpx.AsyncClient:
    """Indirection for every check request (tests replace the transport)."""
    return httpx.AsyncClient(**kwargs)


def _raw(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        value = getattr(settings, name, None)
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def is_example(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("your_", "your-", "changeme", "replace_me", "xxx")) or lowered.endswith(
        ("_here", "-here")) or lowered in ("none", "null", "example", "sk-...")


def value(name: str) -> Optional[str]:
    """A setting's value only when it is really set (not blank and not a copied example)."""
    raw = _raw(name)
    return None if raw is None or is_example(raw) else raw


def _first(*names: str) -> Optional[str]:
    return next((v for v in (value(n) for n in names) if v), None)


CheckFn = Callable[[], Awaitable[Tuple[bool, str]]]


@dataclass
class Service:
    key: str
    name: str
    group: str
    enables: str
    settings_needed: List[str]
    setup: str
    alternatives: Dict[str, str] = field(default_factory=dict)  # setting -> accepted alternative name
    optional: List[str] = field(default_factory=list)
    check: Optional[str] = None
    check_note: Optional[str] = None
    enabled_flag: Optional[str] = None

    def missing(self) -> List[str]:
        return [s for s in self.settings_needed if not _first(s, *(self.alternatives.get(s, "").split() or []))]

    def example_values(self) -> List[str]:
        names = self.settings_needed + self.optional + [a for alt in self.alternatives.values() for a in alt.split()]
        return [n for n in names if _raw(n) and is_example(_raw(n) or "")]

    def configured(self) -> bool:
        if self.enabled_flag and not getattr(settings, self.enabled_flag, False):
            return False
        return not self.missing()


SERVICES: List[Service] = [
    Service("claude", "Claude (Anthropic)", "AI models",
            "JARV's primary model for every agent; missions fail over to the next provider when it is unavailable.",
            ["CLAUDE_API_KEY"], "Create an API key at console.anthropic.com > API keys and set CLAUDE_API_KEY "
            "(ANTHROPIC_API_KEY also works).", alternatives={"CLAUDE_API_KEY": "ANTHROPIC_API_KEY"}, check="claude"),
    Service("openai", "OpenAI", "AI models",
            "Failover models, and speech-to-text and text-to-speech when Voicebox is not running.",
            ["OPENAI_API_KEY"], "Create a key at platform.openai.com > API keys and set OPENAI_API_KEY.",
            optional=["OPENAI_MODEL"], check="openai"),
    Service("gemini", "Google Gemini", "AI models", "Additional failover models.",
            ["GEMINI_API_KEY"], "Create a key in Google AI Studio (aistudio.google.com) and set GEMINI_API_KEY.",
            check="gemini"),
    Service("ollama", "Ollama (local models)", "AI models",
            "Last-resort local models on your own server, with no per-token cost.",
            ["OLLAMA_BASE_URL"], "Run Ollama on the server, pull a model (ollama pull llama3.1), then set "
            "OLLAMA_ENABLED=true and OLLAMA_BASE_URL.", optional=["OLLAMA_MODEL"], check="ollama",
            enabled_flag="OLLAMA_ENABLED"),
    Service("email_sending", "Email sending (SMTP)", "Email",
            "Support replies, the agents' approved emails and notifications to you; without it they are saved as drafts.",
            ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"],
            "Use your mail provider's SMTP server with an app password: set SMTP_HOST, SMTP_PORT (587), "
            "SMTP_USER, SMTP_PASSWORD and SMTP_FROM.",
            alternatives={"SMTP_HOST": "EMAIL_SMTP_HOST", "SMTP_USER": "EMAIL_SMTP_USER",
                          "SMTP_PASSWORD": "EMAIL_SMTP_PASSWORD", "SMTP_FROM": "EMAIL_FROM SMTP_USER EMAIL_SMTP_USER"},
            optional=["SMTP_PORT"], check="smtp"),
    Service("email_reading", "Email reading (IMAP)", "Email",
            "The support inbox sync and the agents' email_read and email_search, all read-only.",
            ["IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"],
            "Use your mail provider's IMAP server with an app password: set IMAP_HOST, IMAP_PORT (993), IMAP_USER, "
            "IMAP_PASSWORD and optionally IMAP_FOLDER.",
            alternatives={"IMAP_HOST": "EMAIL_IMAP_HOST", "IMAP_USER": "EMAIL_IMAP_USER",
                          "IMAP_PASSWORD": "EMAIL_IMAP_PASSWORD"}, optional=["IMAP_PORT", "IMAP_FOLDER"], check="imap"),
    Service("notify_webhook", "Notification webhook", "Notifications",
            "Notifications to your phone or chat (Slack, Discord or ntfy) as well as by email.",
            ["NOTIFY_WEBHOOK_URL"], "Create an incoming webhook in Slack or Discord, or pick an ntfy.sh topic, and set "
            "NOTIFY_WEBHOOK_URL to its https URL.",
            check_note="Use Send test notification: a check would itself post a message."),
    Service("slack", "Slack", "Notifications",
            "The agents' Slack tools: post updates (after approval), read channels and search messages.",
            ["SLACK_BOT_TOKEN"], "Create an app at api.slack.com/apps, add the bot scopes chat:write, channels:read and "
            "channels:history, install it to your workspace and set SLACK_BOT_TOKEN (xoxb-). For workspace-wide search "
            "also set SLACK_USER_TOKEN (xoxp-) with the search:read scope.", optional=["SLACK_USER_TOKEN"],
            check="slack"),
    Service("stripe", "Stripe", "Revenue",
            "Revenue, subscriptions, failed payments and conversion read directly from Stripe.",
            ["STRIPE_SECRET_KEY"], "Create a restricted key with read access in the Stripe Dashboard > Developers > "
            "API keys and set STRIPE_SECRET_KEY. Add STRIPE_WEBHOOK_SECRET to record payments as they happen.",
            optional=["STRIPE_WEBHOOK_SECRET"], check="stripe"),
    Service("plausible", "Plausible Analytics", "Revenue",
            "Website traffic for Analytics and Revenue Operations; without it JARV uses recorded KPIs.",
            ["PLAUSIBLE_API_KEY", "PLAUSIBLE_SITE_ID"], "In Plausible go to Account settings > API keys, create a Stats "
            "API key and set PLAUSIBLE_API_KEY and PLAUSIBLE_SITE_ID (your site's domain).",
            optional=["PLAUSIBLE_URL"], check="plausible"),
    Service("elevenlabs", "ElevenLabs", "Voice",
            "Natural spoken replies when Voicebox is not running.", ["ELEVENLABS_API_KEY"],
            "Create an API key at elevenlabs.io > Developers > API keys and set ELEVENLABS_API_KEY "
            "(and ELEVENLABS_VOICE_ID for a chosen voice).", optional=["ELEVENLABS_VOICE_ID"], check="elevenlabs"),
    Service("voicebox", "Voicebox (self-hosted speech)", "Voice",
            "Private speech-to-text and text-to-speech on your own server.", ["VOICEBOX_BASE_URL"],
            "Run the Voicebox service and set VOICEBOX_BASE_URL (and VOICEBOX_PROFILE_ID for the voice).",
            optional=["VOICEBOX_PROFILE_ID"], check="voicebox"),
    Service("github", "GitHub", "Code and assets",
            "Repository operations on private repositories.", ["GITHUB_TOKEN"],
            "Create a fine-grained token at github.com > Settings > Developer settings > Personal access tokens, "
            "scoped to the repositories JARV works on, and set GITHUB_TOKEN.", check="github"),
    Service("unsplash", "Unsplash", "Code and assets", "Free-licence photos for content and sites.",
            ["UNSPLASH_ACCESS_KEY"], "Register an app at unsplash.com/developers and set UNSPLASH_ACCESS_KEY.",
            check="unsplash"),
    Service("pexels", "Pexels", "Code and assets", "Free-licence photos and video.", ["PEXELS_API_KEY"],
            "Request a key at pexels.com/api and set PEXELS_API_KEY.", check="pexels"),
    Service("deploy_ssh", "Deploy server (SSH)", "Infrastructure",
            "Staging and production deploys and rollbacks on your VPS.",
            ["DEPLOY_SSH_HOST", "DEPLOY_SSH_PRIVATE_KEY", "DEPLOY_SSH_KNOWN_HOSTS"],
            "Follow docs/DEPLOYMENT.md: create a dedicated deploy key, set DEPLOY_SSH_HOST, DEPLOY_SSH_USER, "
            "DEPLOY_SSH_PRIVATE_KEY (base64) and DEPLOY_SSH_KNOWN_HOSTS.", optional=["DEPLOY_SSH_USER"],
            check_note="Checked by every deploy, which connects before changing anything."),
    Service("docker_ops", "Container operations", "Infrastructure",
            "Container status and approved restarts through the restricted Docker proxy.", ["DOCKER_OPS_URL"],
            "The production compose file sets DOCKER_OPS_URL to the docker-proxy service.", check="docker_ops"),
    Service("prometheus", "Prometheus", "Infrastructure", "Metrics behind monitoring and self-healing.",
            ["PROMETHEUS_URL"], "Start the monitoring stack (docker-compose.monitoring.yml) and set PROMETHEUS_URL.",
            check="prometheus"),
    Service("sentry", "Sentry", "Infrastructure", "Error reports from the backend.", ["SENTRY_DSN"],
            "Create a project at sentry.io and set SENTRY_DSN.",
            check_note="Sentry has no read-only check; errors appear in your Sentry project once set."),
]
BY_KEY = {s.key: s for s in SERVICES}


# ----- checks ------------------------------------------------------------------------------------

def _verdict(response: httpx.Response, what: str) -> Tuple[bool, str]:
    code = response.status_code
    if 200 <= code < 300:
        return True, f"{what} accepted the credentials (HTTP {code})"
    if code in (401, 403):
        return False, f"{what} rejected the credentials (HTTP {code}); create a new key and update the setting"
    if code == 429:
        return False, f"{what} is rate limiting this account (HTTP 429); try again shortly"
    return False, f"{what} answered HTTP {code}"


async def _get(url: str, what: str, **kwargs: Any) -> Tuple[bool, str]:
    async with http_client(timeout=httpx.Timeout(15.0)) as client:
        return _verdict(await client.get(url, **kwargs), what)


async def _check_claude() -> Tuple[bool, str]:
    return await _get("https://api.anthropic.com/v1/models", "Anthropic",
                      headers={"x-api-key": _first("CLAUDE_API_KEY", "ANTHROPIC_API_KEY"),
                               "anthropic-version": "2023-06-01"})


async def _check_openai() -> Tuple[bool, str]:
    return await _get("https://api.openai.com/v1/models", "OpenAI",
                      headers={"Authorization": f"Bearer {value('OPENAI_API_KEY')}"})


async def _check_gemini() -> Tuple[bool, str]:
    return await _get("https://generativelanguage.googleapis.com/v1beta/models", "Google AI",
                      headers={"x-goog-api-key": value("GEMINI_API_KEY")})


async def _check_ollama() -> Tuple[bool, str]:
    return await _get(f"{value('OLLAMA_BASE_URL').rstrip('/')}/api/tags", "Ollama")


async def _check_elevenlabs() -> Tuple[bool, str]:
    return await _get("https://api.elevenlabs.io/v1/models", "ElevenLabs",
                      headers={"xi-api-key": value("ELEVENLABS_API_KEY")})


async def _check_stripe() -> Tuple[bool, str]:
    return await _get("https://api.stripe.com/v1/balance_transactions", "Stripe", params={"limit": 1},
                      auth=(value("STRIPE_SECRET_KEY"), ""))


async def _check_plausible() -> Tuple[bool, str]:
    base = (value("PLAUSIBLE_URL") or "https://plausible.io").rstrip("/")
    async with http_client(timeout=httpx.Timeout(15.0)) as client:
        response = await client.post(f"{base}/api/v2/query",
                                     headers={"Authorization": f"Bearer {value('PLAUSIBLE_API_KEY')}"},
                                     json={"site_id": value("PLAUSIBLE_SITE_ID"), "metrics": ["visitors"],
                                           "date_range": "day"})
    if response.status_code == 400:
        return False, "Plausible accepted the key but not the site: check PLAUSIBLE_SITE_ID (HTTP 400)"
    return _verdict(response, "Plausible")


async def _check_github() -> Tuple[bool, str]:
    return await _get("https://api.github.com/user", "GitHub",
                      headers={"Authorization": f"Bearer {value('GITHUB_TOKEN')}",
                               "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})


async def _check_unsplash() -> Tuple[bool, str]:
    return await _get("https://api.unsplash.com/photos", "Unsplash", params={"per_page": 1},
                      headers={"Authorization": f"Client-ID {value('UNSPLASH_ACCESS_KEY')}"})


async def _check_pexels() -> Tuple[bool, str]:
    return await _get("https://api.pexels.com/v1/curated", "Pexels", params={"per_page": 1},
                      headers={"Authorization": value("PEXELS_API_KEY")})


async def _check_voicebox() -> Tuple[bool, str]:
    return await _get(f"{value('VOICEBOX_BASE_URL').rstrip('/')}/health", "Voicebox")


async def _check_docker_ops() -> Tuple[bool, str]:
    return await _get(f"{value('DOCKER_OPS_URL').rstrip('/')}/_ping", "The Docker proxy")


async def _check_prometheus() -> Tuple[bool, str]:
    return await _get(f"{value('PROMETHEUS_URL').rstrip('/')}/-/ready", "Prometheus")


async def _check_slack() -> Tuple[bool, str]:
    async with http_client(timeout=httpx.Timeout(15.0)) as client:
        response = await client.post("https://slack.com/api/auth.test",
                                     headers={"Authorization": f"Bearer {value('SLACK_BOT_TOKEN')}"})
    if response.status_code != 200:
        return _verdict(response, "Slack")
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if body.get("ok") is True:
        return True, f"Slack accepted the bot token for the {body.get('team', 'workspace')} workspace"
    return False, f"Slack rejected the bot token ({body.get('error', 'unknown error')})"


async def _check_smtp() -> Tuple[bool, str]:
    from app.core.business import mailer

    await mailer.check_sending()
    return True, "Signed in to the SMTP server (no message sent)"


async def _check_imap() -> Tuple[bool, str]:
    from app.core.business import mailer

    await mailer.check_reading()
    return True, "Signed in to the mailbox read-only (nothing read or changed)"


CHECKS: Dict[str, CheckFn] = {
    "claude": _check_claude, "openai": _check_openai, "gemini": _check_gemini, "ollama": _check_ollama,
    "elevenlabs": _check_elevenlabs, "stripe": _check_stripe, "plausible": _check_plausible,
    "github": _check_github, "unsplash": _check_unsplash, "pexels": _check_pexels, "voicebox": _check_voicebox,
    "slack": _check_slack, "docker_ops": _check_docker_ops, "prometheus": _check_prometheus, "smtp": _check_smtp, "imap": _check_imap,
}


async def check(key: str) -> Dict[str, Any]:
    """Run one service's live check. LookupError for an unknown service, ValueError when it cannot be checked."""
    import smtplib

    service = BY_KEY.get(key)
    if service is None:
        raise LookupError(f"No service named '{key}'")
    if service.check is None:
        raise ValueError(service.check_note or f"{service.name} has no live check")
    if not service.configured():
        raise ValueError(f"{service.name} is not configured: set {', '.join(service.missing()) or service.enabled_flag}")
    try:
        ok, detail = await CHECKS[service.check]()
    except smtplib.SMTPAuthenticationError:
        ok, detail = False, "The mail server rejected the username or password"
    except httpx.TimeoutException:
        ok, detail = False, f"{service.name} did not answer within 15 seconds"
    except (httpx.HTTPError, OSError) as exc:
        ok, detail = False, f"Could not reach {service.name} ({type(exc).__name__})"
    except RuntimeError as exc:
        ok, detail = False, str(exc)[:200]
    except Exception as exc:  # imaplib.IMAP4.error and other client errors carry no credentials
        ok, detail = False, f"{service.name} check failed ({type(exc).__name__})"
    return {"service": key, "ok": ok, "detail": detail}


def overview() -> List[Dict[str, Any]]:
    rows = []
    for s in SERVICES:
        configured = s.configured()
        examples = s.example_values()
        rows.append({
            "key": s.key, "name": s.name, "group": s.group, "enables": s.enables, "configured": configured,
            "settings": s.settings_needed, "optional_settings": s.optional, "missing": s.missing(),
            "example_values": examples, "setup": None if configured else s.setup,
            "flag": s.enabled_flag, "flag_on": bool(getattr(settings, s.enabled_flag, False)) if s.enabled_flag else None,
            "checkable": bool(s.check) and configured, "check_note": s.check_note,
        })
    return rows
