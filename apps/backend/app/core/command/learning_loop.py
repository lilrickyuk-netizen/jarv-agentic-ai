"""
JAI Backend - The learning loop: playbooks JAI writes from its own finished missions (after Hermes Agent)

Richard, 15 November: add the Hermes upgrades so JAI gets better at a kind of job each time it does one. Hermes
Agent (Nous Research, MIT) keeps a skill for a procedure worth repeating: after a task, a background review replays
the conversation in a forked agent and asks whether a skill should be saved or updated; it prefers patching an
existing skill to creating a new one and never deletes one; a skill is a SKILL.md with a name, a description and four
sections (When to Use, Procedure, Pitfalls, Verification); every change is written to an append-only ledger with its
SHA-256 so a single change can be rolled back; agent-written content is scanned for prompt injection, credentials
and invisible characters before it is kept.

JAI does the same on the Claude engine:

- WHEN: a specialist's mission on the engine passed JAI's independent check.
- HOW: the review is a fork of that mission's own Claude Code session (resume with fork_session), so it sees every
  search, page and tool result the specialist saw, and it may only read and write JAI's learned playbooks (the
  PreToolUse hook refuses anything else). It is small: a few turns and a few pence (REVIEW_TURNS, REVIEW_USD).
- WHERE: LEARNED_SKILLS_DIR/skills/<name>/SKILL.md, loaded into every later session as the plugin "jai-learned",
  so the next booking database starts from how the last one was done.
- SAFETY: a playbook that carries an injection, a secret or hidden characters is refused and the earlier version
  kept; each accepted change is in ledger.jsonl with its hash, and rollback() restores the version before it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

PLUGIN = "jai-learned"
REVIEW_TURNS = 14
REVIEW_USD = 0.25
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
SECTIONS = ("When to Use", "Procedure", "Pitfalls", "Verification")
# Hermes' memory and skill scans are pattern checks: instructions to override the agent, a credential, a key, or
# characters a reader cannot see. A playbook carrying one is never kept.
_INJECTION = re.compile(r"ignore (?:all |any )?(?:previous|prior|above) (?:instructions|rules)|disregard (?:your|the) "
                        r"(?:rules|instructions|system prompt)|you are no longer|new system prompt|jailbreak|"
                        r"(?:disable|bypass|turn off) (?:the )?(?:gate|hook|safety|verifier|audit)", re.I)
_SECRET = re.compile(r"(?:sk-ant-|sk-proj-|sk-|AKIA|ghp_|xox[bp]-)[A-Za-z0-9_\-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY|"
                     r"(?:password|passwd|api[_ ]?key|secret)\s*[:=]\s*\S{6,}", re.I)
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤﻿]")


def learned_root() -> Path:
    return Path(str(getattr(settings, "LEARNED_SKILLS_DIR", "") or "/app/.jai-learned"))


def plugin_dir() -> Path:
    """The learned playbooks as a Claude Code plugin folder (made on first use)."""
    root = learned_root()
    (root / "skills").mkdir(parents=True, exist_ok=True)
    manifest = root / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"name": PLUGIN, "version": "1",
                                        "description": "Playbooks JAI wrote from its own finished missions"}))
    return root


def playbooks() -> List[str]:
    root = learned_root() / "skills"
    return sorted(p.parent.name for p in root.glob("*/SKILL.md")) if root.is_dir() else []


def unsafe(text: str) -> List[str]:
    """What makes agent-written text unsafe to keep (any file of a playbook)."""
    found: List[str] = []
    if _INJECTION.search(text or ""):
        found.append("it carries an instruction to override JAI's rules")
    if _SECRET.search(text or ""):
        found.append("it carries what looks like a password, key or token")
    if _INVISIBLE.search(text or ""):
        found.append("it carries characters a reader cannot see")
    return found


def problems(text: str) -> List[str]:
    """Why a SKILL.md may not be kept: unsafe content, or not the shape a playbook has. Empty: it may be kept."""
    found = unsafe(text)
    head = re.match(r"^---\s*\n(.*?)\n---\s*\n", text or "", re.S)
    if not head:
        found.append("it has no frontmatter (name and description)")
    else:
        name = re.search(r"^name:\s*(\S+)\s*$", head.group(1), re.M)
        description = re.search(r"^description:\s*(.+)$", head.group(1), re.M)
        if not name or not NAME.match(name.group(1).strip()):
            found.append("its name is missing or not lower-case words joined by hyphens (64 characters at most)")
        if not description or len(description.group(1).strip()) > 1024:
            found.append("its description is missing or longer than 1,024 characters")
    for section in SECTIONS:
        if not re.search(rf"^#+\s*{re.escape(section)}\s*$", text or "", re.M | re.I):
            found.append(f"it has no '{section}' section")
    return found


def _ledger(entry: Dict[str, Any]) -> None:
    root = learned_root()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "ledger.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(entry, ensure_ascii=False) + "\n")


def accept(path: Path, before: Optional[str], mission: str = "") -> Optional[str]:
    """After the review wrote a playbook file: keep it (ledger entry with both hashes, the earlier version kept for
    rollback) or refuse it and put the earlier version back. Returns why it was refused, or None."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"the playbook could not be read: {exc}"
    wrong = problems(text) if path.name == "SKILL.md" else unsafe(text)
    now = datetime.now(timezone.utc).isoformat()
    rel = str(path.relative_to(learned_root()))
    if wrong:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(before, encoding="utf-8")
        _ledger({"at": now, "file": rel, "mission": mission, "refused": wrong})
        return "; ".join(wrong)
    if before is not None:
        keep = learned_root() / ".history" / rel
        keep.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        (keep.parent / f"{keep.name}.{stamp}").write_text(before, encoding="utf-8")
    _ledger({"at": now, "file": rel, "mission": mission, "change": "patch" if before is not None else "create",
             "sha256": hashlib.sha256(text.encode()).hexdigest(),
             "previous_sha256": hashlib.sha256(before.encode()).hexdigest() if before is not None else None})
    return None


