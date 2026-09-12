#!/bin/bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <experiment-server-ip>" >&2
    exit 2
fi

ip=$1
key=/root/Raftel/TShard
ssh_options=(-i "$key" -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=5)

echo "[$ip] Running simulation-mode experiment environment initialization..."
ssh "${ssh_options[@]}" "root@$ip" 'bash /root/init.sh'
echo "[$ip] Initialization completed."
