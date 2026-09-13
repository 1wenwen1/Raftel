#!/bin/bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <experiment-server-ip>" >&2
    exit 2
fi

ip=$1
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "${REPO}/aliyun/config.json" ]; then
    key=$(python3 -c 'import json, pathlib; p=pathlib.Path("aliyun/config.json"); c=json.loads(p.read_text()); print(c.get("ssh_private_key", "TShard"))' 2>/dev/null || true)
fi
key=${RAFTEL_SSH_KEY:-${key:-TShard}}
[[ "$key" = /* ]] || key="${REPO}/${key}"
ssh_options=(-i "$key" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes -o ConnectTimeout=5)

echo "[$ip] Preparing the SGX kernel..."
ssh "${ssh_options[@]}" "root@$ip" 'bash /root/SGX_init.sh'

if ssh "${ssh_options[@]}" "root@$ip" 'test -f /var/run/raftel-reboot-required'; then
    echo "[$ip] Scheduling required kernel reboot..."
    ssh "${ssh_options[@]}" "root@$ip" \
        'nohup sh -c "sleep 1; /sbin/reboot" >/dev/null 2>&1 &'

    echo "[$ip] Waiting for SSH to go offline..."
    offline_deadline=$((SECONDS + 120))
    while ssh "${ssh_options[@]}" "root@$ip" true >/dev/null 2>&1; do
        if (( SECONDS >= offline_deadline )); then
            echo "ERROR: $ip did not go offline within 120 seconds." >&2
            exit 1
        fi
        sleep 3
    done

    echo "[$ip] Waiting for SSH to come back..."
    online_deadline=$((SECONDS + 600))
    until ssh "${ssh_options[@]}" "root@$ip" true >/dev/null 2>&1; do
        if (( SECONDS >= online_deadline )); then
            echo "ERROR: $ip did not return within 600 seconds." >&2
            exit 1
        fi
        sleep 5
    done
else
    echo "[$ip] SGX devices already use a suitable kernel; reboot skipped."
fi

echo "[$ip] SSH is available; running the remaining initialization..."
ssh "${ssh_options[@]}" "root@$ip" 'bash /root/init.sh'
echo "[$ip] Initialization completed."
