# Settings for the engineering sandbox's shell (a login shell: `su - openhands`), from the files JAI's installers write
# into infra/sandbox/env/ (never committed): myco-dev.env (MYCO's local development stack) and studio.env (the video
# studio's free footage source). The folder is mounted read-only at /etc/jai-sandbox; the same files are in the
# container's environment, so a shell that is not a login shell inherits them too. Nothing here when none exists.
for f in /etc/jai-sandbox/*.env; do
  if [ -f "$f" ] && [ -r "$f" ]; then
    set -a
    . "$f"
    set +a
  fi
done
unset f
