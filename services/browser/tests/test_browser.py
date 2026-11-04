"""
JAI's browser service: a real headless Chromium driven through browser-use, against a page served on this
container's own loopback (the test allows that address; the service never does). No network is needed.
"""
import asyncio
import http.server
import re
import signal
import threading
import types

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
def site(monkeypatch):
    # A threading server: Chromium opens spare connections ahead of time, and a one-at-a-time server would wait on
    # one of those forever instead of answering the page.
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setattr(server, "TOKEN", "test-token")
    real = server.public_url
    monkeypatch.setattr(server, "public_url", lambda url: None if url.startswith("http://127.0.0.1:") else real(url))
    monkeypatch.setattr(server, "PROHIBITED", tuple(d for d in server.PROHIBITED if d not in ("127.0.0.1",)))
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    for key in list(server.SESSIONS):
        asyncio.run(server.SESSIONS.pop(key).close())


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
    def too_long(*_):
        raise TimeoutError("the browser test took over 3 minutes")

    signal.signal(signal.SIGALRM, too_long)
    signal.alarm(180)
    try:
        _drive_the_page(site)
    finally:
        signal.alarm(0)


def _drive_the_page(site):
    with TestClient(server.app) as client:
        opened = client.post("/open", headers=AUTH, json={"session": "m1", "url": site + "/"}).json()
        assert opened["ok"] is True, opened
        assert opened["title"] == "Plexecute waitlist" and opened["elements"] >= 4
        page = opened["page"]
        email, password = _index(page, "email"), _index(page, "password")
        typed = client.post("/act", headers=AUTH, json={"session": "m1", "action": "type", "index": email,
                                                        "text": "hello@plexecute.co.uk"}).json()
        assert typed["ok"] is True, typed
        refused = client.post("/act", headers=AUTH, json={"session": "m1", "action": "type", "index": password,
                                                          "text": "hunter2"}).json()
        assert refused["refused"] is True and refused["boundary"] is True and "password" in refused["reason"]
        about = _index(client.post("/act", headers=AUTH, json={"session": "m1", "action": "read"}).json()["page"],
                       "About Plexecute")
        followed = client.post("/act", headers=AUTH, json={"session": "m1", "action": "click", "index": about}).json()
        assert followed["ok"] is True and "helps you execute" in followed["page"], followed
        assert client.post("/act", headers=AUTH, json={"session": "m1", "action": "evaluate"}).json()["refused"]
        assert client.post("/close", headers=AUTH, json={"session": "m1"}).json()["closed"] is True
