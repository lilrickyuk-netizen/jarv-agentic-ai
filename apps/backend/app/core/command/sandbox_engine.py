"""
JAI Backend - A specialist's work package, done in JAI's engineering sandbox (OpenHands)

The mission's team hands a package to the sandbox service (services/openhands): OpenHands' agent loop, with its
context condenser and stuck detection, drives a full shell and file editor on the mission's workspace, thinking
with JAI's model through JAI's gateway. JAI keeps the authority: before the run starts the run's scope (workspace,
owned paths, authority, parent agent) is registered here, and the sandbox asks this backend before every action
(app/api/v1/agent_gate.py). While the run works it is followed every few seconds: its actions join the mission's
record (for the report and the independent check), its step and what it is doing go into the mission's progress,
and a run that goes past its time is stopped. Its final report says which requirements it delivered.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RUN_KEY = "sandbox:run:{}"
RUN_TTL_SECONDS = 8 * 3600
POLL_SECONDS = 5.0
RUN_TIMEOUT_SECONDS = 3 * 3600
_REQUIREMENT_LINE = re.compile(r"\b(R\d+|P\d+\.\d+)\s*[:\-–—]\s*(done|open|waiting)\b\s*[-–—:,]?\s*(.*)", re.I)


def _no_credit(result: Dict[str, Any]) -> bool:
    """A run that stopped because the model's account has no credit left."""
    if result.get("success"):
        return False
    text = f"{result.get('error') or ''} {result.get('answer') or ''}".lower()
    return any(word in text for word in ("credit balance", "insufficient_quota", "billing", "out of credit"))


def _unreachable(result: Dict[str, Any]) -> bool:
    """A run that stopped because the model's provider could not be reached for a moment (not a fault of the work)."""
    if result.get("success"):
        return False
    text = f"{result.get('error') or ''} {result.get('answer') or ''}".lower()
    return any(word in text for word in ("could not be reached", "upstream_unreachable", "badgateway",
                                         "bad gateway", "connecterror", "overloaded", "serviceunavailable",
                                         "service unavailable", "apiconnectionerror"))


def _budget_out(result: Dict[str, Any]) -> bool:
    """A run that stopped at its spending limit before it finished."""
    if result.get("success"):
        return False
    text = f"{result.get('error') or ''} {result.get('answer') or ''}".lower()
    return "budget limit" in text or "maximum budget" in text


UNREACHABLE_WAIT_SECONDS = 45.0


def sandbox_url() -> str:
    return str(getattr(settings, "OPENHANDS_URL", "") or "").rstrip("/")


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {settings.OPENHANDS_TOKEN or ''}"}


async def available(client: Optional[httpx.AsyncClient] = None) -> bool:
    """True when the sandbox is switched on, has its tokens and answers."""
    if not sandbox_url() or not settings.OPENHANDS_TOKEN:
        return False
    owned = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0))
    try:
        response = await client.get(f"{sandbox_url()}/health")
        return response.status_code == 200 and bool(response.json().get("ready"))
    except (httpx.HTTPError, ValueError):
        return False
    finally:
        if owned:
            await client.aclose()


async def save_run(run_id: str, data: Dict[str, Any]) -> None:
    from app.core.redis import get_redis

    await (await get_redis()).set(RUN_KEY.format(run_id), json.dumps(data, default=str), ex=RUN_TTL_SECONDS)


async def load_run(run_id: str) -> Optional[Dict[str, Any]]:
    from app.core.redis import get_redis

    raw = await (await get_redis()).get(RUN_KEY.format(run_id))
    return json.loads(raw) if raw else None


async def forget_run(run_id: str) -> None:
    from app.core.redis import get_redis

    await (await get_redis()).delete(RUN_KEY.format(run_id))


def requirement_statuses(report: str) -> Dict[str, Dict[str, str]]:
    """{"R3": {"status": "done", "evidence": "..."}} from the lines of a specialist's final report."""
    found: Dict[str, Dict[str, str]] = {}
    for line in (report or "").splitlines():
        match = _REQUIREMENT_LINE.search(line.strip(" -*`"))
        if match:
            found[match.group(1).upper()] = {"status": match.group(2).lower(),
                                             "evidence": " ".join(match.group(3).split())[:400]}
    return found


