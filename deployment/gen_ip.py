import sys
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def read_ip_list(filename):
    with open(filename, 'r') as f:
        ip_list = [line.strip() for line in f.readlines()]
    return ip_list

def generate_servers(ip_list, n, m):
    server_lines = []
    used_ips = []
    ip_count = len(ip_list)
    
    # Adjust n to be a multiple of m if necessary
    if n % m != 0:
        n = math.ceil(n / m) * m
    
    port_start = 8760
    server_id = 0
    for i in range(n):
        ip = ip_list[(i // m) % ip_count]
        if ip not in used_ips:
            used_ips.append(ip)
        base_port = port_start + (i % m)
        port1 = base_port
        port2 = base_port + 1000
        server_lines.append(f"id:{server_id} host:{ip} port:{port1} port:{port2} isTEE:1")
        server_id += 1
    
    return server_lines, used_ips

def write_servers(filename, server_lines):
    with open(filename, 'w') as f:
        for line in server_lines:
            f.write(line + '\n')

def write_ip_list(filename, used_ips):
    with open(filename, 'w') as f:
        for ip in used_ips:
            f.write(ip + '\n')

def write_clients(filename, first_server_line):
    parts = first_server_line.split()
    client_line = (parts[0]+' '+ parts[1] + " port:8750 port:9750")
    with open(filename, 'w') as f:
        f.write(client_line + '\n')

def main():
    if len(sys.argv) != 3:
        print("Usage: python script.py <n> <m>")
        return
    
    n = int(sys.argv[1])
    m = int(sys.argv[2])
    
    ip_list = read_ip_list(PROJECT_ROOT / 'aliyun' / 'priv_ip.txt')
    
    server_lines, used_ips = generate_servers(ip_list, n, m)
    
    write_servers(PROJECT_ROOT / 'servers', server_lines)
    write_servers(PROJECT_ROOT / 'config', server_lines)
    write_ip_list(PROJECT_ROOT / 'ip_list', used_ips)
    write_clients(PROJECT_ROOT / 'clients', server_lines[0])

if __name__ == "__main__":
    main()
