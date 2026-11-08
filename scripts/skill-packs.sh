#!/usr/bin/env bash
# Clones JAI's third-party skill packs (Superpowers, UI/UX Pro Max, Marketing Skills, No AI Slop, BRAG) into
# skill-packs/<name>, each at the exact commit pinned in apps/backend/app/core/knowledge/skill_packs.py, and checks
# each one's licence is still MIT. skill-packs/ is git-ignored and mounted read-only into the backend, the worker and
# the engineering sandbox. Run again after a pin changes; delete skill-packs/<name> to remove one pack.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=skill-packs
mkdir -p "$DEST"
python3 - <<'PY' > "$DEST/.pins"
import ast
tree = ast.parse(open("apps/backend/app/core/knowledge/skill_packs.py", encoding="utf-8").read())
for node in tree.body:
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "PACKS":
        for name, pack in ast.literal_eval(node.value).items():
            print(name, pack["repo"], pack["commit"])
PY
fail=0
while read -r name repo commit; do
  dir="$DEST/$name"
  if [ -f "$dir/.jai-commit" ] && [ "$(cat "$dir/.jai-commit")" = "$commit" ]; then
    echo "   $name: pinned at ${commit:0:7}"
    continue
  fi
  rm -rf "$dir.tmp"
  if ! git clone -q --filter=blob:none --no-checkout "https://github.com/$repo.git" "$dir.tmp" \
     || ! git -C "$dir.tmp" checkout -q "$commit"; then
    echo "   $name: could not fetch $repo at $commit"; rm -rf "$dir.tmp"; fail=1; continue
  fi
  if ! head -3 "$dir.tmp/LICENSE" | grep -q "MIT License"; then
    echo "   $name: its licence is no longer MIT at this commit, so it was not installed"; rm -rf "$dir.tmp"; fail=1; continue
  fi
  rm -rf "$dir.tmp/.git"
  echo "$commit" > "$dir.tmp/.jai-commit"
  chmod -R a+rX "$dir.tmp"
  rm -rf "$dir" && mv "$dir.tmp" "$dir"
  echo "   $name: installed at ${commit:0:7}"
done < "$DEST/.pins"
rm -f "$DEST/.pins"
exit $fail
