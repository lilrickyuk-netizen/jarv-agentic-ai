"""
JARV Backend - Central Tool Permission Policy (Repair 10)

ONE shared permission-enforcement function for every tool-execution path in the
system. Both runtimes route through it BEFORE any tool acts:

  * app.core.command.tool_runtime.ToolRuntime (the command/agent-executor path)
  * app.core.tools.base.ToolBase.execute       (the registry tool path)

The policy classifies each tool (action type, risk level, required authority,
workspace-scope requirement, static approval requirement, audit requirement),
then delegates risk detection to the deterministic hard-boundary detector
(app.core.safety.hard_boundary.evaluate_action) and combines the results into a
single structured PermissionDecision.

Decision semantics (honest, never fabricated):
  * allowed=True, requires_approval=False  -> the action may execute now.
  * allowed=False, requires_approval=True  -> pause ONLY this action; it may run
    later under an exact-scoped Richard approval (boundary chain).
  * allowed=False, requires_approval=False -> the action is never runnable on
    this path (destructive/privileged/pipe-to-shell/unknown executable/
    protected location/out-of-scope); no approval chain is opened for it.

Everything the decision carries (display, reason, audit metadata) is redacted,
so it is safe to persist, log, and return from APIs.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.safety.hard_boundary import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    evaluate_action,
)


@dataclass
class ToolPolicy:
    """Static classification of one tool in the permission policy."""
    tool_id: str
    action_type: str                    # read / write / execute / external_send / network_read
    risk_level: str                     # baseline risk when nothing else triggers
    required_authority: int             # minimum authority level
    workspace_scope_required: bool = False
    requires_approval: bool = False     # statically approval-gated regardless of input
    hard_boundary_reason: Optional[str] = None  # why the static gate exists
    audit_required: bool = True

    @property
    def allowed_without_approval(self) -> bool:
        return not self.requires_approval


@dataclass
class PermissionDecision:
    """Structured result of one permission check (safe to persist/log/return)."""
    allowed: bool
    requires_approval: bool
    boundary_type: Optional[str]
    boundary_reason: Optional[str]
    risk_level: str
    safe_alternative: Optional[str]
    redacted_display: str
    audit_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "boundary_type": self.boundary_type,
            "boundary_reason": self.boundary_reason,
            "risk_level": self.risk_level,
            "safe_alternative": self.safe_alternative,
            "redacted_display": self.redacted_display,
            "audit_metadata": self.audit_metadata,
        }


# --------------------------------------------------------------------------- #
# Policy table for the command-runtime tools. Registry tools (app.core.tools)
# carry their own declared required_authority_level / requires_approval, which
# the caller passes explicitly; they fall back to _DEFAULT_POLICY here.
# --------------------------------------------------------------------------- #
TOOL_POLICIES: Dict[str, ToolPolicy] = {p.tool_id: p for p in [
    ToolPolicy("list_files", "read", RISK_LOW, 1, workspace_scope_required=True),
    ToolPolicy("read_file", "read", RISK_LOW, 1, workspace_scope_required=True),
    ToolPolicy("search_files", "read", RISK_LOW, 1, workspace_scope_required=True),
    ToolPolicy("scan_workspace", "read", RISK_LOW, 1, workspace_scope_required=True),
    ToolPolicy("memory_add", "write", RISK_LOW, 1),
    ToolPolicy("memory_search", "read", RISK_LOW, 1),
    ToolPolicy("create_live_operations_feed_item", "write", RISK_LOW, 1),
    ToolPolicy("create_boundary_report", "write", RISK_LOW, 1),
    ToolPolicy("write_file", "write", RISK_MEDIUM, 2, workspace_scope_required=True),
    ToolPolicy("run_safe_readonly_command", "execute", RISK_LOW, 3),
    ToolPolicy("run_command", "execute", RISK_MEDIUM, 3),
    ToolPolicy("send_notification", "external_send", RISK_HIGH, 4,
               hard_boundary_reason=("Sending real (non-dry-run) messages from Richard's "
                                     "accounts is a hard boundary.")),
    ToolPolicy("fetch_url", "network_read", RISK_LOW, 1),
    ToolPolicy("check_package_registry", "network_read", RISK_LOW, 1),
    ToolPolicy("check_cve", "network_read", RISK_LOW, 1),
    ToolPolicy("asset_licence_check", "network_read", RISK_LOW, 1),
]}

_DEFAULT_POLICY = ToolPolicy("__default__", "execute", RISK_MEDIUM, 1)


def get_tool_policy(tool_id: str) -> ToolPolicy:
    """Return the static policy for a tool (default classification if unlisted)."""
    return TOOL_POLICIES.get(tool_id, _DEFAULT_POLICY)


def _input_hash(*parts: Optional[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="replace"))
        h.update(b"\x00")
    return h.hexdigest()


def check_tool_permission(
    *,
    tool_id: str,
    command: Optional[str] = None,
    target_path: Optional[str] = None,
    action_description: Optional[str] = None,
    content: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    # Identity / scope context (recorded in audit metadata).
    operator: Optional[str] = None,
    agent_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    workspace_id: Optional[UUID] = None,
    # Authority.
    authority_level: int = 0,
    required_authority: Optional[int] = None,
    # Approval state. ``requires_approval_flag`` lets a runtime mark THIS call
    # approval-gated (e.g. a registry tool's own flag, or send dry_run=False).
    requires_approval_flag: Optional[bool] = None,
    approval_granted: bool = False,
    approved_tools: Optional[List[str]] = None,
    # Scope verdict computed by the caller (None = this path has no path scope).
    path_in_scope: Optional[bool] = None,
    allow_build: bool = True,
    allow_install: bool = True,
) -> PermissionDecision:
    """THE shared permission gate. Every tool execution path calls this first.

    Checks, in order: static tool policy, the deterministic hard-boundary
    detector (protected paths, scope, destructive/pipe-to-shell/unknown-
    executable commands, Design section 6 text rules, secret material, residual
    command gating), authority level, and static/explicit approval gates.
    A valid approval signal (approval_granted / approved_tools) satisfies
    approval-gated outcomes but NEVER un-blocks a never-runnable action.
    """
    policy = get_tool_policy(tool_id)
    req_authority = int(required_authority if required_authority is not None
                        else policy.required_authority)
    has_approval = bool(approval_granted or (tool_id in (approved_tools or [])))

    base_meta: Dict[str, Any] = {
        "tool_id": tool_id,
        "action_type": policy.action_type,
        "operator": operator,
        "agent_id": str(agent_id) if agent_id else None,
        "task_id": str(task_id) if task_id else None,
        "workspace_id": str(workspace_id) if workspace_id else None,
        "authority_level": int(authority_level),
        "required_authority": req_authority,
        "approval_granted": has_approval,
        "input_hash": _input_hash(tool_id, command, target_path, content,
                                  action_description),
        "audit_required": policy.audit_required,
    }

    # 1) Deterministic hard-boundary detection (the detector redacts output).
    detection = evaluate_action(
        tool_id=tool_id,
        command=command,
        target_path=target_path,
        action_description=action_description,
        content=content,
        payload=payload,
        workspace_scope_required=policy.workspace_scope_required,
        path_in_scope=path_in_scope,
        allow_build=allow_build,
        allow_install=allow_install,
    )
    meta = dict(base_meta)
    meta["detection"] = detection["audit_metadata"]

    if not detection["allowed"]:
        if not detection["requires_approval"]:
            # Never-runnable on this path; approval cannot un-block it.
            return PermissionDecision(
                allowed=False, requires_approval=False,
                boundary_type=detection["boundary_type"],
                boundary_reason=detection["boundary_reason"],
                risk_level=detection["risk_level"],
                safe_alternative=detection["safe_alternative"],
                redacted_display=detection["redacted_display"],
                audit_metadata=meta)
        if not has_approval:
            return PermissionDecision(
                allowed=False, requires_approval=True,
                boundary_type=detection["boundary_type"],
                boundary_reason=detection["boundary_reason"],
                risk_level=detection["risk_level"],
                safe_alternative=detection["safe_alternative"],
                redacted_display=detection["redacted_display"],
                audit_metadata=meta)
        # A granted approval covers this approval-gated action.
        meta["approval_satisfied_boundary"] = detection["boundary_type"]

    # 2) Authority: insufficient authority pauses the action for approval
    #    (an approval can grant exactly this action; it never raises the
    #    agent's authority globally).
    if int(authority_level) < req_authority and not has_approval:
        return PermissionDecision(
            allowed=False, requires_approval=True,
            boundary_type="authority_required",
            boundary_reason=(f"Tool '{tool_id}' requires authority level {req_authority} "
                             f"but the caller has level {int(authority_level)}."),
            risk_level=RISK_MEDIUM,
            safe_alternative="Request approval for exactly this action, or use a lower-authority tool.",
            redacted_display=detection["redacted_display"],
            audit_metadata=meta)

    # 3) Static / explicit approval gate (tool is approval-gated regardless of input).
    statically_gated = bool(policy.requires_approval or requires_approval_flag)
    if statically_gated and not has_approval:
        return PermissionDecision(
            allowed=False, requires_approval=True,
            boundary_type="tool_requires_approval",
            boundary_reason=(policy.hard_boundary_reason
                             or f"Tool '{tool_id}' requires approval before execution."),
            risk_level=policy.risk_level if policy.risk_level != RISK_LOW else RISK_MEDIUM,
            safe_alternative="Request approval for exactly this action.",
            redacted_display=detection["redacted_display"],
            audit_metadata=meta)

    return PermissionDecision(
        allowed=True, requires_approval=False,
        boundary_type=None, boundary_reason=None,
        risk_level=policy.risk_level,
        safe_alternative=None,
        redacted_display=detection["redacted_display"],
        audit_metadata=meta)
