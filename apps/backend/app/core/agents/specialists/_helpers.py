"""
Shared honest-behaviour helpers for specialist agents (Repair 5).

These utilities let specialist agents do REAL work or return HONEST
limitations instead of fabricated/templated output. They do not bypass
AgentBase, do not invent metrics, and never claim an external action happened.

Three honest modes a specialist can use:
- Local analysis  : inspect real provided files / context (resolve_files,
                    read_file_safe, scan_secrets, count_lines).
- Model-backed    : call the real model router when a provider key is
                    configured (provider_configured + llm_complete), clearly
                    labelling output as model-generated and unverified.
- Blocked/limited : when the action needs a subsystem/tool/credential that is
                    not wired into standalone agent execution, return a
                    structured limitation (limitation) instead of fake success.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple


# --- provider / model router -------------------------------------------------

def provider_configured() -> bool:
    """True only if a real LLM API key is configured (honest gate, no network)."""
    try:
        from app.core.config import settings
    except Exception:  # noqa: BLE001
        return False
    for attr in ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        if getattr(settings, attr, None):
            return True
    return False


async def llm_complete(
    model: str,
    prompt: str,
    *,
    system: Optional[str] = None,
    temperature: float = 0.5,
    max_tokens: int = 1200,
) -> Optional[Dict[str, Any]]:
    """Call the real model router. Returns {text, provider_used, tokens} or None.

    Returns None (never fabricates) if providers are unavailable or the call
    fails, so callers can fall back to an honest limitation.
    """
    try:
        from app.core.providers import get_router, CompletionRequest, Message
    except Exception:  # noqa: BLE001
        return None
    try:
        router = get_router()
        req = CompletionRequest(
            model=model,
            messages=[Message(role="user", content=prompt)],
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
        )
        resp = await router.complete(req)
    except Exception:  # noqa: BLE001 - provider unavailable/errored
        return None
    provider = (
        f"{resp.provider}:{resp.model}" if getattr(resp, "provider", None)
        else getattr(resp, "model", model)
    )
    return {
        "text": (resp.content or "").strip(),
        "provider_used": provider,
        "tokens": dict(resp.usage) if getattr(resp, "usage", None) else {},
    }


def no_provider_limitation() -> str:
    return (
        "No LLM provider API key is configured; returned a structured limitation "
        "instead of model-generated content (set CLAUDE_API_KEY/OPENAI_API_KEY/"
        "GEMINI_API_KEY to enable real generation)."
    )


# --- input / task text -------------------------------------------------------

def task_text(input_data: Dict[str, Any], *preferred: str) -> str:
    """Pull the instruction text from preferred keys, else the first string field."""
    for k in preferred:
        v = input_data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for v in input_data.values():
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# --- file / repo local analysis ----------------------------------------------

def resolve_files(paths: List[str], context: Any) -> Tuple[List[str], List[str]]:
    """Resolve candidate paths to existing files; return (existing, missing).

    Tries absolute, workspace-relative (context.metadata.workspace_path), then
    cwd-relative. Never invents files.
    """
    existing: List[str] = []
    missing: List[str] = []
    meta = getattr(context, "metadata", None) or {}
    base = meta.get("workspace_path") or meta.get("folder_path")
    for p in paths or []:
        if not p:
            continue
        cands: List[str] = []
        if os.path.isabs(p):
            cands.append(p)
        else:
            if base:
                cands.append(os.path.join(base, p))
            cands.append(os.path.abspath(p))
        found = next((c for c in cands if os.path.exists(c)), None)
        if found:
            existing.append(found)
        else:
            missing.append(p)
    return existing, missing


def read_file_safe(path: str, max_bytes: int = 200_000) -> Optional[str]:
    """Read a text file safely; None if unreadable. No fabrication."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except Exception:  # noqa: BLE001
        return None


def count_lines(text: str) -> Dict[str, int]:
    """Real line counts for a source text (no estimates)."""
    blank = code = comment = 0
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            blank += 1
        elif s.startswith(("#", "//", "/*", "*", "--")):
            comment += 1
        else:
            code += 1
    return {"total": blank + code + comment, "code": code, "comment": comment, "blank": blank}


# Common secret/credential patterns (real regex scan; not exhaustive — reported
# as a limitation by callers).
_SECRET_PATTERNS = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("generic_api_key", re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]")),
    ("aws_secret", re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}")),
    ("password_assign", re.compile(r"(?i)password\s*[:=]\s*['\"][^'\"]{6,}['\"]")),
]

# Dangerous code patterns (real substring/regex; honest static signal only).
_DANGEROUS_PATTERNS = [
    ("eval", re.compile(r"\beval\s*\(")),
    ("exec", re.compile(r"\bexec\s*\(")),
    ("os_system", re.compile(r"os\.system\s*\(")),
    ("subprocess_shell_true", re.compile(r"shell\s*=\s*True")),
    ("pickle_loads", re.compile(r"pickle\.loads?\s*\(")),
    ("yaml_load_unsafe", re.compile(r"yaml\.load\s*\((?!.*Loader)")),
]


def scan_secrets(text: str) -> List[Dict[str, str]]:
    """Return REAL regex matches for secret-like patterns in text."""
    findings: List[Dict[str, str]] = []
    for name, pat in _SECRET_PATTERNS:
        if pat.search(text):
            findings.append({"type": "secret", "pattern": name})
    return findings


def scan_dangerous(text: str) -> List[Dict[str, str]]:
    """Return REAL regex matches for dangerous code patterns in text."""
    findings: List[Dict[str, str]] = []
    for name, pat in _DANGEROUS_PATTERNS:
        if pat.search(text):
            findings.append({"type": "dangerous_call", "pattern": name})
    return findings


def context_summary(context: Any) -> Dict[str, int]:
    """What the agent actually had available locally (no fabrication)."""
    return {
        "memory_context_items": len(getattr(context, "memory_context", None) or []),
        "previous_results": len(getattr(context, "previous_results", None) or []),
        "workspace_rules": len(getattr(context, "workspace_rules", None) or []),
    }


# Fake-value tokens that must NEVER appear in repaired agent output. Used by the
# Repair-5 test-suite to assert no fabrication remains.
FORBIDDEN_FAKE_TOKENS = [
    "88.5", "Simulate", "simulate", "simulated",
    "Source 1", "Source 2", "Finding about",
    "Memory 1", "mem_123",
    "Related topic 1", "Related topic 2",
]
