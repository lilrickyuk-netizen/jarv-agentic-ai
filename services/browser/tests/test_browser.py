"""
JAI's browser service: a real headless Chromium driven through browser-use, against a page served on this
container's own loopback (the test allows that address; the service never does). No network is needed.
"""
import http.server
import re
import socket
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import httpx

import pytest
from fastapi.testclient import TestClient

import server

PAGE = b"""<!doctype html><html><head><title>Plexecute waitlist</title></head><body>
<h1>Join the Plexecute waitlist</h1>
<form action="/thanks"><label>Email <input name="email" type="email"></label>
<label>Password <input name="password" type="password"></label>
<label>Card number <input name="card_number" autocomplete="cc-number"></label>
<button type="submit">Join</button></form><a href="/about">About Plexecute</a></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAGE if self.path.startswith("/") and not self.path.startswith("/about") else \
            b"<html><head><title>About</title></head><body><p>Plexecute helps you execute.</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def site():
    """The test's own page on loopback, and JAI's browser service running as a real server in its own process."""
    # A threading server: Chromium opens spare connections ahead of time, and a one-at-a-time server would wait on
    # one of those forever instead of answering the page.
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    service = subprocess.Popen([sys.executable, str(Path(__file__).with_name("run_service.py")), str(port)],
                               cwd=str(Path(server.__file__).parent))
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    yield f"http://127.0.0.1:{httpd.server_port}", base
    service.terminate()
    try:
        service.wait(timeout=20)
    except subprocess.TimeoutExpired:
        service.kill()
    httpd.shutdown()


AUTH = {"Authorization": "Bearer test-token"}


def _index(page: str, marker: str) -> int:
    """The number browser-use gave the element this text belongs to (on its line, or the nearest line above)."""
    lines = page.splitlines()
    for at, line in enumerate(lines):
        if marker in line:
            for candidate in reversed(lines[:at + 1]):
                found = re.search(r"\[(\d+)\]", candidate)
                if found:
                    return int(found.group(1))
    raise AssertionError(f"{marker} not in page:\n{page}")


def test_only_public_pages_are_opened_and_secret_fields_are_recognised():
    assert server.public_url("https://example.com/") is None
    for url in ("http://localhost:8000", "http://backend:8000/api", "http://10.1.2.3/", "file:///etc/passwd",
                "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data"):
        assert server.public_url(url), url
    node = lambda **a: types.SimpleNamespace(attributes=a)  # noqa: E731
    assert server.secret_field(node(type="password"))
    assert server.secret_field(node(name="card_number"))
    assert server.secret_field(node(autocomplete="one-time-code"))
    assert server.secret_field(node(id="sort-code"))
    assert server.secret_field(node(name="email", type="email")) is None
    assert server.secret_field(node(placeholder="Spinning class")) is None


def test_the_browser_needs_jais_token():
    with TestClient(server.app) as client:
        assert client.post("/open", json={"session": "m1", "url": "https://example.com"}).status_code == 401
        assert client.get("/health").json()["ok"] is True


def test_an_agent_reads_a_page_types_its_email_and_is_stopped_at_the_password(site):
    page_site, base = site

    def call(path, body):
        return httpx.post(base + path, json=body, headers=AUTH, timeout=90).json()

    opened = call("/open", {"session": "m1", "url": page_site + "/"})
    assert opened["ok"] is True, opened
    assert opened["title"] == "Plexecute waitlist" and opened["elements"] >= 4
    page = opened["page"]
    email, password = _index(page, "email"), _index(page, "password")
    typed = call("/act", {"session": "m1", "action": "type", "index": email, "text": "hello@plexecute.co.uk"})
    assert typed["ok"] is True, typed
    refused = call("/act", {"session": "m1", "action": "type", "index": password, "text": "hunter2"})
    assert refused["refused"] is True and refused["boundary"] is True and "password" in refused["reason"]
    about = _index(call("/act", {"session": "m1", "action": "read"})["page"], "About Plexecute")
    followed = call("/act", {"session": "m1", "action": "click", "index": about})
    assert followed["ok"] is True and "helps you execute" in followed["page"], followed
    assert call("/act", {"session": "m1", "action": "evaluate"})["refused"]
    assert call("/close", {"session": "m1"})["closed"] is True
    # The real service still refuses this computer's own addresses: only the test's copy allows its page.
    assert server.public_url(page_site + "/") is not None