def rollback(rel: str) -> bool:
    """Put a playbook file back to the version before its last change (Hermes: curator rollback). The rollback is
    itself written to the ledger. False when there is nothing to roll back to."""
    root = learned_root()
    history = sorted((root / ".history" / rel).parent.glob(f"{Path(rel).name}.*")) if (root / ".history").is_dir() \
        else []
    target = root / rel
    if not history:
        if target.exists():
            created = [json.loads(line) for line in (root / "ledger.jsonl").read_text().splitlines()
                       if line.strip()] if (root / "ledger.jsonl").is_file() else []
            if any(e.get("file") == rel and e.get("change") == "create" for e in created):
                target.unlink()
                _ledger({"at": datetime.now(timezone.utc).isoformat(), "file": rel, "change": "rollback (removed)"})
                if target.parent != root / "skills" and not any(target.parent.iterdir()):
                    shutil.rmtree(target.parent, ignore_errors=True)
                return True
        return False
    last = history[-1]
    target.write_text(last.read_text(encoding="utf-8"), encoding="utf-8")
    last.unlink()
    _ledger({"at": datetime.now(timezone.utc).isoformat(), "file": rel, "change": "rollback",
             "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    return True


def review_prompt(title: str, mission: str) -> str:
    """Hermes' background review, for a JAI specialist's finished mission."""
    have = playbooks()
    return (
        f"This mission is finished and JAI's independent check accepted it. Before you go: you are now reviewing it "
        f"as JAI's {title}, to decide whether how it was done should be kept as a playbook for the next job like it. "
        f"The mission was:\n{mission[:1500]}\n\n"
        f"JAI's playbooks are in {learned_root() / 'skills'} (one folder per playbook, each with a SKILL.md). "
        + (f"The ones there now: {', '.join(have)}. " if have else "There are none yet. ")
        + "Keep a playbook only when this mission found a method worth repeating: a sequence of tools that worked, a "
        "dead end it found its way out of, a source that delivered, a step that saved time or money. If an existing "
        "playbook covers this kind of job, improve it (Edit) rather than writing another; write a new one only when "
        "none covers it; never delete one. If nothing here is worth keeping, say so and stop.\n\n"
        "A playbook is a SKILL.md beginning with frontmatter:\n---\nname: <lower-case words joined by hyphens>\n"
        "description: <one or two sentences: the kind of job it is for, so it is picked for the right missions>\n---\n"
        "then four sections, each a heading: When to Use, Procedure (numbered steps naming the exact tools and the "
        "order that worked), Pitfalls (what went wrong or wasted time, and what to do instead), Verification (how "
        "to check the work before finishing). Write only what this mission's record shows; no figures, contacts or "
        "facts about particular businesses, which belong in the work, not the method. Keep it under 6,000 "
        "characters.")


async def review(executor: Any, mission: str) -> Dict[str, Any]:
    """The background review of a finished engine mission (see the module's notes). Never raises: a mission's
    result never depends on its review."""
    out: Dict[str, Any] = {"reviewed": False, "written": [], "refused": []}
    if not getattr(executor, "session_id", None) or not bool(getattr(settings, "LEARNING_LOOP_ENABLED", True)):
        return out
    try:
        import claude_agent_sdk as sdk
    except Exception:  # noqa: BLE001
        return out
    from app.core.command import claude_engine

    skills = plugin_dir() / "skills"
    before: Dict[Path, Optional[str]] = {}
    task = str(getattr(executor.runtime, "task_id", "") or "")

    def inside(raw: str) -> Optional[Path]:
        path = Path(str(raw or ""))
        path = path if path.is_absolute() else skills / path
        try:
            path.resolve().relative_to(skills.resolve())
            return path
        except ValueError:
            return None

    async def pre(hook_input, tool_use_id, context):
        tool = str((hook_input or {}).get("tool_name") or "")
        args = (hook_input or {}).get("tool_input") or {}
        if tool in ("Read", "Glob", "Grep", "Skill", "ToolSearch"):
            return {}
        if tool in ("Write", "Edit"):
            path = inside(args.get("file_path"))
            if path is None:
                return claude_engine._deny(f"In this review you may only write JAI's playbooks, in {skills}.")
            if path not in before:
                before[path] = path.read_text(encoding="utf-8") if path.is_file() else None
            return {}
        return claude_engine._deny(f"{tool} is not part of a playbook review.")

    async def post(hook_input, tool_use_id, context):
        tool = str((hook_input or {}).get("tool_name") or "")
        if tool in ("Write", "Edit"):
            path = inside(((hook_input or {}).get("tool_input") or {}).get("file_path"))
            if path is not None:
                refused = accept(path, before.get(path), task)
                (out["refused"] if refused else out["written"]).append(
                    f"{path.relative_to(skills)}" + (f": {refused}" if refused else ""))
                before.pop(path, None)
                if refused:
                    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": (
                        f"That playbook was not kept: {refused}. Fix it and write it again, or stop.")}}
        return {}

    config = claude_engine.sessions_root() / task
    options = sdk.ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code", "append": executor._appended()},
        model=claude_engine.engine_model(),
        cwd=str(skills), add_dirs=[str(skills)],
        setting_sources=["user"], plugins=[{"type": "local", "path": str(plugin_dir())}],
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "ToolSearch"],
        disallowed_tools=list(claude_engine.REMOVED) + ["WebSearch", "WebFetch", "Agent", "Task"],
        permission_mode="dontAsk",
        hooks={"PreToolUse": [sdk.HookMatcher(matcher=None, hooks=[pre])],
               "PostToolUse": [sdk.HookMatcher(matcher=None, hooks=[post])]},
        resume=executor.session_id, fork_session=True,
        max_turns=REVIEW_TURNS, max_budget_usd=REVIEW_USD,
        env={"ANTHROPIC_API_KEY": claude_engine.api_key(), "CLAUDE_AGENT_SDK_CLIENT_APP": "jai-backend",
             "CLAUDE_CONFIG_DIR": str(config), "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
             "DISABLE_TELEMETRY": "1"},
    )
    try:
        async with sdk.ClaudeSDKClient(options=options) as client:
            await client.query(review_prompt(getattr(executor, "title", "specialist"), mission))
            async for message in client.receive_response():
                if type(message).__name__ == "ResultMessage":
                    executor._book(message)
        out["reviewed"] = True
    except Exception as exc:  # noqa: BLE001 - the mission stands whatever its review does
        logger.warning(f"mission {task}: playbook review stopped ({type(exc).__name__}: {exc})")
        out["error"] = f"{type(exc).__name__}: {exc}"[:300]
    if out["written"] or out["refused"]:
        logger.info(f"mission {task}: playbooks written {out['written']}, refused {out['refused']}")
    return out
