"""
JARV Backend - Workspace tools in the tool registry under the design's names (Repair 12e-3a)

list_files, read_file, write_file, edit_file, create_folder, move_file,
copy_file, delete_file_with_boundary, get_file_metadata, search_files,
scan_workspace, run_command, run_build, run_tests, install_package,
check_installed, get_command_log, git_status/diff/log, git_create_branch,
git_push_with_boundary, memory_add, memory_search, memory_link_to_workspace,
memory_link_to_task, detect_workspace_type, detect_stack, detect_commands,
find_missing_files, fetch_url, check_package_registry, check_cve,
asset_licence_check.

These are the same confined implementations agents use through their toolbox
(``app.core.agents.toolbox`` and ``workspace_ops``), registered so every
design tool name is in the registry. Calling one through the registry runs
the full chain twice over: ToolBase.execute (authority, permission policy,
ToolRun, audit) and then the toolbox (paths confined to the workspace's
registered folder, ToolRuntime gate, task/feed/audit record).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field, create_model

from app.core.agents.base import AuthorityLevel
from app.core.tools import ToolBase, ToolContext, ToolResult

# Design authority (1-7) -> AuthorityLevel used by registry tools; the toolbox maps it back.
_TO_AGENT_LEVEL = {1: AuthorityLevel.LEVEL_1_BASIC_TOOLS, 2: AuthorityLevel.LEVEL_2_FILE_OPERATIONS,
                   3: AuthorityLevel.LEVEL_3_CODE_EXECUTION, 4: AuthorityLevel.LEVEL_4_SYSTEM_CHANGES,
                   5: AuthorityLevel.LEVEL_7_DEPLOYMENT}
_TYPES = {"string": str, "integer": int, "boolean": bool, "number": float}
_DESIGN_LEVEL = {"run_command": 3, "run_build": 3, "run_tests": 3, "install_package": 4,
                 "git_status": 1, "git_diff": 1, "git_log": 1}


class _Output(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


def _model(name: str, schema: Dict[str, Any]) -> Type[BaseModel]:
    required = set(schema.get("required") or [])
    fields: Dict[str, Any] = {}
    for key, prop in (schema.get("properties") or {}).items():
        kind = _TYPES.get(prop.get("type"), str)
        description = prop.get("description")
        if key in required:
            fields[key] = (kind, Field(..., description=description))
        else:
            fields[key] = (Optional[kind], Field(None, description=description))
    return create_model(f"{name.title().replace('_', '')}Input", **fields)


class _ToolboxAgent:
    """The minimum of an agent the toolbox needs, built from a registry call."""

    def __init__(self, tool_name: str, level: AuthorityLevel, agent_id):
        self.name = "registry"
        self.config = SimpleNamespace(authority_level=level, agent_id=agent_id)
        self._tool = tool_name

    def get_allowed_tools(self) -> List[str]:
        return [self._tool]


class _WorkspaceTool(ToolBase):
    _spec = None
    _level = AuthorityLevel.LEVEL_1_BASIC_TOOLS
    _approval = False
    _input: Type[BaseModel] = BaseModel

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def description(self) -> str:
        return self._spec.description

    @property
    def input_schema(self) -> Type[BaseModel]:
        return self._input

    @property
    def output_schema(self) -> Type[BaseModel]:
        return _Output

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return self._level

    @property
    def requires_approval(self) -> bool:
        return self._approval

    @property
    def category(self) -> str:
        return "workspace_runtime"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.agents.toolbox import AgentToolbox

        if context.db_session is None or context.workspace_id is None:
            return self.create_result(success=False, error_message="Workspace tools need a workspace and a database session.")
        agent = _ToolboxAgent(self.name, self.config.authority_level, context.agent_id)
        box_context = SimpleNamespace(
            db_session=context.db_session, workspace_id=context.workspace_id, task_id=context.task_id,
            user_id=context.user_id, session_id=context.session_id, metadata=dict(context.metadata or {}),
            approval_granted=bool(getattr(context, "approval_granted", False)) or self._has_approval(context),
            approved_tools=list(getattr(context, "approved_tools", None) or []))
        box = AgentToolbox(agent, box_context)
        try:
            await box.prepare()
        except RuntimeError as exc:
            return self.create_result(success=False, error_message=str(exc))
        args = {k: v for k, v in input_data.items() if v is not None}
        result = await box.call(self.name, args)
        ok = bool(result.get("success"))
        return self.create_result(
            success=ok, result_data=result,
            output_text=str(result.get("summary") or ("done" if ok else ""))[:500] or None,
            error_message=None if ok else str(result.get("reason") or result.get("error") or "failed")[:1000],
            requires_approval=bool(result.get("requires_approval")))


def _build() -> List[Type[ToolBase]]:
    from app.core.agents.toolbox import WORKSPACE_TOOLS
    from app.core.command.tool_runtime import _TOOL_AUTHORITY
    from app.core.safety.permission_policy import get_tool_policy

    classes: List[Type[ToolBase]] = []
    for spec in WORKSPACE_TOOLS.values():
        design = _DESIGN_LEVEL.get(spec.name) or _TOOL_AUTHORITY.get(spec.name, 1)
        attrs = {"_spec": spec, "_level": _TO_AGENT_LEVEL[min(max(int(design), 1), 5)],
                 "_approval": get_tool_policy(spec.name).requires_approval,
                 "_input": _model(spec.name, spec.input_schema), "__module__": __name__}
        classes.append(type(f"{spec.name.title().replace('_', '')}Tool", (_WorkspaceTool,), attrs))
    return classes


WORKSPACE_RUNTIME_TOOLS = _build()

__all__ = ["WORKSPACE_RUNTIME_TOOLS"]
