"""Acceptance test: all 31 agents execute role tasks; lead agents spawn employees."""
import json
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
ROLE_TASK = {
    "orchestrator": "Plan a small dev-tool launch and select the lead agents.",
    "company_operator": "Run today's operating loop and list next best actions.",
    "workspace_manager": "Describe how you would scan and register a project workspace.",
    "coding_agent": "Write a Python function add(a,b) returning the sum.",
    "debugging_agent": "Diagnose a failing build with an ImportError and propose a fix.",
    "verifier": "Verify the claim 'all tests pass' and state how you check it.",
    "devops": "Produce a local release readiness checklist for a Next.js app.",
    "documentation": "Draft a README intro for a CLI dev tool.",
    "research": "Research the latest stable Node.js LTS and cite sources.",
    "memory": "Store and summarise a key project decision.",
    "marketing": "Draft a launch tagline and one social post for a dev tool.",
    "growth": "Propose 3 activation experiments for a SaaS dev tool.",
    "customer_support": "Draft a support reply for a password reset question.",
    "business": "Outline a simple business model for a paid dev tool.",
    "finance": "Estimate monthly costs for a small hosted SaaS.",
    "creation": "List 3 royalty-free asset sources and licence notes.",
    "self_healing": "Describe steps to auto-recover from an API error spike.",
    "monitoring": "List the health signals you would monitor for a web app.",
    "rollback": "Describe a safe rollback plan for a bad deploy.",
    "security": "List secret-handling and dependency-risk checks for a repo.",
    "legal": "Draft a short privacy-policy intro paragraph.",
    "sales": "Draft a 3-step outreach sequence for SaaS founders.",
    "analytics": "Define 5 KPIs and one drop-off to watch for a dev tool.",
    "qa": "Write an acceptance test plan for a login flow.",
    "infrastructure": "Produce a Docker + cloud readiness checklist.",
    "onboarding": "Draft a first-run onboarding flow for new users.",
    "community": "Draft a community update post for a launch.",
    "partnerships": "Draft an integration-partnership outreach message.",
    "content": "Draft a short blog intro announcing a launch.",
    "self_evolution": "Propose one safe workflow improvement (no safety changes).",
    "swarm_manager": "Explain how you spawn and dissolve scoped employees.",
}
LEADS = ["coding_agent", "debugging_agent", "marketing", "customer_support",
         "infrastructure", "qa", "research"]


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
        return e.code, json.loads(e.read() or "{}")


def main():
    _, tok = call("POST", "/auth/login", b={"username": "testadmin", "password": "testpass123"})
    T = tok["access_token"]
    s, agents = call("GET", "/api/agents/list?only_implemented=true", t=T)
    names = sorted(a["name"] for a in agents)
    print(f"registered agents: {len(names)}")

    completed = partial = failed = 0
    print("\n===== ALL 31 AGENTS EXECUTE ROLE TASKS =====")
    for n in names:
        task = ROLE_TASK.get(n, f"Perform your {n} role for a dev-tool launch.")
        spawn = n in LEADS
        s, d = call("POST", f"/api/agents/{n}/run", {"task": task, "spawn_employees": spawn}, T)
        st = d.get("status")
        emp = len(d.get("employees", []))
        completed += st == "completed"
        partial += st == "partial"
        failed += st == "failed"
        tag = f" emp={emp}" if spawn else ""
        print(f"  {n:18} {st:9} verified={d.get('verified')}{tag}")

    print(f"\nSUMMARY: completed={completed} partial={partial} failed={failed} / {len(names)}")

    print("\n===== EMPLOYEE SPAWNING (lead agents) =====")
    s, tasks = call("GET", "/api/tasks/list?task_status=completed&limit=100", t=T)
    s, allt = call("GET", "/api/tasks/list?limit=100", t=T)
    emp_tasks = [t for t in allt if t.get("task_type") == "employee_task"]
    print(f"  employee_task records: {len(emp_tasks)} "
          f"(dissolved/completed: {sum(1 for t in emp_tasks if t['status'] in ('completed','partial'))})")

    print("\nDONE")


if __name__ == "__main__":
    main()
