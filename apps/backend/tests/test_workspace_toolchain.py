"""
Toolchain for building projects in a workspace (MYCO Phase 0: pnpm, uv, local git).

The classifier lets agents run pnpm and uv, initialise a repository, stage and commit inside the
workspace folder, and still blocks chaining, pushing, resetting and cleaning. Commands that change
the folder they run in are refused without a workspace folder. The worker image carries Node 24 with
Corepack, uv with Python 3.12 to 3.14, Task, Terraform and Helm at build time. The git test runs real git through the real ToolRuntime.
"""
import asyncio
import shutil
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.command.tool_runtime import ToolRuntime
from app.core.workspaces.fs_inspector import SANDBOX_CONTAINER_ROOT, classify_command, needs_workspace

from tests.conftest import AsyncTestingSessionLocal
from tests.repo_paths import repo_path


@pytest.mark.parametrize("command, expected", [
    ("pnpm --version", "safe"),
    ("uv --version", "safe"),
    ("uv python list", "safe"),
    ("git rev-parse HEAD", "safe"),
    ("pnpm install", "install"),
    ("pnpm install --lockfile-only", "install"),
    ("uv lock", "install"),
    ("uv sync", "install"),
    ("uv venv", "install"),
    ("uv tool install semgrep", "install"),
    ("uv python install 3.14", "install"),
    ("uvx osv-scanner --help", "install"),
    ("pnpm dlx create-vite", "install"),
    ("sudo uv tool install semgrep", "dangerous"),
    ("uv tool list", "safe"),
    ("jq --version", "safe"),
    ("pnpm -r test", "build"),
    ("pnpm typecheck", "build"),
    ("uv run pytest", "build"),
    ("git init", "build"),
    ("git add .", "build"),
    ("git add -A", "build"),
    ("git add docs/architecture.md pnpm-workspace.yaml", "build"),
    ('git commit -m "Phase 0: platform skeleton and format rules"', "build"),
    ('git commit -a -m "Confirm the dependency manifest"', "build"),
    ("git add . && rm -rf docs", "dangerous"),
    ("git add a;b", "dangerous"),
    ("git add $(ls)", "dangerous"),
    # Quoted text is data: the commit message is one argument, never a second command.
    ('git commit -m "x; rm -rf /"', "build"),
    ('git commit -m "a" && rm x', "dangerous"),
    ('git commit -m "$(whoami)"', "dangerous"),
    ("git push origin main", "dangerous"),
    ("git reset --hard", "dangerous"),
    ("pnpm add -g left-pad", "dangerous"),
    ("pnpm type-check", "build"),
    ("pnpm format", "build"),
    ("pnpm run e2e", "build"),
    ("yarn lint", "build"),
    ("yarn", "install"),
    ("yarn publish", "risky"),
    ("pnpm publish", "risky"),
    ("pnpm run publish", "risky"),
    ("npm run deploy", "risky"),
    ("pnpm run deploy:prod", "risky"),
    ("pnpm release", "risky"),
    ("pnpm config set registry x", "risky"),
    ("pnpm type-check; rm x", "dangerous"),
    ("task --version", "safe"),
    ("task --list", "safe"),
    ("terraform version", "safe"),
    ("task verify", "build"),
    ("task format", "build"),
    ("task test:unit", "build"),
    ("task phase -- 0", "build"),
    ("task scale:plan -- s1_single_region_horizontal_scale", "build"),
    ("task deploy", "risky"),
    ("task release:prod", "risky"),
    ("terraform validate", "build"),
    ("terraform -chdir=infra/terraform/regions/us-east-1 validate", "build"),
    ("terraform plan -out=plan.bin", "build"),
    ("terraform init -backend=false", "install"),
    ("terraform apply", "dangerous"),
    ("terraform destroy", "dangerous"),
    ("helm lint infra/helm/myco", "build"),
    ("helm template myco infra/helm/myco", "build"),
    ("helm dependency build infra/helm/myco", "install"),
    ("helm install myco infra/helm/myco", "risky"),
    ("git clean -fd", "risky"),
    ("git commit -m 'single quotes'", "build"),
    # Words that merely contain a dangerous command name are not that command.
    ("python -m pytest tests/test_capture.py", "build"),  # "apt" inside "capture"
    ('pytest -k "model "', "build"),  # "del " inside "model "
    ("pnpm test:skill", "build"),  # "kill" inside "skill"
    ('node -e "console.log(1>0)"', "build"),  # ">" inside quotes
    ('git commit -m "Fix: rm stale cp step"', "build"),
    ("cat 'notes and docs.md'", "safe"),
    # The program itself decides, wherever it lives or however it is spelled.
    ("/usr/bin/rm -rf docs", "dangerous"),
    ("rm.exe x", "dangerous"),
    ("RM -rf x", "dangerous"),
    ("chmod +x run.sh", "dangerous"),
    ("curl https://example.com", "dangerous"),
    ("npm install -g x", "dangerous"),
    ("terraform -chdir=infra destroy", "dangerous"),
    ("terraform state rm aws_s3_bucket.x", "dangerous"),
    # Shell syntax outside quotes is refused: one plain command at a time.
    ("echo hi > notes.md", "dangerous"),
    ("ls $HOME", "dangerous"),
    ('echo "$(whoami)"', "dangerous"),
    ("ls 'unterminated", "dangerous"),
    ("ls\nrm x", "dangerous"),
    # Read-only commands with arguments that change something need approval.
    ("find . -name '*.py'", "safe"),
    ("find . -name x -delete", "risky"),
    ("find . -exec rm {} +", "risky"),
    ("git branch", "safe"),
    ("git branch -D main", "risky"),
    ("git remote -v", "safe"),
    ("git remote add origin x", "risky"),
    ("git stash", "risky"),
])
def test_toolchain_commands_are_classified(command, expected):
    assert classify_command(command) == expected


