#!/bin/sh
# Starts MYCO's local Vault and unseals it with the key the installer saved when it initialised Vault, so a restart
# (a persistence test, a host restart) brings it back ready, as an auto-unseal does in a real deployment. Before the
# installer has initialised it, Vault starts sealed and waits.
set -u
vault server -config=/myco/config.hcl &
server=$!
export VAULT_ADDR=http://127.0.0.1:8200
if [ -n "${MYCO_DEV_VAULT_UNSEAL_KEY:-}" ]; then
  for _ in $(seq 1 60); do
    vault status >/dev/null 2>&1
    [ $? -eq 2 ] && break   # 2: answering and sealed
    sleep 1
  done
  vault operator unseal "$MYCO_DEV_VAULT_UNSEAL_KEY" >/dev/null && echo "MYCO dev Vault unsealed"
fi
wait "$server"
