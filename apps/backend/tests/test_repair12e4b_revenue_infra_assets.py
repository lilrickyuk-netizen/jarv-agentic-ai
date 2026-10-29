"""Repair 12e-4b: revenue operations, business monitoring, infrastructure
configuration, budget-bounded scaling, and licence-checked assets.

Every tool runs through the registry against real rows and a real sandbox
folder. Replaced at the boundary only: the App Store feed (a recorded feed
response), the asset download's HTTP GET (bytes and a content type), and the
deployment server (the local shell and compose recorder from the deploy tests).
"""
import asyncio
import hashlib
import hmac
import json
import shutil
import time
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

import app.tools.deploy as deploy_tools
from app.core import internet
from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.assets import library
from app.core.auth import get_current_user_id
from app.core.business import reviews
from app.core.business.revenue import verify_stripe_signature
from app.core.config import settings
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.registry import create_tool, get_registry
from app.main import app
from app.models.assets import Asset, AssetLicence
from app.models.company_operations import KPIRecord
from app.models.content import CommunityItem, ContentItem
from app.models.operations import DeploymentRecord
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.assets_library import ASSET_TOOLS
from app.tools.deploy import DeployStagingTool
from app.tools.infra_config import INFRA_CONFIG_TOOLS
from app.tools.revenue import REVENUE_TOOLS
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12e_deploy import _workspace as _deploy_workspace
from tests.test_repair12e_deploy import server  # noqa: F401 - the deployment server fixture

SANDBOX = Path("/tmp/jarv_sandbox")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _run(coro):
    return asyncio.run(coro)


async def _call(name, data, ctx, level=AuthorityLevel.LEVEL_7_DEPLOYMENT):
    return await create_tool(name, ToolConfig(authority_level=level)).execute(data, ctx)


@pytest.fixture
def folder():
    name = f"r12e4b-{uuid4().hex[:8]}"
    root = SANDBOX / name
    root.mkdir(parents=True)
    yield f"/test_workspaces/{name}", root
    shutil.rmtree(root, ignore_errors=True)


async def _seed(db, host=None):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="MYCO", slug=f"myco-{ws_id.hex[:8]}",
                     description="Booking platform", workspace_type="project", authority_level=7,
                     is_active=True, config={"root_path": host} if host else {}))
    await db.commit()
    return user_id, ws_id


# ----- registry ---------------------------------------------------------------------------------

def test_revenue_infrastructure_and_asset_tools_are_registered_with_authority():
    registry = get_registry()
    expected = {
        "check_revenue_metrics", "check_conversion_metrics", "check_subscription_metrics", "check_failed_payments",
        "create_revenue_experiment", "update_revenue_operations_loop", "record_revenue_event",
        "check_payment_events", "check_reviews", "check_analytics",
        "check_ssl_certificate", "check_domain_dns", "generate_nginx_config", "generate_docker_compose",
        "validate_cloud_config", "estimate_infrastructure_cost", "scale_service_with_budget_boundary",
        "web_search", "download_asset", "check_licence", "save_source_record", "generate_asset_manifest",
        "update_asset_licence_file", "create_offer_draft", "create_pricing_review",
    }
    names = [t(ToolConfig()).name for t in REVENUE_TOOLS + INFRA_CONFIG_TOOLS + ASSET_TOOLS]
    assert len(names) == len(set(names)) == 23
    for name in expected:
        assert registry.is_implemented(name), name
    assert registry.get_metadata("check_revenue_metrics").category == "revenue"
    assert registry.get_metadata("generate_nginx_config").category == "infrastructure"
    assert registry.get_metadata("download_asset").category == "assets"
    assert registry.get_metadata("scale_service_with_budget_boundary").required_authority_level == 7
    assert registry.get_metadata("download_asset").required_authority_level == 5
    from app.core.tools.base import ToolAuthorizationError

    low = create_tool("download_asset", ToolConfig(authority_level=AuthorityLevel.LEVEL_2_FILE_OPERATIONS))

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _owner, ws_id = await _seed(db)
            return await low.execute({"url": "https://cdn.pixabay.com/a.png"}, ToolContext(workspace_id=ws_id,
                                                                                          db_session=db))

    with pytest.raises(ToolAuthorizationError):
        _run(run())