def test_commands_run_as_the_exact_words_that_were_classified(tmp_path):
    from app.core.workspaces.fs_inspector import command_argv, parse_command

    assert parse_command('git commit -m "x; rm -rf /"').argv == ["git", "commit", "-m", "x; rm -rf /"]
    assert parse_command(r'echo "say \"hi\""').argv == ["echo", 'say "hi"']
    assert parse_command("echo a\\ b").argv == ["echo", "a b"]
    for blocked in ("a && b", "a; b", "a | b", "a > b", "a < b", "a &", "echo `id`", "echo $X", "a\nb"):
        assert parse_command(blocked) is None, blocked
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    assert command_argv("ls *.py", str(tmp_path)) == ["ls", "a.py", "b.py"]
    assert command_argv("ls '*.py'", str(tmp_path)) == ["ls", "*.py"]  # quoted patterns stay literal
    assert command_argv("ls *.md", str(tmp_path)) == ["ls", "*.md"]  # no match stays as written


def test_folder_changing_commands_need_a_workspace():
    for command in ("git init", "git add .", 'git commit -m "x"', "pnpm install", "uv sync"):
        assert needs_workspace(command) is True, command
    for command in ("git status", "pnpm --version", "uv run pytest", "pnpm -r test"):
        assert needs_workspace(command) is False, command


async def _runtime(session):
    from app.models.user import User
    from app.models.workspace import Workspace

    uid, wid = uuid4(), uuid4()
    session.add(User(id=uid, username=f"u{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.io",
                     password_hash="$2b$12$x", is_active=True, is_admin=False))
    session.add(Workspace(id=wid, name="Toolchain", slug=f"toolchain-{wid.hex[:8]}", description="d",
                          owner_id=uid, is_active=True, workspace_type="test", authority_level=5))
    await session.commit()
    return ToolRuntime(session, wid, None, operator=str(uid), authority_level=5, user_id=uid)


