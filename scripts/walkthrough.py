"""Browser-loop walkthrough: drives the exact endpoints each dashboard page uses."""
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
DASH = "http://localhost:3000"


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def head(t):
    print("\n" + "=" * 70 + "\n" + t + "\n" + "=" * 70)


def main():
    _, tok = call("POST", "/auth/login", body={"username": "testadmin", "password": "testpass123"})
    token = tok["access_token"]
    print("Logged in as testadmin.")

    head("STEP 1  /dashboard/command  — run a safe status command")
    s, d = call("POST", "/api/command/execute", token,
                {"command": "JARV, confirm you are online and give a short status report. Do not modify files."})
    t1 = d["task_id"]
    print(f"  status   : {d['status']}")
    print(f"  provider : {d['provider']} / {d['model']}")
    print(f"  agents   : {', '.join(d['selected_agents'])}")
    print(f"  tokens   : {d['tokens_used']}   time: {d['execution_time']}s")
    print(f"  task_id  : {t1}")
    print("  response (first lines):")
    for ln in d["response_text"].splitlines()[:5]:
        print("    " + ln)

    head("STEP 2  /dashboard/tasks  — the command appears in task history")
    s, tasks = call("GET", "/api/tasks/list?limit=5", token)
    for t in tasks[:5]:
        print(f"  [{t['status']:9}] {t['task_type']:8} {t['title'][:50]}")
    print(f"  -> click the top task to open /dashboard/tasks/{t1}")

    head(f"STEP 3  /dashboard/tasks/[id]  — full task detail")
    s, dt = call("GET", f"/api/tasks/{t1}", token)
    print(f"  status        : {dt['status']}   approval: {dt['approval_status']}")
    print(f"  provider/model: {dt['provider']} / {dt['model']}")
    print(f"  agents        : {', '.join(dt['selected_agents'])}")
    print(f"  tool_calls    : {[c['tool'] for c in dt['tool_calls']]}")
    print(f"  audit events  : {len(dt['audit_events'])}   operation events: {len(dt['operation_events'])}")

    head("STEP 4  /dashboard/command  — real read-only workspace scan (tools + QA)")
    s, d = call("POST", "/api/command/execute", token,
                {"command": "JARV, perform a read-only scan of the approved test workspace at C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_WORKSPACE_TEST. Do not modify files."})
    t3 = d["task_id"]
    s, dt = call("GET", f"/api/tasks/{t3}", token)
    print(f"  status     : {dt['status']}")
    print(f"  tool calls : {[c['tool'] for c in dt['tool_calls']]}")
    v = dt.get("verification") or {}
    print(f"  QA verify  : passed={v.get('passed')} confidence={v.get('confidence_score')} "
          f"({v.get('tests_passed')}/{(v.get('tests_passed',0)+v.get('tests_failed',0))}) by {v.get('verifier')}")
    print(f"  -> open /dashboard/tasks/{t3}  (Tool calls + QA Verification sections)")

    head("STEP 5  /dashboard/command  — destructive command hits the boundary")
    s, d = call("POST", "/api/command/execute", token,
                {"command": "Delete C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_DELETE_TEST"})
    t5 = d["task_id"]
    print(f"  status          : {d['status']}  (NOT executed)")
    print(f"  requires_approval: {d['requires_approval']}")
    print(f"  reason          : {d['approval_reason']}")

    head("STEP 6  /dashboard/approvals  — the blocked action is queued for you")
    s, blocks = call("GET", "/api/approvals/command-blocks", token)
    for b in blocks[:3]:
        mark = "  <-- this one" if b["task_id"] == t5 else ""
        print(f"  [{b['status']}] {b['command'][:45]}  ({b['boundary_type']}){mark}")
    print("  Buttons available on each: Confirm | Cancel | Intervene")

    head("STEP 7  reject (Cancel) the delete, confirm folder remains")
    s, r = call("POST", f"/api/approvals/command-blocks/{t5}/reject", token, {"note": "walkthrough cancel"})
    print(f"  after Cancel -> task status: {r['status']}")
    s, dt = call("GET", f"/api/tasks/{t5}", token)
    print(f"  task detail approval_status: {dt['approval_status']}")

    head("STEP 8  /dashboard/operations  — everything was logged live")
    s, feed = call("GET", "/api/operations-feed/list?limit=8", token)
    items = feed if isinstance(feed, list) else feed.get("items", [])
    for it in items[:8]:
        print(f"  [{it.get('item_type'):16}] {it.get('title')}")

    head("OPEN THESE IN YOUR BROWSER")
    print(f"  Command center : {DASH}/dashboard/command")
    print(f"  Status task    : {DASH}/dashboard/tasks/{t1}")
    print(f"  Scan task      : {DASH}/dashboard/tasks/{t3}")
    print(f"  Blocked delete : {DASH}/dashboard/tasks/{t5}")
    print(f"  Approvals      : {DASH}/dashboard/approvals")
    print(f"  Operations     : {DASH}/dashboard/operations")


if __name__ == "__main__":
    main()
