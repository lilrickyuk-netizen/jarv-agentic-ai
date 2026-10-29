"""
JARV Backend - Specialist tool mode (Repair 12c)

How each engineering specialist works a task through its toolbox. Every agent
listed here runs its tool loop whenever a model provider is configured and the
task has a database session and a workspace (``AgentBase.tools_enabled``).
Without a provider, the agent's local analysis path runs instead and says so.

Each entry gives the agent its tools (confined to the mission's workspace; see
``app.core.agents.toolbox``), the standing instructions for its role, and how
its structured input becomes the task brief.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

# Registry names. The toolbox maps file/command names onto the workspace-confined
# tools (file_read -> read_file, command_run -> run_command, ...); see toolbox.ALIASES.
READ = ["file_list", "file_read", "file_search"]
GIT_READ = ["git_status", "git_diff", "git_log"]
RECALL = ["memory_search"]
REMEMBER = ["memory_store"]  # authority 6; experience is also captured automatically after every run
DEPLOY = ["check_deploy_target", "deploy_staging", "deploy_production_with_boundary", "deployment_status",
          "deployment_logs", "rollback"]


def _lines(pairs: List[tuple]) -> str:
    return "\n".join(f"{label}: {value}" for label, value in pairs if value not in (None, "", [], {}))


@dataclass(frozen=True)
class ToolMode:
    tools: List[str]
    instructions: str
    brief: Callable[[Dict[str, Any]], str]
    max_steps: int = 16


MODES: Dict[str, ToolMode] = {
    "coding_agent": ToolMode(
        tools=READ + ["file_write", "edit_file", "create_folder", "move_file", "copy_file",
                      "delete_file_with_boundary", "command_run", "run_build", "run_tests", "check_installed",
                      "detect_commands", "detect_stack", "git_create_branch"] + GIT_READ
        + ["analyze_code", "analyze_complexity", "analyze_dependencies"] + RECALL,
        instructions=(
            "Implement the change in the workspace. Read the relevant code first and follow the project's "
            "existing conventions. Use edit_file for targeted changes and write_file for new files. After "
            "writing, verify with run_build and run_tests (they use the project's own commands). Fix what fails. Check memory_search "
            "for earlier decisions about this code. Your finish outputs list every file you wrote."),
        brief=lambda d: _lines([("Task", d.get("task")), ("Language", d.get("language")),
                                ("Requirements", d.get("requirements")),
                                ("Files to change", ", ".join(d.get("files") or [])),
                                ("Context", d.get("context"))]),
        max_steps=24,
    ),
    "debugging_agent": ToolMode(
        tools=READ + ["file_write", "edit_file", "command_run", "run_tests", "run_build", "get_command_log",
                      "detect_commands"] + GIT_READ + ["analyze_code"] + RECALL,
        instructions=(
            "Find the root cause before changing anything: reproduce the failure with run_command when "
            "possible, read the code on the failing path, and check recent changes with git_diff/git_log. "
            "Then make the smallest fix, re-run the reproduction to prove it passes, and run the tests. "
            "State the root cause, the evidence, and the fix in your finish summary; it is kept as an "
            "experience record so the lesson is reused."),
        brief=lambda d: _lines([("Error", d.get("error_message")), ("Stack trace", d.get("stack_trace")),
                                ("Affected files", ", ".join(d.get("affected_files") or [])),
                                ("Reproduction", d.get("reproduction_steps")), ("Context", d.get("context"))]),
        max_steps=24,
    ),
    "verifier": ToolMode(
        tools=READ + ["command_run", "run_tests", "run_build", "detect_commands"] + GIT_READ
        + ["analyze_code", "analyze_coverage", "analyze_security"] + RECALL,
        instructions=(
            "Verify independently; do not trust claims. Inspect the code, run the relevant tests and builds, "
            "and check each stated requirement against evidence from a tool result. You must not modify "
            "files. finish success=true only if every check passed; list each check and its result in "
            "outputs as 'PASS: ...' or 'FAIL: ...'."),
        brief=lambda d: _lines([("What to verify", d.get("code_to_verify")),
                                ("Test files", ", ".join(d.get("test_files") or [])),
                                ("Quality standards", d.get("quality_standards"))]),
        max_steps=16,
    ),
    "qa": ToolMode(
        tools=READ + ["command_run", "run_tests", "run_build", "detect_commands", "find_missing_files"] + GIT_READ
        + ["analyze_code", "analyze_coverage"] + RECALL,
        instructions=(
            "Plan the checks for this QA type, then run them: compile/type-check, the test suite, the build, "
            "and targeted checks of edge cases you can exercise with commands. Do not modify source files. "
            "Report each check as 'PASS: ...' or 'FAIL: ...' in outputs, with the command used."),
        brief=lambda d: _lines([("QA type", d.get("test_type")),
                                ("Targets", ", ".join(d.get("target_files") or [])),
                                ("Test plan", d.get("test_plan")), ("Suggested test command", d.get("test_command"))]),
        max_steps=16,
    ),
    "documentation": ToolMode(
        tools=READ + ["file_write", "edit_file", "find_missing_files", "detect_stack", "detect_commands"]
        + GIT_READ + ["analyze_code", "analyze_architecture"] + RECALL,
        instructions=(
            "Read the code and existing docs before writing. Document what the code actually does: commands, "
            "configuration, endpoints and examples must come from the source you read, not from assumption. "
            "Write the documentation into the workspace (e.g. README.md or docs/). List files written in outputs."),
        brief=lambda d: _lines([("Document", d.get("target")), ("Type", d.get("doc_type")),
                                ("Format", d.get("format")),
                                ("Existing files", ", ".join(d.get("existing_files") or []))]),
        max_steps=16,
    ),
    "devops": ToolMode(
        tools=READ + ["file_write", "edit_file", "command_run", "run_build", "run_tests", "install_package",
                      "check_installed", "detect_commands", "detect_stack", "git_create_branch",
                      "git_push_with_boundary"] + GIT_READ + ["analyze_dependencies"] + RECALL + REMEMBER
        + DEPLOY,
        instructions=(
            "Prepare and run the operation inside the workspace: inspect Dockerfiles, compose files, CI "
            "configuration and scripts; run builds and tests; prepare deployment configuration. To release: "
            "check_deploy_target, then deploy_staging and confirm it with deployment_status and the health "
            "result, then deploy_production_with_boundary, which pauses for Richard's approval; attempt it "
            "once so the approval request is created and continue with whatever does not depend on it. "
            "Only committed code deploys. If a release misbehaves, use rollback with the reason. Pushes and "
            "anything that spends money also pause for approval."),
        brief=lambda d: _lines([("Operation", d.get("operation")), ("Environment", d.get("environment")),
                                ("Configuration", d.get("config"))]),
        max_steps=20,
    ),
    "security": ToolMode(
        tools=READ + ["command_run"] + GIT_READ + ["analyze_security", "analyze_dependencies", "analyze_code"]
        + RECALL + REMEMBER,
        instructions=(
            "Review the targets for real vulnerabilities: injection, authentication and authorization gaps, "
            "secrets in code, unsafe deserialization, path traversal, SSRF, and vulnerable dependencies "
            "(analyze_dependencies, and the lock files). Do not modify files. Each finding in outputs: "
            "severity, file:line, issue, evidence, fix. Never print a secret's value; name the file and line."),
        brief=lambda d: _lines([("Scan type", d.get("scan_type")),
                                ("Targets", ", ".join(d.get("targets") or []) or "the whole workspace"),
                                ("Report findings at or above", d.get("severity_threshold"))]),
        max_steps=20,
    ),
}


async def run(agent: Any, input_data: Dict[str, Any], context: Any):
    """Run ``agent`` in tool mode and return its AgentResult."""
    mode = MODES[agent.name]
    brief = mode.brief(input_data) or str(input_data)
    outcome = await agent.use_tools(context, brief, instructions=mode.instructions, max_steps=mode.max_steps)
    return agent.result_from_tools(outcome, mode="tools")


def tools_for(agent_name: str) -> List[str]:
    return list(MODES[agent_name].tools)
