"""
JARV Backend - Deployment tools (Repair 12e-2)

Spec names: deploy_staging, deploy_production_with_boundary, rollback, plus
deployment_status, deployment_logs and check_deploy_target. All of them go
through ToolBase.execute (authority check, permission policy, ToolRun, audit).

- Staging deploys and rollbacks are production repair work: authority 7, no
  approval.
- A production deploy is a live release: it always pauses for Richard's
  approval (hard boundary "publishing a live release").

The project comes from the mission's workspace: its registered folder must be
a git repository; ``workspace.config["deploy"]`` may set ``app``,
``compose_file`` and ``health_url`` (a URL or ``{"staging": ..., "production": ...}``).
Every deploy and rollback is recorded as a DeploymentRecord.
"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Type
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.core.tools import ToolBase, ToolContext, ToolResult


@asynccontextmanager
async def _session(context: ToolContext):
    if context.db_session is not None:
        yield context.db_session
    else:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            yield session
            await session.commit()


def _deployer():
    """Indirection so the server connection is created per call (and replaceable in tests)."""
    from app.core import deploy

    return deploy.deployer()


async def _project(db, context: ToolContext, data: Dict[str, Any], environment: str) -> Dict[str, Any]:
    """The workspace's project: folder, app name, compose file, health URL."""
    from sqlalchemy import select

    from app.core.deploy import DeployError
    from app.core.workspaces import fs_inspector
    from app.models.workspace import Workspace

    if context.workspace_id is None:
        raise DeployError("A workspace is required.")
    workspace = (await db.execute(select(Workspace).where(Workspace.id == context.workspace_id))).scalar_one_or_none()
    if workspace is None:
        raise DeployError("Workspace not found.")
    config = workspace.config if isinstance(workspace.config, dict) else {}
    settings_ = config.get("deploy") if isinstance(config.get("deploy"), dict) else {}
    root_host = config.get("root_path")
    root = fs_inspector.host_to_container(root_host) if root_host else None
    if root is None:
        raise DeployError("This workspace has no registered folder to deploy from.")
    app = data.get("app") or settings_.get("app") or re.sub(r"[^a-z0-9-]+", "-", (workspace.slug or "").lower())
    app = app.strip("-")[:40]
    health = data.get("health_url") or settings_.get("health_url")
    if isinstance(health, dict):
        health = health.get(environment)
    return {"root": Path(root), "root_host": root_host, "app": app,
            "compose_file": data.get("compose_file") or settings_.get("compose_file") or "docker-compose.yml",
            "health_url": health, "workspace": workspace}


async def _record(db, context: ToolContext, *, name: str, environment: str, version: str, result, started,
                  commit: Optional[str] = None, branch: Optional[str] = None, kind: str = "deploy") -> str:
    from app.models.operations import DeploymentRecord

    finished = datetime.now(timezone.utc)
    status = "succeeded" if result.success else ("rolled_back" if result.rolled_back else "failed")
    record = DeploymentRecord(
        id=uuid4(), workspace_id=context.workspace_id, deployment_name=name[:255],
        deployment_type="rollback" if kind == "rollback" else "application", environment=environment,
        version=(version or "")[:50], status=status, success=bool(result.success),
        commit_sha=(commit or "")[:40] or None, branch=(branch or "")[:100] or None,
        started_at=started, completed_at=finished, duration_seconds=int((finished - started).total_seconds()),
        deployment_logs="\n\n".join(result.log)[-60000:], error_message=result.error,
        can_rollback=bool(result.success and result.previous), rolled_back=bool(result.rolled_back),
        rollback_reason=result.error if result.rolled_back else None,
        meta_data={"app": result.app, "release": result.release, "previous_release": result.previous,
                   "health": result.health, "kind": kind,
                   "agent_id": str(context.agent_id) if context.agent_id else None,
                   "task_id": str(context.task_id) if context.task_id else None},
        created_at=finished, updated_at=finished)
    db.add(record)
    await db.flush()
    return str(record.id)


class _DeployTool(ToolBase):
    _name = ""
    _description = ""
    _input: Type[BaseModel] = BaseModel
    _authority = AuthorityLevel.LEVEL_7_DEPLOYMENT
    _approval = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> Type[BaseModel]:
        return self._input

    @property
    def output_schema(self) -> Type[BaseModel]:
        return _Output

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return self._authority

    @property
    def requires_approval(self) -> bool:
        return self._approval

    @property
    def category(self) -> str:
        return "deployment"

    def fail(self, message: str, **data: Any) -> ToolResult:
        return self.create_result(success=False, result_data=data, error_message=message)