@pytest.mark.integration
def test_agent_initialises_stages_and_commits_inside_the_workspace(monkeypatch):
    for key, value in (("GIT_AUTHOR_NAME", "JARV"), ("GIT_AUTHOR_EMAIL", "jarv@localhost"),
                       ("GIT_COMMITTER_NAME", "JARV"), ("GIT_COMMITTER_EMAIL", "jarv@localhost")):
        monkeypatch.setenv(key, value)
    name = f"toolchain-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    host = f"/test_workspaces/{name}"

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            outside = await rt.run_command("git init")
            init = await rt.run_command("git init", cwd_host=host)
            write = await rt.write_file(f"{host}/README.md", "# MYCO\n")
            add = await rt.run_command("git add .", cwd_host=host)
            commit = await rt.run_command('git commit -m "Phase 0: platform skeleton"', cwd_host=host)
            push = await rt.run_command("git push origin main", cwd_host=host)
            # A message holding shell syntax is committed as text; nothing else runs.
            await rt.write_file(f"{host}/keep.md", "keep\n")
            await rt.run_command("git add keep.md", cwd_host=host)
            tricky = await rt.run_command('git commit -m "Keep; rm -rf keep.md"', cwd_host=host)
            missing = await rt.run_command("cargo check", cwd_host=host) if not shutil.which("cargo") else None
            return outside, init, write, add, commit, push, tricky, missing

    outside, init, write, add, commit, push, tricky, missing = asyncio.run(run())
    assert tricky["success"] is True, tricky
    assert (folder / "keep.md").exists()
    if missing is not None:
        assert missing["exit_code"] == 127 and "not installed" in missing["reason"]
    assert outside["blocked"] is True and "not inside an approved workspace" in outside["reason"]
    assert init["success"] is True, init
    assert write["success"] is True
    assert add["success"] is True, add
    assert commit["success"] is True, commit
    assert push["success"] is False and push["blocked"] is True
    log = subprocess.run(["git", "log", "--format=%an %s"], cwd=folder, capture_output=True, text=True)
    assert log.stdout.strip().splitlines() == ["JARV Keep; rm -rf keep.md", "JARV Phase 0: platform skeleton"]
    shutil.rmtree(folder, ignore_errors=True)


def test_worker_image_carries_the_build_toolchain():
    dockerfile = repo_path("apps", "backend", "Dockerfile").read_text()
    header = dockerfile.split("\nFROM ", 1)[0]
    runtime = dockerfile.split("# Production stage", 1)[1]
    assert "ARG NODE_IMAGE=node:24.21.0-bookworm-slim" in header  # usable in FROM lines
    assert "ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.17" in header
    assert "FROM ${NODE_IMAGE} AS node" in dockerfile and "FROM ${UV_IMAGE} AS uv" in dockerfile
    assert "COPY --from=node /usr/local/bin/node /usr/local/bin/node" in runtime
    assert "corepack enable --install-directory /usr/local/bin pnpm yarn" in runtime
    assert "npm install -g" not in runtime  # each project's pnpm/yarn version comes from Corepack
    assert "COPY --from=uv /uv /uvx /usr/local/bin/" in runtime
    assert "uv python install 3.12 3.13 3.14" in runtime
    for tool in ("TASK_VERSION=3.52.0", "TERRAFORM_VERSION=1.16.3", "HELM_VERSION=4.3.0"):
        assert f"ARG {tool}" in runtime
    assert runtime.count("sha256sum -c") == 3  # every downloaded binary is checksum-verified
    assert "build-essential" in runtime and "ripgrep" in runtime
    assert "PATH=/home/jarv/.local/bin:$PATH" in runtime
    assert "HOME=/home/jarv" in runtime and "GIT_AUTHOR_NAME=JARV" in runtime
    assert "COREPACK_HOME=/home/jarv/.cache/corepack" in runtime
    assert "    nodejs \\" not in runtime  # the distribution's old Node is not installed


def test_jarv_user_matches_the_workspace_owner():
    dockerfile = repo_path("apps", "backend", "Dockerfile").read_text()
    assert "ARG JARV_UID=1000" in dockerfile and "ARG JARV_GID=1000" in dockerfile
    assert 'useradd -r -m -d /home/jarv -u "${JARV_UID}" -g jarv jarv' in dockerfile
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = repo_path(name).read_text()
        assert compose.count("JARV_UID: ${JARV_UID:-1000}") == 4, name


def test_tool_home_persists_for_backend_and_worker():
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = repo_path(name).read_text()
        assert compose.count("- tool_home:/home/jarv") == 2, name
        assert "\n  tool_home:\n    driver: local\n" in compose, name


