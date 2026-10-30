"""
JARV Backend - Email adapter (SMTP out, IMAP in)

Settings (environment or .env, never logged or returned):
  SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM
  IMAP_HOST, IMAP_PORT (993), IMAP_USER, IMAP_PASSWORD, IMAP_FOLDER (INBOX)
The earlier EMAIL_SMTP_* / EMAIL_IMAP_* / EMAIL_FROM names are still read when
the canonical name is unset.

Without them the adapter reports itself as not configured and nothing is
sent or read; replies stay as drafts. Each message goes to one recipient
(mass sending from Richard's accounts is a hard boundary and has no path
here). Reading and searching open the mailbox read-only and fetch with
BODY.PEEK, so nothing is marked as read, moved or deleted.
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings

SMTP_KEYS = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")
IMAP_KEYS = ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD")
_LEGACY = {"SMTP_HOST": "EMAIL_SMTP_HOST", "SMTP_PORT": "EMAIL_SMTP_PORT", "SMTP_USER": "EMAIL_SMTP_USER",
           "SMTP_PASSWORD": "EMAIL_SMTP_PASSWORD", "SMTP_FROM": "EMAIL_FROM", "IMAP_HOST": "EMAIL_IMAP_HOST",
           "IMAP_PORT": "EMAIL_IMAP_PORT", "IMAP_USER": "EMAIL_IMAP_USER", "IMAP_PASSWORD": "EMAIL_IMAP_PASSWORD",
           "IMAP_FOLDER": "EMAIL_IMAP_FOLDER"}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def _value(name: str) -> Optional[str]:
    """The canonical setting (environment, then .env through settings), then its legacy name."""
    for key in (name, _LEGACY.get(name)):
        if not key:
            continue
        raw = os.getenv(key)
        if raw is None:
            raw = getattr(settings, key, None)
        if raw not in (None, ""):
            return str(raw)
    return None


def smtp_settings() -> Dict[str, Any]:
    user = _value("SMTP_USER")
    return {"host": _value("SMTP_HOST"), "port": int(_value("SMTP_PORT") or 587), "user": user,
            "password": _value("SMTP_PASSWORD"), "sender": _value("SMTP_FROM") or user}


def imap_settings() -> Dict[str, Any]:
    return {"host": _value("IMAP_HOST"), "port": int(_value("IMAP_PORT") or 993), "user": _value("IMAP_USER"),
            "password": _value("IMAP_PASSWORD"), "folder": _value("IMAP_FOLDER") or "INBOX"}


def smtp_configured() -> bool:
    s = smtp_settings()
    return bool(s["host"] and s["user"] and s["password"] and s["sender"])


def imap_configured() -> bool:
    s = imap_settings()
    return bool(s["host"] and s["user"] and s["password"])


def _missing(keys: Sequence[str]) -> List[str]:
    return [k for k in keys if not _value(k) and not (k == "SMTP_FROM" and _value("SMTP_USER"))]


def status() -> Dict[str, Any]:
    return {"sending": smtp_configured(), "reading": imap_configured(),
            "missing_for_sending": _missing(SMTP_KEYS), "missing_for_reading": _missing(IMAP_KEYS)}


# ----- sending -----------------------------------------------------------------------------------

def _send(to: str, subject: str, body: str, reply_to_id: Optional[str], html: bool,
          attachments: Sequence[Path]) -> str:
    s = smtp_settings()
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = s["sender"], to, subject
    message["Message-ID"] = make_msgid()
    if reply_to_id:
        message["In-Reply-To"] = message["References"] = reply_to_id
    if html:
        message.set_content("This message is HTML; open it in an email client that shows HTML.")
        message.add_alternative(body, subtype="html")
    else:
        message.set_content(body)
    for path in attachments:
        kind, _encoding = mimetypes.guess_type(path.name)
        main, sub = (kind or "application/octet-stream").split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=main, subtype=sub, filename=path.name)
    with smtplib.SMTP(s["host"], s["port"], timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(s["user"], s["password"])
        server.send_message(message)
    return message["Message-ID"] or ""


async def send_email(to: str, subject: str, body: str, reply_to_id: str | None = None, *, html: bool = False,
                     attachments: Sequence[Path] = ()) -> Dict[str, Any]:
    if not smtp_configured():
        raise RuntimeError("Email sending is not configured (set SMTP_HOST, SMTP_USER, SMTP_PASSWORD and SMTP_FROM)")
    _name, address = parseaddr(to)
    if not address or "@" not in address or "," in to or ";" in to:
        raise ValueError("Exactly one recipient address is required")
    if sum(p.stat().st_size for p in attachments) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"Attachments are larger than {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB")
    message_id = await asyncio.to_thread(_send, address, subject, body, reply_to_id, html, list(attachments))
    return {"to": address, "subject": subject, "message_id": message_id}


# ----- reading and searching ---------------------------------------------------------------------

def _parse(raw: bytes) -> Dict[str, Any]:
    msg = email.message_from_bytes(raw)
    body, has_attachments = "", False
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_filename():
                has_attachments = True
            elif part.get_content_type() == "text/plain" and not body:
                payload = part.get_payload(decode=True) or b""
                body = payload.decode(part.get_content_charset() or "utf-8", "replace")
    else:
        payload = msg.get_payload(decode=True) or b""
        body = payload.decode(msg.get_content_charset() or "utf-8", "replace")
    name, address = parseaddr(msg.get("From", ""))
    return {"message_id": msg.get("Message-ID", ""), "from_name": name, "from_email": address,
            "subject": msg.get("Subject", "(no subject)"), "body": body[:20000], "date": msg.get("Date", ""),
            "has_attachments": has_attachments}


def _imap_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _fetch(criteria: List[str], limit: int, folder: Optional[str]) -> List[Dict[str, Any]]:
    s = imap_settings()
    out: List[Dict[str, Any]] = []
    with imaplib.IMAP4_SSL(s["host"], s["port"]) as client:
        client.login(s["user"], s["password"])
        typ, _ = client.select(folder or s["folder"], readonly=True)
        if typ != "OK":
            raise LookupError(f"The mailbox has no folder named '{folder or s['folder']}'")
        _typ, data = client.search("UTF-8" if any(not c.isascii() for c in criteria) else None, *criteria)
        ids = (data[0] or b"").split()[-limit:]
        for msg_id in reversed(ids):
            _typ, parts = client.fetch(msg_id, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if raw is not None:
                out.append(_parse(raw))
    return out


def _require_imap() -> None:
    if not imap_configured():
        raise RuntimeError("Email reading is not configured (set IMAP_HOST, IMAP_USER and IMAP_PASSWORD)")


async def read_unseen(limit: int = 50) -> List[Dict[str, Any]]:
    _require_imap()
    return await asyncio.to_thread(_fetch, ["UNSEEN"], max(1, min(limit, 200)), None)


async def read_messages(folder: Optional[str] = None, unread_only: bool = False, limit: int = 50) -> List[Dict[str, Any]]:
    """Newest messages first, read-only."""
    _require_imap()
    return await asyncio.to_thread(_fetch, ["UNSEEN" if unread_only else "ALL"], max(1, min(limit, 200)), folder)


async def search_messages(query: str, folder: Optional[str] = None, from_addr: Optional[str] = None,
                          limit: int = 50) -> List[Dict[str, Any]]:
    """Server-side IMAP TEXT search (subject, headers and body), optionally from one sender."""
    _require_imap()
    if not query.strip():
        raise ValueError("A search needs some text")
    criteria = ["TEXT", _imap_quote(query.strip())]
    if from_addr:
        criteria += ["FROM", _imap_quote(from_addr.strip())]
    return await asyncio.to_thread(_fetch, criteria, max(1, min(limit, 200)), folder)


# ----- connection checks (no message is sent or read) -------------------------------------------

def _check_smtp() -> None:
    s = smtp_settings()
    with smtplib.SMTP(s["host"], s["port"], timeout=15) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(s["user"], s["password"])


def _check_imap() -> None:
    s = imap_settings()
    with imaplib.IMAP4_SSL(s["host"], s["port"]) as client:
        client.login(s["user"], s["password"])
        client.select(s["folder"], readonly=True)


async def check_sending() -> None:
    if not smtp_configured():
        raise RuntimeError("Email sending is not configured")
    await asyncio.to_thread(_check_smtp)


async def check_reading() -> None:
    _require_imap()
    await asyncio.to_thread(_check_imap)
