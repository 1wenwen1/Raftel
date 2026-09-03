#!/bin/bash
# This script configures the SGX environment on remote servers
# by creating the "stats" folder and running the initialization script (init.sh).

# 读取存放远程服务器私有 IP 地址的文件
IP_LIST=$(cat /root/Raftel/aliyun/priv_ip.txt)

# 初始化计数器，用于为每个 tmux 会话命名
count=1

echo "Configuring SGX environment on remote servers..."

# 遍历 IP 地址列表
for ip in $IP_LIST
do
    # 创建一个新的 tmux 会话，名称为 "setup<count>"
    tmux new-session -d -s "setup$count"
    
    # 在 tmux 会话中通过 SSH 登录远程服务器，执行以下命令：
    # 1. 创建目录 /root/Raftel/stats（如果不存在则创建）
    # 2. 执行初始化脚本 init.sh
    tmux send-keys -t "setup$count" "ssh -i /root/Raftel/TShard -o StrictHostKeyChecking=no root@$ip 'mkdir -p /root/Raftel/stats'" C-m

    # 计数器加 1
    ((count++))
done

echo "Remote configuration initiated."