@pytest.mark.integration
def test_an_approved_command_runs_exactly_in_its_workspace_folder():
    """Approving a paused command runs that command in the workspace folder, not a new agent mission."""
    from sqlalchemy import select
    from app.core.richard.workflow import COMPLETED, RichardBoundaryWorkflow
    from app.models.boundary import ResumeAction
    from app.models.workspace import Workspace

    name = f"approved-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    host = f"/test_workspaces/{name}"
    subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
    (folder / "stray.txt").write_text("left over")

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            workspace = (await session.execute(
                select(Workspace).where(Workspace.id == rt.workspace_id))).scalar_one()
            workspace.config = {"root_path": host}
            await session.commit()
            paused = await rt.run_command("git clean -n", cwd_host=host)
            workflow = RichardBoundaryWorkflow(session)
            await workflow.record_richard_decision(
                approval_id=UUID(paused["approval_id"]), authenticated_user_id=rt.user_id,
                approve=True, authority_granted=5, expiry_seconds=3600)
            resumed = await workflow.resume_mission(checkpoint_id=UUID(paused["checkpoint_id"]),
                                                    authenticated_user_id=rt.user_id)
            action = (await session.execute(select(ResumeAction).where(
                ResumeAction.checkpoint_id == UUID(paused["checkpoint_id"])))).scalar_one()
            return paused, resumed, action.action_details

    paused, resumed, details = asyncio.run(run())
    assert paused["requires_approval"] is True and paused["boundary_chain_opened"] is True
    assert resumed["resumed"] is True and resumed["status"] == COMPLETED, resumed
    ran = details["ran"][0]
    assert ran["success"] is True
    assert ran["output_preview"].startswith("Ran the approved command `git clean -n` (exit 0)")
    assert "Would remove stray.txt" in ran["output_preview"]
    assert (folder / "stray.txt").exists()  # git clean -n only lists; nothing was removed
    shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.integration
def test_an_approved_command_needs_a_workspace_folder():
    from app.core.richard.workflow import RichardBoundaryWorkflow

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            paused = await rt.run_command("git clean -n")
            workflow = RichardBoundaryWorkflow(session)
            await workflow.record_richard_decision(
                approval_id=UUID(paused["approval_id"]), authenticated_user_id=rt.user_id,
                approve=True, authority_granted=5, expiry_seconds=3600)
            return await workflow.resume_mission(checkpoint_id=UUID(paused["checkpoint_id"]),
                                                 authenticated_user_id=rt.user_id)

    resumed = asyncio.run(run())
    assert resumed["resumed"] is False
    assert "no folder" in str(resumed)


def test_the_planner_keeps_normal_work_away_from_richard():
    from app.agents import orchestrator

    source = Path(orchestrator.__file__).read_text()
    assert "true for any task that modifies files" not in source
    assert "Writing and editing files, installing" in source


@pytest.mark.integration
def test_an_approved_command_runs_in_the_folder_it_was_paused_in():
    """A mission works in its own folder (MYCO) while its task belongs to another workspace. Approving a paused
    command ran nothing ("the workspace has no folder"); the folder is now kept with the checkpoint."""
    from app.core.richard.workflow import COMPLETED, RichardBoundaryWorkflow

    name = f"mission-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    host = f"/test_workspaces/{name}"
    subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
    (folder / "notes.txt").write_text("x")

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)  # its workspace has no folder
            paused = await rt.run_command("git clean -n", cwd_host=host)
            workflow = RichardBoundaryWorkflow(session)
            await workflow.record_richard_decision(
                approval_id=UUID(paused["approval_id"]), authenticated_user_id=rt.user_id,
                approve=True, authority_granted=5, expiry_seconds=3600)
            return await workflow.resume_mission(checkpoint_id=UUID(paused["checkpoint_id"]),
                                                 authenticated_user_id=rt.user_id)

    resumed = asyncio.run(run())
    assert resumed["status"] == COMPLETED, resumed
    assert "Would remove notes.txt" in resumed["ran"][0]["output_preview"]
    shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.integration
def test_a_failed_approved_command_does_not_overwrite_a_running_mission():
    from sqlalchemy import select
    from app.core.richard.workflow import RichardBoundaryWorkflow
    from app.models.task import Task

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            mission = Task(id=uuid4(), title="Finish MYCO Phase 0", description="d", workspace_id=rt.workspace_id,
                           status="pending", priority=5, task_type="agent_task")
            session.add(mission)
            await session.commit()
            rt.task_id = mission.id
            paused = await rt.run_command("git clean -n")  # no folder anywhere: the approved run fails
            row = (await session.execute(select(Task).where(Task.id == mission.id))).scalar_one()
            row.status = "running"  # the mission's agent loop carried on and is still working
            await session.commit()
            workflow = RichardBoundaryWorkflow(session)
            await workflow.record_richard_decision(
                approval_id=UUID(paused["approval_id"]), authenticated_user_id=rt.user_id,
                approve=True, authority_granted=5, expiry_seconds=3600)
            resumed = await workflow.resume_mission(checkpoint_id=UUID(paused["checkpoint_id"]),
                                                    authenticated_user_id=rt.user_id)
            status = (await session.execute(select(Task.status).where(Task.id == mission.id))).scalar_one()
            return resumed, status

    resumed, status = asyncio.run(run())
    assert resumed["resumed"] is False
    assert status == "running"


