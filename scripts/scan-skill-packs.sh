#!/usr/bin/env bash
# Scans every skill pack in skill-packs/ with AgentShield (affaan-m/agentshield, MIT; ecc-agentshield on npm), a
# security auditor for agent configuration: injected instructions, hardcoded secrets, risky hooks and MCP servers.
# It runs in a throwaway Node container that sees the pack read-only. Each pack gets .agentshield.json (the full
# report) and .jai-blocked (the skills JAI will not load: any skill folder with a critical finding in the injection,
# secrets, hooks, mcp, skills or agents categories that is not merely a documentation or template example).
# A scan that cannot run is reported and leaves the pack's previous verdict in place.
set -uo pipefail
cd "$(dirname "$0")/.."
VERSION="${AGENTSHIELD_VERSION:-1.6.0}"
status=0
for dir in skill-packs/*/; do
  name=$(basename "$dir")
  [ -f "$dir/.jai-commit" ] || continue
  report="$dir/.agentshield.json"
  if ! docker run --rm --network bridge -v "$PWD/$dir":/scan:ro node:20 \
        sh -c "npx --yes ecc-agentshield@$VERSION scan --path /scan --format json 2>/dev/null" > "$report.tmp"; then
    : # AgentShield exits non-zero when it finds something; the JSON below is what counts
  fi
  if verdict=$(python3 - "$report.tmp" "$dir" <<'PY'
import json, sys
from pathlib import Path, PurePosixPath
path, folder = sys.argv[1], sys.argv[2]
raw = open(path, encoding="utf-8", errors="replace").read()
start = raw.find("{")
report = json.JSONDecoder().raw_decode(raw[start:])[0] if start != -1 else None
if not isinstance(report, dict) or "findings" not in report:
    raise SystemExit(1)
blocking = {"injection", "secrets", "hooks", "mcp", "skills", "agents"}
examples = {"docs-example", "template-example"}
blocked = set()
for finding in report.get("findings") or []:
    if finding.get("severity") != "critical" or finding.get("category") not in blocking:
        continue
    if finding.get("runtimeConfidence") in examples:
        continue
    parts = PurePosixPath(str(finding.get("file") or "").replace("/scan/", "", 1).lstrip("/")).parts
    # The skill folder that holds the file: the part before SKILL.md, or the folder two levels under the pack root.
    for i in range(len(parts) - 1, 0, -1):
        if (Path(folder) / PurePosixPath(*parts[:i]) / "SKILL.md").exists():
            blocked.add("/".join(parts[:i]))
            break
open(f"{folder}/.jai-blocked", "w").write("".join(f"{b}\n" for b in sorted(blocked)))
summary = report.get("summary") or {}
grade = (report.get("score") or {}).get("grade", "?")
print(f"grade {grade}: {summary.get('critical', 0)} critical, {summary.get('high', 0)} high findings; "
      f"{len(blocked)} skill(s) blocked" + (f" ({', '.join(sorted(blocked))})" if blocked else ""))
PY
  ); then
    echo "   $name: $verdict"
    mv -f "$report.tmp" "$report"
  else
    echo "   $name: AgentShield could not scan it this time; its last verdict stands"
    rm -f "$report.tmp"
    status=1
  fi
done
exit $status
