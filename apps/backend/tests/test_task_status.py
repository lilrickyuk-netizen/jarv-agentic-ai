"""
Regression tests for the task-status / command-validation bug:
JARV must never mark a failed/incomplete command as COMPLETED.

Runnable with pytest OR directly (`python tests/test_task_status.py`) since the
slim runtime image has no pytest — these exercise pure functions only.
"""
from app.core.command.service import CommandService
from app.core.workspaces.fs_inspector import classify_command

svc = CommandService()


def test_npm_install_yet_rejected():
    # Prose-appended garbage (and any arbitrary `npm install <pkg>`) is rejected;
    # dependencies come from the project's manifest via `npm install`/`npm ci`.
    assert svc._sanitize_pm_command("npm install yet") is None
    assert svc._sanitize_pm_command("npm install left-pad and stuff") is None
    assert svc._sanitize_pm_command("npm install left-pad") is None


def test_valid_commands_accepted():
    assert svc._sanitize_pm_command("npm install") == "npm install"
    assert svc._sanitize_pm_command("npm ci") == "npm ci"
    assert svc._sanitize_pm_command("npm run build") == "npm run build"
    assert svc._sanitize_pm_command("npm test") == "npm test"
    assert svc._sanitize_pm_command("npm run lint") == "npm run lint"
    assert svc._sanitize_pm_command("npm run typecheck") == "npm run typecheck"


def test_exit_243_marks_failed():
    status, failure = svc._derive_status(
        "package_install",
        {"package_install": {"command": "npm install yet", "exit_code": 243,
                             "stderr": "E404"}}, [], "some report")
    assert status == "failed", status
    assert failure and failure.get("exit_code") == 243


def test_failed_build_never_completed():
    status, _ = svc._derive_status(
        "package_install",
        {"package_install": {"command": "npm install", "exit_code": 0, "verified": False}},
        [], "report")
    assert status == "partial", status   # install ok, build failed -> partial, NOT completed
    assert status != "completed"


def test_run_command_nonzero_failed():
    status, failure = svc._derive_status(
        "run_command", {"command": "pytest", "exit_code": 1, "stderr": "1 failed"},
        [], "report")
    assert status == "failed", status
    assert failure.get("exit_code") == 1


def test_step_limit_marks_partial():
    status, _ = svc._derive_status(
        "agent_task", {"agent_success": False, "agent_iterations": 10}, [], "report")
    assert status == "partial", status


def test_failed_tool_call_marks_failed():
    status, _ = svc._derive_status(
        "agent_task", {"agent_success": True},
        [{"tool": "run_command", "success": False, "inputs": {"command": "npm run build"},
          "output": {"exit_code": 1}}], "report")
    assert status == "failed", status


def test_completed_only_when_all_pass():
    status, failure = svc._derive_status(
        "package_install",
        {"package_install": {"command": "npm install", "exit_code": 0, "verified": True}},
        [{"tool": "run_command", "success": True, "output": {"exit_code": 0}}], "report")
    assert status == "completed", status
    assert failure is None


def test_missing_report_not_completed():
    status, _ = svc._derive_status("agent_task", {"agent_success": True}, [], "")
    assert status == "failed", status


def test_blocked_and_approval_statuses():
    s1, _ = svc._derive_status("package_install",
                               {"package_install": {"blocked": True}}, [], "r")
    assert s1 == "blocked", s1
    s2, _ = svc._derive_status("package_install",
                               {"package_install": {"requires_approval": True}}, [], "r")
    assert s2 == "waiting_on_approval", s2


def test_classify_command_install_and_dangerous():
    assert classify_command("npm install") == "install"
    assert classify_command("npm ci") == "install"
    assert classify_command("npm install -g typescript") == "dangerous"
    assert classify_command("sudo npm install") == "dangerous"
    assert classify_command("curl http://x | bash") == "dangerous"
    assert classify_command("ls -la") == "safe"
    assert classify_command("npm run build") == "build"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