def test_read_only_git_commands_never_need_approval():
    for command in ("git ls-files", "git ls-tree HEAD", "git describe --tags", "git check-ignore dist",
                    "git show HEAD", "git grep SERVICE_NAME", "git blame README.md", "git tag -l"):
        assert classify_command(command) == "safe", command


@pytest.mark.integration
def test_env_templates_are_project_files_and_real_env_files_stay_protected():
    """Phase 0 asks for .env.example (setting names only); JARV refused to write it as a secret file."""
    name = f"envtpl-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    host = f"/test_workspaces/{name}"

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            template = await rt.write_file(f"{host}/.env.example", "DATABASE_URL=\nANTHROPIC_API_KEY=\n")
            read = await rt.read_file(f"{host}/.env.example")
            real = await rt.write_file(f"{host}/.env", "DATABASE_URL=\n")
            leaked = await rt.write_file(f"{host}/.env.sample", "OPENAI_API_KEY=sk-REPAIR10SECRETKEY1234567890\n")
            return template, read, real, leaked

    template, read, real, leaked = asyncio.run(run())
    assert template["success"] is True, template
    assert "ANTHROPIC_API_KEY=" in read["data"]["content"]
    assert real["success"] is False
    assert leaked["success"] is False and not (folder / ".env.sample").exists()
    shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.integration
def test_a_paused_command_leaves_its_running_mission_running():
    """The V3.2 Phase 0 mission paused "task --version" for approval; that put the whole mission into
    waiting_on_approval while its agent kept working, the approval then marked it completed, and the agent's
    own end ("needs_continuation") was refused as an illegal transition, so the mission stopped after one round.
    A mission's agent loop now pauses only the blocked action."""
    from sqlalchemy import select
    from app.core.command.agent_executor import AgentExecutor
    from app.core.richard.workflow import RichardBoundaryWorkflow
    from app.models.boundary import BoundaryApproval
    from app.models.task import Task

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            mission = Task(id=uuid4(), title="Rebuild MYCO Phase 0", description="d", workspace_id=rt.workspace_id,
                           status="running", priority=5, task_type="command")
            session.add(mission)
            await session.commit()
            rt.task_id = mission.id
            AgentExecutor(rt, "test-model", None)  # the mission's agent loop takes the runtime
            paused = await rt.run_command("git clean -n")
            approval = (await session.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(paused["approval_id"])))).scalar_one()
            approval_status = approval.status  # read now: the decision below updates this same row
            status_while_waiting = (await session.execute(
                select(Task.status).where(Task.id == mission.id))).scalar_one()
            workflow = RichardBoundaryWorkflow(session)
            await workflow.record_richard_decision(approval_id=approval.id, authenticated_user_id=rt.user_id,
                                                   approve=True, authority_granted=5, expiry_seconds=3600)
            await workflow.resume_mission(checkpoint_id=UUID(paused["checkpoint_id"]),
                                          authenticated_user_id=rt.user_id)
            status_after_resume = (await session.execute(
                select(Task.status).where(Task.id == mission.id))).scalar_one()
            return rt.pause_task_on_boundary, paused, approval_status, status_while_waiting, status_after_resume

    pause, paused, approval_status, while_waiting, after_resume = asyncio.run(run())
    assert pause is False
    assert paused["requires_approval"] is True and paused["boundary_chain_opened"] is True
    assert approval_status == "pending"
    assert while_waiting == "running"
    assert after_resume == "running"


@pytest.mark.integration
def test_a_paused_command_outside_a_mission_still_pauses_its_task():
    from sqlalchemy import select
    from app.models.task import Task

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            task = Task(id=uuid4(), title="One command", description="d", workspace_id=rt.workspace_id,
                        status="running", priority=5, task_type="command")
            session.add(task)
            await session.commit()
            rt.task_id = task.id
            await rt.run_command("git clean -n")
            return (await session.execute(select(Task.status).where(Task.id == task.id))).scalar_one()

    assert asyncio.run(run()) == "waiting_on_approval"


