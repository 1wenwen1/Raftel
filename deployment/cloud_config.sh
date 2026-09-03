#!/bin/bash

# Read the list of IP addresses
IP_LIST=$(cat /root/Raftel/aliyun/priv_ip.txt)

# Use the counter to name the tmux session from 1
count=1


echo "Config SGX environment..."
# Loop the list of IP addresses
for ip in $IP_LIST
do
    # Create a new tmux session and name it a number
    # Create (or attach to) a tmux session named setup<count> without failing if it already exists
    tmux has-session -t "setup$count" 2>/dev/null && tmux kill-session -t "setup$count"
    tmux new-session -Ad -s "setup$count"
    
    # Connect to the specified IP address in the new tmux session
    tmux send-keys -t "setup$count" "ssh -i  /root/Raftel/TShard -o StrictHostKeyChecking=no root@$ip 'bash init.sh'" C-m

    # Add a counter
    ((count++))
done
