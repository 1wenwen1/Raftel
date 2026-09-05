#!/bin/bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <experiment-server-ip>" >&2
    exit 2
fi

ip=$1
key=/root/Raftel/TShard
ssh_options=(-i "$key" -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=5)

echo "[$ip] Preparing the SGX kernel..."
ssh "${ssh_options[@]}" "root@$ip" 'bash /root/SGX_init.sh'

echo "[$ip] Scheduling reboot..."
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

echo "[$ip] SSH is available; running the remaining initialization..."
ssh "${ssh_options[@]}" "root@$ip" 'bash /root/init.sh'
echo "[$ip] Initialization completed."
