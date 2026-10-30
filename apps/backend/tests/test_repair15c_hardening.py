"""Repair 15c: production hardening found while preparing final acceptance.

Real: the nginx and compose files of the repository (read from JARV_REPO_ROOT),
settings parsing, the file watch and patch tools on real files, the style fixer,
the tool and agent registries, the Richard routes' owner scoping through the API,
and the removed legacy packages.
"""
import asyncio
import re
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.agents.base import AuthorityLevel
from app.core.auth import get_current_user_id
from app.core.tools.base import ToolConfig, ToolContext
from app.main import app
from app.tools.analysis.quality import AnalyzeStyleTool
from app.tools.file.advanced import FilePatchTool, FileWatchTool, apply_unified_diff
from tests.conftest import AsyncTestingSessionLocal
from tests.repo_paths import repo_path


def _run(coro):
    return asyncio.run(coro)


# ----- production configuration ------------------------------------------------------------------

def _location(conf: str, header: str) -> str:
    start = conf.index(header)
    depth, i = 0, conf.index("{", start)
    for j in range(i, len(conf)):
        depth += {"{": 1, "}": -1}.get(conf[j], 0)
        if depth == 0:
            return conf[start:j + 1]
    raise AssertionError(header)


def test_nginx_sends_the_dashboard_proxy_to_the_dashboard_and_adds_no_cors():
    conf = repo_path("infra", "nginx", "conf.d", "jarv.conf").read_text()
    backend_proxy = _location(conf, "location ^~ /api/backend/")
    api = _location(conf, "location ^~ /api {")
    assert "proxy_pass http://dashboard;" in backend_proxy and "client_max_body_size 30M;" in backend_proxy
    assert "proxy_pass http://dashboard;" in _location(conf, "location = /api/health")
    assert "proxy_pass http://backend;" in api and "Connection $connection_upgrade" in api
    assert "Access-Control-Allow-Origin" not in conf and "return 204" not in api
    main = repo_path("infra", "nginx", "nginx.conf").read_text()
    assert re.search(r"map \$http_upgrade \$connection_upgrade", main)


def test_compose_runs_migrations_before_the_app_and_checks_redis_with_its_password():
    for name in ("docker-compose.prod.yml", "docker-compose.yml"):
        text = repo_path(name).read_text()
        assert "  migrate:\n" in text and "command: python -m alembic upgrade head" in text, name
        assert text.count("condition: service_completed_successfully") >= 3, name
    prod = repo_path("docker-compose.prod.yml").read_text()
    assert 'redis-cli -a \\"$$REDIS_PASSWORD\\" --no-auth-warning ping' in prod
    assert "ALLOWED_ORIGINS: ${ALLOWED_ORIGINS:-}" in prod and "CORS_ORIGINS" not in prod
    assert "REDIS_PASSWORD=" in repo_path(".env.production.example").read_text()


