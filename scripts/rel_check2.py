import json, urllib.error, urllib.request
BASE = "http://localhost:8000"
WS = "C:\\Users\\lilri\\OneDrive\\Desktop\\JARV_WORKSPACE_TEST"


def call(m, p, b=None, t=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    if t:
        r.add_header("Authorization", "Bearer " + t)
    try:
        with urllib.request.urlopen(r, timeout=120) as x:
            return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")


_, tok = call("POST", "/auth/login", b={"username": "testadmin", "password": "testpass123"})
T = tok["access_token"]
d = call("POST", "/api/command/execute",
         {"command": f"JARV, run the command `ls /nonexistent_xyz_path` in the workspace at {WS}."}, T)[1]
dt = call("GET", f"/api/tasks/{d['task_id']}", t=T)[1]
f = dt.get("failure") or {}
print("FAILED CMD: task=", dt.get("status"), "exit=", f.get("exit_code"),
      "stderr=", (f.get("stderr") or "")[:70])
d = call("POST", "/api/command/execute",
         {"command": f"JARV, install dependencies using `npm install yet please` in {WS}."}, T)[1]
print("INVALID PKG: resp=", d.get("status"))
s, feed = call("GET", "/api/operations-feed/list?limit=10", T)
items = feed if isinstance(feed, list) else feed.get("items", [])
print("top feed titles:")
for i in items[:6]:
    print("  -", i.get("item_type"), "|", i.get("title"))
