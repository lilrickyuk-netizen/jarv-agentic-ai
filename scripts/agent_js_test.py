"""Prove the agent loop can build/run JS now that node/npm are in the runtime."""
import json
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
WS = "C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_WORKSPACE_TEST"


def call(m, p, b=None, t=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    if t:
        r.add_header("Authorization", "Bearer " + t)
    try:
        with urllib.request.urlopen(r, timeout=300) as x:
            return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


def main():
    _, tok = call("POST", "/auth/login", b={"username": "testadmin", "password": "testpass123"})
    T = tok["access_token"]
    mission = (
        f"In the workspace at {WS}, create a Node.js file src/greet.js that exports a "
        f"function greet(name) returning `Hello, ${{name}}!`, and a src/run_greet.js that "
        f"requires it, asserts greet('JARV') === 'Hello, JARV!', and prints OK. Then run "
        f"node src/run_greet.js and make sure it passes."
    )
    print("MISSION:", mission[:100], "...")
    t0 = time.time()
    s, d = call("POST", "/api/command/execute", {"command": mission}, T)
    print("status:", d.get("status"), "| time:", round(time.time() - t0, 1), "s")
    s, dt = call("GET", f"/api/tasks/{d['task_id']}", T)
    print("tool_calls:", [c["tool"] for c in dt.get("tool_calls", [])])
    r = dt.get("result") or {}
    print("iterations:", r.get("agent_iterations"), "| success:", r.get("agent_success"))
    print("response head:")
    print("\n".join(d.get("response_text", "").splitlines()[:10]))


if __name__ == "__main__":
    main()