class _Output(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


class _Empty(BaseModel):
    pass


class _DeployInput(BaseModel):
    app: Optional[str] = Field(None, description="App name on the server; defaults to the workspace's")
    compose_file: Optional[str] = Field(None, description="Compose file in the repository")
    health_url: Optional[str] = Field(None, description="URL that must answer below 500 after the deploy")


class CheckDeployTargetTool(_DeployTool):
    _name = "check_deploy_target"
    _description = "Whether a deployment server is configured and reachable, and that Docker Compose works on it."
    _input = _Empty
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core import deploy

        status = deploy.target_status()
        if not status["configured"]:
            return self.create_result(success=True, result_data=status,
                                      output_text="No deployment server configured: missing "
                                                  + ", ".join(status["missing"]))
        try:
            shell = deploy.remote_shell()
            code, out, err = await shell.run(
                f"{deploy.load_target().compose} version --short && df -h / | tail -1", timeout=60)
        except deploy.DeployError as exc:
            return self.fail(str(exc), **status)
        status.update({"reachable": code == 0, "server": (out or err).strip()[:500]})
        return self.create_result(success=code == 0, result_data=status,
                                  output_text="server reachable" if code == 0 else "server not reachable",
                                  error_message=None if code == 0 else err.strip()[:500])


class _Deploy(_DeployTool):
    _input = _DeployInput
    environment = "staging"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.deploy import DeployError, package_workspace

        started = datetime.now(timezone.utc)
        async with _session(context) as db:
            try:
                project = await _project(db, context, input_data, self.environment)
                package = await package_workspace(project["root"])
                result = await _deployer().deploy(project["app"], self.environment, package,
                                                  compose_file=project["compose_file"],
                                                  health_url=project["health_url"])
            except DeployError as exc:
                return self.fail(str(exc))
            record_id = await _record(db, context, name=f"{project['app']} {self.environment}",
                                      environment=self.environment, version=package.release_id,
                                      result=result, started=started, commit=package.commit,
                                      branch=package.branch)
        data = {**result.as_dict(), "deployment_id": record_id, "commit": package.commit}
        data["log"] = data["log"][-20:]
        if result.success:
            return self.create_result(success=True, result_data=data,
                                      output_text=f"{project['app']} {package.release_id} live on {self.environment}")
        return self.create_result(success=False, result_data=data, error_message=(
            f"{self.environment} deploy failed: {result.error}"
            + (f"; restored {result.previous}" if result.rolled_back else "")))


class DeployStagingTool(_Deploy):
    _name = "deploy_staging"
    _description = ("Deploy the workspace's committed code to the staging environment on the server "
                    "(Docker Compose), health-check it, and restore the previous release if it fails.")
    environment = "staging"


class DeployProductionTool(_Deploy):
    _name = "deploy_production_with_boundary"
    _description = ("Release the workspace's committed code to production. Always pauses for Richard's "
                    "approval first; health-checked with automatic restore of the previous release.")
    environment = "production"
    _approval = True


class _RollbackInput(BaseModel):
    environment: str = Field(..., description="staging or production")
    to_release: Optional[str] = Field(None, description="Release id; defaults to the one before current")
    reason: str = Field(..., min_length=5, description="Why the rollback is needed (recorded)")
    app: Optional[str] = None
    compose_file: Optional[str] = None
    health_url: Optional[str] = None


class RollbackTool(_DeployTool):
    _name = "rollback"
    _description = ("Roll a deployed environment back to the previous release (or a named one), "
                    "health-checked; production repair, recorded with the reason.")
    _input = _RollbackInput

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.deploy import DeployError, validate_names

        environment = input_data["environment"]
        started = datetime.now(timezone.utc)
        async with _session(context) as db:
            try:
                project = await _project(db, context, input_data, environment)
                validate_names(project["app"], environment)
                result = await _deployer().rollback(project["app"], environment,
                                                    to_release=input_data.get("to_release"),
                                                    compose_file=project["compose_file"],
                                                    health_url=project["health_url"])
            except DeployError as exc:
                return self.fail(str(exc))
            record_id = await _record(db, context, name=f"{project['app']} {environment} rollback",
                                      environment=environment, version=result.release or "", result=result,
                                      started=started, kind="rollback")
        data = {**result.as_dict(), "deployment_id": record_id, "reason": input_data["reason"]}
        if result.success:
            return self.create_result(success=True, result_data=data,
                                      output_text=f"{project['app']} {environment} rolled back to {result.release}")
        return self.create_result(success=False, result_data=data, error_message=f"rollback failed: {result.error}")


class _EnvInput(BaseModel):
    environment: str = Field("production", description="staging or production")
    app: Optional[str] = None
    compose_file: Optional[str] = None


class DeploymentStatusTool(_DeployTool):
    _name = "deployment_status"
    _description = "Releases on the server, which one is current, and the state of its containers."
    _input = _EnvInput
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.deploy import DeployError, validate_names

        async with _session(context) as db:
            try:
                project = await _project(db, context, input_data, input_data["environment"])
                validate_names(project["app"], input_data["environment"])
                data = await _deployer().status(project["app"], input_data["environment"], project["compose_file"])
            except DeployError as exc:
                return self.fail(str(exc))
        return self.create_result(success=True, result_data=data,
                                  output_text=f"current release: {data['current'] or 'none'}")


class _LogsInput(_EnvInput):
    lines: int = Field(200, ge=1, le=1000)


class DeploymentLogsTool(_DeployTool):
    _name = "deployment_logs"
    _description = "Recent logs of the current release's containers (secrets redacted)."
    _input = _LogsInput
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.deploy import DeployError, validate_names

        async with _session(context) as db:
            try:
                project = await _project(db, context, input_data, input_data["environment"])
                validate_names(project["app"], input_data["environment"])
                text = await _deployer().logs(project["app"], input_data["environment"],
                                              input_data.get("lines", 200), project["compose_file"])
            except DeployError as exc:
                return self.fail(str(exc))
        return self.create_result(success=True, result_data={"logs": text[-20000:]},
                                  output_text=f"{len(text.splitlines())} log lines")


DEPLOY_TOOLS = [CheckDeployTargetTool, DeployStagingTool, DeployProductionTool, RollbackTool,
                DeploymentStatusTool, DeploymentLogsTool]

__all__ = ["DEPLOY_TOOLS"] + [t.__name__ for t in DEPLOY_TOOLS]
