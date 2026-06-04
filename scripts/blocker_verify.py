"""Verify the 5 blocker fixes end-to-end via the live API."""
import json
import urllib.request

BASE = "http://localhost:8000"


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


def main():
    _, tok = call("POST", "/auth/login", body={"username": "testadmin", "password": "testpass123"})
    token = tok["access_token"]
    print("TOKEN OK")

    print("\n##### BLOCKER 1 — MEMORY #####")
    s, d = call("POST", "/api/command/execute", token,
                {"command": 'JARV, remember this safe test fact: "JARV memory verification marker 001". Do not modify files.'})
    print("remember status:", d["status"], "| agents:", d["selected_agents"])
    s, d = call("POST", "/api/command/execute", token,
                {"command": "JARV, recall the memory verification marker. Do not modify files."})
    print("recall status:", d["status"])
    print("recall response:", d["response_text"][:300])
    s, mem = call("GET", "/api/memory/list?limit=5", token)
    n = len(mem) if isinstance(mem, list) else len(mem.get("items", []))
    print("memory records in DB (api):", n)

    print("\n##### BLOCKER 2 — OLLAMA READINESS #####")
    s, prov = call("GET", "/api/models/providers", token)
    for k, v in prov.items():
        print(f"  {k}: available={v['available']} status={v.get('status')} models={len(v['models'])} msg={(v.get('message') or '')[:60]}")

    print("\n##### BLOCKER 3 + 5 — TOOLS + QA (scan) #####")
    s, d = call("POST", "/api/command/execute", token,
                {"command": "JARV, perform a read-only scan of the approved test workspace at C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_WORKSPACE_TEST. List real files only. Do not modify files."})
    t_scan = d["task_id"]
    print("scan status:", d["status"], "| agents:", d["selected_agents"])
    s, dt = call("GET", f"/api/tasks/{t_scan}", token)
    print("tool_calls:", [c["tool"] for c in dt.get("tool_calls", [])])
    v = dt.get("verification")
    if v:
        print(f"verification: passed={v['passed']} confidence={v['confidence_score']} "
              f"{v['tests_passed']}/{v['tests_passed']+v['tests_failed']} verifier={v['verifier']}")
    else:
        print("verification: MISSING")

    print("\n##### BLOCKER 4 — APPROVAL GATE #####")
    s, d = call("POST", "/api/command/execute", token,
                {"command": "Delete C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_DELETE_TEST"})
    t_del = d["task_id"]
    print("delete status:", d["status"], "| requires_approval:", d["requires_approval"])
    s, blocks = call("GET", "/api/approvals/command-blocks", token)
    present = any(b["task_id"] == t_del for b in blocks)
    print("in approvals queue:", present)
    s, dt = call("GET", f"/api/tasks/{t_del}", token)
    print("task detail status:", s, "| approval_status:", dt.get("approval_status"))
    # reject it
    s, r = call("POST", f"/api/approvals/command-blocks/{t_del}/reject", token, {"note": "verify"})
    print("after reject:", r.get("status"))

    print("\nDONE")


if __name__ == "__main__":
    main()
