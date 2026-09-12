#!/usr/bin/env bash
# AE FIX (pipeline reliability): wait for initialization jobs and propagate failures; detached tmux
# sessions previously returned success before SDK installation or reboot finished.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${REPO}/deployment/logs"
pids=()
while read -r ip; do
    [[ -z "$ip" ]] && continue
    bash "${REPO}/deployment/configure_experiment_server.sh" "$ip" > "${REPO}/deployment/logs/${ip}.log" 2>&1 &
    pids+=("$!")
done < "${REPO}/aliyun/public_ip.txt"
(( ${#pids[@]} > 0 )) || { echo "ERROR: no deployment hosts" >&2; exit 1; }
failed=0
for pid in "${pids[@]}"; do
    wait "$pid" || failed=$((failed + 1))
    echo "Initialization job completed; failures so far: ${failed}. Logs: deployment/logs/"
done
(( failed == 0 ))
