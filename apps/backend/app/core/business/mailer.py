"""
JARV Backend - Email adapter (SMTP out, IMAP in)

Settings (environment, never logged):
  EMAIL_SMTP_HOST, EMAIL_SMTP_PORT (587), EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD, EMAIL_FROM
  EMAIL_IMAP_HOST, EMAIL_IMAP_PORT (993), EMAIL_IMAP_USER, EMAIL_IMAP_PASSWORD, EMAIL_IMAP_FOLDER (INBOX)

Without them the adapter reports itself as not configured and nothing is
sent or read; replies stay as drafts. Messages are sent one at a time to one
recipient (mass sending from Richard's accounts is a hard boundary and has no
path here). Reading uses BODY.PEEK so the mailbox is not changed.
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Any, Dict, List


def smtp_settings() -> Dict[str, Any]:
    return {"host": os.getenv("EMAIL_SMTP_HOST"), "port": int(os.getenv("EMAIL_SMTP_PORT") or 587),
            "user": os.getenv("EMAIL_SMTP_USER"), "password": os.getenv("EMAIL_SMTP_PASSWORD"),
            "sender": os.getenv("EMAIL_FROM") or os.getenv("EMAIL_SMTP_USER")}


def imap_settings() -> Dict[str, Any]:
    return {"host": os.getenv("EMAIL_IMAP_HOST"), "port": int(os.getenv("EMAIL_IMAP_PORT") or 993),
            "user": os.getenv("EMAIL_IMAP_USER"), "password": os.getenv("EMAIL_IMAP_PASSWORD"),
            "folder": os.getenv("EMAIL_IMAP_FOLDER") or "INBOX"}


def smtp_configured() -> bool:
    s = smtp_settings()
    return bool(s["host"] and s["user"] and s["password"] and s["sender"])


def imap_configured() -> bool:
    s = imap_settings()
    return bool(s["host"] and s["user"] and s["password"])


def status() -> Dict[str, Any]:
    missing_out = [k for k in ("EMAIL_SMTP_HOST", "EMAIL_SMTP_USER", "EMAIL_SMTP_PASSWORD") if not os.getenv(k)]
    missing_in = [k for k in ("EMAIL_IMAP_HOST", "EMAIL_IMAP_USER", "EMAIL_IMAP_PASSWORD") if not os.getenv(k)]
    return {"sending": smtp_configured(), "reading": imap_configured(),
            "missing_for_sending": missing_out, "missing_for_reading": missing_in}


def _send(to: str, subject: str, body: str, reply_to_id: str | None) -> str:
    s = smtp_settings()
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = s["sender"], to, subject
    message["Message-ID"] = make_msgid()
    if reply_to_id:
        message["In-Reply-To"] = message["References"] = reply_to_id
    message.set_content(body)
    with smtplib.SMTP(s["host"], s["port"], timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(s["user"], s["password"])
        server.send_message(message)
    return message["Message-ID"] or ""


async def send_email(to: str, subject: str, body: str, reply_to_id: str | None = None) -> Dict[str, Any]:
    if not smtp_configured():
        raise RuntimeError("Email sending is not configured (set EMAIL_SMTP_HOST, EMAIL_SMTP_USER, "
                           "EMAIL_SMTP_PASSWORD and EMAIL_FROM)")
    name, address = parseaddr(to)
    if not address or "@" not in address or "," in to or ";" in to:
        raise ValueError("Exactly one recipient address is required")
    message_id = await asyncio.to_thread(_send, address, subject, body, reply_to_id)
    return {"to": address, "subject": subject, "message_id": message_id}


def _read(limit: int) -> List[Dict[str, Any]]:
    s = imap_settings()
    out: List[Dict[str, Any]] = []
    with imaplib.IMAP4_SSL(s["host"], s["port"]) as client:
        client.login(s["user"], s["password"])
        client.select(s["folder"], readonly=True)
        _typ, data = client.search(None, "UNSEEN")
        ids = (data[0] or b"").split()[-limit:]
        for msg_id in ids:
            _typ, parts = client.fetch(msg_id, "(BODY.PEEK[])")
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if raw is None:
                continue
            msg = email.message_from_bytes(raw)
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain" and not part.get_filename():
                        body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")
            name, address = parseaddr(msg.get("From", ""))
            out.append({"message_id": msg.get("Message-ID", ""), "from_name": name, "from_email": address,
                        "subject": msg.get("Subject", "(no subject)"), "body": body[:20000],
                        "date": msg.get("Date", "")})
    return out


async def read_unseen(limit: int = 50) -> List[Dict[str, Any]]:
    if not imap_configured():
        raise RuntimeError("Email reading is not configured (set EMAIL_IMAP_HOST, EMAIL_IMAP_USER and "
                           "EMAIL_IMAP_PASSWORD)")
    return await asyncio.to_thread(_read, max(1, min(limit, 200)))