def test_agents_declare_the_new_tools_within_their_authority():
    from app.core.agents.registry import get_registry as agents
    from app.core.agents.toolbox import ALIASES

    meta = agents()
    assert "update_revenue_operations_loop" in meta.get_metadata("finance").default_tools
    assert "check_conversion_metrics" in meta.get_metadata("growth").default_tools
    assert "create_pricing_review" in meta.get_metadata("business").default_tools
    assert {"check_payment_events", "check_reviews", "check_analytics"} <= set(meta.get_metadata("monitoring").default_tools)
    assert "scale_service_with_budget_boundary" in meta.get_metadata("infrastructure").default_tools
    assert "generate_nginx_config" in meta.get_metadata("devops").default_tools
    assert "download_asset" in meta.get_metadata("creation").default_tools
    assert "web_search" in meta.get_metadata("research").default_tools
    assert "web_search" not in ALIASES and "check_licence" not in ALIASES
    tools = get_registry()
    for name in ("finance", "growth", "business", "monitoring", "infrastructure", "devops", "creation", "research"):
        agent = meta.get_metadata(name)
        for tool in agent.default_tools:
            tmeta = tools.get_metadata(tool)
            assert tmeta is not None and tmeta.is_implemented, (name, tool)
            assert tmeta.required_authority_level <= agent.required_authority_level, (name, tool)


# ----- revenue ----------------------------------------------------------------------------------

@pytest.mark.integration
def test_revenue_metrics_loop_and_experiment_from_recorded_events():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            empty = await _call("check_revenue_metrics", {}, ctx)
            for event in ({"event": "payment", "amount": 49, "customer_id": "c1"},
                          {"event": "payment", "amount": 99, "customer_id": "c2"},
                          {"event": "refund", "amount": 9, "customer_id": "c1"},
                          {"event": "subscription_started", "amount": 20, "customer_id": "c1"},
                          {"event": "subscription_started", "amount": 240, "customer_id": "c2", "interval": "year"},
                          {"event": "subscription_started", "amount": 20, "customer_id": "c3"},
                          {"event": "subscription_cancelled", "amount": 20, "customer_id": "c3"},
                          {"event": "failed_payment", "amount": 20, "customer_id": "c4",
                           "description": "card_declined"}):
                recorded = await _call("record_revenue_event", event, ctx)
                assert recorded.success, recorded.error_message
            bad = await _call("record_revenue_event", {"event": "gift", "amount": 1}, ctx)
            revenue = await _call("check_revenue_metrics", {"days": 30}, ctx)
            subs = await _call("check_subscription_metrics", {}, ctx)
            failed = await _call("check_failed_payments", {}, ctx)
            events = await _call("check_payment_events", {"hours": 24}, ctx)
            from app.core.company_ops.service import company_ops

            for name, value in (("visitors", 2000), ("signups", 200), ("paying_customers", 10)):
                await company_ops.record_kpi(db, ws_id, name=name, value=value, kpi_type="growth")
            conversion = await _call("check_conversion_metrics", {}, ctx)
            loop = await _call("update_revenue_operations_loop", {"days": 30}, ctx)
            experiment = await _call("create_revenue_experiment", {
                "name": "Annual plan discount", "hypothesis": "A 20% annual discount lifts paid conversion",
                "metric": "mrr", "variants": ["monthly only", "monthly + annual"], "success_threshold": "+10% mrr"},
                ctx)
            offer = await _call("create_offer_draft", {"topic": "Founders' annual plan"}, ctx)
            pricing = await _call("create_pricing_review", {"topic": "Should Pro cost 29?"}, ctx)
            await db.commit()
            kpis = {k.kpi_name: float(k.value) for k in (await db.execute(
                select(KPIRecord).where(KPIRecord.workspace_id == ws_id))).scalars().all()}
            item = (await db.execute(select(ContentItem).where(
                ContentItem.workspace_id == ws_id, ContentItem.content_type == "revenue_experiment"))).scalar_one()
            return (empty, bad, revenue, subs, failed, events, conversion, loop, experiment, offer, pricing, kpis, item)

    (empty, bad, revenue, subs, failed, events, conversion, loop, experiment, offer, pricing, kpis, item) = _run(run())
    assert empty.success and empty.result_data["has_data"] is False and empty.result_data["source"] == "recorded"
    assert bad.success is False
    r = revenue.result_data
    assert (r["gross"], r["refunds"], r["net"], r["payments"]) == (148.0, 9.0, 139.0, 2)
    s = subs.result_data
    assert s["active"] == 2 and s["mrr"] == 40.0 and s["cancelled"] == 1  # 20 + 240/12
    assert failed.result_data["count"] == 1 and failed.result_data["items"][0]["reason"] == "card_declined"
    assert events.result_data["status"] == "attention" and events.result_data["by_type"]["payment"] == 2
    c = conversion.result_data
    assert [st["stage"] for st in c["stages"]] == ["visitors", "signups", "paying"] and c["overall"] == 0.005
    assert loop.success and "failed payment" in loop.result_data["findings"][0]
    assert {"revenue_30d", "mrr", "active_subscriptions", "failed_payments_open"} <= set(kpis)
    assert kpis["mrr"] == 40.0 and kpis["revenue_30d"] == 139.0
    assert experiment.success and experiment.result_data["baseline"] == 40.0
    assert item.meta_data["variants"][0] == "monthly only" and item.status == "planned"
    assert offer.success and "net 139.00" in offer.result_data["body"] and "[confirm: price" in offer.result_data["body"]
    assert pricing.success and "MRR 40.00" in pricing.result_data["body"]


