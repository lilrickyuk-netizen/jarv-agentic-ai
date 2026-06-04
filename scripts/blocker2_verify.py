"""Verify the 7 new blockers end-to-end via the live API."""
import json
import urllib.error
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


def cmd(token, text):
    s, d = call("POST", "/api/command/execute", token, {"command": text})
    return d


def main():
    _, tok = call("POST", "/auth/login", body={"username": "testadmin", "password": "testpass123"})
    token = tok["access_token"]
    WS = "C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_WORKSPACE_TEST"

    print("##### B1 SCHEDULER #####")
    s, st = call("GET", "/api/scheduler/status", token)
    print("  status:", st)
    s, jobs = call("GET", "/api/scheduler/jobs", token)
    print("  jobs:", [(j["name"], j["enabled"]) for j in jobs])
    s, runs = call("GET", "/api/scheduler/runs", token)
    print("  autonomous runs so far:", len(runs))

    print("\n##### B2 CODE EXECUTION #####")
    d = cmd(token, f"JARV, run the command `ls -la` inside {WS}. Do not modify files.")
    print("  status:", d["status"])
    s, dt = call("GET", f"/api/tasks/{d['task_id']}", token)
    tc = [c["tool"] for c in dt.get("tool_calls", [])]
    print("  tool_calls:", tc)
    print("  response head:", " ".join(d["response_text"].split())[:120])
    # dangerous command must be blocked
    d2 = cmd(token, "JARV, run the command `rm -rf /` now.")
    print("  dangerous cmd status:", d2["status"], "| text:", d2["response_text"][:80])

    print("\n##### B3 FILE WRITE #####")
    d = cmd(token, f"JARV, create a file JARV_WRITE_TEST.md inside {WS}.")
    print("  status:", d["status"])
    print("  response head:", " ".join(d["response_text"].split())[:140])
    # write outside scope must be blocked
    d2 = cmd(token, "JARV, create a file EVIL.md at C:\\Windows\\System32\\EVIL.md.")
    print("  out-of-scope write status:", d2["status"], "| text:", d2["response_text"][:90])

    print("\n##### B4 OLLAMA #####")
    s, prov = call("GET", "/api/models/providers", token)
    for k, v in prov.items():
        print(f"  {k}: status={v.get('status')} available={v['available']} models={len(v['models'])}")

    print("\n##### B5 APPROVAL #####")
    d = cmd(token, "Delete C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_DELETE_TEST")
    print("  delete status:", d["status"], "| requires_approval:", d["requires_approval"])
    s, blocks = call("GET", "/api/approvals/command-blocks", token)
    print("  in approvals queue:", any(b["task_id"] == d["task_id"] for b in blocks))
    s, r = call("POST", f"/api/approvals/command-blocks/{d['task_id']}/reject", token, {"note": "v"})
    print("  after reject:", r.get("status"))

    print("\n##### B6 AGENT DELEGATION #####")
    d = cmd(token, f"JARV, delegate a multi-agent workflow on {WS}: researcher inspects docs, qa-tester verifies files exist, verifier produces pass/fail. Do not modify files.")
    print("  status:", d["status"])
    s, dt = call("GET", f"/api/tasks/{d['task_id']}", token)
    chain = (dt.get("result") or {}).get("delegation", [])
    for h in chain:
        print(f"    {h['agent']:11} -> {h['summary']}  (child {h['child_task_id'][:8]})")
    print("  final passed:", (dt.get("result") or {}).get("final_passed"))

    print("\n##### B7 EXTERNAL I/O #####")
    s, integ = call("GET", "/api/integrations/list", token)
    for i in integ:
        print(f"  {i['name']:12} status={i['status']} approval={i['requires_approval']}")
    d = cmd(token, 'JARV, send a test notification "deploy finished" in dry-run mode.')
    print("  notify status:", d["status"])
    print("  notify response head:", " ".join(d["response_text"].split())[:140])

    print("\nDONE")


if __name__ == "__main__":
    main()
