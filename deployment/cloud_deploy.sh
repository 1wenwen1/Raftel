#!/bin/bash

# Read the list of IP addresses
IP_LIST=$(cat /root/Raftel/aliyun/priv_ip.txt)

# Remove the old SSH host key entry for this IP to avoid SSH key conflicts
echo "Removing old SSH host key entries..."
for ip in $IP_LIST
do
    ssh-keygen -f "/root/.ssh/known_hosts" -R "$ip"
    sleep 3
done
sleep 30
echo "Running transfer.py..."
python /root/Raftel/deployment/transfer.py