def test_stripe_webhook_signatures_are_verified():
    secret, payload = "whsec_test", b'{"id":"evt_1"}'
    stamp = str(int(time.time()))
    good = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    assert verify_stripe_signature(payload, f"t={stamp},v1={good}", secret)
    assert not verify_stripe_signature(payload, f"t={stamp},v1={'0' * 64}", secret)
    assert not verify_stripe_signature(payload + b" ", f"t={stamp},v1={good}", secret)
    old = str(int(time.time()) - 3600)
    stale = hmac.new(secret.encode(), f"{old}.".encode() + payload, hashlib.sha256).hexdigest()
    assert not verify_stripe_signature(payload, f"t={old},v1={stale}", secret)


@pytest.mark.api
def test_revenue_api_and_stripe_webhook(client, monkeypatch):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _seed(db)

    owner, ws_id = _run(seed())
    secret = "whsec_jarv_test"
    event = {"id": f"evt_{uuid4().hex[:10]}", "type": "invoice.paid", "created": int(time.time()),
             "data": {"object": {"amount_paid": 2900, "currency": "gbp", "customer": "cus_1",
                                 "description": "Pro plan"}}}
    payload = json.dumps(event).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    headers = {"stripe-signature": f"t={stamp},v1={signature}", "content-type": "application/json"}

    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", None)
    disabled = client.post(f"/api/revenue/{ws_id}/stripe-webhook", content=payload, headers=headers)
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", secret)
    forged = client.post(f"/api/revenue/{ws_id}/stripe-webhook", content=payload,
                         headers={**headers, "stripe-signature": f"t={stamp},v1={'1' * 64}"})
    accepted = client.post(f"/api/revenue/{ws_id}/stripe-webhook", content=payload, headers=headers)
    replay = client.post(f"/api/revenue/{ws_id}/stripe-webhook", content=payload, headers=headers)
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        recorded = client.post(f"/api/revenue/{ws_id}/events", json={"event": "refund", "amount": 4})
        metrics = client.get(f"/api/revenue/{ws_id}/metrics")
        loop = client.post(f"/api/revenue/{ws_id}/loop")
        app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
        stranger = client.get(f"/api/revenue/{ws_id}/metrics")
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert disabled.status_code == 503
    assert forged.status_code == 400
    assert accepted.status_code == 200 and accepted.json()["recorded"] is True
    assert replay.status_code == 200 and replay.json()["id"] == accepted.json()["id"]  # once per Stripe event
    assert recorded.status_code == 200
    body = metrics.json()
    assert metrics.status_code == 200 and body["revenue"]["gross"] == 29.0 and body["revenue"]["net"] == 25.0
    assert loop.status_code == 200 and "mrr" in loop.json()["kpis_recorded"]
    assert stranger.status_code == 404


