"""JARV reliability gate: prove failed/partial/blocked/completed are honest."""
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
WS = "C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_WORKSPACE_TEST"


def call(m, p, b=None, t=None, timeout=300):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    if t:
        r.add_header("Authorization", "Bearer " + t)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


def main():
    _, tok = call("POST", "/auth/login", b={"username": "testadmin", "password": "testpass123"})
    T = tok["access_token"]

    def run(text):
        d = call("POST", "/api/command/execute", {"command": text}, T)[1]
        dt = call("GET", f"/api/tasks/{d['task_id']}", t=T)[1]
        fail = dt.get("failure") or {}
        return {"resp_status": d.get("status"), "task_status": dt.get("status"),
                "failure": fail, "task_id": d["task_id"]}

    print("===== 1. INVALID COMMAND (npm install yet) =====")
    r = run(f"JARV, install dependencies using `npm install yet` in the test workspace at {WS}.")
    print(f"  resp={r['resp_status']} task={r['task_status']} reason={r['failure'].get('reason')}")

    print("\n===== 2. FAILED COMMAND (non-zero exit) =====")
    r = run(f"JARV, run the command `python3 -c \"import sys; sys.exit(5)\"` in the workspace at {WS}.")
    f = r["failure"]
    print(f"  resp={r['resp_status']} task={r['task_status']} exit={f.get('exit_code')} cmd={f.get('command')}")

    print("\n===== 3. STEP-LIMIT (unfixable) =====")
    r = run(f"JARV, fix the failing assertion in src/impossible.py in {WS} WITHOUT editing impossible.py; make it pass.")
    print(f"  resp={r['resp_status']} task={r['task_status']} next={r['failure'].get('next')}")

    print("\n===== 4. SUCCESSFUL COMMAND =====")
    r = run(f"JARV, run the command `ls -la` in the workspace at {WS}.")
    print(f"  resp={r['resp_status']} task={r['task_status']}")
    r2 = run("JARV, confirm you are online. Do not modify files.")
    print(f"  status cmd: resp={r2['resp_status']} task={r2['task_status']}")

    print("\n===== 6. OPERATIONS FEED (invalid command rejected) =====")
    s, feed = call("GET", "/api/operations-feed/list?limit=30", T)
    items = feed if isinstance(feed, list) else feed.get("items", [])
    rejected = [i for i in items if "invalid" in (i.get("title", "").lower()) or
                (i.get("item_type") == "error" and "command" in i.get("title", "").lower())]
    print(f"  rejection/error feed items: {[i.get('title') for i in rejected[:3]]}")
    fails = [i for i in items if i.get("item_type") == "task" and "failed" in i.get("title", "").lower()]
    print(f"  failed task feed items: {len(fails)}")

    print("\nDONE")


if __name__ == "__main__":
    main()
