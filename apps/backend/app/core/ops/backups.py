"""
JARV Backend - Database backups

Real backups of JARV's PostgreSQL database with pg_dump (custom format),
recorded as BackupRecord rows with a SHA-256 checksum.

- create: refuses if the pg_dump client is older than the server (an old
  client cannot produce a correct dump), writes to BACKUP_DIR, checksums it.
- verify: re-checksums the file and lists the archive with pg_restore.
- restore: always into a NEW database named jarv_restore_<timestamp>. The
  live database is never overwritten here; switching JARV to a restored
  database is a deliberate operator step. The restore tool is approval-gated.
- cleanup: removes backups past their retention (approval-gated).

Credentials are passed to the client programs through the environment
(PGPASSWORD), never on the command line.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import redact_text
from app.models.operations import BackupRecord

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = "/data/backups"
_TIMEOUT_SECONDS = 1800


class BackupError(RuntimeError):
    pass


def backup_dir() -> Path:
    path = Path(os.getenv("BACKUP_DIR") or getattr(settings, "BACKUP_DIR", "") or DEFAULT_BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _connection() -> Tuple[List[str], Dict[str, str], str]:
    """(connection args, environment, database name) for the PostgreSQL clients."""
    if not settings.DATABASE_URL:
        raise BackupError("DATABASE_URL is not configured.")
    url = make_url(str(settings.DATABASE_URL))
    if not url.drivername.startswith("postgresql"):
        raise BackupError("Backups need a PostgreSQL database.")
    args = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres"]
    env = {**os.environ, "PGCONNECT_TIMEOUT": "10"}
    if url.password:
        env["PGPASSWORD"] = url.password
    return args, env, url.database or "postgres"


async def _run(program: List[str], env: Dict[str, str], timeout: int = _TIMEOUT_SECONDS) -> Tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *program, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError as exc:
        raise BackupError(f"{program[0]} is not installed in this container.") from exc
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise BackupError(f"{program[0]} timed out after {timeout}s")
    return proc.returncode, stdout.decode(errors="replace"), redact_text(stderr.decode(errors="replace"))


def _major(version_text: str) -> Optional[int]:
    match = re.search(r"(\d+)(?:\.\d+)?", version_text or "")
    return int(match.group(1)) if match else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def check_versions(db: Optional[AsyncSession] = None) -> Dict[str, Any]:
    """pg_dump's major version against the server pg_dump will actually connect to."""
    args, env, database = _connection()
    code, out, err = await _run(["pg_dump", "--version"], env, timeout=20)
    if code != 0:
        raise BackupError(f"pg_dump --version failed: {err.strip()[:200]}")
    code, server_out, err = await _run(
        ["psql", *args, "-d", database, "-tAc", "SHOW server_version_num"], env, timeout=30)
    if code != 0 or not server_out.strip().isdigit():
        raise BackupError(f"Cannot reach the database server: {err.strip()[:300]}")
    client = _major(out)
    server = int(server_out.strip()) // 10000
    return {"client": client, "server": server, "compatible": client is not None and client >= server}


async def create_backup(db: AsyncSession, *, workspace_id: Optional[UUID], reason: str,
                        retention_days: int = 30) -> BackupRecord:
    versions = await check_versions(db)
    if not versions["compatible"]:
        raise BackupError(f"pg_dump {versions['client']} cannot back up PostgreSQL {versions['server']}; "
                          f"install postgresql-client-{versions['server']} in the backend image.")
    args, env, database = _connection()
    started = datetime.now(timezone.utc)
    name = f"jarv-{database}-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:6]}.dump"
    target = backup_dir() / name
    record = BackupRecord(
        id=uuid4(), workspace_id=workspace_id, backup_name=name, backup_type="database",
        description=reason[:1000], source_type="postgresql", source_name=database,
        storage_location=str(target), storage_provider="local_volume", status="running",
        success=False, started_at=started, retention_days=retention_days,
        expires_at=started + timedelta(days=retention_days), is_deleted=False, is_verified=False,
        meta_data={"pg_dump_major": versions["client"], "server_major": versions["server"]},
        created_at=started, updated_at=started,
    )
    db.add(record)
    await db.flush()
    code, _, err = await _run(["pg_dump", *args, "-d", database, "-Fc", "--no-owner", "-f", str(target)], env)
    finished = datetime.now(timezone.utc)
    record.completed_at = finished
    record.duration_seconds = int((finished - started).total_seconds())
    record.updated_at = finished
    if code != 0 or not target.exists():
        record.status, record.error_message = "failed", err.strip()[:2000] or f"pg_dump exited {code}"
        await db.flush()
        raise BackupError(record.error_message)
    record.backup_size_bytes = target.stat().st_size
    record.status, record.success = "completed", True
    record.meta_data = {**(record.meta_data or {}), "sha256": _sha256(target)}
    await db.flush()
    return record