@pytest.mark.integration
def test_reviews_and_analytics_checks(monkeypatch):
    feed = [{"id": "901", "author": "Ana", "rating": 5, "title": "Love it", "content": "Booking is so fast",
             "version": "1.2", "updated": "2026-10-01"},
            {"id": "902", "author": "Ben", "rating": 1, "title": "Crashes", "content": "The app crashes at checkout "
             "every time, checkout crash", "version": "1.2", "updated": "2026-10-02"}]
    calls = []

    async def fake_feed(app_id, country):
        calls.append((app_id, country))
        return feed

    monkeypatch.setattr(reviews, "fetch_app_store", fake_feed)
    monkeypatch.setattr(settings, "PLAUSIBLE_API_KEY", None)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            first = await _call("check_reviews", {"app_store_id": "1234567", "country": "GB"}, ctx)
            second = await _call("check_reviews", {"app_store_id": "1234567", "country": "gb"}, ctx)
            bad_id = await _call("check_reviews", {"app_store_id": "myco-app"}, ctx)
            from app.core.company_ops.service import company_ops

            await company_ops.record_kpi(db, ws_id, name="visitors", value=1500, kpi_type="growth")
            analytics = await _call("check_analytics", {}, ctx)
            await db.commit()
            stored = (await db.execute(select(CommunityItem).where(CommunityItem.workspace_id == ws_id,
                                                                   CommunityItem.category == "app_store"))).scalars().all()
            return first, second, bad_id, analytics, stored

    monkeypatch.setattr(reviews, "fetch_app_store", fake_feed)
    first, second, bad_id, analytics, stored = _run(run())
    assert calls[0] == ("1234567", "gb")
    assert first.success and first.result_data["new"] == 2 and first.result_data["average_rating"] == 3.0
    assert first.result_data["recent_low_ratings"][0]["author"] == "Ben"
    assert "checkout" in [term for term, _count in first.result_data["themes"]]
    assert second.result_data["new"] == 0 and second.result_data["reviews"] == 2
    assert len(stored) == 2 and {s.meta_data["rating"] for s in stored} == {1, 5}
    assert bad_id.success is False
    assert analytics.success and analytics.result_data["source"] == "recorded KPIs"
    assert analytics.result_data["kpis"][0]["name"] == "visitors"


# ----- infrastructure ---------------------------------------------------------------------------

