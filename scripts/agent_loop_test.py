"""Prove the autonomous agent loop: implement code, run it, iterate until it passes."""
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
        f"Implement a Python module src/calc.py in the workspace at {WS} with a function "
        f"add(a, b) that returns their sum, and a script src/check_calc.py that imports add "
        f"from calc, asserts add(2,3)==5, and prints OK. Then run the check with "
        f"python3 src/check_calc.py and make sure it passes."
    )
    print("MISSION:", mission[:100], "...")
    t0 = time.time()
    s, d = call("POST", "/api/command/execute", {"command": mission}, T)
    print("status:", d.get("status"), "| time:", round(time.time() - t0, 1), "s")
    print("agents:", d.get("selected_agents"))
    print("response head:")
    print("\n".join(d.get("response_text", "").splitlines()[:14]))
    s, dt = call("GET", f"/api/tasks/{d['task_id']}", T)
    tcs = dt.get("tool_calls", [])
    print("\ntool_calls:", [c["tool"] for c in tcs])
    r = dt.get("result") or {}
    print("agent_iterations:", r.get("agent_iterations"), "| success:", r.get("agent_success"))


if __name__ == "__main__":
    main()