def to_host(container_path: str, container_root: str, host_root: str) -> str:
    """A path as the sandbox saw it, as Richard's folder names it (for the mission's record and report)."""
    try:
        rel = PurePosixPath(container_path).relative_to(PurePosixPath(container_root))
    except ValueError:
        return container_path
    if ":" in host_root[:3] or "\\" in host_root:
        return str(PureWindowsPath(host_root) / PureWindowsPath(*rel.parts)) if rel.parts else host_root
    return str(PurePosixPath(host_root) / rel) if rel.parts else host_root


def as_call(action: Dict[str, Any], container_root: str, host_root: str, specialist: str, package: str) -> Dict[str, Any]:
    """One sandbox action in the shape of JAI's own tool records."""
    tool = action.get("tool")
    if tool == "terminal":
        name = "run_command"
        inputs = {"command": str(action.get("command") or "")[:2000],
                  "cwd": to_host(str(action.get("cwd") or container_root), container_root, host_root)}
        code = action.get("exit_code")
        summary = (f"exit={code}, " if code is not None else "") + str(action.get("summary") or "")[-400:]
        output: Dict[str, Any] = {"exit_code": code}
    else:
        command = str(action.get("command") or "")
        name = "write_file" if command == "create" else "read_file" if command == "view" else "edit_file"
        inputs = {"path": to_host(str(action.get("path") or ""), container_root, host_root), "command": command}
        summary = str(action.get("summary") or "")[-400:]
        output = {}
    return {"tool": name, "inputs": inputs, "success": bool(action.get("ok")) and not action.get("refused"),
            "summary": summary, "output": output, "authorized": not action.get("refused"),
            "ts": datetime.now(timezone.utc).isoformat(), "agent": specialist, "package": package,
            "engine": "openhands"}


