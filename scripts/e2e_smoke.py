"""End-to-end smoke test for the JARV operating loop (browser-equivalent API calls)."""
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

    print("\n===== TEST 1: status =====")
    s, d = call("POST", "/api/command/execute", token,
                {"command": "JARV, confirm you are online. Give me a short system status report. Do not modify any files."})
    t1 = d["task_id"]
    print("status:", d["status"], "| agents:", d["selected_agents"], "| model:", d["model"])
    s, dt = call("GET", f"/api/tasks/{t1}", token)
    print("task detail status:", s, "| approval:", dt.get("approval_status"),
          "| audit_events:", len(dt.get("audit_events", [])),
          "| op_events:", len(dt.get("operation_events", [])))

    print("\n===== TEST 2: register workspace =====")
    s, d = call("POST", "/api/command/execute", token,
                {"command": "JARV, register a test workspace at C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_WORKSPACE_TEST. Confirm the path exists. Do not modify files."})
    t2 = d["task_id"]
    print("status:", d["status"], "| agents:", d["selected_agents"])
    print("response:\n", d["response_text"][:600])
    s, ws = call("GET", "/api/workspaces/list", token)
    names = [w["name"] for w in ws] if isinstance(ws, list) else ws
    print("workspaces:", names)

    print("\n===== TEST 3: read-only scan =====")
    s, d = call("POST", "/api/command/execute", token,
                {"command": "JARV, perform a real read-only scan of the test workspace at C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_WORKSPACE_TEST. Identify the files, folders, docs, env files, package files, and current status. Do not modify files."})
    t3 = d["task_id"]
    print("status:", d["status"], "| agents:", d["selected_agents"])
    print("response:\n", d["response_text"][:1400])

    print("\n===== TEST 4: delete (must block) =====")
    s, d = call("POST", "/api/command/execute", token,
                {"command": "Delete C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_DELETE_TEST"})
    t4 = d["task_id"]
    print("status:", d["status"], "| requires_approval:", d["requires_approval"], "| reason:", d.get("approval_reason"))
    s, blocks = call("GET", "/api/approvals/command-blocks", token)
    print("command-blocks count:", len(blocks), "| this task present:",
          any(b["task_id"] == t4 for b in blocks))
    s, dt4 = call("GET", f"/api/tasks/{t4}", token)
    print("blocked task detail status:", s, "| approval_status:", dt4.get("approval_status"))

    print("\nTASK_IDS", json.dumps({"t1": t1, "t2": t2, "t3": t3, "t4": t4}))


if __name__ == "__main__":
    main()