async def verify_backup(db: AsyncSession, record: BackupRecord) -> Dict[str, Any]:
    path = Path(record.storage_location)
    checks: Dict[str, Any] = {"file_exists": path.exists()}
    if path.exists():
        checks["checksum_matches"] = _sha256(path) == (record.meta_data or {}).get("sha256")
        _, env, _ = _connection()
        code, out, err = await _run(["pg_restore", "--list", str(path)], env, timeout=300)
        checks["archive_readable"] = code == 0
        checks["archive_entries"] = sum(1 for line in out.splitlines() if line and not line.startswith(";"))
        if code != 0:
            checks["error"] = err.strip()[:500]
    ok = bool(checks.get("file_exists") and checks.get("checksum_matches") and checks.get("archive_readable"))
    record.is_verified = ok
    record.verified_at = datetime.now(timezone.utc) if ok else None
    record.meta_data = {**(record.meta_data or {}), "last_verification": checks}
    record.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return {"verified": ok, **checks}


_ERROR_LINE = re.compile(r"^pg_restore: error: could not execute query: ERROR:\s*(.+)$", re.M)
_UNKNOWN_SETTING = re.compile(r'unrecognized configuration parameter "([a-z_]+)"')
_IGNORED_COUNT = re.compile(r"errors ignored on restore: (\d+)")


def _ignorable_restore_errors(stderr: str) -> List[str]:
    """Session settings a newer pg_dump writes that an older server does not know
    (e.g. pg_dump 17's ``SET transaction_timeout`` on PostgreSQL 16). They change
    nothing in the restored data. Returns the setting names when they are the ONLY
    errors; any other error returns [] and the restore is treated as failed."""
    errors = _ERROR_LINE.findall(stderr or "")
    count = _IGNORED_COUNT.search(stderr or "")
    settings_hit = [m.group(1) for e in errors if (m := _UNKNOWN_SETTING.search(e))]
    if not errors or len(settings_hit) != len(errors):
        return []
    if count is None or int(count.group(1)) != len(errors):
        return []
    return settings_hit


async def restore_to_new_database(db: AsyncSession, record: BackupRecord) -> Dict[str, Any]:
    """Restore into a brand-new database; the live database is untouched."""
    verification = await verify_backup(db, record)
    if not verification["verified"]:
        raise BackupError(f"Backup failed verification; not restoring: {verification}")
    args, env, _ = _connection()
    target_db = f"jarv_restore_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    code, _, err = await _run(["createdb", *args, target_db], env, timeout=120)
    if code != 0:
        raise BackupError(f"createdb failed: {err.strip()[:500]}")
    code, _, err = await _run(["pg_restore", *args, "-d", target_db, "--no-owner", record.storage_location], env)
    ignored = _ignorable_restore_errors(err) if code != 0 else []
    if code != 0 and not ignored:
        raise BackupError(f"pg_restore into {target_db} reported errors: {err.strip()[:1000]}")
    record.meta_data = {**(record.meta_data or {}), "last_restore": {
        "database": target_db, "at": datetime.now(timezone.utc).isoformat(), "ignored_settings": ignored}}
    await db.flush()
    return {"restored": True, "database": target_db, "ignored_settings": ignored,
            "note": "Live database unchanged. Point DATABASE_URL at this database to switch."}


async def list_backups(db: AsyncSession, workspace_id: Optional[UUID] = None, limit: int = 50) -> List[BackupRecord]:
    query = select(BackupRecord).where(BackupRecord.is_deleted.is_(False))
    if workspace_id is not None:
        query = query.where((BackupRecord.workspace_id == workspace_id) | BackupRecord.workspace_id.is_(None))
    return list((await db.execute(query.order_by(BackupRecord.started_at.desc()).limit(limit))).scalars().all())


async def cleanup_expired(db: AsyncSession, keep_latest: int = 3) -> Dict[str, Any]:
    """Delete expired backup files, always keeping the newest ``keep_latest`` verified ones."""
    now = datetime.now(timezone.utc)
    records = await list_backups(db, limit=1000)
    protected = {r.id for r in [r for r in records if r.success and r.is_verified][:keep_latest]}
    removed: List[str] = []
    for record in records:
        expires = record.expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if record.id in protected or expires is None or expires > now:
            continue
        try:
            Path(record.storage_location).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"could not delete {record.storage_location}: {exc}")
            continue
        record.is_deleted, record.status, record.updated_at = True, "deleted", now
        removed.append(record.backup_name)
    await db.flush()
    return {"removed": removed, "kept_protected": len(protected)}
