"""
The Docker proxy's rules. On 9 November the Command Center's service switches were refused although ALLOW_START and
ALLOW_STOP were set: tecnativa/docker-socket-proxy checks them after the rule that refuses every POST when POST=0, so
they could never match. JAI's own copy of the rules checks start, stop and restart first, anchored to the end of the
path, and still refuses every other POST.
"""
from __future__ import annotations

import re

from tests.repo_paths import repo_path


def _frontend_rules() -> list:
    text = repo_path("infra", "docker-proxy", "haproxy.cfg").read_text(encoding="utf-8")
    frontend = text.split("frontend dockerfrontend", 1)[1]
    return [line.strip() for line in frontend.splitlines() if line.strip().startswith("http-request")]


def _verdict(rules: list, method: str, path: str, env: dict) -> str:
    """Which rule decides a request, as HAProxy reads them: the first that matches."""
    for rule in rules:
        if rule.startswith("http-request deny unless METH_GET"):
            if not (method == "GET" or env.get("POST") == "1"):
                return "deny"
            continue
        if rule == "http-request deny":
            return "deny"
        found = re.search(r"-m reg -i (\S+) \} \{ env\((\w+)\)", rule)
        if not found:
            continue
        pattern, variable = found.groups()
        if "METH_POST" in rule and method != "POST":
            continue
        if re.search(pattern, path, re.I) and env.get(variable) == "1":
            return "allow"
    return "deny"


def test_the_service_switches_can_start_and_stop_but_nothing_else_is_posted():
    rules = _frontend_rules()
    env = {"CONTAINERS": "1", "ALLOW_RESTARTS": "1", "ALLOW_START": "1", "ALLOW_STOP": "1", "POST": "0"}
    assert _verdict(rules, "POST", "/v1.47/containers/jarv-comfyui/start", env) == "allow"
    assert _verdict(rules, "POST", "/containers/abc123/stop", env) == "allow"
    assert _verdict(rules, "POST", "/containers/jarv-worker/restart", env) == "allow"
    assert _verdict(rules, "GET", "/containers/json", env) == "allow"
    assert _verdict(rules, "POST", "/containers/create", env) == "deny"
    assert _verdict(rules, "POST", "/containers/x/exec", env) == "deny"
    assert _verdict(rules, "POST", "/containers/x/start/../../create", env) == "deny"
    assert _verdict(rules, "POST", "/images/create", env) == "deny"
    assert _verdict(rules, "POST", "/containers/x/start", {**env, "ALLOW_START": "0"}) == "deny"


def test_both_compose_files_give_the_proxy_these_rules():
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        text = repo_path(name).read_text(encoding="utf-8")
        assert "./infra/docker-proxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg.template:ro" in text, name
