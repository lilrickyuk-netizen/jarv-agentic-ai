# MYCO's local development stack, for the engineering sandbox's shell (a login shell: `su openhands -`).
# The connection settings are written by scripts/myco-dev-stack.sh into infra/myco-dev/connection.env (never
# committed) and mounted read-only at /etc/myco-dev.env. Nothing here when the stack is not installed.
if [ -f /etc/myco-dev.env ] && [ -r /etc/myco-dev.env ]; then
  set -a
  . /etc/myco-dev.env
  set +a
fi