def test_a_continuation_round_knows_what_earlier_rounds_did():
    """A long mission (V3.2 Phase 0) wrote its phase contract and about 30 files, reached its step limit, and the
    next round started a new conversation with only the request: it found files it did not recognise, ran
    nothing and reported the mission unverifiable. The next round now gets the earlier rounds' work."""
    from app.core.command.continuation import progress_note

    result = {
        "response": "Wrote docs/phases/PHASE-00.md and config/regions/regions.yaml; Taskfile next.",
        "tool_calls": [
            {"tool": "write_file", "inputs": {"path": "C:\\\\Users\\\\lilri\\\\Projects\\\\MYCO\\\\docs\\\\phases\\\\PHASE-00.md"},
             "success": True},
            {"tool": "write_file", "inputs": {"path": "config/regions/regions.yaml"}, "success": True},
            {"tool": "write_file", "inputs": {"path": ".env"}, "success": False},
            {"tool": "run_command", "inputs": {"command": "pnpm install"}, "success": True, "output": {"exit_code": 0}},
            {"tool": "run_command", "inputs": {"command": "task verify"}, "success": False, "output": {"exit_code": 201}},
            {"tool": "read_file", "inputs": {"path": "MYCO_V3_SPEC.md"}, "success": True},
        ],
    }
    note = progress_note(result)
    assert note.startswith("PROGRESS FROM EARLIER ROUNDS OF THIS SAME MISSION")
    assert "PHASE-00.md" in note and "config/regions/regions.yaml" in note
    assert ".env (write failed)" in note
    assert "`pnpm install`: exit 0" in note and "`task verify`: exit 201" in note
    assert "Taskfile next." in note
    assert "Do not redo finished work" in note
    assert progress_note({}) == ""


def test_finish_must_say_whether_the_mission_succeeded():
    """The same round finished with "Phase 0 exit gate is NOT PASSED" and no success flag, and the missing flag
    counted as success, so the mission showed COMPLETED. The finish tool now requires it."""
    from app.core.command.agent_executor import _tool_schemas

    finish = next(t for t in _tool_schemas() if t["name"] == "finish")
    assert finish["input_schema"]["required"] == ["summary", "success"]


class _MissionRouter:
    """Scripted model: the mission's turns, then the independent check's turns, told apart by the system prompt."""

    def __init__(self, mission_turns, verifier_turns):
        self.turns = {"mission": list(mission_turns), "verifier": list(verifier_turns)}
        self.offered = {"mission": [], "verifier": []}
        self.first_message = {}

    async def complete(self, request):
        import json as _json
        from app.core.providers import CompletionResponse

        who = "verifier" if (request.system or "").startswith("You are JARV's Verifier Agent") else "mission"
        self.offered[who].append(sorted(t["name"] for t in request.tools or []))
        self.first_message.setdefault(who, request.messages[0].content)
        turn = self.turns[who].pop(0) if self.turns[who] else {"content": "done"}
        calls = [{"id": f"{who}-{len(self.offered[who])}-{i}", "type": "function",
                  "function": {"name": name, "arguments": _json.dumps(args)}}
                 for i, (name, args) in enumerate(turn.get("tools", []))]
        return CompletionResponse(id="r", model="test", content=turn.get("content", ""),
                                  usage={"total_tokens": 10}, tool_calls=calls)


def _mission_turns():
    return [
        {"tools": [("search_files", {"contains": "def add"})]},
        {"tools": [("edit_file", {"path": "src/app.py", "old_text": "return a + b\n",
                                  "new_text": "return a + b\n\n\ndef sub(a, b):\n    return a - b\n"})]},
        {"tools": [("run_command", {"command": "python3 -m py_compile src/app.py"})]},
        {"tools": [("memory_add", {"content": "MYCO src/app.py now has add and sub.", "memory_type": "decision"})]},
        {"tools": [("finish", {"summary": "Added sub(a, b) and a test; compiled cleanly.", "success": True})]},
    ]


