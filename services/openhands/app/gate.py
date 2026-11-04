"""
JAI's engineering sandbox - every action goes through JAI's authority checker

The OpenHands agent works with a full shell and file editor inside this container. Before any command runs or any
file is read or written, the action is sent to JAI's backend (POST /api/agent-gate/check), which decides with the
mission's own scope (its workspace folder and the paths its work package owns) and JAI's hard boundaries (pushing,
publishing, deploying, secrets, other projects). Anything the backend does not allow is not run, and the agent is
told why. The check fails closed: if JAI cannot be reached, nothing runs. After an action runs, what happened is
sent to the backend (POST /api/agent-gate/record), which writes it to the mission's audit trail and live feed.

The terminal and file editor here are OpenHands' own (registered under the names the model knows, "terminal" and
"file_editor"), wrapped so the check comes first.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any, ClassVar, Dict, List, Optional, Sequence

import httpx

from openhands.sdk.tool import ToolExecutor, register_tool
from openhands.tools.file_editor import FileEditorTool as _FileEditorTool
from openhands.tools.file_editor.definition import FileEditorObservation
from openhands.tools.terminal import TerminalTool as _TerminalTool
from openhands.tools.terminal.definition import TerminalObservation

logger = logging.getLogger("jai.openhands.gate")

# Keys sent to a running program (Ctrl+C, arrows, Enter): they start nothing new, so they are not checked.
SPECIAL_KEY = re.compile(r"^(C-[A-Za-z]|UP|DOWN|LEFT|RIGHT|HOME|END|PGUP|PGDN|TAB|ESC|BS|ENTER)$")
CHECK_SECONDS = 20.0
OUTPUT_TAIL = 2000


class Gate:
    """One run's line to JAI's authority checker."""

    def __init__(self, url: str, token: str, run_id: str, transport: Optional[httpx.BaseTransport] = None):
        self.url = url.rstrip("/")
        self.run_id = run_id
        self._headers = {"Authorization": f"Bearer {token}"}
        self._client = httpx.Client(timeout=httpx.Timeout(CHECK_SECONDS, connect=5.0), transport=transport)
        self.actions: List[Dict[str, Any]] = []  # what this run did, for its report
        self._lock = threading.Lock()

    def check(self, tool: str, payload: Dict[str, Any]) -> Optional[str]:
        """None when JAI allows the action; otherwise why not. Any failure to get an answer is a refusal."""
        try:
            response = self._client.post(f"{self.url}/api/agent-gate/check", headers=self._headers,
                                         json={"run_id": self.run_id, "tool": tool, **payload})
        except httpx.HTTPError as exc:
            return (f"Not run: JAI's authority check could not be reached ({type(exc).__name__}), and nothing runs "
                    "without it. Try again in a moment.")
        if response.status_code != 200:
            return f"Not run: JAI's authority check answered {response.status_code}: {response.text[:300]}"
        try:
            answer = response.json()
        except ValueError:
            return "Not run: JAI's authority check gave no readable answer."
        if answer.get("allow") is True:
            return None
        return str(answer.get("reason") or "Not run: JAI's authority check refused it.")

    def record(self, tool: str, payload: Dict[str, Any], ok: bool, summary: str, **extra: Any) -> None:
        entry = {"tool": tool, **payload, "ok": ok, "summary": summary[:OUTPUT_TAIL], **extra}
        with self._lock:
            self.actions.append(entry)
        try:
            self._client.post(f"{self.url}/api/agent-gate/record", headers=self._headers,
                              json={"run_id": self.run_id, **entry})
        except httpx.HTTPError as exc:  # the action ran; its record is kept here and in the run's report
            logger.warning("record for %s not delivered: %s", self.run_id, exc)

    def close(self) -> None:
        self._client.close()


# The gate for each run, by run id (set by the server before the conversation starts).
GATES: Dict[str, Gate] = {}


def _gate(run_id: Optional[str]) -> Gate:
    gate = GATES.get(str(run_id or ""))
    if gate is None:
        raise ValueError(f"No JAI gate for run {run_id!r}: the sandbox runs nothing without one.")
    return gate


class GatedTerminal(ToolExecutor):
    """OpenHands' terminal, with JAI's check before every command."""

    def __init__(self, inner: ToolExecutor, gate: Gate, cwd: str):
        self.inner, self.gate, self.cwd = inner, gate, cwd

    def __getattr__(self, name: str) -> Any:  # the terminal's own attributes (its pooling, its session)
        if name == "inner":
            raise AttributeError(name)
        return getattr(self.inner, name)

    def __call__(self, action, conversation=None):
        command = str(action.command or "")
        checked = bool(command.strip()) and not (action.is_input and SPECIAL_KEY.match(command.strip()))
        payload = {"command": command, "cwd": self.cwd, "is_input": bool(action.is_input)}
        if checked:
            refusal = self.gate.check("terminal", payload)
            if refusal:
                self.gate.record("terminal", payload, False, refusal, refused=True)
                return TerminalObservation.from_text(text=refusal, is_error=True, command=command, exit_code=1)
        observation = self.inner(action, conversation)
        where = getattr(getattr(observation, "metadata", None), "working_dir", None)
        if where:
            self.cwd = where
        if checked:
            code = getattr(observation, "exit_code", None)
            self.gate.record("terminal", payload, code == 0, observation.text[-OUTPUT_TAIL:], exit_code=code)
        return observation

    def close(self) -> None:
        self.inner.close()


class GatedEditor(ToolExecutor):
    """OpenHands' file editor, with JAI's check before every read or change."""

    def __init__(self, inner: ToolExecutor, gate: Gate):
        self.inner, self.gate = inner, gate

    def __getattr__(self, name: str) -> Any:
        if name == "inner":
            raise AttributeError(name)
        return getattr(self.inner, name)

    def __call__(self, action, conversation=None):
        payload = {"command": str(action.command), "path": str(action.path)}
        refusal = self.gate.check("file_editor", payload)
        if refusal:
            self.gate.record("file_editor", payload, False, refusal, refused=True)
            return FileEditorObservation.from_text(text=refusal, is_error=True, command=action.command,
                                                   path=action.path)
        observation = self.inner(action, conversation)
        if action.command != "view":
            self.gate.record("file_editor", payload, not observation.is_error, observation.text[-500:])
        return observation

    def close(self) -> None:
        self.inner.close()


class TerminalTool(_TerminalTool):
    name: ClassVar[str] = "terminal"

    @classmethod
    def create(cls, conv_state, jai_run: Optional[str] = None, **params) -> Sequence["TerminalTool"]:
        gate = _gate(jai_run)
        # The agent's shell runs as the unprivileged user "openhands", never as the root that holds the service.
        tools = super().create(conv_state, username="openhands", terminal_type="tmux", **params)
        return [t.model_copy(update={"executor": GatedTerminal(t.executor, gate, conv_state.workspace.working_dir)})
                for t in tools]


class FileEditorTool(_FileEditorTool):
    name: ClassVar[str] = "file_editor"

    @classmethod
    def create(cls, conv_state, jai_run: Optional[str] = None) -> Sequence["FileEditorTool"]:
        gate = _gate(jai_run)
        tools = super().create(conv_state)
        return [t.model_copy(update={"executor": GatedEditor(t.executor, gate)}) for t in tools]


register_tool(TerminalTool.name, TerminalTool)
register_tool(FileEditorTool.name, FileEditorTool)