class SandboxSpecialist:
    """Runs one work package in the sandbox and follows it to the end."""

    def __init__(self, team, package, mission: str, known: Optional[str],
                 client: Optional[httpx.AsyncClient] = None, poll_seconds: float = POLL_SECONDS,
                 timeout_seconds: float = RUN_TIMEOUT_SECONDS):
        self.team, self.package, self.mission, self.known = team, package, mission, known
        self.client = client
        self.poll_seconds, self.timeout_seconds = poll_seconds, timeout_seconds
        self.run_id = f"{str(team.runtime.task_id or 'mission')[:8]}-{package.id}-{uuid4().hex[:8]}"

    def _brief(self, requirements: List[Dict[str, Any]]) -> str:
        from app.core.command.requirements import render

        brief = self.team._brief(self.package, self.mission)
        if self.known:
            brief += ("\n\nWHAT JAI ALREADY KNOWS ABOUT THIS WORKSPACE (check it against the files):\n"
                      + self.known[:6000])
        if requirements:
            brief += "\n\nYOUR REQUIREMENTS:\n" + render(requirements)
        return brief + (
            "\n\nHOW TO WORK: you have a full shell (chaining, pipes and redirection work) and a file editor, in "
            "the mission's workspace. Use the project's own commands to install, build, lint, type-check and test, "
            "and fix what fails before you finish. A tool or version the project pins that is missing (Syft, a CLI, "
            "a language) you install yourself at that exact version (`mise install <tool>@<version>`); that is never "
            "a blocker and never an action for Richard. Fresh-clone checks go in a new folder under /tmp, never "
            "inside the repository. Run a check once rather than starting a server or a watcher that never ends. "
            "JAI checks every action: pushing, publishing, deploying and anything outside this workspace are "
            "refused; when one is needed, leave it and name it in your report."
            "\n\nYOUR FINAL MESSAGE (call finish with it): what you changed (files), the commands you ran and "
            "their results, and one line per requirement, exactly like `R3: done — <the file or command that "
            "proves it>` or `R3: open — <what is still missing>`.")

    def _standard(self) -> str:
        from app.core.command.mission_org import SPECIALISTS

        spec = SPECIALISTS.get(self.package.specialist) or SPECIALISTS["coding_agent"]
        return (f"You are JAI's {spec['title']}, one specialist in a team. Your standard of work: "
                f"{spec['standard']} Never claim something was done or passed unless a command or file in this "
                "conversation shows it.")

    async def _register(self, container_root: str) -> None:
        owns = [str(PurePosixPath(container_root) / p.strip("/")) for p in self.package.owns]
        await save_run(self.run_id, {
            "task_id": str(self.team.runtime.task_id) if self.team.runtime.task_id else None,
            "workspace_id": str(self.team.runtime.workspace_id) if self.team.runtime.workspace_id else None,
            "user_id": str(self.team.runtime.user_id) if self.team.runtime.user_id else None,
            "root": container_root, "root_host": self.team.workspace_root, "owns": owns,
            "authority": int(self.team.runtime.authority_level or 3), "specialist": self.package.specialist,
            "package": self.package.id, "read_only": self.package.id == "VER",
            "sub_agent_id": str(self.package.sub_agent_id) if self.package.sub_agent_id else None,
            "parent_agent_id": str(self.team.lead_agent_id) if self.team.lead_agent_id else None})

    async def model(self) -> str:
        """Opus 5.5 for the specialists while Anthropic can serve it; GPT-6 Sol when JAI has no Anthropic key or
        the account has run out of credit."""
        from app.core.providers.router import has_no_credit

        chosen = str(settings.OPENHANDS_MODEL or settings.OPENAI_MODEL)
        if chosen.startswith("claude"):
            if not (settings.CLAUDE_API_KEY or settings.ANTHROPIC_API_KEY) or await has_no_credit("claude"):
                return str(settings.OPENHANDS_FALLBACK_MODEL or settings.OPENAI_MODEL)
        return chosen

    async def run(self, requirements: List[Dict[str, Any]]) -> Dict[str, Any]:
        from app.core.providers.router import mark_no_credit
        from app.core.workspaces import fs_inspector

        container = fs_inspector.host_to_container(self.team.workspace_root or "")
        if container is None:
            return {"success": False, "answer": "The workspace folder is outside JAI's approved root."}
        container_root = str(container)
        model = await self.model()
        result = await self._attempt(requirements, container_root, model)
        if _unreachable(result):
            # The provider dropped out for a moment: wait, then carry on from the files on disk; if it is still
            # unreachable, the other provider finishes the package.
            await asyncio.sleep(UNREACHABLE_WAIT_SECONDS)
            result = self._merge(result, await self._again(requirements, container_root, model))
            if _unreachable(result) and model.startswith("claude"):
                fallback = str(settings.OPENHANDS_FALLBACK_MODEL or settings.OPENAI_MODEL)
                result = self._merge(result, await self._again(requirements, container_root, fallback))
                result["answer"] = (f"(Anthropic could not be reached, so this package finished on {fallback}.)\n"
                                    + str(result.get("answer") or ""))
        if _budget_out(result):
            # Its spending limit ran out mid-task: one more run picks up from the files already written, so a
            # large package is finished instead of abandoned (the daily limit still caps all spending).
            result = self._merge(result, await self._again(requirements, container_root, model))
        if model.startswith("claude") and _no_credit(result):
            # Anthropic ran out of credit mid-package: the rest of JAI is told, and the package carries on with
            # GPT-6 Sol from the files already on disk.
            await mark_no_credit("claude")
            self.run_id = f"{self.run_id.rsplit('-', 1)[0]}-{uuid4().hex[:8]}"
            fallback = str(settings.OPENHANDS_FALLBACK_MODEL or settings.OPENAI_MODEL)
            again = await self._attempt(requirements, container_root, fallback)
            again["answer"] = (f"(Anthropic had no credit, so this package finished on {fallback}.)\n"
                               + str(again.get("answer") or ""))
            for key in ("steps", "tokens", "cost_usd"):
                again[key] = (again.get(key) or 0) + (result.get(key) or 0)
            return again
        return result

    async def _again(self, requirements: List[Dict[str, Any]], container_root: str, model: str) -> Dict[str, Any]:
        """Another run of the same package under a new run id, continuing from what is on disk."""
        self.run_id = f"{self.run_id.rsplit('-', 1)[0]}-{uuid4().hex[:8]}"
        return await self._attempt(requirements, container_root, model)

    @staticmethod
    def _merge(earlier: Dict[str, Any], later: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("steps", "tokens", "cost_usd"):
            later[key] = (later.get(key) or 0) + (earlier.get(key) or 0)
        return later

    async def _attempt(self, requirements: List[Dict[str, Any]], container_root: str, model: str) -> Dict[str, Any]:
        from app.core.command.metrics import PRICES

        await self._register(container_root)
        from app.core.knowledge.skill_packs import sandbox_skills

        price = PRICES.get(model)
        body = {"run_id": self.run_id, "workspace": container_root, "brief": self._brief(requirements),
                "standard": self._standard(), "model": model,
                "provider": "anthropic" if model.startswith("claude") else "openai",
                "reasoning_effort": settings.OPENHANDS_REASONING_EFFORT,
                "max_iterations": int(settings.OPENHANDS_MAX_ITERATIONS),
                "max_cost_usd": float(settings.OPENHANDS_MAX_COST_PER_PACKAGE_USD),
                "input_cost_per_token": price[0] / 1e6 if price else None,
                "output_cost_per_token": price[1] / 1e6 if price else None,
                "cache_read_cost_per_token": price[2] / 1e6 if price else None,
                "cache_write_cost_per_token": price[3] / 1e6 if price else None,
                "skills": sandbox_skills(self.package.specialist)}
        owned = self.client is None
        client = self.client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
        try:
            started = await client.post(f"{sandbox_url()}/runs", json=body, headers=_headers())
            if started.status_code != 200:
                return {"success": False, "answer": f"The sandbox did not start the package: "
                                                    f"{started.status_code} {started.text[:300]}"}
            view = await self._follow(client, container_root)
        except httpx.HTTPError as exc:
            return {"success": False, "answer": f"The sandbox stopped answering ({type(exc).__name__})."}
        finally:
            if owned:
                await client.aclose()
            await forget_run(self.run_id)
        report = str(view.get("final_message") or view.get("error") or "")
        statuses = requirement_statuses(report)
        theirs = []
        for r in requirements:
            said = statuses.get(str(r["id"]).upper())
            theirs.append({**r, **said} if said else dict(r))
        tokens = view.get("tokens") or {}
        return {"success": view.get("status") == "finished", "answer": report, "requirements": theirs,
                "status": view.get("status"), "steps": int(view.get("steps") or 0), "model": model,
                "error": str(view.get("error") or ""),
                "tokens": int(tokens.get("input") or 0) + int(tokens.get("output") or 0),
                "token_detail": tokens, "cost_usd": float(view.get("cost_usd") or 0)}

    async def _follow(self, client: httpx.AsyncClient, container_root: str) -> Dict[str, Any]:
        seen = 0
        deadline = time.monotonic() + self.timeout_seconds
        view: Dict[str, Any] = {}
        failures = 0
        while True:
            await asyncio.sleep(self.poll_seconds)
            try:
                response = await client.get(f"{sandbox_url()}/runs/{self.run_id}", params={"since": seen},
                                            headers=_headers())
                if response.status_code == 404:
                    # The sandbox was restarted (switched off and on, or rebuilt) and the run went with it.
                    return {**view, "status": "lost",
                            "error": "The sandbox was restarted while this package was working, so the run was lost; "
                                     "its files are on disk and the next round carries on from them."}
                response.raise_for_status()
                view = response.json()
                failures = 0
            except (httpx.HTTPError, ValueError) as exc:
                failures += 1
                if failures >= 6:
                    return {**view, "status": "error", "error": f"The sandbox stopped answering ({exc})."}
                continue
            actions = view.get("actions") or []
            seen += len(actions)
            calls = [as_call(a, container_root, self.team.workspace_root or "", self.package.specialist,
                             self.package.id) for a in actions]
            if calls:
                await self.team.adopt(calls)
                self.package.calls += len(calls)
                for call in calls:
                    if call["tool"] not in self.package.tools:
                        self.package.tools.append(call["tool"])
            self.package.step = int(view.get("steps") or 0)
            self.package.steps = int(view.get("max_iterations") or 0)
            if view.get("doing_now"):
                self.package.doing = str(view["doing_now"])[:300]
            await self.team.save_progress()
            if view.get("status") not in ("starting", "running"):
                return view
            if time.monotonic() > deadline:
                await client.post(f"{sandbox_url()}/runs/{self.run_id}/stop", headers=_headers())
                view["error"] = f"Stopped after {int(self.timeout_seconds // 60)} minutes."
