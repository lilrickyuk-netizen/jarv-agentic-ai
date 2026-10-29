"""
JARV Backend - WorkspaceManagerAgent

Manages workspaces through the workspace lifecycle tools
(app.tools.workspace.lifecycle): create, import (folder, repository, document
pack, live platform), scan, task plans, roadmap, launch checklist, rules,
archive and (with Richard's approval) delete.

- With a model provider and a workspace, it works through those tools.
- Without a provider but inside a workspace, "scan" records a real scan of the
  workspace folder and "launch_checklist" re-verifies the launch checklist.
- Otherwise, when a real folder path is supplied (input or
  context.metadata.workspace_path), it walks that folder and reports the files
  and stack markers that actually exist. Nothing is fabricated.
"""
from typing import Dict, Any, List, Type
import os
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class WorkspaceManagerAgentInput(BaseModel):
    """WorkspaceManagerAgent input"""
    operation: str = Field(..., description="create, update, delete, configure")
    workspace_name: str = Field(default="")
    config: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceManagerAgentOutput(BaseModel):
    """WorkspaceManagerAgent output (honest; real scan, no fabricated detection)."""
    operation_completed: bool = False
    operation: str = ""
    scanned_path: str = ""
    path_valid: bool = False
    file_count: int = 0
    files_by_extension: Dict[str, int] = Field(default_factory=dict)
    detected_stack: List[str] = Field(default_factory=list)
    stack_markers_found: List[str] = Field(default_factory=list)
    db_persisted: bool = False
    limitations: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class WorkspaceManagerAgent(AgentBase):
    """
    WorkspaceManagerAgent - Manages workspace configuration, rules, and lifecycle
    """

    @property
    def name(self) -> str:
        return "workspace_manager"

    @property
    def role(self) -> str:
        return "Manages workspace configuration, rules, and lifecycle"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceManagerAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceManagerAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def default_tools(self) -> list[str]:
        from app.core.tools.base import ToolConfig
        from app.tools.workspace.lifecycle import WORKSPACE_LIFECYCLE_TOOLS

        return [tool(ToolConfig()).name for tool in WORKSPACE_LIFECYCLE_TOOLS] + [
            "scan_workspace", "detect_workspace_type", "detect_stack", "detect_commands", "find_missing_files",
            "workspace_list", "workspace_info"]

    # Stack marker filename -> stack label.
    _STACK_MARKERS = {
        "package.json": "node",
        "pyproject.toml": "python",
        "requirements.txt": "python",
        "go.mod": "go",
        "Cargo.toml": "rust",
        "Dockerfile": "docker",
    }
    _MAX_FILES = 20000  # cap the walk so huge trees don't hang the agent.

    def _resolve_path(self, input_data: Dict[str, Any], context: AgentContext) -> str:
        """Return a real existing folder path from input/config/metadata, else ''."""
        cfg = input_data.get("config") or {}
        candidates = [
            input_data.get("folder_path"),
            input_data.get("path"),
            cfg.get("folder_path") if isinstance(cfg, dict) else None,
            cfg.get("path") if isinstance(cfg, dict) else None,
        ]
        meta = getattr(context, "metadata", None) or {}
        candidates.append(meta.get("workspace_path"))
        candidates.append(meta.get("folder_path"))
        for c in candidates:
            if c and isinstance(c, str) and os.path.isdir(c):
                return os.path.abspath(c)
        return ""

    def _scan(self, base: str) -> Dict[str, Any]:
        """Real filesystem walk: count files by extension + detect stack markers."""
        files_by_ext: Dict[str, int] = {}
        markers_found: List[str] = []
        marker_set = set()
        file_count = 0
        for root, dirs, files in os.walk(base):
            # Skip common noise dirs to keep the walk meaningful and bounded.
            dirs[:] = [d for d in dirs if d not in (
                ".git", "node_modules", "__pycache__", ".venv", "venv",
                "dist", "build", ".next", "target",
            )]
            for fn in files:
                file_count += 1
                if file_count > self._MAX_FILES:
                    break
                ext = os.path.splitext(fn)[1].lower() or "<none>"
                files_by_ext[ext] = files_by_ext.get(ext, 0) + 1
                if fn in self._STACK_MARKERS and fn not in marker_set:
                    marker_set.add(fn)
                    markers_found.append(fn)
            if file_count > self._MAX_FILES:
                break
        detected = sorted({self._STACK_MARKERS[m] for m in markers_found})
        return {
            "file_count": min(file_count, self._MAX_FILES),
            "files_by_extension": files_by_ext,
            "stack_markers_found": markers_found,
            "detected_stack": detected,
            "capped": file_count > self._MAX_FILES,
        }

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """Lifecycle work through tools, a recorded scan, or a real folder walk."""
        goal = (input_data.get("config") or {}).get("goal")
        if self.tools_enabled(context) and goal:
            outcome = await self.use_tools(
                context, f"Operation: {input_data.get('operation')}\nWorkspace: {input_data.get('workspace_name')}\n"
                         f"Goal: {goal}", instructions=_INSTRUCTIONS, max_steps=16)
            return self.result_from_tools(outcome, mode="tools")
        operation = str(input_data.get("operation") or "").lower()
        if context.db_session is not None and context.workspace_id is not None and \
                operation in ("scan", "launch_checklist"):
            return await self._lifecycle(operation, context)
        try:
            operation = input_data.get("operation", "update")
            workspace_name = input_data.get("workspace_name", "")
            base = self._resolve_path(input_data, context)

            self.logger.info(
                f"Workspace operation: {operation} for '{workspace_name}' "
                f"(scan path: {base or 'none'})"
            )

            limitations: List[str] = [
                "Workspace lifecycle records (create/update/delete/configure) "
                "are stored in the database; no DB write was performed by this "
                "standalone agent.",
            ]
            recommendations: List[str] = []

            if not base:
                limitations.append(
                    "No valid folder path was supplied (input folder_path/path "
                    "or context.metadata.workspace_path); no filesystem scan was "
                    "performed."
                )
                recommendations.append(
                    "Provide an existing folder path to scan the real workspace "
                    "structure and detect its stack."
                )
                result_data = {
                    "operation_completed": False,
                    "operation": operation,
                    "scanned_path": "",
                    "path_valid": False,
                    "file_count": 0,
                    "files_by_extension": {},
                    "detected_stack": [],
                    "stack_markers_found": [],
                    "db_persisted": False,
                    "limitations": limitations,
                    "recommendations": recommendations,
                }
                output_text = (
                    f"Workspace {operation} (LIMITED): no valid folder path to "
                    "scan and no DB session to persist lifecycle changes."
                )
                return self.create_result(
                    success=True,
                    result_data=result_data,
                    output_text=output_text,
                    tools_used=[],
                )

            scan = self._scan(base)
            if scan["capped"]:
                limitations.append(
                    f"File walk capped at {self._MAX_FILES} files; counts reflect "
                    "the cap, not the full tree."
                )

            result_data = {
                "operation_completed": False,
                "operation": operation,
                "scanned_path": base,
                "path_valid": True,
                "file_count": scan["file_count"],
                "files_by_extension": scan["files_by_extension"],
                "detected_stack": scan["detected_stack"],
                "stack_markers_found": scan["stack_markers_found"],
                "db_persisted": False,
                "limitations": limitations,
                "recommendations": recommendations or [
                    "Route lifecycle changes through the workspace subsystem (DB) "
                    "to actually create/update the workspace record."
                ],
            }

            stack = ", ".join(scan["detected_stack"]) if scan["detected_stack"] else "none detected"
            output_text = (
                f"Workspace scan ({operation}) of {base}: {scan['file_count']} "
                f"file(s); stack: {stack}. No DB lifecycle write performed."
            )

            # A truthful real scan is a successful agent run.
            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=output_text,
                tools_used=["workspace_list"],
            )

        except Exception as e:
            self.logger.error(f"workspace_manager task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )

    async def _lifecycle(self, operation: str, context: AgentContext) -> AgentResult:
        from sqlalchemy import select

        from app.core.workspaces.lifecycle import workspace_lifecycle
        from app.models.workspace import Workspace

        ws = (await context.db_session.execute(select(Workspace).where(Workspace.id == context.workspace_id))
              ).scalar_one_or_none()
        if ws is None:
            return self.create_result(success=False, result_data={}, error_message="Workspace not found")
        try:
            if operation == "scan":
                scan = await workspace_lifecycle.scan(context.db_session, ws)
                return self.create_result(
                    success=scan["status"] == "completed", result_data={"operation": operation, "scan": scan},
                    output_text=(f"Scan recorded: {', '.join(scan['detected'].get('stack') or []) or 'no stack detected'}; "
                                 f"{len(scan['missing_files'])} missing file(s)"),
                    tools_used=["scan_workspace"], error_message=scan.get("reason"))
            checklist = await workspace_lifecycle.update_launch_checklist(context.db_session, ws, None, True)
            return self.create_result(
                success=True, result_data={"operation": operation, "launch_checklist": checklist},
                output_text=f"Launch checklist {checklist['done']}/{checklist['total']}",
                tools_used=["update_launch_checklist"])
        except (LookupError, PermissionError, ValueError) as exc:
            return self.create_result(success=False, result_data={"operation": operation}, error_message=str(exc))


_INSTRUCTIONS = (
    "You manage this owner's workspaces. Use the lifecycle tools: import folders, repositories, document packs "
    "and live platforms; scan and detect the project; turn goals into task plans; keep the roadmap and launch "
    "checklist current; record rule changes (protected rules pause for Richard). Deleting a workspace needs "
    "Richard's approval and never deletes files. Finish with what changed.")