@pytest.mark.integration
def test_generated_nginx_and_compose_validate_and_unsafe_configs_are_flagged(folder):
    host, root = folder
    (root / "requirements.txt").write_text("fastapi\nsqlalchemy\nasyncpg\nredis\n")
    (root / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (root / ".env.example").write_text("POSTGRES_DB=\nPOSTGRES_USER=\nPOSTGRES_PASSWORD=\n")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _owner, ws_id = await _seed(db, host)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            nginx = await _call("generate_nginx_config", {"domain": "myco.example",
                                                          "routes": {"/": "web:3000", "/api": "api:8000",
                                                                     "/ws": "api:8000"},
                                                          "websocket_paths": ["/ws"]}, ctx)
            bad_domain = await _call("generate_nginx_config", {"domain": "not a domain", "routes": {"/": "web:3000"}},
                                     ctx)
            compose = await _call("generate_docker_compose", {}, ctx)
            clean = await _call("validate_cloud_config", {}, ctx)
            (root / "docker-compose.yml").write_text(
                "services:\n  web:\n    image: nginx\n    privileged: true\n    volumes:\n"
                "      - /var/run/docker.sock:/var/run/docker.sock\n    environment:\n"
                "      API_KEY: sk-abcdefghijklmnopqrstu\n")
            (root / "Dockerfile").write_text("FROM python:latest\nENV SECRET_TOKEN=abc\n")
            unsafe = await _call("validate_cloud_config", {}, ctx)
            return nginx, bad_domain, compose, clean, unsafe

    nginx, bad_domain, compose, clean, unsafe = _run(run())
    assert nginx.success and nginx.result_data["issues"] == []
    conf = (root / "infra" / "nginx" / "myco.example.conf").read_text()
    assert "listen 443 ssl" in conf and "Strict-Transport-Security" in conf and "/.well-known/acme-challenge/" in conf
    assert "proxy_pass http://api:8000" in conf and "Upgrade" in conf
    assert bad_domain.success is False and "not a valid domain" in bad_domain.error_message
    assert compose.success, compose.error_message
    generated = (root / "docker-compose.generated.yml").read_text()
    assert "uvicorn main:app" in generated and "postgres:16-alpine" in generated and "redis:7-alpine" in generated
    assert "${POSTGRES_PASSWORD}" in generated
    assert not [i for i in compose.result_data["issues"] if i["severity"] == "error"]
    assert clean.success and clean.result_data["errors"] == 0
    issues = " | ".join(i["issue"] for v in unsafe.result_data["files"].values() for i in v)
    assert unsafe.result_data["valid"] is False and unsafe.result_data["errors"] >= 4
    for expected in ("privileged container", "Docker socket mounted writable", "inline secret value",
                     "secret set in the image"):
        assert expected in issues, expected
    assert "sk-abcdefghijklmnopqrstu" not in json.dumps(unsafe.result_data)


@pytest.mark.integration
def test_cost_estimate_reads_fixed_costs_and_budget(monkeypatch):
    monkeypatch.setattr(settings, "INFRA_FIXED_COSTS", json.dumps({"vps": 24, "domain": 1.25}))
    monkeypatch.setattr(settings, "INFRA_MONTHLY_BUDGET", 60.0)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            estimate = await _call("estimate_infrastructure_cost", {}, ctx)
            monkeypatch.setattr(settings, "INFRA_FIXED_COSTS", "not json")
            broken = await _call("estimate_infrastructure_cost", {}, ctx)
            return estimate, broken

    estimate, broken = _run(run())
    data = estimate.result_data
    fixed = {i["item"]: i["monthly"] for i in data["items"] if i["source"] == "INFRA_FIXED_COSTS"}
    assert fixed == {"vps": 24.0, "domain": 1.25}
    assert data["budget"] == 60.0 and data["remaining"] == round(60.0 - data["monthly_total"], 2)
    assert broken.success is False and "INFRA_FIXED_COSTS" in broken.error_message


@pytest.mark.integration
def test_scaling_runs_within_budget_and_pauses_beyond_it(server, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "INFRA_FIXED_COSTS", json.dumps({"vps": 20}))
    monkeypatch.setattr(settings, "INFRA_REPLICA_MONTHLY_COST", 10.0)
    monkeypatch.setattr(settings, "INFRA_MAX_REPLICAS", 4)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            ws_id = await _deploy_workspace(db, server["host"])
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            no_release = await _call("scale_service_with_budget_boundary", {"service": "web", "replicas": 2}, ctx)
            deployed = await DeployStagingTool(ToolConfig(authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT)).execute(
                {}, ctx)
            monkeypatch.setattr(settings, "INFRA_MONTHLY_BUDGET", 1_000_000.0)
            within = await _call("scale_service_with_budget_boundary", {"service": "web", "replicas": 3}, ctx)
            over_limit = await _call("scale_service_with_budget_boundary", {"service": "web", "replicas": 6}, ctx)
            monkeypatch.setattr(settings, "INFRA_MONTHLY_BUDGET", 0.01)
            over_budget = await _call("scale_service_with_budget_boundary", {"service": "web", "replicas": 2}, ctx)
            approved_ctx = ToolContext(workspace_id=ws_id, db_session=db, approval_granted=True)
            approved = await _call("scale_service_with_budget_boundary", {"service": "web", "replicas": 2},
                                   approved_ctx)
            bad = await _call("scale_service_with_budget_boundary", {"service": "web;rm -rf /", "replicas": 2}, ctx)
            await db.commit()
            records = (await db.execute(select(DeploymentRecord).where(
                DeploymentRecord.workspace_id == ws_id, DeploymentRecord.deployment_type == "scale"))).scalars().all()
            return no_release, deployed, within, over_limit, over_budget, approved, bad, records

    no_release, deployed, within, over_limit, over_budget, approved, bad, records = _run(run())
    log = server["compose_log"].read_text()
    assert no_release.success is False and "no current staging release" in no_release.error_message
    assert deployed.success, deployed.error_message
    assert within.success, within.error_message
    assert within.result_data["cost"]["needs_approval"] is False and within.result_data["replicas"] == 3
    assert "--scale web=3" in log
    assert over_limit.success is False and over_limit.result_data["requires_approval"] is True
    assert "INFRA_MAX_REPLICAS" in over_limit.result_data["reason"] and "web=6" not in log
    assert over_budget.success is False and over_budget.result_data["requires_approval"] is True
    assert "budget" in over_budget.result_data["reason"]
    assert approved.success and approved.result_data["cost"]["needs_approval"] is True and "--scale web=2" in log
    assert bad.success is False
    assert len(records) == 2
    assert {r.meta_data["approved_by"] for r in records} == {"budget", "richard"}


# ----- assets -----------------------------------------------------------------------------------

@pytest.mark.integration
def test_assets_are_downloaded_only_with_a_usable_licence(folder, monkeypatch):
    host, root = folder
    fetched = []

    async def fake_fetch(url):
        fetched.append(url)
        if url.endswith(".svg"):
            return b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "image/svg+xml"
        if url.endswith("fake.png"):
            return b"<html>not an image</html>", "text/html"
        if url.endswith(".woff2"):
            return b"wOF2" + b"\x00" * 32, "font/woff2"
        return PNG, "image/png"

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _owner, ws_id = await _seed(db, host)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            internal = await _call("download_asset", {"url": "https://127.0.0.1/logo.png", "licence": "cc0"}, ctx)
            real_ssrf = internet._ssrf_ok
            monkeypatch.setattr(internet, "_ssrf_ok", lambda url: (True, None) if "127.0.0.1" not in url
                                else real_ssrf(url))
            monkeypatch.setattr(library, "fetch", fake_fetch)
            plain_http = await _call("download_asset", {"url": "http://cdn.example.org/a.png", "licence": "cc0"}, ctx)
            unknown = await _call("download_asset", {"url": "https://cdn.example.org/hero.png"}, ctx)
            noncommercial = await _call("download_asset", {"url": "https://cdn.example.org/hero.png",
                                                           "licence": "CC BY-NC 4.0"}, ctx)
            exe = await _call("download_asset", {"url": "https://cdn.example.org/setup.exe", "licence": "mit"}, ctx)
            escape = await _call("download_asset", {"url": "https://cdn.example.org/a.png", "licence": "cc0",
                                                    "folder": "../outside"}, ctx)
            disguised = await _call("download_asset", {"url": "https://cdn.example.org/fake.png", "licence": "cc0"},
                                    ctx)
            scripted = await _call("download_asset", {"url": "https://cdn.example.org/icon.svg", "licence": "mit"}, ctx)
            pixabay = await _call("download_asset", {"url": "https://cdn.pixabay.com/photo/2026/hero.png",
                                                     "source_page": "https://pixabay.com/photos/hero-1/"}, ctx)
            ccby = await _call("download_asset", {"url": "https://upload.example.org/team.png",
                                                  "licence": "CC-BY-4.0", "author": "Jo Smith",
                                                  "folder": "public/images"}, ctx)
            font = await _call("download_asset", {"url": "https://fonts.gstatic.com/s/inter/v1/inter.woff2"}, ctx)
            verdict = await _call("check_licence", {"licence": "cc-by-nc"}, ctx)
            verdict_ok = await _call("check_licence", {"url": "https://images.unsplash.com/photo-1"}, ctx)
            corrected = await _call("save_source_record", {"asset_id": ccby.result_data["id"],
                                                           "source_page": "https://example.org/team",
                                                           "author": "Jo Smith Studio"}, ctx)
            manifest = await _call("generate_asset_manifest", {}, ctx)
            licences = await _call("update_asset_licence_file", {}, ctx)
            await db.commit()
            assets = (await db.execute(select(Asset).where(Asset.workspace_id == ws_id))).scalars().all()
            licence_rows = (await db.execute(select(AssetLicence).where(AssetLicence.workspace_id == ws_id))
                            ).scalars().all()
            return (internal, plain_http, unknown, noncommercial, exe, escape, disguised, scripted, pixabay, ccby,
                    font, verdict, verdict_ok, corrected, manifest, licences, assets, licence_rows)

    (internal, plain_http, unknown, noncommercial, exe, escape, disguised, scripted, pixabay, ccby, font, verdict,
     verdict_ok, corrected, manifest, licences, assets, licence_rows) = _run(run())
    assert internal.success is False and "refused" in internal.error_message.lower()
    assert plain_http.success is False and "https" in plain_http.error_message
    assert unknown.success is False and "Unknown licence" in unknown.error_message
    assert noncommercial.success is False and "commercial" in noncommercial.error_message
    assert exe.success is False and "executables" in exe.error_message
    assert escape.success is False
    assert disguised.success is False and "text/html" in disguised.error_message
    assert scripted.success is False and "script" in scripted.error_message
    assert all(u.endswith((".png", ".svg", ".woff2")) for u in fetched)  # refused before any download otherwise
    assert pixabay.success, pixabay.error_message
    assert pixabay.result_data["licence"] == "pixabay" and pixabay.result_data["provider"] == "Pixabay"
    assert pixabay.result_data["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert (root / "assets" / "hero.png").read_bytes() == PNG
    assert ccby.success and ccby.result_data["path"] == "public/images/team.png"
    assert "Jo Smith" in ccby.result_data["attribution"] and "CC BY 4.0" in ccby.result_data["attribution"]
    assert font.success and font.result_data["licence"] == "ofl-1.1" and font.result_data["type"] == "font"
    assert verdict.success and verdict.result_data["allowed"] is False
    assert verdict_ok.result_data["allowed"] is True and verdict_ok.result_data["licence"] == "unsplash"
    assert corrected.success and "Jo Smith Studio" in corrected.result_data["attribution"]
    assert len(assets) == 3 and {a.license_type for a in assets} == {"pixabay", "cc-by-4.0", "ofl-1.1"}
    assert {r.licence_type for r in licence_rows} == {"pixabay", "cc-by-4.0", "ofl-1.1"}
    data = json.loads((root / "ASSETS.json").read_text())
    assert manifest.result_data["assets"] == 3 and len(data["assets"]) == 3
    credits = (root / "ASSET-LICENCES.md").read_text()
    assert "## CC BY 4.0" in credits and "Jo Smith Studio" in credits and "public/images/team.png" in credits
    assert licences.result_data["attribution_required"] == ["team.png"]


@pytest.mark.api
def test_assets_api_is_owner_scoped(client, folder, monkeypatch):
    host, root = folder

    async def fake_fetch(url):
        return PNG, "image/png"

    monkeypatch.setattr(library, "fetch", fake_fetch)
    monkeypatch.setattr(internet, "_ssrf_ok", lambda url: (True, None))

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _seed(db, host)

    owner, ws_id = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        refused = client.post(f"/api/assets/{ws_id}/download", json={"url": "https://cdn.example.org/a.png"})
        saved = client.post(f"/api/assets/{ws_id}/download", json={"url": "https://cdn.example.org/a.png",
                                                                   "licence": "cc0"})
        listed = client.get("/api/assets/list")
        stats = client.get("/api/assets/stats")
        lib = client.get(f"/api/assets/{ws_id}/library")
        files = client.post(f"/api/assets/{ws_id}/manifest")
        check = client.post("/api/assets/licence-check", json={"licence": "CC BY-NC 4.0"})
        app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
        stranger_list = client.get("/api/assets/list")
        stranger_lib = client.get(f"/api/assets/{ws_id}/library")
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert refused.status_code == 403
    assert saved.status_code == 200 and saved.json()["licence"] == "cc0-1.0"
    assert listed.status_code == 200 and [a["asset_name"] for a in listed.json()] == ["a.png"]
    assert stats.json()["total_assets"] == 1 and stats.json()["by_licence"] == {"cc0-1.0": 1}
    assert lib.json()["assets"][0]["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert files.status_code == 200 and (root / "ASSETS.json").is_file()
    assert check.json()["allowed"] is False
    assert stranger_list.json() == [] and stranger_lib.status_code == 404


# ----- web search -------------------------------------------------------------------------------

def test_web_search_results_are_parsed_and_redirects_unwrapped():
    html = ('<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fpixabay.com'
            '%2Fservice%2Flicense%2F&amp;rut=abc">Pixabay <b>License</b></a>'
            '<a class="result__snippet" href="#">Free for <b>commercial</b> use</a></div>'
            '<div class="result"><a class="result__a" href="https://fonts.google.com/">Google Fonts</a>'
            '<a class="result__snippet">Open source fonts</a></div>')
    results = internet.parse_duckduckgo(html, 5)
    assert results[0] == {"title": "Pixabay License", "url": "https://pixabay.com/service/license/",
                          "snippet": "Free for commercial use"}
    assert results[1]["url"] == "https://fonts.google.com/"
    assert internet.parse_duckduckgo(html, 1) == results[:1]
    assert {t["name"]: t["status"] for t in internet.internet_tools()}["web_search"] == "allowed_auto"


# ----- agents -----------------------------------------------------------------------------------

@pytest.mark.integration
def test_finance_growth_and_creation_agents_use_their_tools(folder, monkeypatch):
    from app.core.agents.specialists.creation import CreationAgent
    from app.core.agents.specialists.finance import FinanceAgent
    from app.core.agents.specialists.growth import GrowthAgent

    host, root = folder

    async def fake_fetch(url):
        return PNG, "image/png"

    monkeypatch.setattr(library, "fetch", fake_fetch)
    monkeypatch.setattr(internet, "_ssrf_ok", lambda url: (True, None))

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db, host)
            tool_ctx = ToolContext(workspace_id=ws_id, db_session=db)
            await _call("record_revenue_event", {"event": "payment", "amount": 120, "customer_id": "c1"}, tool_ctx)
            await db.commit()
            ctx = AgentContext(workspace_id=ws_id, user_id=owner, db_session=db, metadata={"business_enabled": True})
            finance = await FinanceAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                                     authority_level=AuthorityLevel.LEVEL_8_FINANCIAL)).execute(
                {"operation": "reporting", "time_period": "30d"}, ctx)
            growth = await GrowthAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                                   authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).execute(
                {"growth_metric": "revenue", "current_value": 120, "target_value": 500, "timeframe": "30d"}, ctx)
            creation = await CreationAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                                       authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).execute(
                {"asset_type": "image", "specifications": {"url": "https://cdn.pixabay.com/photo/hero.png"}}, ctx)
            refused = await CreationAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                                      authority_level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS)).execute(
                {"asset_type": "image", "specifications": {"url": "https://cdn.example.org/unknown.png"}}, ctx)
            kpi = (await db.execute(select(KPIRecord).where(KPIRecord.workspace_id == ws_id,
                                                            KPIRecord.kpi_name == "revenue_30d"))).scalar_one_or_none()
            return finance, growth, creation, refused, kpi

    finance, growth, creation, refused, kpi = _run(run())
    assert finance.success, finance.error_message
    assert finance.result_data["tool"] == "update_revenue_operations_loop" and kpi is not None and float(kpi.value) == 120
    assert growth.success and growth.result_data["tool"] == "check_revenue_metrics" and growth.result_data["net"] == 120
    assert creation.success and creation.result_data["tool"] == "download_asset"
    assert (root / "assets" / "hero.png").is_file()
    assert refused.success is False and "Unknown licence" in (refused.error_message or "")