async def _mission_workspace(session, host):
    from app.models.task import Task
    from app.models.user import User
    from app.models.workspace import Workspace

    uid, wid = uuid4(), uuid4()
    session.add(User(id=uid, username=f"u{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.io",
                     password_hash="$2b$12$x", is_active=True, is_admin=False))
    session.add(Workspace(id=wid, name="MYCO", slug=f"myco-{wid.hex[:8]}", description="d", owner_id=uid,
                          is_active=True, workspace_type="software", authority_level=4,
                          config={"root_path": host}))
    mission = Task(id=uuid4(), title="Add sub", description="d", workspace_id=wid, status="running",
                   priority=5, task_type="command")
    session.add(mission)
    await session.commit()
    return ToolRuntime(session, wid, mission.id, operator=str(uid), authority_level=4, user_id=uid)


def _mission_folder():
    name = f"mission-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n")
    return f"/test_workspaces/{name}", folder


@pytest.mark.integration
@pytest.mark.parametrize("verdict, expect_done", [
    ({"verified": False, "unmet": ["The mission asks for a test of sub(); tests/test_app.py does not exist."],
      "checks": [{"requirement": "sub(a, b) in src/app.py", "met": True, "evidence": "read src/app.py"},
                 {"requirement": "a test for sub", "met": False, "evidence": "no tests/ folder"}]}, False),
    ({"verified": True, "unmet": [],
      "checks": [{"requirement": "sub(a, b) in src/app.py", "met": True, "evidence": "read src/app.py"}]}, True),
])
def test_missions_use_every_tool_and_never_accept_themselves(monkeypatch, verdict, expect_done):
    """MYCO Phase 0 was marked complete on the agent's own word while its Taskfile commands only printed that they
    passed. A mission now works with the full toolbox (search, edit, memory, specialist knowledge, delete and push
    through approval) and, when it says it is done, a Verifier that did not do the work checks the workspace with
    look-and-test tools only. An unmet requirement sends the mission on to fix it, with the findings."""
    from app.core.command import agent_executor
    from app.core.command.agent_executor import AgentExecutor

    host, folder = _mission_folder()
    router = _MissionRouter(_mission_turns(), [
        {"tools": [("read_file", {"path": "src/app.py"})]},
        {"tools": [("verdict", verdict)]},
    ])
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            executor = AgentExecutor(rt, "test-model", host)
            result = await executor.run("Add sub(a, b) to src/app.py with a test.",
                                        known="- Memory (decision): Richard wants a test for every function.")
            return result, [c["tool"] for c in rt.calls]

    result, mission_tools = asyncio.run(run())
    offered = router.offered["mission"][0]
    for tool in ("search_files", "edit_file", "memory_add", "memory_search", "delete_file_with_boundary",
                 "git_push_with_boundary", "detect_commands", "check_cve", "run_tests", "finish"):
        assert tool in offered, tool
    assert "Richard wants a test for every function." in router.first_message["mission"]
    verifier_tools = router.offered["verifier"][0]
    assert "verdict" in verifier_tools and "read_file" in verifier_tools and "run_tests" in verifier_tools
    for tool in ("write_file", "edit_file", "delete_file_with_boundary", "git_push_with_boundary",
                 "install_package", "memory_add", "move_file"):
        assert tool not in verifier_tools, tool
    assert "Added sub(a, b)" in router.first_message["verifier"]  # the claim, given to check, not to trust
    assert "def sub(a, b)" in (folder / "src" / "app.py").read_text()
    assert "read_file" not in mission_tools  # the verifier's reads are on its own runtime, not the mission's
    assert result["finished"] is True
    assert result["success"] is expect_done
    assert result["needs_continuation"] is (not expect_done)
    assert result["step_limit_reached"] is False
    assert result["verification"]["verified"] is expect_done
    if not expect_done:
        assert "tests/test_app.py does not exist" in result["answer"]
        assert any("a test for sub" in item for item in result["verification"]["unmet"])
    shutil.rmtree(folder, ignore_errors=True)


def test_the_next_round_is_told_what_the_check_found():
    from app.core.command.continuation import progress_note

    note = progress_note({"response": "Added sub.", "verification": {
        "verified": False, "unmet": ["Taskfile `verify` only echoes; it runs no checks."]}})
    assert "INDEPENDENT CHECK FOUND" in note and "only echoes" in note