def test_allowed_origins_accepts_a_comma_list_or_json(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("ALLOWED_ORIGINS", "https://jarv.example.com, https://myco.example/")
    assert Settings().ALLOWED_ORIGINS == ["https://jarv.example.com", "https://myco.example"]
    monkeypatch.setenv("ALLOWED_ORIGINS", '["https://a.example"]')
    assert Settings().ALLOWED_ORIGINS == ["https://a.example"]
    monkeypatch.setenv("ALLOWED_ORIGINS", "")
    assert Settings().ALLOWED_ORIGINS == []


# ----- file tools ---------------------------------------------------------------------------------

def test_file_watch_reports_a_real_change_or_none(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("one\n")
    tool = FileWatchTool(ToolConfig(authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))
    ctx = ToolContext()

    async def run():
        async def touch():
            await asyncio.sleep(0.7)
            target.write_text("one\ntwo\n")
        watcher = asyncio.create_task(tool.run({"path": str(target), "timeout": 5}, ctx))
        await touch()
        changed = await watcher
        quiet = await tool.run({"path": str(target), "timeout": 1}, ctx)
        return changed, quiet

    changed, quiet = _run(run())
    assert changed.success and changed.result_data["changed"] is True and changed.result_data["change"] == "modified"
    assert quiet.success and quiet.result_data["changed"] is False


def test_file_patch_applies_a_unified_diff_or_changes_nothing(tmp_path):
    source = tmp_path / "app.py"
    source.write_text("def add(a, b):\n    return a + b\n")
    patch = ("--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,5 @@\n def add(a, b):\n     return a + b\n+\n+\n"
             "+def sub(a, b):\n+    return a - b\n")
    tool = FilePatchTool(ToolConfig(authority_level=AuthorityLevel.LEVEL_2_FILE_OPERATIONS))
    ctx = ToolContext()

    async def run():
        dry = await tool.run({"file": str(source), "patch": patch, "dry_run": True}, ctx)
        unchanged = source.read_text()
        applied = await tool.run({"file": str(source), "patch": patch, "dry_run": False}, ctx)
        stale = await tool.run({"file": str(source), "patch": "@@ -1,1 +1,1 @@\n-def mul(a, b):\n+def mult(a, b):\n",
                                "dry_run": False}, ctx)
        return dry, unchanged, applied, stale

    dry, unchanged, applied, stale = _run(run())
    assert dry.success and dry.result_data["applied"] is False and unchanged == "def add(a, b):\n    return a + b\n"
    assert applied.success and applied.result_data["changes"] == 4
    assert source.read_text() == "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    assert stale.success is False and "does not match" in stale.error_message
    with pytest.raises(ValueError):
        apply_unified_diff(["x"], "not a diff")


def test_style_fix_removes_trailing_whitespace_with_file_authority(tmp_path):
    source = tmp_path / "mod.py"
    source.write_text("x = 1   \n\t\ny = 2\n" + "z = '" + "a" * 90 + "'\n")
    reader = AnalyzeStyleTool(ToolConfig(authority_level=AuthorityLevel.LEVEL_1_BASIC_TOOLS))
    editor = AnalyzeStyleTool(ToolConfig(authority_level=AuthorityLevel.LEVEL_2_FILE_OPERATIONS))
    refused = _run(reader.run({"path": str(source), "fix": True}, ToolContext()))
    fixed = _run(editor.run({"path": str(source), "fix": True}, ToolContext()))
    assert refused.success is False and "level 2" in refused.error_message
    assert fixed.success and fixed.result_data["fixed_count"] == 2
    assert [v["code"] for v in fixed.result_data["violations"]] == ["E501"]
    assert source.read_text().splitlines()[:2] == ["x = 1", ""]


# ----- registries ---------------------------------------------------------------------------------

def test_resource_tools_are_registered_and_offered_to_the_infrastructure_agent():
    from app.core.agents.registry import get_registry as agents
    from app.core.agents.specialists.ops_mode import tools_for
    from app.core.tools.registry import get_registry as tools

    for name in ("resource_provision", "resource_scale", "resource_health_check", "resource_status",
                 "resource_terminate"):
        meta = tools().get_metadata(name)
        assert meta is not None and meta.is_implemented and meta.category == "infrastructure", name
    offered = set(tools_for("infrastructure"))
    assert {"resource_provision", "resource_scale", "resource_health_check", "resource_status"} <= offered
    assert "resource_terminate" not in offered  # stopping a service stays with Richard
    level = agents().get_metadata("infrastructure").required_authority_level
    assert all(tools().get_metadata(t).required_authority_level <= level for t in offered if tools().get_metadata(t))


@pytest.mark.parametrize("module", ["core/approval", "core/authority", "core/resume", "core/workflows",
                                    "core/workspaces/scanner.py", "core/safety/detector.py",
                                    "core/richard/guidance.py", "api/v1/business_ops.py"])
def test_legacy_modules_that_faked_their_work_are_gone(module):
    import app as app_package

    path = Path(app_package.__file__).parent / module
    sources = list(path.rglob("*.py")) if path.is_dir() else ([path] if path.exists() else [])
    assert sources == [], sources


# ----- Richard routes are owner-scoped ------------------------------------------------------------

@pytest.mark.api
def test_richard_reads_are_limited_to_the_owner(client):
    from tests.test_repair9_relational_contract import _seed_boundary

    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s)
            return str(uid), res

    owner, res = _run(seed())
    report, approval = res["boundary_report_id"], res["approval_id"]
    try:
        app.dependency_overrides[get_current_user_id] = lambda: owner
        own = (client.get("/api/richard/pending").json(), client.get(f"/api/richard/boundary-reports/{report}"),
               client.get(f"/api/richard/approval-windows/{approval}"))
        app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
        other = (client.get("/api/richard/pending").json(), client.get(f"/api/richard/boundary-reports/{report}"),
                 client.get(f"/api/richard/approval-windows/{approval}"))
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert any(p["approval_id"] == approval for p in own[0])
    assert own[1].status_code == 200 and own[2].status_code == 200
    assert other[0] == [] and other[1].status_code == 404 and other[2].status_code == 404
