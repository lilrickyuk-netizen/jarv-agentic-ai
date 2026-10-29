"""
JARV Backend - Operations agents on real tools (Repair 12d)

The monitoring, self-healing, rollback and infrastructure agents work through
the operations tools (``app.tools.ops``) via their toolbox, so every check and
every repair is authority-checked, logged as a ToolRun, and audited.

Two ways to run, chosen per task:
- Tool loop: when a model provider is configured, the agent plans and acts
  with its tools (``AgentBase.use_tools``), like the engineering agents.
- Direct operations: without a provider, the agent still does its job with a
  fixed procedure: monitoring measures; self-healing measures, repairs what
  JARV may repair (stuck missions, crashed services), and verifies; rollback
  and infrastructure report real state and run backups.

Both need a database session and a workspace. The unit-test suite opts in per
test (``metadata["ops_enabled"]`` / ``metadata["tools_enabled"]``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from app.core.agents.specialists.tool_mode import GIT_READ, READ, RECALL, REMEMBER, _lines

OBSERVE = ["check_health", "check_queue", "check_errors", "check_logs", "check_crashes",
           "check_container_status", "check_container_logs", "check_database_health", "query_metrics",
           "inspect_server", "check_disk_space", "check_memory_usage", "check_cpu_usage"]
EXTERNAL = ["check_uptime", "ssl_check", "dns_verify"]
BACKUP_READ = ["list_backups", "verify_backup"]
INFRA_CONFIG = ["check_ssl_certificate", "check_domain_dns", "generate_nginx_config", "generate_docker_compose",
                "validate_cloud_config", "estimate_infrastructure_cost", "scale_service_with_budget_boundary"]


@dataclass(frozen=True)
class OpsMode:
    tools: List[str]
    instructions: str
    brief: Callable[[Dict[str, Any]], str]
    max_steps: int = 16


MODES: Dict[str, OpsMode] = {
    "monitoring": OpsMode(
        tools=OBSERVE + EXTERNAL + ["check_payment_events", "check_reviews", "check_analytics"] + RECALL + REMEMBER,
        instructions=(
            "Measure; never assume. Start with check_health and check_container_status, then check_errors "
            "and check_crashes. Probe each URL target with check_uptime (and ssl_check for https). Use "
            "query_metrics for trends; for a live product also check_payment_events, check_reviews and "
            "check_analytics. Do not change anything. In outputs, give one line per target or "
            "check as 'OK: ...', 'WARN: ...' or 'CRITICAL: ...' with the measured value."),
        brief=lambda d: _lines([("Targets", ", ".join(d.get("targets") or []) or "all JARV services"),
                                ("Metrics", ", ".join(d.get("metrics") or [])),
                                ("Alert thresholds", d.get("alert_threshold"))]),
    ),
    "self_healing": OpsMode(
        tools=OBSERVE + ["restart_service", "recover_stuck_missions", "create_backup"] + BACKUP_READ
        + READ + GIT_READ + RECALL + REMEMBER,
        instructions=(
            "Diagnose before acting: check_health, check_container_status, check_crashes, check_errors and the "
            "logs of the affected service. Then repair only what the evidence shows: recover_stuck_missions "
            "for missions that stopped heartbeating; restart_service for a crashed or unhealthy JARV service "
            "(never postgres or redis; they are refused). After each repair, verify with check_health. If the "
            "cause is in code, state the file and evidence so the debugging agent can fix it. Summarise root "
            "cause, actions taken, and the verified result."),
        brief=lambda d: _lines([("Issue", d.get("issue_detected")), ("Affected system", d.get("affected_system")),
                                ("Severity", d.get("severity")),
                                ("Repairs allowed", "yes" if d.get("auto_fix_enabled", True) else
                                 "no - diagnose and report only")]),
        max_steps=20,
    ),
    "rollback": OpsMode(
        tools=["check_container_status", "check_service_logs", "check_health", "create_backup"]
        + BACKUP_READ + ["restore_backup_with_boundary", "deployment_status", "deployment_logs", "rollback"]
        + READ + GIT_READ + RECALL,
        instructions=(
            "Establish what changed and what state to return to: deployment_status and deployment_logs for the "
            "environment, git_log/git_diff in the workspace, and the backups available (list_backups, "
            "verify_backup). Roll a deployed app back with rollback (previous release by default, health-checked, "
            "with the reason). Take a fresh create_backup before any data restore; restoring data uses "
            "restore_backup_with_boundary, which restores into a new database and pauses for Richard's approval. "
            "Never claim a rollback that a tool result does not show."),
        brief=lambda d: _lines([("Deployment", d.get("deployment_id")), ("Reason", d.get("reason")),
                                ("Target version", d.get("target_version"))]),
    ),
    "infrastructure": OpsMode(
        tools=["inspect_server", "check_disk_space", "check_memory_usage", "check_cpu_usage", "check_docker_status",
               "check_container_status", "check_container_logs", "check_database_health", "check_env_vars",
               "restart_container", "create_backup", "list_backups", "verify_backup",
               "restore_backup_with_boundary", "cleanup_backups", "ssl_check", "dns_verify", "cost_estimate"]
        + INFRA_CONFIG
        + READ + RECALL + REMEMBER,
        instructions=(
            "Work from measurements: server resources, containers, database, configuration (check_env_vars "
            "never shows values). For backups, create then verify. Restores and backup deletion pause for "
            "Richard's approval. Check configs with validate_cloud_config; generate nginx and compose files "
            "when missing; check costs with estimate_infrastructure_cost before scaling, and scale only with "
            "scale_service_with_budget_boundary, which pauses for Richard beyond the budget or replica limit. "
            "Report numbers exactly as the tools returned them."),
        brief=lambda d: _lines([("Operation", d.get("operation")),
                                ("Resources", ", ".join(d.get("resources") or [])),
                                ("Target capacity", d.get("target_capacity"))]),
    ),
}


def tools_for(agent_name: str) -> List[str]:
    return list(MODES[agent_name].tools)


def ops_enabled(agent: Any, context: Any) -> bool:
    from app.core.config import settings

    if context.db_session is None or context.workspace_id is None:
        return False
    return bool(context.metadata.get("ops_enabled", not settings.TESTING))


async def run(agent: Any, input_data: Dict[str, Any], context: Any):
    """AgentResult from the tool loop or the direct procedure; None when neither applies."""
    if agent.tools_enabled(context):
        mode = MODES[agent.name]
        outcome = await agent.use_tools(context, mode.brief(input_data) or str(input_data),
                                        instructions=mode.instructions, max_steps=mode.max_steps)
        return agent.result_from_tools(outcome, mode="tools")
    if not ops_enabled(agent, context):
        return None
    from app.core.agents.toolbox import AgentToolbox

    toolbox = AgentToolbox(agent, context)
    try:
        await toolbox.prepare()
    except RuntimeError as exc:
        agent.logger.warning(f"{agent.name}: direct operations unavailable: {exc}")
        return None
    procedure = {"monitoring": _monitor, "self_healing": _heal, "rollback": _rollback,
                 "infrastructure": _infrastructure}[agent.name]
    data, text, success, approval = await procedure(toolbox, input_data)
    trail = toolbox.summary()
    data.update({"mode": "operations", "tool_calls": trail["calls"], "blocked_actions": trail["blocked"],
                 "approval_needed": trail["approval_needed"]})
    return agent.create_result(success=success, result_data=data, output_text=text,
                               tools_used=sorted({c["name"] for c in trail["calls"]}),
                               requires_approval=approval,
                               error_message=None if success else text)


# ----- procedures --------------------------------------------------------------------------

async def _call(toolbox, name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await toolbox.call(name, args or {})


def _data(result: Dict[str, Any]) -> Dict[str, Any]:
    return (result.get("data") or {}) if result.get("success") else {}


def _is_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


async def _observe(toolbox) -> Dict[str, Any]:
    health = await _call(toolbox, "check_health")
    containers = await _call(toolbox, "check_container_status")
    errors = await _call(toolbox, "check_errors", {"hours": 24})
    server = await _call(toolbox, "inspect_server")
    return {"health": health, "containers": containers, "errors": errors, "server": server}


async def _monitor(toolbox, input_data: Dict[str, Any]):
    seen = await _observe(toolbox)
    health, containers = _data(seen["health"]), _data(seen["containers"])
    by_service = {c["service"]: c for c in containers.get("containers", [])}
    statuses: List[Dict[str, str]] = []
    alerts: List[Dict[str, str]] = []

    for name, check in (health.get("checks") or {}).items():
        statuses.append({"target": f"jarv:{name}", "status": "healthy" if check.get("ok") else "critical",
                         "detail": str(check.get("error") or f"{check.get('latency_ms')} ms")})
    for service, info in by_service.items():
        bad = info["state"] != "running" or info.get("health") == "unhealthy"
        statuses.append({"target": f"service:{service}", "status": "critical" if bad else "healthy",
                         "detail": info.get("status", "")})
    for target in [str(t).strip() for t in (input_data.get("targets") or []) if str(t).strip()]:
        if _is_url(target):
            probe = _data(await _call(toolbox, "check_uptime", {"url": target}))
            up = probe.get("up")
            statuses.append({"target": target, "status": "unknown" if up is None else ("healthy" if up else "critical"),
                             "detail": str(probe.get("status_code") or probe.get("error") or "probe refused")})
        elif target.lower() not in by_service and not any(s["target"].endswith(f":{target}") for s in statuses):
            statuses.append({"target": target, "status": "unknown",
                             "detail": "not a URL or a JARV service; nothing to probe"})

    server = _data(seen["server"])
    thresholds = input_data.get("alert_threshold") or {}
    for metric, value in (("cpu_percent", server.get("cpu_percent")), ("memory_percent", server.get("memory_percent"))):
        limit = float(thresholds.get(metric, 90))
        if value is not None and value >= limit:
            statuses.append({"target": f"server:{metric}", "status": "warning", "detail": f"{value}% >= {limit}%"})
    for disk in server.get("disks", []):
        if disk["percent"] >= float(thresholds.get("disk_percent", 85)):
            statuses.append({"target": f"disk:{disk['mount']}", "status": "warning", "detail": f"{disk['percent']}%"})
    errors = _data(seen["errors"])
    if errors.get("open_incidents"):
        statuses.append({"target": "incidents", "status": "warning",
                         "detail": f"{len(errors['open_incidents'])} open incident(s)"})

    for s in statuses:
        if s["status"] in ("critical", "warning"):
            alerts.append({"target": s["target"], "severity": s["status"], "detail": s["detail"]})
    counts = {k: sum(1 for s in statuses if s["status"] == k) for k in ("healthy", "warning", "critical", "unknown")}
    limitations = [r["error"] for r in (seen["containers"],) if not r.get("success") and r.get("error")]
    data = {
        "monitoring_active": True, "live_integration_connected": bool(seen["health"].get("success")),
        "targets_provided": len(input_data.get("targets") or []), "target_statuses": statuses,
        "systems_healthy": counts["healthy"], "systems_warning": counts["warning"],
        "systems_critical": counts["critical"], "systems_unknown": counts["unknown"],
        "alerts_triggered": alerts,
        "recommendations": (["Run the self-healing agent for the critical items."] if counts["critical"] else []),
        "limitations": limitations, "server": server, "recent_errors": errors,
    }
    text = (f"Monitoring: {counts['healthy']} healthy, {counts['warning']} warning, "
            f"{counts['critical']} critical, {counts['unknown']} unknown.")
    return data, text, True, False


async def _heal(toolbox, input_data: Dict[str, Any]):
    from app.core.ops.docker_ops import NEVER_RESTART, RESTARTABLE

    allowed = bool(input_data.get("auto_fix_enabled", True))
    affected = str(input_data.get("affected_system") or "").strip().lower()
    before = await _observe(toolbox)
    health = _data(before["health"])
    containers = _data(before["containers"]).get("containers", [])
    findings: List[Dict[str, str]] = []
    actions: List[Dict[str, Any]] = []

    missions = (health.get("checks") or {}).get("missions", {})
    if missions and not missions.get("ok"):
        findings.append({"cause": "stuck_missions", "evidence": str(missions.get("error"))})
    broken = [c for c in containers if c["state"] != "running" or c.get("health") == "unhealthy"]
    for c in broken:
        findings.append({"cause": "service_down", "service": c["service"], "evidence": c.get("status", "")})
    if affected and affected in {c["service"] for c in containers} and affected not in {c["service"] for c in broken}:
        logs = _data(await _call(toolbox, "check_container_logs", {"service": affected, "lines": 150}))
        findings.append({"cause": "reported", "service": affected,
                         "evidence": "service running; recent log tail captured for diagnosis",
                         "log_tail": (logs.get("logs") or "")[-2000:]})

    if allowed:
        if missions and not missions.get("ok"):
            result = await _call(toolbox, "recover_stuck_missions")
            actions.append({"action": "recover_stuck_missions", "success": result.get("success"),
                            "result": result.get("data") or result.get("error")})
        for c in broken:
            if c["service"] in NEVER_RESTART or c["service"] not in RESTARTABLE:
                actions.append({"action": "restart_service", "service": c["service"], "success": False,
                                "result": "not restarted automatically; reported for Richard"})
                continue
            result = await _call(toolbox, "restart_service", {
                "service": c["service"], "reason": f"self-healing: {c['service']} was {c.get('status') or c['state']}"})
            actions.append({"action": "restart_service", "service": c["service"], "success": result.get("success"),
                            "result": result.get("data") or result.get("error") or result.get("reason")})

    after = _data(await _call(toolbox, "check_health")) if actions else health
    healthy_after = bool(after.get("healthy"))
    containers_after = _data(await _call(toolbox, "check_container_status")) if actions else {}
    still_broken = containers_after.get("unhealthy", []) if actions else [c["service"] for c in broken]
    resolved = healthy_after and not still_broken
    limitations: List[str] = []
    if not before["containers"].get("success"):
        limitations.append(str(before["containers"].get("error")))
    if not allowed and findings:
        limitations.append("Repairs were not allowed for this task; findings reported only.")
    data = {
        "affected_system": affected, "severity": input_data.get("severity", "medium"),
        "blocked": bool(findings) and not resolved, "files_analyzed": [], "findings": findings,
        "remediation_plan": [f"{a['action']} {a.get('service', '')}".strip() for a in actions],
        "actions_taken": actions, "verified_healthy": resolved, "health_after": after,
        "provider_used": None, "limitations": limitations,
    }
    if not findings:
        text = "Self-healing: no fault found; all measured checks healthy." if healthy_after else \
            f"Self-healing: checks failing ({', '.join(health.get('failing', []))}) with no repair JARV may apply."
        return data, text, True, False
    text = (f"Self-healing: {len(findings)} finding(s), {len(actions)} action(s); "
            f"{'verified healthy afterwards' if resolved else 'NOT resolved'}"
            + (f" (still unhealthy: {', '.join(still_broken)})" if still_broken else "") + ".")
    return data, text, resolved or not allowed, False


async def _deployment_record(toolbox, deployment_id: str):
    from uuid import UUID

    from sqlalchemy import select

    from app.models.operations import DeploymentRecord

    try:
        key = UUID(str(deployment_id))
    except ValueError:
        return None
    return (await toolbox.context.db_session.execute(select(DeploymentRecord).where(
        DeploymentRecord.id == key, DeploymentRecord.workspace_id == toolbox.context.workspace_id))
    ).scalar_one_or_none()


async def _rollback(toolbox, input_data: Dict[str, Any]):
    """Roll a recorded deployment back to the release before it (or the named
    target version), health-checked; otherwise report state and restorable backups."""
    deployment_id = str(input_data.get("deployment_id") or "")
    reason = str(input_data.get("reason") or "requested rollback")
    target = str(input_data.get("target_version") or "previous")
    record = await _deployment_record(toolbox, deployment_id)
    environment = record.environment if record is not None else (
        deployment_id if deployment_id in ("staging", "production") else None)
    data: Dict[str, Any] = {"deployment_id": deployment_id, "reason": reason, "target_version": target,
                            "blocked": True, "rollback_performed": False, "requirements": [], "limitations": []}
    if environment is not None:
        args: Dict[str, Any] = {"environment": environment, "reason": reason if len(reason) >= 5 else f"rollback: {reason}"}
        if target != "previous":
            args["to_release"] = target
        elif record is not None and (record.meta_data or {}).get("previous_release") and record.status == "succeeded":
            args["to_release"] = record.meta_data["previous_release"]
        if record is not None and (record.meta_data or {}).get("app"):
            args["app"] = record.meta_data["app"]
        result = await _call(toolbox, "rollback", args)
        outcome = result.get("data") or {}
        data.update({"blocked": not result.get("success"), "rollback_performed": bool(result.get("success")),
                     "rolled_back_to": outcome.get("release"), "from_release": outcome.get("previous"),
                     "health": outcome.get("health"), "rollback_deployment_id": outcome.get("deployment_id")})
        if result.get("success"):
            return data, f"Rolled {environment} back to {outcome.get('release')} (health-checked).", True, False
        data["limitations"].append(str(result.get("error") or result.get("reason")))
    containers = await _call(toolbox, "check_container_status")
    backups = _data(await _call(toolbox, "list_backups")).get("backups", [])
    git_log = await _call(toolbox, "git_log", {"count": 10}) if "git_log" in toolbox.available else {}
    data["requirements"] = [
        "A deployment rollback needs the deployment id (or 'staging'/'production') of a release JARV made "
        "with its deploy tools.",
        "Data is rolled back by restoring a verified backup into a new database "
        "(restore_backup_with_boundary), which pauses for Richard's approval.",
    ]
    if not containers.get("success"):
        data["limitations"].append(str(containers.get("error")))
    data.update({"services": _data(containers).get("containers", []), "backups_available": backups,
                 "recent_commits": (git_log.get("stdout") or git_log.get("output")) if git_log.get("success") else None})
    text = (f"Rollback of {deployment_id or 'the deployment'} not performed"
            + (f": {data['limitations'][0]}" if environment is not None and data["limitations"] else "")
            + f". {len(backups)} backup(s) available for an approved data restore.")
    return data, text, environment is None, False


async def _infrastructure(toolbox, input_data: Dict[str, Any]):
    operation = str(input_data.get("operation") or "status").strip().lower()
    results: Dict[str, Any] = {}
    for name in ("inspect_server", "check_disk_space", "check_docker_status", "check_database_health",
                 "check_env_vars"):
        results[name] = await _call(toolbox, name)
    approval = False
    if operation in ("backup", "create_backup"):
        created = await _call(toolbox, "create_backup", {"reason": "infrastructure agent: requested backup"})
        results["create_backup"] = created
        if created.get("success"):
            results["verify_backup"] = await _call(toolbox, "verify_backup",
                                                   {"backup_id": created["data"]["backup_id"]})
    elif operation in ("list_backups", "backups"):
        results["list_backups"] = await _call(toolbox, "list_backups")
    elif operation in ("cleanup", "cleanup_backups"):
        results["cleanup_backups"] = await _call(toolbox, "cleanup_backups")
        approval = bool(results["cleanup_backups"].get("requires_approval"))

    measured = {k: v.get("data") for k, v in results.items() if v.get("success")}
    failed = {k: v.get("error") or v.get("reason") for k, v in results.items() if not v.get("success")}
    completed = operation in ("status", "inspect", "check") or (
        operation in ("backup", "create_backup") and bool((measured.get("verify_backup") or {}).get("verified"))
    ) or (operation in ("list_backups", "backups") and "list_backups" in measured) or (
        operation in ("cleanup", "cleanup_backups") and "cleanup_backups" in measured)
    supported = {"status", "inspect", "check", "backup", "create_backup", "list_backups", "backups",
                 "cleanup", "cleanup_backups"}
    limitations = [f"{k}: {v}" for k, v in failed.items() if v]
    if operation not in supported:
        limitations.append(f"'{operation}' (provisioning/scaling cloud resources) needs a cloud provider account "
                           "connected in Settings; measured the current infrastructure instead.")
    data = {
        "operation_completed": bool(completed), "operation": operation, "scanned_path": toolbox.root_host or "",
        "infra_files_found": [], "infra_files_missing": [], "resources_requested": input_data.get("resources") or [],
        "live_integration_connected": "check_docker_status" in measured, "limitations": limitations,
        "recommendations": [], "measurements": measured,
    }
    disks = (measured.get("check_disk_space") or {}).get("over_85_percent") or []
    if disks:
        data["recommendations"].append(f"Free space on {', '.join(disks)} (above 85%).")
    missing = (measured.get("check_env_vars") or {}).get("required_missing") or []
    if missing:
        data["recommendations"].append(f"Set required settings: {', '.join(missing)}.")
    text = (f"Infrastructure {operation}: {'completed' if completed else 'not completed'}; "
            f"{len(measured)} measurement(s), {len(failed)} unavailable.")
    return data, text, bool(completed) or operation not in supported, approval