@pytest.mark.integration
def test_a_verdict_without_evidence_is_not_a_pass(monkeypatch):
    from app.core.command import agent_executor
    from app.core.command.agent_executor import AgentExecutor

    host, folder = _mission_folder()
    router = _MissionRouter([{"tools": [("finish", {"summary": "Done.", "success": True})]}],
                            [{"tools": [("verdict", {"verified": True, "unmet": [], "checks": []})]}])
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            return await AgentExecutor(rt, "test-model", host).run("Add sub(a, b) to src/app.py.")

    result = asyncio.run(run())
    assert result["success"] is False and result["verification"]["verified"] is False
    shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.integration
def test_an_approved_delete_from_a_mission_deletes_exactly_that_file():
    """A mission asks to delete one file; it waits for Richard; once approved, that exact file goes and nothing else."""
    from sqlalchemy import select
    from app.core.command.agent_executor import mission_toolbox
    from app.core.richard.workflow import RichardBoundaryWorkflow
    from app.models.boundary import BoundaryApproval

    host, folder = _mission_folder()
    (folder / "old.md").write_text("stale\n")

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            rt.pause_task_on_boundary = False
            toolbox = mission_toolbox(rt, host)
            await toolbox.prepare()
            paused = await toolbox.call("delete_file_with_boundary", {"path": "old.md", "reason": "superseded"})
            still_there = (folder / "old.md").exists()
            approval = (await session.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(paused["approval_id"])))).scalar_one()
            workflow = RichardBoundaryWorkflow(session)
            await workflow.record_richard_decision(approval_id=approval.id, authenticated_user_id=rt.user_id,
                                                   approve=True, authority_granted=4, expiry_seconds=3600)
            resumed = await workflow.resume_mission(checkpoint_id=UUID(paused["checkpoint_id"]),
                                                    authenticated_user_id=rt.user_id)
            return paused, still_there, resumed

    paused, still_there, resumed = asyncio.run(run())
    assert paused["requires_approval"] is True and still_there is True
    assert not (folder / "old.md").exists(), resumed
    assert (folder / "src" / "app.py").exists()
    shutil.rmtree(folder, ignore_errors=True)


def test_long_missions_trim_old_results_and_keep_the_newest():
    """A long mission re-sent every earlier file read on every step (about 2.6 million tokens a round). Old tool
    results are now cut to a short head once the conversation is large; the newest stay whole, and tool calls
    and their pairing are untouched."""
    from app.core.command.agent_executor import compact_messages
    from app.core.providers import Message

    messages = [Message(role="user", content="MISSION: rebuild Phase 0")]
    for i in range(12):
        messages.append(Message(role="assistant", content=[
            {"type": "tool_use", "id": f"t{i}", "name": "read_file", "input": {"path": f"docs/part{i}.md"}}]))
        messages.append(Message(role="user", content=[
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": f"part {i} " + "x" * 30000}]))
    assert compact_messages(messages, budget=10_000_000) == 0  # under budget: nothing changes
    removed = compact_messages(messages, budget=100_000, keep_recent=4)
    results = [m.content[0]["content"] for m in messages if m.role == "user" and isinstance(m.content, list)]
    assert removed > 200_000
    assert all("[earlier result cut" in r and "read_file docs/part" in r for r in results[:8])
    assert all(len(r) > 30000 for r in results[8:])
    assert results[0].startswith("part 0 ")
    assert compact_messages(messages, budget=100_000, keep_recent=4) == 0  # already cut: stable prefix
    assert [m.content[0]["id"] for m in messages if m.role == "assistant"] == [f"t{i}" for i in range(12)]


def test_claude_requests_mark_the_repeated_prefix_for_the_prompt_cache():
    from app.core.providers.base import CompletionRequest, Message
    from app.core.providers.claude import ClaudeProvider, _usage

    provider = object.__new__(ClaudeProvider)
    request = CompletionRequest(model="claude-sonnet-4-6", system="You are JARV.", max_tokens=100, messages=[
        Message(role="user", content="MISSION"),
        Message(role="assistant", content=[{"type": "tool_use", "id": "a", "name": "read_file", "input": {}}]),
        Message(role="user", content=[{"type": "tool_result", "tool_use_id": "a", "content": "text"}])],
        tools=[{"name": "read_file", "description": "d", "input_schema": {"type": "object", "properties": {}}},
               {"name": "finish", "description": "d", "input_schema": {"type": "object", "properties": {}}}])
    payload = provider._convert_request(request)
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert payload["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert payload["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in request.messages[-1].content[-1]  # the mission's own record is unchanged
    assert _usage({"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 900})["total_tokens"] == 915
