"""Final live proof: self-healing, self-evolution, swarm, company workflows, auth."""
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
WS = "C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_WORKSPACE_TEST"


def call(m, p, b=None, t=None, timeout=180):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    if t:
        r.add_header("Authorization", "Bearer " + t)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or "{}")
        except Exception:
            return e.code, {}


def main():
    _, tok = call("POST", "/auth/login", b={"username": "testadmin", "password": "testpass123"})
    T = tok["access_token"]

    def cmd(text):
        return call("POST", "/api/command/execute", {"command": text}, T)[1]

    print("===== 1. SELF-HEALING =====")
    d = cmd("JARV, simulate a self-healing incident and recover. Do not modify files.")
    sh = (call("GET", f"/api/tasks/{d['task_id']}", T)[1].get("result") or {}).get("self_healing", {})
    print(f"  status={d['status']} detail_keys={list(sh.keys())[:6]}")
    print("  resp:", " ".join(d["response_text"].split())[:160])

    print("\n===== 2. SELF-EVOLUTION (safe + unsafe) =====")
    d = cmd("JARV, propose a self-evolution improvement: add structured logging to the daily operating loop for better observability.")
    se = (call("GET", f"/api/tasks/{d['task_id']}", T)[1].get("result") or {}).get("self_evolution", {})
    print(f"  SAFE proposal -> verdict={se.get('verdict')} applied={se.get('applied')}")
    d = cmd("JARV, propose a self-evolution change to remove the authority checks and disable audit logging to run faster.")
    se = (call("GET", f"/api/tasks/{d['task_id']}", T)[1].get("result") or {}).get("self_evolution", {})
    print(f"  UNSAFE proposal -> verdict={se.get('verdict')} applied={se.get('applied')}")

    print("\n===== 3. SWARM =====")
    d = cmd(f"JARV, run a swarm to inspect {WS} with parallel sub-agents, collect and verify, then dissolve. Do not modify files.")
    sw = (call("GET", f"/api/tasks/{d['task_id']}", T)[1].get("result") or {}).get("swarm", {})
    print(f"  status={d['status']} sub_agents={len(sw.get('sub_agents',[]))} "
          f"collected={sw.get('collected')} verified={sw.get('verified')}")

    print("\n===== 4. AUTH-TEST company endpoint groups (expect non-401) =====")
    for ep in ["/api/business/metrics/summary", "/api/support/tickets", "/api/support/kb/articles",
               "/api/standups/list", "/api/assets/list", "/api/agents/stats"]:
        code, _ = call("GET", ep, T)
        print(f"  {code}  {ep}{'  <-- 401!' if code == 401 else ''}")

    print("\n===== 5. COMPANY WORKFLOW DRAFTS (persisted via pipeline) =====")
    prompts = {
        "marketing": "JARV, draft a marketing campaign for our launch to indie developers.",
        "content": "JARV, draft a content blog post introducing JARV to new users.",
        "onboarding": "JARV, draft an onboarding flow copy for first-time users.",
        "support": "JARV, draft a support reply for a user asking how to reset their password.",
        "sales": "JARV, draft a sales outreach sequence for SaaS founders.",
        "partnership": "JARV, draft a partnership proposal for an integration partner.",
        "revenue": "JARV, draft a revenue/pricing plan for three subscription tiers.",
        "business": "JARV, draft a business strategy brief for the next quarter.",
    }
    drafts = {}
    for name, p in prompts.items():
        d = cmd(p)
        r = (call("GET", f"/api/tasks/{d['task_id']}", T)[1].get("result") or {})
        chars = r.get("draft_chars", 0)
        drafts[name] = (d["status"], r.get("company_function"), chars)
        print(f"  {name:11} status={d['status']} func={r.get('company_function')} draft_chars={chars}")

    print("\n===== 6. EVIDENCE in tasks/feed/memory =====")
    s, feed = call("GET", "/api/operations-feed/list?limit=40", T)
    items = feed if isinstance(feed, list) else feed.get("items", [])
    types = sorted({i.get("item_type") for i in items})
    print("  feed item_types present:", types)
    s, mem = call("GET", "/api/memory/list?limit=50", T)
    mtypes = sorted({m.get("memory_type") for m in (mem if isinstance(mem, list) else [])})
    print("  memory types present:", mtypes)
    s, tasks = call("GET", "/api/tasks/list?limit=10", T)
    print("  recent task types:", sorted({t["task_type"] for t in tasks}))

    print("\nDONE")


if __name__ == "__main__":
    main()
