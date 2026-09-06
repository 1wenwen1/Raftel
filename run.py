"""Build, launch, and summarize Raftel experiments.

The script supports local and SSH-based runs, with optional replica fault
injection and Redis-backed application state. Its high-level workflow is to
resolve protocol topology, generate configuration, build binaries, run the
processes, and aggregate their throughput and latency statistics.

Several paths and defaults are shared with the C++ code, so they intentionally
remain module-level constants below.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import glob
import math
import multiprocessing
import os
from pathlib import Path
import shlex
import shutil
import signal
import stat
import statistics
import subprocess
from subprocess import PIPE, Popen
import threading
import time
from threading import Lock
from typing import Optional

from paramiko import AutoAddPolicy, SSHClient
from scp import SCPClient


# ---------------------------------------------------------------------------
# Protocol topology
# ---------------------------------------------------------------------------

# Each value is (replica-count factor, source branch). A factor of 3 means
# 3f+1 replicas; a factor of 2 means 2f+1 replicas.
_PROTOCOL_CHECKOUT = {
    "HybridTEE": (3, "main"),
    "Chained-HybridTEE": (3, "main"),
    "Achilles": (2, "main"),
    "Hotstuff": (3, "main"),
    "Basic-Damysus": (2, "main"),
}


def protocol_factor(protocol: str) -> int:
    """Return the coefficient in the protocol's ``factor * faults + 1`` size."""
    if protocol not in _PROTOCOL_CHECKOUT:
        raise ValueError(f"Unknown protocol: {protocol!r}")
    return _PROTOCOL_CHECKOUT[protocol][0]


def protocol_git_branch(protocol: str) -> str:
    """Return the source branch associated with ``protocol``."""
    if protocol not in _PROTOCOL_CHECKOUT:
        raise ValueError(f"Unknown protocol: {protocol!r}")
    return _PROTOCOL_CHECKOUT[protocol][1]


def num_replicas(factor: int, faults: int) -> int:
    """Calculate the replica population for a fault threshold."""
    return factor * faults + 1


def tee_quorum_size(totaltee: int, faults: int) -> int:
    """Return QT using the same formula as Handler::tqsize."""
    return max((totaltee // 2) + 1, faults + 1)


def protocol_totaltee(protocol: str, faults: int, totalnodes: int, requested: int) -> int:
    """Resolve the protocol-defined trusted replica population.

    Only HybridTEE exposes a configurable trusted population.  The remaining
    protocols use the populations from their original protocol definitions.
    """
    if protocol == "HybridTEE":
        return requested
    if protocol == "Chained-HybridTEE":
        return faults + 1
    if protocol in ("Achilles", "Basic-Damysus"):
        return totalnodes
    if protocol == "Hotstuff":
        return 0
    raise ValueError(f"Unknown protocol: {protocol!r}")


# ---------------------------------------------------------------------------
# Defaults and repository layout
# ---------------------------------------------------------------------------

# run.py CLI flags vs experiments.py (for comparable experiments)
# experiments.py uses --p1..--p8; run.py uses different numbering. Rough mapping:
#   run --p0 HybridTEE          -> BASIC_HYBRID_TEE
#   run --p1 Chained-Hybrid    ~ (no direct single flag; see experiments CH*)
#   run --p2 Achilles          ~ experiments Achilles branch
#   run --p3 Hotstuff          ~ experiments --p1 (BASE / BASIC_HOTSTUFF)
#   run --p4 Basic-Damysus     ~ upstream BASIC_CHEAP_AND_QUICK / BASIC_DAMYSUS
# Local defaults aligned with experiments.py: numViews=10, numClTrans=1, config isTEE:1 for all nodes.


# Paths (single place to change repo layout)
PROJECT_ROOT = Path(__file__).resolve().parent
# Remote SSH/SCP tree (default: same as local checkout; override if needed)
REMOTE_PROJECT_ROOT = Path(os.environ.get("DAMYSUS_REMOTE_ROOT", str(PROJECT_ROOT)))

raw_ip_list = PROJECT_ROOT / "aliyun" / "priv_ip.txt"
ip_list = PROJECT_ROOT / "ip_list"
clients = PROJECT_ROOT / "clients"
close_py = PROJECT_ROOT / "close.py"

# These output paths are initialized to their historical root for import
# compatibility. main() redirects them to the selected experiment directory.
RUN_OUTPUT_ROOT = PROJECT_ROOT
stats_dir = RUN_OUTPUT_ROOT / "results" / "current"
out_dir = RUN_OUTPUT_ROOT / "log" / "current"
stats_txt = RUN_OUTPUT_ROOT / "stats.txt"
exen = RUN_OUTPUT_ROOT / "exe"
client_stats_file = RUN_OUTPUT_ROOT / "client_stats"


# Experiment defaults. CLI arguments override the values exposed by main();
# the remaining values are shared by helper functions below.
sgxmode     = "SIM"
#sgxmode      = "HW"
srcsgx       = "source /opt/intel/sgxsdk/environment" # this is where the sdk is supposed to be installed
statsdir     = "stats"        # stats directory (don't change, hard coded in C++)
params       = "App/params.h" # (don't change, hard coded in C++)
config       = "App/config.h" # (don't change, hard coded in C++)
addresses    = RUN_OUTPUT_ROOT / "config"  # basename is hard coded in C++
useMultiCores = True
numMakeCores  = multiprocessing.cpu_count()  # number of cores to use to make
repeats      = 100 #10 #50 #5 #100 #2     # number of times to repeat each experiment
numViews     = 20     # number of views in each run
cutOffBound  = 60     # stop experiment after some time
#
numCTran     = 100   # number of transactions
numNonChCls  = 1     # number of clients for the non-chained versions
numChCls     = 1     # number of clients for the chained versions
numClTrans   = 1     # number of transactions sent by each clients
sleepTime    = 0     # start servers between 2 sends (in microseconds)
timeout      = 5     # timeout before changing changing leader (in seconds)
timeoutTime  = 240    #waiting time for the servers execution
# WAN / cloud runs (~100ms RTT): view-change timer near 2s is typical (override via --view-timeout).
kv_set_ratio = 30
kv_get_ratio = 60
kv_del_ratio = 10
kv_keyspace = 1000
kv_value_len = 16

# Build settings

# fault       = 1
# factor      = 3
# numTrans    = 400
# payloadsize = 256
# counterDelay = 0
forcrmake = True
no_stash = True
# SSH defaults
SSH_USERNAME = 'root'
SSH_KEY_PATH = './TShard'

# Deployment settings
numInstance   = 15 #number of instances run in a Machine
allLocalPorts = []    # list of all port numbers used in local experiments
ipsOfNodes    = {}    # dictionnary mapping node ids to IPs (local override)
startRport    = 8760
startCport    = 9760
startRedisPort = 6379
allLocalRedisPorts = []


def configure_output_paths(local: bool, experiment_number: Optional[int]) -> None:
    """Route generated artifacts to the directory for the selected run.

    Raw per-node measurements are collected under ``results/current`` and
    process logs under ``log/current``. Batch experiment wrappers archive those
    current-run files into case-specific subdirectories. Compiled binaries and
    generated params are cached under ``exe``; computed summaries are appended
    to ``stats.txt``.
    """
    global RUN_OUTPUT_ROOT, addresses, statsdir, stats_dir, out_dir, stats_txt, exen
    global client_stats_file

    if local:
        RUN_OUTPUT_ROOT = PROJECT_ROOT / "local_experiment"
    else:
        # A cloud run without an explicit experiment number is the minimal
        # smoke test and writes to experiment0.
        if experiment_number is None:
            experiment_number = 0
        RUN_OUTPUT_ROOT = (
            PROJECT_ROOT
            / "experiments_reproduction"
            / f"experiment{experiment_number}"
        )

    addresses = RUN_OUTPUT_ROOT / "config"
    stats_dir = RUN_OUTPUT_ROOT / "results" / "current"
    statsdir = str(stats_dir)
    out_dir = RUN_OUTPUT_ROOT / "log" / "current"
    stats_txt = RUN_OUTPUT_ROOT / "stats.txt"
    exen = RUN_OUTPUT_ROOT / "exe"
    client_stats_file = RUN_OUTPUT_ROOT / "client_stats"

    RUN_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    stats_dir.mkdir(parents=True, exist_ok=True)
    exen.mkdir(parents=True, exist_ok=True)


def prepare_local_runtime_files(debug: bool) -> None:
    """Copy SGX runtime files needed when local binaries use the new cwd."""
    if debug:
        return
    for filename in ("enclave.signed.so", "enclave.token"):
        source = PROJECT_ROOT / filename
        if source.is_file():
            shutil.copy2(source, RUN_OUTPUT_ROOT / filename)


# ---------------------------------------------------------------------------
# Configuration parsing and remote file transfer
# ---------------------------------------------------------------------------

def read_ip_list(filename):
    """Read non-empty host addresses from ``filename`` in file order."""
    with open(filename, 'r') as file:
        ip_list = [line.strip() for line in file.readlines() if line.strip()]
    return ip_list

def read_servers(total, filename):
    """Read at most ``total`` replica records from a generated config file."""
    servers = []
    with open(filename, 'r') as file:
        for line in file:
            parts = line.strip().split()
            id = int(parts[0].split(':')[1])
            host = parts[1].split(':')[1]
            port1 = int(parts[2].split(':')[1])
            port2 = int(parts[3].split(':')[1])
            servers.append((id, host, port1, port2))
            if(len(servers) == total):
                break
    return servers


def count_tee_nodes_in_config(filename) -> int:
    """
    Count nodes marked as TEE in config file.
    Expected token format per line: ... isTEE:<0|1>
    """
    cfg_path = Path(filename)
    if not cfg_path.is_absolute():
        cfg_path = PROJECT_ROOT / filename
    tee_count = 0
    if not cfg_path.exists():
        return 0
    with open(cfg_path, "r") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            for part in parts:
                if part.startswith("isTEE:"):
                    val = part.split(":", 1)[1]
                    tee_count += 1 if val == "1" else 0
                    break
    return tee_count

def scp_to_node(ip, files):
    """Copy every local path in ``files`` to one remote project directory."""
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(ip, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    transport = ssh.get_transport()
    if transport is None:
        raise RuntimeError(f"Failed to get transport for {ip}")
    with SCPClient(transport) as scp:
        for file in files:
            remote_path = str(REMOTE_PROJECT_ROOT)
            scp.put(file, remote_path=remote_path)
    ssh.close()

def remote_stats_dir() -> str:
    """Remote stats directory on each cluster node (under REMOTE_PROJECT_ROOT)."""
    return str(REMOTE_PROJECT_ROOT / "stats")


def ssh_clear_remote_stats_on_host(ip: str) -> None:
    """Recreate the remote stats directory once before launching replicas."""
    remote_stats = remote_stats_dir()
    bash = (
        f"mkdir -p {shlex.quote(remote_stats)} && "
        f"find {shlex.quote(remote_stats)} -mindepth 1 -maxdepth 1 -delete"
    )
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(ip, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    stdin, stdout, stderr = ssh.exec_command("bash -lc " + shlex.quote(bash))
    exit_code = stdout.channel.recv_exit_status()
    err = stderr.read().decode().strip()
    ssh.close()
    if exit_code != 0:
        raise RuntimeError(
            f"clear remote stats failed on {ip}: exit={exit_code} err={err}"
        )


def ssh_clear_remote_stats_on_hosts(ip_list, max_workers=6) -> None:
    """Clear each distinct remote host's stats directory exactly once."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(ssh_clear_remote_stats_on_host, ip)
            for ip in sorted(set(ip_list))
        ]
        for future in as_completed(futures):
            future.result()


def ssh_exec_server_non_blocking(
    id,
    host,
    port1,
    port2,
    debug,
    factor,
    faults,
    totaltee,
    completion_set,
    lock,
    num_views,
    opdist,
    *,
    view_timeout=None,
    leader_mode="rotate",
    leader_id=0,
    clear_remote_stats: bool = True,
    redis_enabled: bool = False,
):
    """Start one remote replica and monitor it in a background thread."""
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(host, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    nodeType = "TEE" if id < totaltee else "nonTEE"
    vc_to = float(timeout if view_timeout is None else view_timeout)
    # The repository checkout does not necessarily contain the runtime stats
    # directory.  Create it before the server opens stats/vals-* files.
    rm_stats = "mkdir -p stats && rm -rf stats/* && " if clear_remote_stats else "mkdir -p stats && "
    app_backend = "redis" if redis_enabled else "memory"
    if debug:
        cmd = f"export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/intel/sgxsdk/sdk_libs && export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib && cd {REMOTE_PROJECT_ROOT} && {rm_stats}./server {id} {nodeType} {totaltee} {faults} {factor} {num_views} {vc_to} {opdist} {leader_mode} {leader_id} {app_backend} > out{id}"
    else:
        cmd = f"export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/intel/sgxsdk/sdk_libs && export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib && cd {REMOTE_PROJECT_ROOT} && {rm_stats}./sgxserver {id} {nodeType} {totaltee} {faults} {factor} {num_views} {vc_to} {opdist} {leader_mode} {leader_id} {app_backend} > out{id}"
    stdin, stdout, stderr = ssh.exec_command(cmd)

    # Non-blocking monitoring of command execution status
    def monitor_ssh():
        stdout.channel.recv_exit_status() 
        output = stdout.read().decode()
        error = stderr.read().decode()
        # print(f"sgxserver on {host} with id {id} output:\n{output}")
        # print(f"sgxserver on {host} with id {id} error:\n{error}")
        with lock:
            completion_set.add((id, host))
        ssh.close()

    # start monitoring thread
    monitor_thread = threading.Thread(target=monitor_ssh)
    monitor_thread.start()

def ssh_exec_servers_non_blocking(
    servers,
    debug,
    factor,
    faults,
    totaltee,
    num_views,
    opdist,
    max_workers=6,
):
    """Start remote replicas and wait until the expected set completes."""
    completion_set = set()
    lock = Lock()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                ssh_exec_server_non_blocking,
                server[0],
                server[1],
                server[2],
                server[3],
                debug,
                factor,
                faults,
                totaltee,
                completion_set,
                lock,
                num_views,
                opdist,
            ): server
            for server in servers
        }
        for future in as_completed(futures):
            server = futures[future]
            try:
                future.result()
                print(f"sgxserver on {server[1]} with id {server[0]} started successfully.")
            except Exception as e:
                print(f"sgxserver on {server[1]} with id {server[0]} generated an exception: {e}")
    
    # waiting sgxserver instances to finish

    total = factor * faults + 1

    l = 0


    while len(completion_set) < total:
        if(len(completion_set) > l):
            l = len(completion_set)
            print(f'finishied {l}')
        print(f'completion_set {len(completion_set)}')
        time.sleep(5)

def ssh_exec_client(id, host, port1, port2, extra_params, totaltee):
    """Issue the legacy remote-client command on one host."""
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(host, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    cmd = f"sgxclient --id {id} --port1 {port1} --port2 {port2} {extra_params} {totaltee}"
    ssh.exec_command(cmd)
    ssh.close()

def scp_from_node(ip):
    """Fetch statistics using the legacy fixed remote paths."""
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(ip, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    transport = ssh.get_transport()
    if transport is None:
        raise RuntimeError(f"Failed to get transport for {ip}")

    with SCPClient(transport) as scp:
        scp.get('/remote/damysus/stats/*', local_path='damysus/stats/')  # 修改为实际的远程路径和本地路径
    ssh.close()

def scp_files_to_nodes(ip_list, files, max_workers=6):
    """Copy the same files to all hosts concurrently."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(scp_to_node, ip, files) for ip in ip_list]
        for future in futures:
            future.result()




def ssh_exec_client_on_id0(servers, extra_params, totaltee):
    """Start the legacy remote client on the host assigned replica zero."""
    id0_server = next((server for server in servers if server[0] == 0), None)
    if id0_server:
        time.sleep(5 + math.log(len(servers), 2))
        ssh_exec_client(id0_server[0], id0_server[1], id0_server[2], id0_server[3], extra_params, totaltee)

def scp_files_from_nodes(ip_list):
    """Fetch legacy statistics from all hosts concurrently."""
    threads = []
    for ip in ip_list:
        thread = threading.Thread(target=scp_from_node, args=(ip,))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()

def start_all_sgxservers(
    servers,
    debug,
    factor,
    faults,
    totaltee,
    num_views,
    opdist,
    max_workers=6,
    *,
    view_timeout=None,
    leader_mode="rotate",
    leader_id=0,
    clear_remote_stats: bool = True,
    redis_enabled: bool = False,
):
    """Dispatch every remote replica and return shared completion state."""
    completion_set = set()
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                ssh_exec_server_non_blocking,
                id,
                host,
                port1,
                port2,
                debug,
                factor,
                faults,
                totaltee,
                completion_set,
                lock,
                num_views,
                opdist,
                view_timeout=view_timeout,
                leader_mode=leader_mode,
                leader_id=leader_id,
                clear_remote_stats=clear_remote_stats,
                redis_enabled=redis_enabled,
            )
            for id, host, port1, port2 in servers
        ]
        for future in as_completed(futures):
            future.result()
    return completion_set, lock


def ssh_kill_sgxserver_on_host(host: str, replica_id=None) -> None:
    """
    Kill replica server process(es) on one VM. If replica_id is set, prefer matching argv id
    (multiple replicas per host would otherwise all receive pkill).
    """
    rp = str(REMOTE_PROJECT_ROOT)
    if replica_id is not None:
        pat = f"sgxserver {replica_id} "
        pat2 = f"./server {replica_id} "
        bash = (
            f"cd {shlex.quote(rp)} && "
            f"( pkill -f {shlex.quote(pat)} || true ) && "
            f"( pkill -f {shlex.quote(pat2)} || true )"
        )
    else:
        bash = (
            f"cd {shlex.quote(rp)} && "
            "( pkill -f sgxserver || true ) && "
            "( pkill -f './server' || true )"
        )
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(host, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    stdin, stdout, stderr = ssh.exec_command("bash -lc " + shlex.quote(bash))
    stdout.channel.recv_exit_status()
    ssh.close()


def ssh_stop_project_servers_on_host(host: str) -> None:
    """Stop all server processes launched from this repository on one host."""
    patterns = (r"^[.]/sgxserver( |$)", r"^[.]/server( |$)")
    bash = " && ".join(
        f"( pkill -TERM -f {shlex.quote(pattern)} || true )"
        for pattern in patterns
    )
    bash += "; sleep 1; " + " && ".join(
        f"( pkill -KILL -f {shlex.quote(pattern)} || true )"
        for pattern in patterns
    )
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(host, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    stdin, stdout, stderr = ssh.exec_command("bash -lc " + shlex.quote(bash))
    exit_code = stdout.channel.recv_exit_status()
    err = stderr.read().decode().strip()
    ssh.close()
    if exit_code != 0:
        raise RuntimeError(
            f"stop remote project servers failed on {host}: exit={exit_code} err={err}"
        )


def ssh_stop_project_servers_on_hosts(hosts, max_workers=6) -> None:
    """Stop repository server processes on every distinct participating host."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(ssh_stop_project_servers_on_host, host)
            for host in sorted(set(hosts))
        ]
        for future in as_completed(futures):
            future.result()


def poll_remote_stats_forever(ips, stop_event: threading.Event, interval_sec: float):
    """Periodically mirror every node's remote stats into this run's output tree."""
    remote_stats = remote_stats_dir()
    while not stop_event.wait(interval_sec):
        try:
            stats_dir.mkdir(parents=True, exist_ok=True)
            scp_stats_from_nodes(ips, str(stats_dir) + os.sep, remote_stats)
        except Exception as e:
            print("[fault-cloud] stats poll failed:", e)


def ssh_start_redis_on_node(host: str, replica_id: int):
    """
    One Redis per replica on that replica's host, same layout as start_local_redis_instances:
    port = startRedisPort + replica_id, bind 127.0.0.1.
    """
    port = startRedisPort + replica_id
    rp = str(REMOTE_PROJECT_ROOT)
    workdir = f"{rp}/stats/redis/r{replica_id}"
    bash = (
        "if ! command -v redis-server >/dev/null 2>&1; then "
        f"echo warning: redis-server not found on {host}; exit 2; fi; "
        f"mkdir -p {shlex.quote(workdir)}; "
        f"fuser -k {port}/tcp 2>/dev/null || true; "
        "redis-server "
        f"--port {port} --save '' --appendonly no --daemonize yes "
        f"--dir {shlex.quote(workdir)} --bind 127.0.0.1 --protected-mode no "
        f"|| {{ echo warning: redis-server start failed on {host} r{replica_id}; exit 3; }}; "
        # daemonized redis can take a short while to bind; retry before failing.
        "ok=0; "
        "for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do "
        f"  if command -v redis-cli >/dev/null 2>&1; then "
        f"    redis-cli -h 127.0.0.1 -p {port} ping 2>/dev/null | grep -q PONG && ok=1 && break; "
        "  else "
        f"    (echo > /dev/tcp/127.0.0.1/{port}) >/dev/null 2>&1 && ok=1 && break; "
        "  fi; "
        "  sleep 0.5; "
        "done; "
        "[ \"$ok\" = \"1\" ] || exit 4"
    )
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(host, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    stdin, stdout, stderr = ssh.exec_command("bash -lc " + shlex.quote(bash))
    exit_code = stdout.channel.recv_exit_status()
    err = stderr.read().decode().strip()
    ssh.close()
    if exit_code != 0:
        raise RuntimeError(
            f"remote redis setup/health-check failed on {host}:"
            f"{port} (replica {replica_id}), exit={exit_code}, err={err}"
        )


def start_remote_redis_for_servers(servers, max_workers=6):
    """Start one Redis instance for every configured remote replica."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(ssh_start_redis_on_node, host, rid)
            for rid, host, _p1, _p2 in servers
        ]
        for future in as_completed(futures):
            future.result()

# execute sgxclient locally (same argv as start_local_client_process / experiment_local)
def local_exec_client(
    debug,
    factor,
    faults,
    totaltee,
    num_cl_trans,
    client_id,
    cl_sleep_us,
    rep,
    kv_set,
    kv_get,
    kv_del,
    kv_keys,
    kv_vlen,
):
    """Start a local client for a cloud run and redirect it to a per-run log."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"client-cloud-rep{rep}-id{client_id}.log"
    log_fp = open(log_path, "w")
    client_bin = PROJECT_ROOT / ("client" if debug else "sgxclient")
    cmd = [
        str(client_bin),
        str(client_id),
        str(faults),
        str(factor),
        str(num_cl_trans),
        str(cl_sleep_us),
        str(rep),
        str(totaltee),
        str(kv_set),
        str(kv_get),
        str(kv_del),
        str(kv_keys),
        str(kv_vlen),
    ]
    proc = Popen(
        cmd,
        cwd=str(RUN_OUTPUT_ROOT),
        stdout=log_fp,
        stderr=log_fp,
        preexec_fn=os.setsid,
    )
    # Keep file handle alive for process lifetime.
    proc._log_fp = log_fp  # type: ignore[attr-defined]
    return proc

def cp_client_stats():
    """Append current client statistics to the long-lived client_stats file."""
    with open(client_stats_file, 'a') as f:
        f.write(f'numviews: {numViews}, numCTrans: {numCTran}, sleepttime: {sleepTime}\n')
    client_files = sorted(glob.glob(str(stats_dir / "client*")))
    if not client_files:
        # Keep this quiet when no client stats were produced in this run.
        return
    with open(client_stats_file, "a") as out:
        for fp in client_files:
            try:
                with open(fp, "r") as src:
                    out.write(src.read())
                out.write("\n")
            except OSError:
                continue
        out.write("\n")


# stop local sgxclient
def stop_local_sgxclient():
    """Persist client stats, then stop all local SGX client processes."""
    cp_client_stats()

    cmd = "pkill -f sgxclient"
    process = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()
    output = stdout.decode()
    error = stderr.decode()
    print(f"Stop sgxclient output:\n{output}")
    print(f"Stop sgxclient error:\n{error}")

def rm_local_stats():
    """Remove local stats contents while preserving the directory."""
    cmd = f"rm -rf {stats_dir}/*"
    process = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()
    output = stdout.decode()
    error = stderr.decode()

def stop_remote_server():
    """Stop project servers on every host in the generated run IP list."""
    ssh_stop_project_servers_on_hosts(read_ip_list(str(ip_list)))


def stop_local_clients() -> None:
    """Stop orchestrator-local clients left by an interrupted remote repeat."""
    for process_name in ("sgxclient", "client"):
        subprocess.run(
            ["pkill", "-TERM", "-x", process_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


# Block and wait for all sgxserver instances to end
def wait_for_all_sgxservers_to_finish(completion_set, lock, total_servers):
    """Wait for remote replicas, stopping the cluster after the timeout."""
    l = 0
    start_time = time.time()  # Start the timer
    while len(completion_set) < total_servers:
        if(len(completion_set) > l):
            l = len(completion_set)
            t = time.time()
            print(f'finishied {l}')
        # Check if the timeout has been reached
        if time.time() - start_time > timeoutTime:
            print(f"Timeout reached. Stopping remote server.")
            stop_remote_server()  # Stop the server if timeout
            break
    
    # If all servers finish, print a message
    if len(completion_set) == total_servers:
        print("All sgxserver instances have finished.")
            


def clear_local_stats():
    """Clear current raw results and prepare the C++ compatibility directory."""
    if stats_dir.exists() and stats_dir.is_dir():
        shutil.rmtree(stats_dir)
    stats_dir.mkdir(parents=True, exist_ok=True)

    # Server/client binaries still write files below a relative ``stats/``.
    # Keep that directory only while a run is active, then migrate its files.
    legacy_dir = RUN_OUTPUT_ROOT / "stats"
    if legacy_dir.exists() and legacy_dir.is_dir():
        shutil.rmtree(legacy_dir)
    legacy_dir.mkdir(parents=True, exist_ok=True)


def migrate_legacy_stats() -> None:
    """Move C++ ``stats/`` output into ``results/current`` and remove ``stats/``."""
    legacy_dir = RUN_OUTPUT_ROOT / "stats"
    if not legacy_dir.is_dir():
        return
    stats_dir.mkdir(parents=True, exist_ok=True)
    for source in legacy_dir.iterdir():
        target = stats_dir / source.name
        if source.is_dir():
            if target.exists():
                shutil.copytree(source, target, dirs_exist_ok=True)
                shutil.rmtree(source)
            else:
                shutil.move(str(source), str(target))
        else:
            if target.exists():
                target.unlink()
            shutil.move(str(source), str(target))
    legacy_dir.rmdir()

def cleanup_local_processes_and_ports(local_ports=None, include_redis=False):
    """
    Best-effort cleanup for local experiments:
    - kill known server/client binaries
    - free the provided TCP ports with fuser
    """
    process_names = "sgxserver sgxclient server client"
    if include_redis:
        process_names += " redis-server"
    subprocess.run(f"killall -q {process_names}", shell=True)
    if local_ports:
        ports = " ".join(map(lambda p: f"{p}/tcp", local_ports))
        subprocess.run(f"fuser -k {ports}", shell=True)
    # Give kernel/process manager a brief moment to release sockets fully.
    time.sleep(0.5)


def start_local_redis_instances(num_replicas: int):
    """
    Start one local Redis per replica (port = startRedisPort + replica_id).
    Uses daemon mode for simple lifecycle during local experiments.
    """
    global allLocalRedisPorts
    allLocalRedisPorts.clear()
    if shutil.which("redis-server") is None:
        print("warning: redis-server not found; KV app will fallback to in-memory backend")
        return

    # Always clean target Redis ports before a new local run.
    # This prevents stale daemonized redis-server processes from previous runs
    # (e.g. after Ctrl+Z / interrupted cleanup) from causing hangs/conflicts.
    target_ports = [startRedisPort + rid for rid in range(num_replicas)]
    if target_ports:
        ports_arg = " ".join(f"{p}/tcp" for p in target_ports)
        subprocess.run(f"fuser -k {ports_arg}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.2)

    redis_root = stats_dir / "redis"
    redis_root.mkdir(parents=True, exist_ok=True)
    for rid in range(num_replicas):
        port = startRedisPort + rid
        allLocalRedisPorts.append(port)
        workdir = redis_root / f"r{rid}"
        workdir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "redis-server",
            "--port", str(port),
            "--save", "",
            "--appendonly", "no",
            "--daemonize", "yes",
            "--dir", str(workdir),
            "--bind", "127.0.0.1",
            "--protected-mode", "no",
        ]
        subprocess.run(cmd, check=False)


def start_local_server_process(
    server_bin: str,
    replica_id: int,
    node_type: str,
    effective_totaltee: int,
    faults: int,
    factor: int,
    num_views: int,
    timeout_val: int,
    local_opdist: int,
    leader_mode: str = "rotate",
    leader_id: int = 0,
    redis_enabled: bool = False,
):
    """
    Start one local replica process without shell wrapping, so kill/terminate
    targets the real server process directly.
    """
    cmd = [
        server_bin,
        str(replica_id),
        node_type,
        str(effective_totaltee),
        str(faults),
        str(factor),
        str(num_views),
        str(timeout_val),
        str(local_opdist),
        leader_mode,
        str(leader_id),
        "redis" if redis_enabled else "memory",
    ]
    return Popen(cmd, cwd=str(RUN_OUTPUT_ROOT), preexec_fn=os.setsid)


def start_local_client_process(
    client_bin: str,
    client_id: int,
    faults: int,
    factor: int,
    num_cl_trans: int,
    cl_sleep_us: int,
    rep: int,
    effective_totaltee: int,
    kv_set: int,
    kv_get: int,
    kv_del: int,
    kv_keys: int,
    kv_vlen: int,
):
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"client-local-rep{rep}-id{client_id}.log"
    log_fp = open(log_path, "w")
    cmd = [
        client_bin,
        str(client_id),
        str(faults),
        str(factor),
        str(num_cl_trans),
        str(cl_sleep_us),
        str(rep),
        str(effective_totaltee),
        str(kv_set),
        str(kv_get),
        str(kv_del),
        str(kv_keys),
        str(kv_vlen),
    ]
    proc = Popen(
        cmd,
        cwd=str(RUN_OUTPUT_ROOT),
        stdout=log_fp,
        stderr=log_fp,
        preexec_fn=os.setsid,
    )
    # Keep file handle alive for process lifetime.
    proc._log_fp = log_fp  # type: ignore[attr-defined]
    return proc


def kill_local_process_tree(proc: subprocess.Popen):
    """
    Kill the process group if possible (preferred), otherwise kill the process.
    """
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        proc.kill()

# ---------------------------------------------------------------------------
# Statistics collection and aggregation
# ---------------------------------------------------------------------------

def scp_stats_from_node(ip, local_path, remote_path):
    """Copy regular result files from one host directly into ``local_path``."""
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(ip, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    sftp = ssh.open_sftp()
    destination = Path(local_path)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        for entry in sftp.listdir_attr(remote_path):
            if not stat.S_ISREG(entry.st_mode):
                continue
            sftp.get(
                f"{remote_path.rstrip('/')}/{entry.filename}",
                str(destination / entry.filename),
            )
    finally:
        sftp.close()
        ssh.close()

# Multi-threaded SCP stats content to local
def scp_stats_from_nodes(ip_list, local_path, remote_path, max_workers=6):
    """Collect remote statistics from all hosts concurrently."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(scp_stats_from_node, ip, local_path, remote_path) for ip in ip_list]
        for future in as_completed(futures):
            future.result()


def clear_local_client_logs():
    """
    Remove orchestrator client logs under log/current (client-*.log) so each run.py
    execution only keeps the latest client output.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for fp in out_dir.glob("client-*.log"):
        if fp.is_file():
            fp.unlink()


def clear_local_out_logs():
    """
    Remove stale remote-server out* logs from log/current before re-fetching.
    Preserve orchestrator client logs (client-*.log) written during this run.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for fp in out_dir.glob("*"):
        if fp.is_file():
            if fp.name.startswith("client-"):
                continue
            fp.unlink()


def clear_remote_server_out_logs():
    """
    Remove files previously fetched by scp_out_logs_from_node (names like
    "<host_with_underscores>-out..."). Does not delete client-*.log or other files.
    Call before each cloud experiment so log/current is not mixed with the last run.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for fp in out_dir.glob("*"):
        if not fp.is_file():
            continue
        if fp.name.startswith("client-"):
            continue
        if "-" not in fp.name:
            continue
        _, rest = fp.name.split("-", 1)
        if rest.startswith("out"):
            fp.unlink()


def ssh_clear_repo_out_logs_on_host(ip: str) -> None:
    """
    Delete server stdout logs under REMOTE_PROJECT_ROOT on one machine (files named out*,
    same convention as scp_out_logs_from_node / sgxserver redirection to out{id}).
    """
    rp = str(REMOTE_PROJECT_ROOT)
    bash = (
        f"cd {shlex.quote(rp)} && "
        "find . -maxdepth 1 -type f -name 'out*' -delete"
    )
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(ip, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    stdin, stdout, stderr = ssh.exec_command("bash -lc " + shlex.quote(bash))
    exit_code = stdout.channel.recv_exit_status()
    err = stderr.read().decode().strip()
    ssh.close()
    if exit_code != 0:
        raise RuntimeError(
            f"clear remote out logs failed on {ip}: exit={exit_code} err={err}"
        )


def ssh_clear_repo_out_logs_on_hosts(ip_list, max_workers=6):
    """Run ssh_clear_repo_out_logs_on_host on each distinct cluster IP."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(ssh_clear_repo_out_logs_on_host, ip) for ip in ip_list
        ]
        for future in as_completed(futures):
            future.result()


def scp_out_logs_from_node(ip: str, local_out_path: str):
    """
    Fetch remote out* logs from REMOTE_PROJECT_ROOT into local log/current.
    Prefix each filename with source host to avoid collisions.
    """
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    ssh.connect(ip, username=SSH_USERNAME, key_filename=SSH_KEY_PATH)
    sftp = ssh.open_sftp()
    try:
        remote_root = str(REMOTE_PROJECT_ROOT)
        for entry in sftp.listdir(remote_root):
            if not entry.startswith("out"):
                continue
            remote_fp = f"{remote_root}/{entry}"
            local_name = f"{ip.replace('.', '_')}-{entry}"
            local_fp = str(Path(local_out_path) / local_name)
            try:
                sftp.get(remote_fp, local_fp)
            except OSError:
                # Ignore transient or missing files and continue collecting others.
                continue
    finally:
        sftp.close()
        ssh.close()


def scp_out_logs_from_nodes(ip_list, local_out_path, max_workers=6):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(scp_out_logs_from_node, ip, local_out_path) for ip in ip_list]
        for future in as_completed(futures):
            future.result()


def collect_remote_artifacts(ips) -> None:
    """Collect raw node results and server logs into the current-run folders."""
    migrate_legacy_stats()
    stats_error = None
    try:
        stats_dir.mkdir(parents=True, exist_ok=True)
        scp_stats_from_nodes(
            ips,
            str(stats_dir) + os.sep,
            remote_stats_dir(),
        )
    except Exception as exc:
        stats_error = exc
    finally:
        clear_local_out_logs()
        scp_out_logs_from_nodes(ips, str(out_dir))

    if stats_error is not None:
        raise stats_error

def find_first_number(directory):
    """Return the first finite number found in an ``rtt-*`` file."""
    rtt_files = glob.glob(os.path.join(directory, 'rtt-*'))

    for file_path in rtt_files:
        with open(file_path, 'r') as file:
            line = file.readline().strip()
            if line:
                try:
                    first_value = float(line.split()[0])
                    if not math.isnan(first_value):
                        return first_value
                except ValueError:
                    continue

    print("No valid data found.")
    return None

def calculate_mean_of_values(directory, *, silent=False):
    """Average valid non-zero throughput/latency pairs from ``vals*`` files."""
    vals_files = glob.glob(os.path.join(directory, 'vals*'))
    total_count = 0
    sum_first = 0.0
    sum_second = 0.0

    for file_path in vals_files:
        with open(file_path, 'r') as file:
            line = file.readline().strip()
            if line:
                values = list(map(float, line.split()))
                if len(values) >= 2:
                    if values[0] == 0.0 or values[1] == 0.0:
                        if not silent:
                            print(
                                f"Skipping abnormal zero-valued stats: "
                                f"{file_path}: {values[0]}, {values[1]}"
                            )
                        continue
                    sum_first += values[0]
                    sum_second += values[1]
                    if not silent:
                        print(f'{total_count}, {values[0]}, {values[1]}')
                    total_count += 1

    if total_count > 0:
        mean_first = sum_first / total_count
        mean_second = sum_second / total_count
        if not silent:
            print(f"Mean of the first number across all vals files: {mean_first}")
            print(f"Mean of the second number across all vals files: {mean_second}")
        return (mean_first, mean_second)
    else:
        if not silent:
            print("No vals files found or no valid data.")
        return (0, 0)


def append_wan_stats_summary_row(label: Optional[str], thr_mean: float, lat_mean: float) -> None:
    """Append ``label, thr_mean, lat_mean`` to stats.txt (WAN sweep). Label must be non-empty."""
    if not label:
        return
    with open(stats_txt, "a") as f:
        f.write(f"{label}, {thr_mean}, {lat_mean}\n")


def compute_stats_like_experiments(stats_directory: str):
    """
    Same aggregation as experiments.computeStats: read each stats/vals* file
    (10 space-separated fields) and return view-averaged throughput/latency/etc.
    """
    migrate_legacy_stats()
    sd = stats_directory.rstrip(os.sep) + os.sep
    throughput_view_val = 0.0
    throughput_view_num = 0
    latency_view_val = 0.0
    latency_view_num = 0
    handle_val = 0.0
    handle_num = 0
    crypto_sign_val = 0.0
    crypto_sign_num = 0
    crypto_verif_val = 0.0
    crypto_verif_num = 0
    crypto_num_sign_val = 0.0
    crypto_num_sign_num = 0
    crypto_num_verif_val = 0.0
    crypto_num_verif_num = 0

    for filename in glob.glob(sd + "vals*"):
        with open(filename, "r") as f:
            s = f.read()
        parts = s.split()
        if len(parts) != 10:
            print("wrong vals file:", filename)
            continue
        (
            thru,
            lat,
            hdl,
            _tos,
            _pbs,
            _pcs,
            sign_num,
            sign_time,
            verif_num,
            verif_time,
        ) = parts
        val_th = float(thru)
        throughput_view_num += 1
        throughput_view_val += val_th
        val_la = float(lat)
        latency_view_num += 1
        latency_view_val += val_la
        val_hd = float(hdl)
        handle_num += 1
        handle_val += val_hd
        val_st = float(sign_time)
        crypto_sign_num += 1
        crypto_sign_val += val_st
        val_vt = float(verif_time)
        crypto_verif_num += 1
        crypto_verif_val += val_vt
        val_sn = int(sign_num)
        crypto_num_sign_num += 1
        crypto_num_sign_val += float(val_sn)
        val_vn = int(verif_num)
        crypto_num_verif_num += 1
        crypto_num_verif_val += float(val_vn)

    throughput_view = throughput_view_val / throughput_view_num if throughput_view_num > 0 else 0.0
    latency_view = latency_view_val / latency_view_num if latency_view_num > 0 else 0.0
    handle = handle_val / handle_num if handle_num > 0 else 0.0
    crypto_sign = crypto_sign_val / crypto_sign_num if crypto_sign_num > 0 else 0.0
    crypto_verif = crypto_verif_val / crypto_verif_num if crypto_verif_num > 0 else 0.0
    crypto_num_sign = crypto_num_sign_val / crypto_num_sign_num if crypto_num_sign_num > 0 else 0.0
    crypto_num_verif = crypto_num_verif_val / crypto_num_verif_num if crypto_num_verif_num > 0 else 0.0

    print("throughput-view:", throughput_view, "out of", throughput_view_num)
    print("latency-view:", latency_view, "out of", latency_view_num)
    print("handle:", handle, "out of", handle_num)
    print("crypto-sign:", crypto_sign, "out of", crypto_sign_num)
    print("crypto-verif:", crypto_verif, "out of", crypto_verif_num)
    print("crypto-num-sign:", crypto_num_sign, "out of", crypto_num_sign_num)
    print("crypto-num-verif:", crypto_num_verif, "out of", crypto_num_verif_num)

    return (
        throughput_view,
        latency_view,
        handle,
        crypto_sign,
        crypto_verif,
        crypto_num_sign,
        crypto_num_verif,
    )


def parse_client_e2e_stats(stats_directory: str):
    """
    Parse client-e2e-* files written by App/Client.cpp and return averaged metrics.
    Format per file:
      key value
    where key includes reply_throughput_ktps, e2e_latency_avg_ms, e2e_latency_p50_ms,
    e2e_latency_p95_ms, e2e_latency_p99_ms, ...
    """
    e2e_files = glob.glob(os.path.join(stats_directory, "client-e2e-*"))
    if not e2e_files:
        return None

    metrics = {
        "reply_throughput_ktps": [],
        "e2e_latency_avg_ms": [],
        "e2e_latency_p50_ms": [],
        "e2e_latency_p95_ms": [],
        "e2e_latency_p99_ms": [],
    }
    client_windows = []
    parsed_files = 0
    for fp in e2e_files:
        file_vals = {}
        try:
            with open(fp, "r") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    key, val = parts[0], parts[1]
                    if key in metrics:
                        try:
                            file_vals[key] = float(val)
                        except ValueError:
                            pass
                    elif key in ("num_completed", "first_reply_unix_us", "last_reply_unix_us"):
                        try:
                            file_vals[key] = float(val)
                        except ValueError:
                            pass
        except OSError:
            continue

        if file_vals:
            parsed_files += 1
            for k in metrics:
                if k in file_vals:
                    metrics[k].append(file_vals[k])
            if all(k in file_vals for k in
                   ("num_completed", "first_reply_unix_us", "last_reply_unix_us")):
                client_windows.append((
                    file_vals["num_completed"],
                    file_vals["first_reply_unix_us"],
                    file_vals["last_reply_unix_us"],
                ))

    if parsed_files == 0:
        return None

    avgs = {}
    for k, vals in metrics.items():
        avgs[k] = (sum(vals) / len(vals)) if vals else 0.0
    # Aggregate concurrent clients as one system: all completed requests over
    # the union of their reply windows.  Do not average per-client throughput.
    if len(client_windows) == parsed_files and client_windows:
        total_completed = sum(w[0] for w in client_windows)
        global_first_us = min(w[1] for w in client_windows)
        global_last_us = max(w[2] for w in client_windows)
        global_window_sec = (global_last_us - global_first_us) / 1_000_000.0
        if global_window_sec > 0.0:
            avgs["reply_throughput_ktps"] = (total_completed / global_window_sec) / 1000.0
        elif parsed_files == 1:
            # Preserve the client's duration-based fallback for a one-request run.
            avgs["reply_throughput_ktps"] = metrics["reply_throughput_ktps"][0]
        else:
            avgs["reply_throughput_ktps"] = 0.0
        avgs["num_completed"] = total_completed
        avgs["global_reply_window_sec"] = global_window_sec
        avgs["throughput_aggregation"] = "global"
    else:
        # A per-client average is not a system throughput.  A single legacy
        # file is still unambiguous; multiple old files must be regenerated.
        if parsed_files > 1:
            raise RuntimeError(
                "cannot aggregate multi-client throughput: client-e2e files lack "
                "num_completed/first_reply_unix_us/last_reply_unix_us; rebuild the client"
            )
        avgs["throughput_aggregation"] = "single_client_legacy"
    avgs["num_client_e2e_files"] = parsed_files
    return avgs


def wait_local_client_procs(client_procs, deadline_sec: float):
    """
    Wait for all orchestrator-local client processes to finish and flush client-e2e-*.
    Any client still alive after deadline_sec is terminated.
    """
    if not client_procs:
        return
    deadline = time.time() + deadline_sec
    while time.time() < deadline:
        if all(p.poll() is not None for p in client_procs):
            return
        time.sleep(0.5)
    alive = [p for p in client_procs if p.poll() is None]
    if alive:
        print(
            f"[warn] {len(alive)} local client(s) still running after {deadline_sec}s; "
            "terminating so run.py can collect stats"
        )
        for p in alive:
            kill_local_process_tree(p)


def close_client_log_handles(client_procs):
    for p in client_procs:
        fp = getattr(p, "_log_fp", None)
        if fp is not None:
            try:
                fp.close()
            except OSError:
                pass


def _live_file_replica_id(path: str):
    """Parse replica id from basename ``live-<id>-<stamp>``."""
    base = os.path.basename(path)
    if not base.startswith("live-"):
        return None
    rest = base[len("live-") :]
    dash = rest.find("-")
    if dash <= 0:
        return None
    try:
        return int(rest[:dash])
    except ValueError:
        return None


def plot_live_throughput(
    stats_directory: str,
    out_png: str,
    out_csv: str,
    *,
    reference_replica_id=None,
    exclude_replica_ids=None,
    aggregate_median=False,
):
    """
    Aggregate per-node stats/live-* into throughput (committed tx/s) vs time.
    Server counts each block's non-dummy transaction count (Block::getSize, up to batch)
    at the commit/execute entry, before application execution.

    Per-replica line format (current server):
      elapsedSec throughput_tx_per_sec view
    Legacy lines with an extra latency column are still accepted (throughput is always field 1).

    If reference_replica_id is set, only that replica's live-* files are used (single curve).
    Otherwise exclude_replica_ids (if non-empty) lists replica ids to omit from the mean
    (e.g. crashed node in fault experiments).

    aggregate_median: if True, use median across replicas per time bucket instead of mean.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    live_files = glob.glob(os.path.join(stats_directory, "live-*"))
    if reference_replica_id is not None:
        live_files = [
            fp
            for fp in live_files
            if _live_file_replica_id(fp) == reference_replica_id
        ]
        if not live_files:
            print(
                "no live-* files for reference replica",
                reference_replica_id,
                "under",
                stats_directory,
            )
            return
    elif exclude_replica_ids:
        excl = set(exclude_replica_ids)
        live_files = [fp for fp in live_files if _live_file_replica_id(fp) not in excl]
        if not live_files:
            print(
                "after excluding replicas",
                sorted(excl),
                "no live-* files left under",
                stats_directory,
            )
            return

    if not live_files:
        print("no live-* files found under", stats_directory)
        return

    if reference_replica_id is not None:
        print(f"[live-plot] reference replica {reference_replica_id}: {len(live_files)} live file(s)")
    elif exclude_replica_ids:
        print(
            f"[live-plot] excluding replicas {sorted(set(exclude_replica_ids))}: "
            f"{len(live_files)} live file(s)"
        )
    if aggregate_median:
        print("[live-plot] aggregating per time bucket with median (not mean)")

    samples_by_t = {}  # elapsed seconds (rounded) -> list of throughput samples
    for fp in live_files:
        try:
            with open(fp, "r") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    try:
                        t = float(parts[0])
                        thr = float(parts[1])
                        t_key = round(t, 2)
                    except ValueError:
                        continue
                    samples_by_t.setdefault(t_key, []).append(thr)
        except FileNotFoundError:
            continue

    if not samples_by_t:
        print("live-* files exist but no parsable samples found")
        return

    secs = sorted(samples_by_t.keys())
    thr_avg = []
    for s in secs:
        thrs = samples_by_t[s]
        if aggregate_median:
            thr_avg.append(statistics.median(thrs))
        else:
            thr_avg.append(sum(thrs) / len(thrs))

    with open(out_csv, "w") as f:
        f.write("sec throughput_tx_per_sec\n")
        for s, thr in zip(secs, thr_avg):
            f.write(f"{s} {thr}\n")

    fig, ax1 = plt.subplots(1, 1, figsize=(10, 4))
    ax1.plot(secs, thr_avg, marker="o", linewidth=1)
    ax1.set_xlabel("elapsed seconds")
    ax1.set_ylabel("throughput (committed tx/s)")
    ax1.grid(True, linestyle="--", alpha=0.4)

    curve_note = ""
    if reference_replica_id is not None:
        curve_note = f" [replica {reference_replica_id} only]"
    elif exclude_replica_ids:
        curve_note = f" [excluded replicas {sorted(set(exclude_replica_ids))}]"
    if aggregate_median:
        curve_note += " [median]"
    else:
        curve_note += " [mean]"
    fig.suptitle(
        f"Live throughput (tx/s) ({os.path.basename(stats_directory.rstrip(os.sep))}){curve_note}"
    )
    fig.tight_layout()  # type: ignore[attr-defined]
    fig.savefig(out_png)  # type: ignore[attr-defined]
    plt.close(fig)
    print("live curve written:", out_png, out_csv)


# ---------------------------------------------------------------------------
# Configuration generation and compilation
# ---------------------------------------------------------------------------

def mkConfig(n, totaltee):
    """Generate remote replica/client configs for ``n`` total replicas."""

    def generate_servers(ip_list, n, numInstance):
        server_lines = []
        used_ips = []

        # Use exactly n replicas (e.g. n = 3f+1). Do NOT inflate n to a multiple of
        # numInstance — that was forcing faults=1,factor=3 from n=4 up to 10 servers and
        # wrong isTEE placement for cloud configs.

        port_start = 8760
        server_id = 0
        # For each port (instance index), enumerate all hosts in order before moving to next port
        for instance_index in range(numInstance):
            base_port = port_start + instance_index
            port1 = base_port
            port2 = base_port + 1000
            for ip in ip_list:
                if server_id >= n:
                    break
                if ip not in used_ips:
                    used_ips.append(ip)
                is_tee = 1 if server_id < totaltee else 0
                server_lines.append(f"id:{server_id} host:{ip} port:{port1} port:{port2} isTEE:{is_tee}")
                server_id += 1
            if server_id >= n:
                break
        
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

    # Read IP list
    host_ips = read_ip_list(str(raw_ip_list))

    # Generate server configuration
    server_lines, used_ips = generate_servers(host_ips, n, numInstance)

    # Write to the configuration file
    write_servers(addresses, server_lines)
    write_ip_list(str(ip_list), used_ips)
    write_clients(str(clients), server_lines[0])
    
    return server_lines, used_ips
#end of mkConfig


## generates a local config file
def genLocalConf(n, filename, totaltee, *, all_is_tee_in_config=False):
    """
    If all_is_tee_in_config=True, every line has isTEE:1 (matches experiments.py local genLocalConf).
    Otherwise isTEE follows totaltee (id < totaltee -> 1).
    """
    open(filename, 'w').close()
    host = "127.0.0.1"

    global allLocalPorts
    allLocalPorts.clear()

    print("ips:", ipsOfNodes)

    f = open(filename, 'a')
    for i in range(n):
        host = ipsOfNodes.get(i, host)
        rport = startRport + i
        cport = startCport + i
        allLocalPorts.append(rport)
        allLocalPorts.append(cport)
        if all_is_tee_in_config:
            is_tee = 1
        else:
            is_tee = 1 if i < totaltee else 0
        f.write(
            "id:"
            + str(i)
            + " host:"
            + host
            + " port:"
            + str(rport)
            + " port:"
            + str(cport)
            + " isTEE:"
            + str(is_tee)
            + "\n"
        )
    f.close()
# End of genLocalConf



#make instance
def makeInstance(protocol, debug, batchsize, payload, faults, totaltee, pct):
    """Select protocol parameters and build or reuse its executable artifacts."""

    # MAX_NUM_TEE_SIGNATURES depends on totaltee, so binaries compiled for
    # different TEE populations must not share the same cache directory.
    pro_dir = str(exen / f"{protocol}_{faults}_{totaltee}_{payload}_{batchsize}_{pct}")

    factor = protocol_factor(protocol)
    branch = protocol_git_branch(protocol)
    # change to the correct branch
    cmd_stash = 'git stash &&'
    if no_stash:
        cmd_stash = ' '
    cmd = f"{cmd_stash} git checkout {branch}"

    process = Popen(cmd, shell=True, stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()
    output = stdout.decode()
    error = stderr.decode()
    print(f"Stop checkout output:\n{output}")
    print(f"Stop checkout error:\n{error}")

    # make params
    print(f"mkprotocol: {protocol}, factor:{factor}, batchsize: {batchsize}, payload: {payload}, teetotal: {totaltee}, pct: {pct}")
    mkParams(protocol,debug,factor,faults,totaltee,batchsize,payload,pct)

    folder_path = pro_dir
    if not os.path.exists(folder_path):
    # If the folder does not exist, create
        os.makedirs(folder_path)
        print(f"Folder '{folder_path}' created.")
    else:
        print(f"Folder '{folder_path}' already exists.")

 
    # check if built binary and params.h exist (debug uses server/, release uses sgxserver)
    if debug:
        server_path = os.path.join(folder_path, "server")
        params_h_path = os.path.join(folder_path, "params.h")
        server_exists = os.path.isfile(server_path)
        params_h_exists = os.path.isfile(params_h_path)
    else:
        sgxserver_path = os.path.join(folder_path, "sgxserver")
        params_h_path = os.path.join(folder_path, "params.h")
        server_exists = os.path.isfile(sgxserver_path)
        params_h_exists = os.path.isfile(params_h_path)
    
    # need to make or not
    need_make = True
    if server_exists and params_h_exists and not forcrmake:
        need_make = False
        print("Files exist and force make is disabled, skipping make")

    # make (debug: server+client; else: sgxserver)
    if need_make:
        print("Starting make process...")
        subprocess.call(["make","clean"])
        if debug:
            subprocess.call(["make","-j8","server","client"])
            for artifact in ("server", "client"):
                shutil.copy2(PROJECT_ROOT / artifact, folder_path)
        else:
            subprocess.run(["bash -c \"" + srcsgx + "\""], shell=True, check=True)
            subprocess.call(["make","-j",str(numMakeCores),"SGX_MODE="+sgxmode])
            for artifact in ("sgxserver", "sgxclient", "sgxkeys"):
                shutil.copy2(PROJECT_ROOT / artifact, folder_path)
        shutil.copy2(PROJECT_ROOT / "App" / "params.h", Path(folder_path) / "params.h")
        print("make finished")
    else:
        print("Skipping make process")
#end of makeInstance

# make params
def mkParams(protocol,debug,constFactor,numFaults,totaltee,numTrans,payloadSize,pct):
    """Write the compile-time constants consumed by the C++ build."""
    f = open(params, 'w')
    f.write("#ifndef PARAMS_H\n")
    f.write("#define PARAMS_H\n")
    f.write("\n")
    # f.write("#define " + protocol.value + "\n")
    if protocol == "HybridTEE":
        if debug:
            f.write("#define BASIC_HYBRID_TEE_DEBUG\n")
        else:
            f.write("#define BASIC_HYBRID_TEE\n")
    elif protocol == "Chained-HybridTEE":
        f.write("#define CHAINED_HYBRID_TEE\n")
    elif protocol == "Achilles":
        f.write("#define CHAINED_ACHILLES\n")
    elif protocol == "Hotstuff":
        f.write("#define BASIC_HOTSTUFF\n")
    elif protocol == "Basic-Damysus":
        f.write("#define BASIC_DAMYSUS\n")
    f.write("#define MAX_NUM_NODES " + str((constFactor*numFaults)+1) + "\n")

    # if protocol == "Chained-HybridTEE":
    #     f.write("#define MAX_NUM_SIGNATURES " + str(numFaults+1) + "\n")
    # else:
    #     f.write("#define MAX_NUM_SIGNATURES " + str((constFactor*numFaults)+1-numFaults) + "\n")
    f.write("#define MAX_NUM_SIGNATURES " + str((constFactor*numFaults)+1-numFaults) + "\n")
    # Keep the compile-time TEE-signature capacity consistent with the
    # runtime Handler threshold: tqsize = max(floor(m/2)+1, f+1).
    f.write("#define MAX_NUM_TEE_SIGNATURES " + str(tee_quorum_size(totaltee, numFaults)) + "\n")
    f.write("#define MAX_NUM_TRANSACTIONS " + str(numTrans) + "\n")
    f.write("#define PAYLOAD_SIZE " +str(payloadSize) + "\n")
    f.write("#define PERSISTENT_COUNTER_TIME " +str(pct) + "\n")
    f.write("\n")
    f.write("#endif\n")
    f.close()
# End of mkParams






# ---------------------------------------------------------------------------
# Experiment runners
# ---------------------------------------------------------------------------

def experiment_local(
    protocol,
    debug,
    batchsize,
    payload,
    faults,
    totaltee,
    pct,
    *,
    num_views=10,
    num_cl_trans=1,
    num_clients=1,
    cl_sleep_us=50,
    repeats=1,
    config_by_totaltee=True,
    local_opdist=0,
    leader_mode="rotate",
    leader_id=0,
    print_vals_means=False,
    cutoff_sec=None,
    stats_summary_label=None,
    redis_enabled=False,
):
    """
    Local run aligned with experiments.py: execute() + computeStats() + computeAvgStats() loop.

    - num_views: per-server view budget (experiments default 10).
    - num_cl_trans: transactions sent by each client (argv[4], default 1).
    - num_clients: number of client processes to start (default 1).
    - cl_sleep_us: client send interval in microseconds (argv[5], default 50).
    - batchsize: still only used for compile-time MAX_NUM_TRANSACTIONS via makeInstance/mkParams.
    - config_by_totaltee: if True, config uses --totaltee (first totaltee nodes are isTEE:1).
    """
    factor = protocol_factor(protocol)
    total = num_replicas(factor, faults)
    pro_dir = f"{protocol}_{faults}_{totaltee}_{payload}_{batchsize}_{pct}"

    server_bin = str(PROJECT_ROOT / ("server" if debug else "sgxserver"))
    client_bin = str(PROJECT_ROOT / ("client" if debug else "sgxclient"))
    stats_directory = str(stats_dir) + os.sep

    throughput_views = []
    latency_views = []
    handles = []
    crypto_signs = []
    crypto_verifs = []
    crypto_num_signs = []
    crypto_num_verifs = []
    e2e_reply_throughputs = []
    e2e_lat_avg = []
    e2e_lat_p50 = []
    e2e_lat_p95 = []
    e2e_lat_p99 = []
    good_values = 0

    clear_local_client_logs()
    for rep in range(repeats):
        # Fault-mode runs may need more time after killing one replica.
        # Keep user-provided --cutoff-sec as highest priority; otherwise use
        # a longer default than the non-fault local path.
        run_cutoff = int(cutoff_sec) if cutoff_sec is not None else timeoutTime
        print(
            ">>>>>>>>>>>>>>>>>>>>",
            f"protocol={protocol}",
            f"payload={payload}",
            f"factor={factor}",
            f"faults={faults}",
            f"repeat={rep}",
            f"num_views={num_views}",
            f"num_cl_trans={num_cl_trans}",
            f"cutoff_sec={run_cutoff}",
        )
        genLocalConf(
            total,
            addresses,
            totaltee,
            all_is_tee_in_config=not config_by_totaltee,
        )
        effective_totaltee = count_tee_nodes_in_config(addresses)
        effective_pro_dir = f"{protocol}_{faults}_{effective_totaltee}_{payload}_{batchsize}_{pct}"
        if rep == 0:
            pro_dir = effective_pro_dir
        # Cleanup BEFORE startup to avoid "Address already in use" from stale processes.
        cleanup_local_processes_and_ports(
            allLocalPorts + (allLocalRedisPorts if redis_enabled else []),
            include_redis=redis_enabled,
        )
        clear_local_stats()
        if redis_enabled:
            start_local_redis_instances(total)

        rep_procs = []
        client_procs = []
        try:
            for i in range(total):
                if i % 10 == 5:
                    time.sleep(2)
                # Keep runtime node type consistent with config's isTEE count.
                node_type = "TEE" if i < effective_totaltee else "nonTEE"
                p = start_local_server_process(
                    server_bin,
                    i,
                    node_type,
                    effective_totaltee,
                    faults,
                    factor,
                    num_views,
                    timeout,
                    local_opdist,
                    leader_mode,
                    leader_id,
                    redis_enabled,
                )
                rep_procs.append(("R", i, p))

            print("started", len(rep_procs), "replicas")

            wait = 5 + int(math.ceil(math.log(faults, 2)))
            time.sleep(wait)

            for client_id in range(num_clients):
                client_proc = start_local_client_process(
                    client_bin,
                    client_id,
                    faults,
                    factor,
                    num_cl_trans,
                    cl_sleep_us,
                    rep,
                    effective_totaltee,
                    kv_set_ratio,
                    kv_get_ratio,
                    kv_del_ratio,
                    kv_keyspace,
                    kv_value_len,
                )
                client_procs.append(client_proc)
            print("started", len(client_procs), "clients")

            total_time = 0
            remaining = rep_procs.copy()
            replicas_done_since = None
            client_grace_sec = 5
            client_done_since = None
            server_after_client_grace_sec = 5
            while total_time < run_cutoff:
                updated_remaining = []
                for (tag, rid, proc) in remaining:
                    done_file_ready = len(glob.glob(statsdir + "/done-" + str(rid) + "*")) > 0
                    proc_exited = (proc.poll() is not None)
                    if proc_exited and proc.returncode != 0:
                        raise RuntimeError(
                            f"replica {rid} exited with status {proc.returncode}; "
                            "inspect the replica stderr above"
                        )
                    if not done_file_ready and not proc_exited:
                        updated_remaining.append((tag, rid, proc))
                remaining = updated_remaining
                client_exited = bool(client_procs) and all(p.poll() is not None for p in client_procs)
                client_e2e_ready = len(glob.glob(statsdir + "/client-e2e-*")) >= num_clients
                if client_exited or client_e2e_ready:
                    if client_done_since is None:
                        client_done_since = time.time()
                # If client is done but some server does not exit / write done-*,
                # do not block too long; proceed to cleanup and stats aggregation.
                if client_done_since is not None and len(remaining) > 0:
                    if (time.time() - client_done_since) >= server_after_client_grace_sec:
                        print(
                            f"[warn] client finished but {len(remaining)} server(s) still pending after "
                            f"{server_after_client_grace_sec}s; continue with cleanup"
                        )
                        break
                if len(remaining) == 0:
                    if replicas_done_since is None:
                        replicas_done_since = time.time()
                    if client_exited or client_e2e_ready:
                        break
                    if (time.time() - replicas_done_since) >= client_grace_sec:
                        print(
                            f"[warn] replicas done but client still running after {client_grace_sec}s; "
                            "continue with cleanup"
                        )
                        break
                print(
                    "remaining processes:",
                    remaining,
                    "client_exited=",
                    client_exited,
                    "client_e2e_ready=",
                    client_e2e_ready,
                )
                time.sleep(1)
                total_time += 1

            if total_time < run_cutoff:
                print("all", len(rep_procs) + len(client_procs), "processes are done")
            else:
                print(f"------ reached cutoff bound ({run_cutoff}s) ------")

        finally:
            for (_, i, p) in rep_procs:
                if p.poll() is None:
                    print("still running:", ("R", i, p.poll()))
                    kill_local_process_tree(p)
            for idx, p in enumerate(client_procs):
                if p.poll() is None:
                    print("still running:", ("C", idx, p.poll()))
                    kill_local_process_tree(p)
            close_client_log_handles(client_procs)
            # Always cleanup ports even on exceptions / KeyboardInterrupt.
            cleanup_local_processes_and_ports(
                allLocalPorts + (allLocalRedisPorts if redis_enabled else []),
                include_redis=redis_enabled,
            )

        (
            throughput_view,
            latency_view,
            handle,
            crypto_sign,
            crypto_verif,
            crypto_num_sign,
            crypto_num_verif,
        ) = compute_stats_like_experiments(stats_directory)

        # Live curve: aggregate stats/live-* written during this repeat.
        live_out_png = str(stats_dir / f"live-curve-{pro_dir}-rep{rep}.png")
        live_out_csv = str(stats_dir / f"live-curve-{pro_dir}-rep{rep}.csv")
        plot_live_throughput(stats_directory, live_out_png, live_out_csv)

        # Fault experiments may end before recordStats() writes vals/done; in that case,
        # fall back to the last live curve point so you still get throughput/latency output.
        vals_present = len(glob.glob(stats_directory + "/vals-*")) > 0
        if not vals_present and os.path.exists(live_out_csv):
            try:
                with open(live_out_csv, "r") as f:
                    last = None
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("sec"):
                            continue
                        last = line
                if last:
                    parts = last.split()
                    if len(parts) >= 2:
                        throughput_view = float(parts[1])
            except Exception:
                pass

        # For fault-injection runs, we mainly care about throughput (live curve is tx/s only).
        # Other counters (handle/crypto-*) may legitimately drop to 0 after a crash.
        good_cond = throughput_view > 0

        if good_cond:
            throughput_views.append(throughput_view)
            latency_views.append(latency_view)
            handles.append(handle)
            crypto_signs.append(crypto_sign)
            crypto_verifs.append(crypto_verif)
            crypto_num_signs.append(crypto_num_sign)
            crypto_num_verifs.append(crypto_num_verif)
            good_values += 1

        if print_vals_means:
            calculate_mean_of_values(stats_directory)
        e2e_stats = parse_client_e2e_stats(stats_directory)
        if e2e_stats is not None:
            e2e_reply_throughputs.append(e2e_stats["reply_throughput_ktps"])
            e2e_lat_avg.append(e2e_stats["e2e_latency_avg_ms"])
            e2e_lat_p50.append(e2e_stats["e2e_latency_p50_ms"])
            e2e_lat_p95.append(e2e_stats["e2e_latency_p95_ms"])
            e2e_lat_p99.append(e2e_stats["e2e_latency_p99_ms"])
            print(
                "client e2e (rep",
                rep,
                "):",
                "reply_ktps=",
                e2e_stats["reply_throughput_ktps"],
                "avg_ms=",
                e2e_stats["e2e_latency_avg_ms"],
                "p95_ms=",
                e2e_stats["e2e_latency_p95_ms"],
                "p99_ms=",
                e2e_stats["e2e_latency_p99_ms"],
                "files=",
                int(e2e_stats["num_client_e2e_files"]),
            )
        cp_client_stats()

    avg_throughput = sum(throughput_views) / good_values if good_values > 0 else 0.0
    avg_latency = sum(latency_views) / good_values if good_values > 0 else 0.0
    avg_handle = sum(handles) / good_values if good_values > 0 else 0.0
    avg_crypto_sign = sum(crypto_signs) / good_values if good_values > 0 else 0.0
    avg_crypto_verif = sum(crypto_verifs) / good_values if good_values > 0 else 0.0
    avg_crypto_num_sign = sum(crypto_num_signs) / good_values if good_values > 0 else 0.0
    avg_crypto_num_verif = sum(crypto_num_verifs) / good_values if good_values > 0 else 0.0
    avg_e2e_reply_tps = (
        sum(e2e_reply_throughputs) / len(e2e_reply_throughputs)
        if e2e_reply_throughputs
        else 0.0
    )
    avg_e2e_lat_avg_ms = (sum(e2e_lat_avg) / len(e2e_lat_avg)) if e2e_lat_avg else 0.0
    avg_e2e_lat_p50_ms = (sum(e2e_lat_p50) / len(e2e_lat_p50)) if e2e_lat_p50 else 0.0
    avg_e2e_lat_p95_ms = (sum(e2e_lat_p95) / len(e2e_lat_p95)) if e2e_lat_p95 else 0.0
    avg_e2e_lat_p99_ms = (sum(e2e_lat_p99) / len(e2e_lat_p99)) if e2e_lat_p99 else 0.0

    print("avg throughput (view):", avg_throughput)
    print("avg latency (view):", avg_latency)
    print("avg handle:", avg_handle)
    print("avg crypto (sign):", avg_crypto_sign)
    print("avg crypto (verif):", avg_crypto_verif)
    print("avg crypto (sign-num):", avg_crypto_num_sign)
    print("avg crypto (verif-num):", avg_crypto_num_verif)
    print("avg client reply throughput (e2e):", avg_e2e_reply_tps)
    print("avg client e2e latency avg (ms):", avg_e2e_lat_avg_ms)
    print("avg client e2e latency p50 (ms):", avg_e2e_lat_p50_ms)
    print("avg client e2e latency p95 (ms):", avg_e2e_lat_p95_ms)
    print("avg client e2e latency p99 (ms):", avg_e2e_lat_p99_ms)
    print("num e2e repeats=", len(e2e_reply_throughputs))
    print("num complete runs=", repeats)
    print("num good stat runs=", good_values)

    if stats_summary_label is None:
        with open(stats_txt, 'a') as f:
            f.write(
                f"{pro_dir}, thr_view={avg_throughput}, lat_view={avg_latency}, "
                f"e2e_reply_tps={avg_e2e_reply_tps}, e2e_lat_avg={avg_e2e_lat_avg_ms}, "
                f"e2e_lat_p50={avg_e2e_lat_p50_ms}, e2e_lat_p95={avg_e2e_lat_p95_ms}, "
                f"e2e_lat_p99={avg_e2e_lat_p99_ms}, good={good_values}/{repeats},\n"
            )
    else:
        vr1, vr2 = calculate_mean_of_values(stats_directory, silent=True)
        append_wan_stats_summary_row(stats_summary_label, vr1, vr2)
    print(
        pro_dir,
        "thr_view=",
        avg_throughput,
        "lat_view=",
        avg_latency,
        "e2e_reply_tps=",
        avg_e2e_reply_tps,
        "e2e_p95=",
        avg_e2e_lat_p95_ms,
        "e2e_p99=",
        avg_e2e_lat_p99_ms,
    )


def experiment_fault_local(
    protocol,
    debug,
    batchsize,
    payload,
    faults,
    totaltee,
    pct,
    *,
    dead_node_id: int = 1,
    kill_after_sec: float = 2.0,
    num_views=10,
    num_cl_trans=1,
    num_clients=1,
    cl_sleep_us=50,
    repeats=1,
    config_by_totaltee=True,
    local_opdist=0,
    leader_mode="rotate",
    leader_id=0,
    print_vals_means=False,
    cutoff_sec=None,
    live_plot_reference_replica=None,
    live_plot_exclude_fault_node=True,
    live_plot_aggregate_median=False,
    stats_summary_label=None,
    redis_enabled=False,
):
    """
    Local experiment with one replica crash during execution.

    - dead_node_id: replica index to kill (0..total-1)
    - kill_after_sec: seconds after starting client
    """
    factor = protocol_factor(protocol)
    total = num_replicas(factor, faults)
    pro_dir = f"{protocol}_{faults}_{totaltee}_{payload}_{batchsize}_{pct}"

    server_bin = str(PROJECT_ROOT / ("server" if debug else "sgxserver"))
    client_bin = str(PROJECT_ROOT / ("client" if debug else "sgxclient"))
    stats_directory = str(stats_dir) + os.sep

    throughput_views = []
    latency_views = []
    handles = []
    crypto_signs = []
    crypto_verifs = []
    crypto_num_signs = []
    crypto_num_verifs = []
    e2e_reply_throughputs = []
    e2e_lat_avg = []
    e2e_lat_p50 = []
    e2e_lat_p95 = []
    e2e_lat_p99 = []
    good_values = 0

    clear_local_client_logs()
    for rep in range(repeats):
        run_cutoff = int(cutoff_sec) if cutoff_sec is not None else cutOffBound
        print(
            ">>>>>>>>>>>>>>>>>>>>",
            f"protocol={protocol}",
            f"payload={payload}",
            f"factor={factor}",
            f"faults={faults}",
            f"repeat={rep}",
            f"num_views={num_views}",
            f"num_cl_trans={num_cl_trans}",
            f"dead_node_id={dead_node_id}",
            f"kill_after_sec={kill_after_sec}",
            f"cutoff_sec={run_cutoff}",
        )

        genLocalConf(
            total,
            addresses,
            totaltee,
            all_is_tee_in_config=not config_by_totaltee,
        )
        effective_totaltee = count_tee_nodes_in_config(addresses)
        effective_pro_dir = f"{protocol}_{faults}_{effective_totaltee}_{payload}_{batchsize}_{pct}"
        if rep == 0:
            pro_dir = effective_pro_dir

        cleanup_local_processes_and_ports(
            allLocalPorts + (allLocalRedisPorts if redis_enabled else []),
            include_redis=redis_enabled,
        )
        clear_local_stats()
        if redis_enabled:
            start_local_redis_instances(total)

        rep_procs = []
        client_procs = []
        killed_dead_node = False
        client_start_ts = None
        try:
            for i in range(total):
                if i % 10 == 5:
                    time.sleep(2)
                node_type = "TEE" if i < effective_totaltee else "nonTEE"
                p = start_local_server_process(
                    server_bin,
                    i,
                    node_type,
                    effective_totaltee,
                    faults,
                    factor,
                    num_views,
                    timeout,
                    local_opdist,
                    leader_mode,
                    leader_id,
                    redis_enabled,
                )
                rep_procs.append(("R", i, p))

            print("started", len(rep_procs), "replicas")

            wait = 5 + int(math.ceil(math.log(faults, 2)))
            time.sleep(wait)

            for client_id in range(num_clients):
                client_proc = start_local_client_process(
                    client_bin,
                    client_id,
                    faults,
                    factor,
                    num_cl_trans,
                    cl_sleep_us,
                    rep,
                    effective_totaltee,
                    kv_set_ratio,
                    kv_get_ratio,
                    kv_del_ratio,
                    kv_keyspace,
                    kv_value_len,
                )
                client_procs.append(client_proc)
            print("started", len(client_procs), "clients")
            client_start_ts = time.time()

            total_time = 0
            remaining = rep_procs.copy()
            replicas_done_since = None
            client_grace_sec = 5
            client_done_since = None
            server_after_client_grace_sec = 5
            while total_time < run_cutoff:
                # Kill the target replica once during the run.
                if (not killed_dead_node) and (client_start_ts is not None):
                    if (time.time() - client_start_ts) >= kill_after_sec:
                        for (_, i, p) in rep_procs:
                            if i == dead_node_id and p.poll() is None:
                                print(f"[fault] killing replica {i} at t≈{time.time() - client_start_ts:.2f}s")
                                kill_local_process_tree(p)
                                time.sleep(0.2)
                                print(f"[fault] replica {i} poll={p.poll()} (None means still alive)")
                        # Remove it from waiting list so we don't block on done-*.
                        remaining = list(filter(lambda x: x[1] != dead_node_id, remaining))
                        killed_dead_node = True

                updated_remaining = []
                for (tag, rid, proc) in remaining:
                    done_file_ready = len(glob.glob(statsdir + "/done-" + str(rid) + "*")) > 0
                    proc_exited = (proc.poll() is not None)
                    if proc_exited and proc.returncode != 0 and rid != dead_node_id:
                        raise RuntimeError(
                            f"replica {rid} exited with status {proc.returncode}; "
                            "inspect the replica stderr above"
                        )
                    if not done_file_ready and not proc_exited:
                        updated_remaining.append((tag, rid, proc))
                remaining = updated_remaining
                client_exited = bool(client_procs) and all(p.poll() is not None for p in client_procs)
                client_e2e_ready = len(glob.glob(statsdir + "/client-e2e-*")) >= num_clients
                if client_exited or client_e2e_ready:
                    if client_done_since is None:
                        client_done_since = time.time()
                if client_done_since is not None and len(remaining) > 0:
                    if (time.time() - client_done_since) >= server_after_client_grace_sec:
                        print(
                            f"[warn] client finished but {len(remaining)} server(s) still pending after "
                            f"{server_after_client_grace_sec}s; continue with cleanup (fault mode)"
                        )
                        break
                if len(remaining) == 0:
                    if replicas_done_since is None:
                        replicas_done_since = time.time()
                    if client_exited or client_e2e_ready:
                        break
                    if (time.time() - replicas_done_since) >= client_grace_sec:
                        print(
                            f"[warn] replicas done but client still running after {client_grace_sec}s; "
                            "continue with cleanup (fault mode)"
                        )
                        break
                print(
                    "remaining processes:",
                    remaining,
                    "client_exited=",
                    client_exited,
                    "client_e2e_ready=",
                    client_e2e_ready,
                )
                time.sleep(1)
                total_time += 1

            if total_time < run_cutoff:
                print("all", len(rep_procs) + len(client_procs), "processes are done (fault mode)")
            else:
                print(
                    "------ reached cutoff bound "
                    f"(fault mode, {run_cutoff}s). "
                    "Processes are force-stopped by run.py. "
                    "Use --cutoff-sec to increase this window. ------"
                )

        finally:
            for (_, i, p) in rep_procs:
                if p.poll() is None:
                    print("still running:", ("R", i, p.poll()))
                    kill_local_process_tree(p)
            for idx, p in enumerate(client_procs):
                if p.poll() is None:
                    print("still running:", ("C", idx, p.poll()))
                    kill_local_process_tree(p)
            close_client_log_handles(client_procs)
            cleanup_local_processes_and_ports(
                allLocalPorts + (allLocalRedisPorts if redis_enabled else []),
                include_redis=redis_enabled,
            )

        (
            throughput_view,
            latency_view,
            handle,
            crypto_sign,
            crypto_verif,
            crypto_num_sign,
            crypto_num_verif,
        ) = compute_stats_like_experiments(stats_directory)

        live_out_png = str(stats_dir / f"live-curve-{pro_dir}-rep{rep}-fault.png")
        live_out_csv = str(stats_dir / f"live-curve-{pro_dir}-rep{rep}-fault.csv")
        plot_live_throughput(
            stats_directory,
            live_out_png,
            live_out_csv,
            reference_replica_id=live_plot_reference_replica,
            exclude_replica_ids=(
                {dead_node_id}
                if live_plot_exclude_fault_node and live_plot_reference_replica is None
                else None
            ),
            aggregate_median=live_plot_aggregate_median,
        )

        # If fault kills consensus before recordStats() writes vals/done,
        # fall back to the last live curve point so we still output throughput/latency.
        vals_present = len(glob.glob(stats_directory + "/vals-*")) > 0
        if not vals_present and os.path.exists(live_out_csv):
            try:
                with open(live_out_csv, "r") as f:
                    last = None
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("sec"):
                            continue
                        last = line
                if last:
                    parts = last.split()
                    if len(parts) >= 2:
                        throughput_view = float(parts[1])
            except Exception:
                pass

        # For fault-injection runs, we mainly care about throughput (live curve is tx/s only).
        # Other counters (handle/crypto-*) may legitimately drop to 0 after a crash.
        good_cond = throughput_view > 0

        if good_cond:
            throughput_views.append(throughput_view)
            latency_views.append(latency_view)
            handles.append(handle)
            crypto_signs.append(crypto_sign)
            crypto_verifs.append(crypto_verif)
            crypto_num_signs.append(crypto_num_sign)
            crypto_num_verifs.append(crypto_num_verif)
            good_values += 1

        if print_vals_means:
            calculate_mean_of_values(stats_directory)
        e2e_stats = parse_client_e2e_stats(stats_directory)
        if e2e_stats is not None:
            e2e_reply_throughputs.append(e2e_stats["reply_throughput_ktps"])
            e2e_lat_avg.append(e2e_stats["e2e_latency_avg_ms"])
            e2e_lat_p50.append(e2e_stats["e2e_latency_p50_ms"])
            e2e_lat_p95.append(e2e_stats["e2e_latency_p95_ms"])
            e2e_lat_p99.append(e2e_stats["e2e_latency_p99_ms"])
            print(
                "client e2e (rep",
                rep,
                "fault):",
                "reply_ktps=",
                e2e_stats["reply_throughput_ktps"],
                "avg_ms=",
                e2e_stats["e2e_latency_avg_ms"],
                "p95_ms=",
                e2e_stats["e2e_latency_p95_ms"],
                "p99_ms=",
                e2e_stats["e2e_latency_p99_ms"],
                "files=",
                int(e2e_stats["num_client_e2e_files"]),
            )
        cp_client_stats()

    avg_throughput = sum(throughput_views) / good_values if good_values > 0 else 0.0
    avg_latency = sum(latency_views) / good_values if good_values > 0 else 0.0
    avg_handle = sum(handles) / good_values if good_values > 0 else 0.0
    avg_crypto_sign = sum(crypto_signs) / good_values if good_values > 0 else 0.0
    avg_crypto_verif = sum(crypto_verifs) / good_values if good_values > 0 else 0.0
    avg_crypto_num_sign = sum(crypto_num_signs) / good_values if good_values > 0 else 0.0
    avg_crypto_num_verif = sum(crypto_num_verifs) / good_values if good_values > 0 else 0.0
    avg_e2e_reply_tps = (
        sum(e2e_reply_throughputs) / len(e2e_reply_throughputs)
        if e2e_reply_throughputs
        else 0.0
    )
    avg_e2e_lat_avg_ms = (sum(e2e_lat_avg) / len(e2e_lat_avg)) if e2e_lat_avg else 0.0
    avg_e2e_lat_p50_ms = (sum(e2e_lat_p50) / len(e2e_lat_p50)) if e2e_lat_p50 else 0.0
    avg_e2e_lat_p95_ms = (sum(e2e_lat_p95) / len(e2e_lat_p95)) if e2e_lat_p95 else 0.0
    avg_e2e_lat_p99_ms = (sum(e2e_lat_p99) / len(e2e_lat_p99)) if e2e_lat_p99 else 0.0

    print("avg throughput (view):", avg_throughput)
    print("avg latency (view):", avg_latency)
    print("avg handle:", avg_handle)
    print("avg crypto (sign):", avg_crypto_sign)
    print("avg crypto (verif):", avg_crypto_verif)
    print("avg crypto (sign-num):", avg_crypto_num_sign)
    print("avg crypto (verif-num):", avg_crypto_num_verif)
    print("avg client reply throughput (e2e):", avg_e2e_reply_tps)
    print("avg client e2e latency avg (ms):", avg_e2e_lat_avg_ms)
    print("avg client e2e latency p50 (ms):", avg_e2e_lat_p50_ms)
    print("avg client e2e latency p95 (ms):", avg_e2e_lat_p95_ms)
    print("avg client e2e latency p99 (ms):", avg_e2e_lat_p99_ms)
    print("num e2e repeats=", len(e2e_reply_throughputs))
    print("num complete runs=", repeats)
    print("num good stat runs=", good_values)

    if stats_summary_label is None:
        with open(stats_txt, "a") as f:
            f.write(
                f"{pro_dir}, thr_view={avg_throughput}, lat_view={avg_latency}, "
                f"e2e_reply_tps={avg_e2e_reply_tps}, e2e_lat_avg={avg_e2e_lat_avg_ms}, "
                f"e2e_lat_p50={avg_e2e_lat_p50_ms}, e2e_lat_p95={avg_e2e_lat_p95_ms}, "
                f"e2e_lat_p99={avg_e2e_lat_p99_ms}, good={good_values}/{repeats}, "
                f"fault_node={dead_node_id}, kill_after={kill_after_sec},\n"
            )
    else:
        vr1, vr2 = calculate_mean_of_values(stats_directory, silent=True)
        append_wan_stats_summary_row(stats_summary_label, vr1, vr2)
    print(
        pro_dir,
        "thr_view=",
        avg_throughput,
        "lat_view=",
        avg_latency,
        "e2e_reply_tps=",
        avg_e2e_reply_tps,
        "e2e_p95=",
        avg_e2e_lat_p95_ms,
        "e2e_p99=",
        avg_e2e_lat_p99_ms,
    )


def experiment_fault_cloud(
    protocol,
    debug,
    batchsize,
    payload,
    faults,
    totaltee,
    pct,
    *,
    num_views=10,
    num_cl_trans=1,
    num_clients=1,
    cl_sleep_us=50,
    local_opdist=0,
    client_rep=0,
    kv_set=None,
    kv_get=None,
    kv_del=None,
    kv_keys=None,
    kv_vlen=None,
    dead_node_id: int = 1,
    kill_after_sec: float = 2.0,
    view_timeout=None,
    leader_mode="rotate",
    leader_id=0,
    cutoff_sec=None,
    stats_poll_interval: float = 0.5,
    live_plot_reference_replica=None,
    live_plot_exclude_fault_node=True,
    live_plot_aggregate_median=False,
    stats_summary_label=None,
    redis_enabled=False,
):
    """
    Cloud/SSH cluster: one replica is killed and stays down until experiment cleanup while live
    server stats are pulled to this machine. plot_live_throughput() aggregates stats/live-* across
    replicas into mean throughput vs time (same as local --fault-local).

    Typical HybridTEE WAN preset (example):
      --p0 --faults 8 --totaltee 9 --fault-cloud --view-timeout 2
    """
    kv_set = kv_set_ratio if kv_set is None else kv_set
    kv_get = kv_get_ratio if kv_get is None else kv_get
    kv_del = kv_del_ratio if kv_del is None else kv_del
    kv_keys = kv_keyspace if kv_keys is None else kv_keys
    kv_vlen = kv_value_len if kv_vlen is None else kv_vlen

    pro_dir = f"{protocol}_{faults}_{totaltee}_{payload}_{batchsize}_{pct}"
    factor = protocol_factor(protocol)
    total = num_replicas(factor, faults)

    servers = read_servers(total, addresses)
    by_id = {rid: (rid, h, p1, p2) for rid, h, p1, p2 in servers}
    if dead_node_id not in by_id:
        raise ValueError(f"dead_node_id={dead_node_id} not in config (0..{total-1})")
    dead_host = by_id[dead_node_id][1]

    ips_set = set()
    for server in servers:
        ips_set.add(server[1])
    ips = list(ips_set)

    if debug:
        files_to_copy = [
            str(addresses),
            str(PROJECT_ROOT / "server"),
            str(PROJECT_ROOT / "client"),
        ]
    else:
        files_to_copy = [
            str(addresses),
            str(PROJECT_ROOT / "sgxserver"),
            str(PROJECT_ROOT / "sgxclient"),
            str(PROJECT_ROOT / "enclave.so"),
            str(PROJECT_ROOT / "enclave.signed.so"),
            str(PROJECT_ROOT / "sgxkeys"),
        ]

    clear_local_stats()
    clear_remote_server_out_logs()
    clear_local_client_logs()
    ssh_clear_repo_out_logs_on_hosts(ips)
    scp_files_to_nodes(ips, files_to_copy)

    if redis_enabled:
        start_remote_redis_for_servers(servers)

    vc = float(timeout if view_timeout is None else view_timeout)
    print(
        "[fault-cloud] view-timeout (server argv, seconds)=",
        vc,
        "(Handler uses this for view-change timer; raise toward ~2s on WAN with ~100ms RTT)",
    )

    completion_set, lock = start_all_sgxservers(
        servers,
        debug,
        factor,
        faults,
        totaltee,
        num_views,
        local_opdist,
        view_timeout=view_timeout,
        leader_mode=leader_mode,
        leader_id=leader_id,
        clear_remote_stats=True,
        redis_enabled=redis_enabled,
    )

    stop_poll = threading.Event()
    poll_thread = threading.Thread(
        target=poll_remote_stats_forever,
        args=(ips, stop_poll, stats_poll_interval),
        daemon=True,
    )
    poll_thread.start()

    wait_before_client = 5 + int(math.ceil(math.log(faults, 2)))
    time.sleep(wait_before_client)

    client_procs = []
    for client_id in range(num_clients):
        client_proc = local_exec_client(
            debug,
            factor,
            faults,
            totaltee,
            num_cl_trans,
            client_id,
            cl_sleep_us,
            client_rep,
            kv_set,
            kv_get,
            kv_del,
            kv_keys,
            kv_vlen,
        )
        client_procs.append(client_proc)

    def fault_worker():
        time.sleep(max(0.0, float(kill_after_sec)))
        print(
            f"[fault-cloud] killing replica {dead_node_id} on {dead_host} "
            f"(t≈{kill_after_sec}s after client start)"
        )
        ssh_kill_sgxserver_on_host(dead_host, replica_id=dead_node_id)

    fault_thread = threading.Thread(target=fault_worker, daemon=True)
    fault_thread.start()

    run_cutoff = float(cutoff_sec) if cutoff_sec is not None else float(timeoutTime)
    deadline = time.time() + run_cutoff
    client_grace_after_done = 15.0
    while time.time() < deadline:
        if client_procs and all(p.poll() is not None for p in client_procs):
            break
        time.sleep(0.5)

    if client_procs and all(p.poll() is not None for p in client_procs):
        time.sleep(client_grace_after_done)

    fault_thread.join(timeout=max(30.0, float(kill_after_sec) + 30.0))

    stop_poll.set()
    poll_thread.join(timeout=30.0)

    print("[fault-cloud] stopping remaining remote servers (close.py)")
    stop_remote_server()
    time.sleep(2.0)

    wait_local_client_procs(client_procs, float(timeoutTime))
    close_client_log_handles(client_procs)

    collect_remote_artifacts(ips)

    stats_directory = str(stats_dir) + os.sep
    live_out_png = str(out_dir / f"fault-cloud-live-{pro_dir}.png")
    live_out_csv = str(out_dir / f"fault-cloud-live-{pro_dir}.csv")
    plot_live_throughput(
        stats_directory,
        live_out_png,
        live_out_csv,
        reference_replica_id=live_plot_reference_replica,
        exclude_replica_ids=(
            {dead_node_id}
            if live_plot_exclude_fault_node and live_plot_reference_replica is None
            else None
        ),
        aggregate_median=live_plot_aggregate_median,
    )

    r1, r2 = calculate_mean_of_values(stats_directory)
    cp_client_stats()
    e2e_stats = parse_client_e2e_stats(stats_directory)
    if e2e_stats is not None:
        print(
            "cloud fault client e2e:",
            "reply_ktps=",
            e2e_stats["reply_throughput_ktps"],
            "avg_ms=",
            e2e_stats["e2e_latency_avg_ms"],
        )
        er = e2e_stats["reply_throughput_ktps"]
        ea = e2e_stats["e2e_latency_avg_ms"]
    else:
        print("[warn] no stats/client-e2e-* parsed")
        er = ea = 0.0

    print(
        pro_dir,
        "fault-cloud server_vals_thr_mean=",
        r1,
        "server_vals_lat_mean=",
        r2,
        "live_plot=",
        live_out_png,
        "dead_node=",
        dead_node_id,
        "kill_after_sec=",
        kill_after_sec,
        "view_timeout=",
        vc,
    )

    if stats_summary_label is None:
        with open(stats_txt, "a") as f:
            f.write(
                f"{pro_dir}, fault-cloud, server_vals_thr_mean={r1}, server_vals_lat_mean={r2}, "
                f"e2e_reply_tps={er}, e2e_lat_avg_ms={ea}, "
                f"dead_node={dead_node_id}, kill_after={kill_after_sec}, "
                f"view_timeout={vc},\n"
            )
    else:
        append_wan_stats_summary_row(stats_summary_label, r1, r2)


#conduct a experiment
def experiment_once(
    protocol,
    debug,
    batchsize,
    payload,
    faults,
    totaltee,
    pct,
    *,
    num_views=10,
    num_cl_trans=1,
    num_clients=1,
    cl_sleep_us=50,
    local_opdist=0,
    client_rep=0,
    kv_set=None,
    kv_get=None,
    kv_del=None,
    kv_keys=None,
    kv_vlen=None,
    view_timeout=None,
    leader_mode="rotate",
    leader_id=0,
    stats_summary_label=None,
    redis_enabled=False,
    write_summary=True,
):
    """
    Remote cluster run aligned with experiment_local(): Redis per replica, server argv includes
    opdist, client argv includes KV workload params (defaults follow module-level kv_* globals).
    """
    kv_set = kv_set_ratio if kv_set is None else kv_set
    kv_get = kv_get_ratio if kv_get is None else kv_get
    kv_del = kv_del_ratio if kv_del is None else kv_del
    kv_keys = kv_keyspace if kv_keys is None else kv_keys
    kv_vlen = kv_value_len if kv_vlen is None else kv_vlen

    pro_dir = f'{protocol}_{faults}_{totaltee}_{payload}_{batchsize}_{pct}'

    factor = protocol_factor(protocol)
    total = num_replicas(factor, faults)

    #get the ip list of servers
    servers = read_servers(total, addresses)
    ips_set = set()
    for server in servers:
        ips_set.add(server[1])
    ips = list(ips_set)

    #scp files to the servers
    if debug:
        files_to_copy = [
            str(addresses),
            str(PROJECT_ROOT / "server"),
            str(PROJECT_ROOT / "client"),
        ]
    else:
        files_to_copy = [
            str(addresses),
            str(PROJECT_ROOT / "sgxserver"),
            str(PROJECT_ROOT / "sgxclient"),
            str(PROJECT_ROOT / "enclave.so"),
            str(PROJECT_ROOT / "enclave.signed.so"),
            str(PROJECT_ROOT / "sgxkeys"),
        ]
    clear_local_stats()
    ssh_clear_remote_stats_on_hosts(ips)
    clear_remote_server_out_logs()
    clear_local_client_logs()
    ssh_clear_repo_out_logs_on_hosts(ips)
    scp_files_to_nodes(ips, files_to_copy)

    # Same ordering as experiment_local: Redis before replicas.
    if redis_enabled:
        start_remote_redis_for_servers(servers)

    # Multi-threaded SSH execution sgxserver (num_views / opdist match local server argv)
    completion_set, lock = start_all_sgxservers(
        servers,
        debug,
        factor,
        faults,
        totaltee,
        num_views,
        local_opdist,
        view_timeout=view_timeout,
        leader_mode=leader_mode,
        leader_id=leader_id,
        clear_remote_stats=False,
        redis_enabled=redis_enabled,
    )
    print("start")
    wait_before_client = 5 + int(math.ceil(math.log(faults, 2)))
    time.sleep(wait_before_client)
    client_procs = []
    for client_id in range(num_clients):
        client_proc = local_exec_client(
            debug,
            factor,
            faults,
            totaltee,
            num_cl_trans,
            client_id,
            cl_sleep_us,
            client_rep,
            kv_set,
            kv_get,
            kv_del,
            kv_keys,
            kv_vlen,
        )
        client_procs.append(client_proc)

    # Block and wait for all sgxserver instances to end
    wait_for_all_sgxservers_to_finish(completion_set, lock, total)

    # Wait for orchestrator-local client so stats/client-e2e-* is flushed before SCP/parse.
    wait_local_client_procs(client_procs, float(timeoutTime))
    close_client_log_handles(client_procs)

    # get data from nodes
    collect_remote_artifacts(ips)

    stats_directory = str(stats_dir) + os.sep

    # Calculate the average value of the first and second numbers of all vals files
    r1, r2 = calculate_mean_of_values(stats_directory)
    # rtt = find_first_number(stats_directory)

    cp_client_stats()

    e2e_stats = parse_client_e2e_stats(stats_directory)
    if e2e_stats is not None:
        print(
            "cloud client e2e:",
            "reply_ktps=",
            e2e_stats["reply_throughput_ktps"],
            "avg_ms=",
            e2e_stats["e2e_latency_avg_ms"],
            "files=",
            int(e2e_stats["num_client_e2e_files"]),
        )
        er = e2e_stats["reply_throughput_ktps"]
        ea = e2e_stats["e2e_latency_avg_ms"]
    else:
        print("[warn] no stats/client-e2e-* parsed; rebuild sgxclient with Client e2e output or check client logs")
        er = ea = 0.0

    print(
        pro_dir,
        "server_vals_thr_mean=",
        r1,
        "server_vals_lat_mean=",
        r2,
        "e2e_reply_tps=",
        er,
        "e2e_lat_avg_ms=",
        ea,
    )

    if write_summary:
        if stats_summary_label is None:
            with open(stats_txt, 'a') as f:
                if e2e_stats is not None:
                    f.write(
                        f"{pro_dir}, server_vals_thr_mean={r1}, server_vals_lat_mean={r2}, "
                        f"e2e_reply_tps={er}, e2e_lat_avg_ms={ea},\n"
                    )
                else:
                    f.write(
                        f"{pro_dir}, server_vals_thr_mean={r1}, server_vals_lat_mean={r2}, "
                        f"e2e_reply_tps=0, e2e_lat_avg_ms=0, e2e_missing=1,\n"
                    )
        else:
            append_wan_stats_summary_row(stats_summary_label, r1, r2)

    return r1, r2


    # Wait and execute sgxclient on the host with id:0
    # ssh_exec_client_on_id0(servers, extra_params, totaltee)

    # Multi-threaded SCP from node to local
    # scp_files_from_nodes(ip_list)o


def experiment(*args, repeats=1, stats_summary_label=None, **kwargs):
    """Run a normal remote experiment repeatedly and report one arithmetic mean."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")

    throughput_values = []
    latency_values = []
    participating_hosts = read_ip_list(str(ip_list))
    for rep in range(repeats):
        print(f"[remote-repeat] {rep + 1}/{repeats}")
        # A prior interrupted run may still be executing the deployed binary,
        # which makes SCP fail with "Text file busy" when replacing it.
        ssh_stop_project_servers_on_hosts(participating_hosts)
        try:
            throughput, latency = experiment_once(
                *args,
                stats_summary_label=stats_summary_label,
                write_summary=False,
                **kwargs,
            )
        finally:
            # Servers normally exit by themselves, but always remove stragglers
            # before the next repeat and when this repeat raises an exception.
            ssh_stop_project_servers_on_hosts(participating_hosts)
            stop_local_clients()
        throughput_values.append(throughput)
        latency_values.append(latency)

    valid_pairs = [
        (throughput, latency)
        for throughput, latency in zip(throughput_values, latency_values)
        if throughput != 0.0 and latency != 0.0
    ]
    skipped = repeats - len(valid_pairs)
    if not valid_pairs:
        raise RuntimeError(
            f"all {repeats} remote repeats produced zero throughput or latency"
        )
    mean_throughput = sum(value[0] for value in valid_pairs) / len(valid_pairs)
    mean_latency = sum(value[1] for value in valid_pairs) / len(valid_pairs)
    print(
        f"[remote-repeat] mean over {len(valid_pairs)}/{repeats} valid runs "
        f"(skipped_zero={skipped}): "
        f"server_vals_thr_mean={mean_throughput} "
        f"server_vals_lat_mean={mean_latency}"
    )
    if stats_summary_label is not None:
        append_wan_stats_summary_row(
            stats_summary_label, mean_throughput, mean_latency
        )
    return mean_throughput, mean_latency



def main():
    """Parse CLI options, prepare artifacts, and dispatch the selected run mode."""
    parser = argparse.ArgumentParser(description='Start one experiment with given parameters.')
    parser.add_argument("--p0",        action="store_true",    help="run HybridTEE")
    parser.add_argument("--p1",        action="store_true",    help="run Chained-HybridTEE")
    parser.add_argument("--p2",        action="store_true",    help="run Achilles")
    parser.add_argument("--p3",        action="store_true",    help="run hotstuff")
    parser.add_argument("--p4",        action="store_true",    help="run basic Damysus")
    parser.add_argument("--debug",     action="store_true",    help="non_TEE")
    parser.add_argument("--local",     action="store_true",    help="run locally")
    parser.add_argument(
        "--experiment-number",
        type=int,
        default=None,
        metavar="N",
        help="remote experiment number; stores local artifacts under "
        "experiments_reproduction/experimentN (default: 0)",
    )
    parser.add_argument('--batchsize', type=int,  default=400, help='MAX_NUM_TRANSACTIONS in params (compile-time batch capacity)')
    parser.add_argument('--payload',   type=int,  default=256, help='Payload size')
    parser.add_argument('--faults',    type=int,  default=1,   help='Number of faults')
    parser.add_argument('--totaltee',  type=int,  default=0,   help='Number of TEE nodes for HybridTEE; other protocols use their protocol-defined value')
    parser.add_argument('--pct',       type=int,  default=0,   help='counter delay')
    # Local experiment parity with experiments.py (execute/computeAvgStats)
    parser.add_argument('--views',type=int,default=10,help='numViews passed to each server (default 10, same as experiments.py)',)
    parser.add_argument('--cl-trans',type=int,default=1,dest='cl_trans',help='number of transactions sent by each client (default 1)',)
    parser.add_argument('--cl-num',type=int,default=1,dest='cl_num',help='number of clients to start (default 1)',)
    parser.add_argument('--cl-sleep',type=int,default=0,dest='cl_sleep',help='client sleep interval in microseconds between sends (default 0)',)
    parser.add_argument('--repeats',type=int,default=1,help='repeat the run and average stats (default 1)',)
    parser.add_argument('--config-by-totaltee',action='store_true',help='deprecated: now default behavior; local config already follows --totaltee',)
    parser.add_argument('--config-all-tee',action='store_true',help='legacy mode: force local config to all isTEE:1',)
    parser.add_argument('--opdist',type=int,default=0,help='server argv opdist (default 0, same as experiments.py)',)
    parser.add_argument('--print-vals-mean',action='store_true',help='also print calculate_mean_of_values (first two cols) after each repeat',)
    parser.add_argument('--cutoff-sec',type=int,default=None,help='max local wait time in seconds before forced stop (default uses built-in cutOffBound=60)',)
    parser.add_argument('--kv-set-ratio', type=int, default=100, help='KV workload SET ratio (percentage-like weight)')
    parser.add_argument('--kv-get-ratio', type=int, default=0, help='KV workload GET ratio (percentage-like weight)')
    parser.add_argument('--kv-del-ratio', type=int, default=0, help='KV workload DEL ratio (percentage-like weight)')
    parser.add_argument('--kv-keyspace', type=int, default=1000, help='KV workload keyspace size')
    parser.add_argument('--kv-value-len', type=int, default=16, help='KV workload SET value length')
    parser.add_argument('--redis',action='store_true',help='run the dedicated Redis-backed KV experiment path (default: in-memory KV, no Redis startup)',)
    # Local fault injection (one replica crash during local experiment).
    parser.add_argument('--fault-local',action='store_true',help='simulate one replica crash during local run (kills a server process mid-run)',)
    parser.add_argument('--fault-node-id',type=int,default=1,help='replica index to kill in --fault-local mode (default 1)',)
    parser.add_argument('--fault-after-sec', type=float, default=2.0, help='seconds after starting the client to kill the fault node (default 2.0)',)
    parser.add_argument('--view-timeout',type=float,default=None,help='view-change timeout in seconds (server argv; default: built-in 5s; ~2s is reasonable on WAN with ~100ms RTT)',)
    parser.add_argument('--leader-mode', choices=('rotate', 'fixed'), default='fixed', help='leader selection: rotate across replicas (default) or always use --leader-id')
    parser.add_argument('--leader-id', type=int, default=0, help='fixed leader replica id when --leader-mode=fixed (default 0)')
    # Cloud / SSH fault injection (mirrors --fault-local but uses SSH + periodic stats pull).
    parser.add_argument('--fault-cloud',action='store_true',help='remote cluster: kill one replica mid-run (no restart), poll stats/live-* from all nodes, plot mean throughput (omit --local)',)
    parser.add_argument(
        '--live-plot-reference-replica',
        type=int,
        default=None,
        metavar='ID',
        dest='live_plot_reference_replica',
        help='live CSV/PNG: use only stats/live-<ID>-* (single replica curve; overrides exclude-fault)',
    )
    parser.add_argument(
        '--live-plot-include-fault-node',
        action='store_true',
        help='live CSV/PNG: include crashed replica when averaging (fault-cloud/--fault-local only; default: exclude)',
    )
    parser.add_argument(
        '--live-plot-median',
        action='store_true',
        dest='live_plot_median',
        help='live CSV/PNG: median across replicas per sec bucket (reduces mean oscillation when replicas desync after fault)',
    )
    parser.add_argument(
        '--stats-summary-label',
        type=str,
        default=None,
        metavar='LABEL',
        dest='stats_summary_label',
        help='When set: stats.txt gets only one appended line per run '
        '"LABEL, server_vals_thr_mean, server_vals_lat_mean" (no Start/pro_dir lines). '
        'When unset: keep legacy stats.txt lines from experiment paths.',
    )
    args = parser.parse_args()

    if getattr(args, "fault_cloud", False) and args.local:
        parser.error("--fault-cloud is only for remote runs (do not pass --local)")
    if getattr(args, "fault_cloud", False) and getattr(args, "fault_local", False):
        parser.error("use only one of --fault-cloud and --fault-local")
    if args.experiment_number is not None and args.experiment_number < 0:
        parser.error("--experiment-number must be at least 0")
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    configure_output_paths(args.local, args.experiment_number)

    global kv_set_ratio, kv_get_ratio, kv_del_ratio, kv_keyspace, kv_value_len
    kv_set_ratio = max(0, args.kv_set_ratio)
    kv_get_ratio = max(0, args.kv_get_ratio)
    kv_del_ratio = max(0, args.kv_del_ratio)
    kv_keyspace = max(1, args.kv_keyspace)
    kv_value_len = max(1, args.kv_value_len)

    if args.stats_summary_label is None:
        with open(stats_txt, 'a') as f:
            f.write(f"Start, numviews: {args.views}\n")

    if args.p0:
        protocol = "HybridTEE"
    elif args.p1:
        protocol = "Chained-HybridTEE"
    elif args.p2:
        protocol = "Achilles"
    elif args.p3:
        protocol = "Hotstuff"
    elif args.p4:
        protocol = "Basic-Damysus"
    else:
        protocol = "HybridTEE"

    # if args.pct > 0:
    #     pct = args.pct

    factor = protocol_factor(protocol)
    total_nodes = num_replicas(factor, args.faults)
    # Resolve protocol-defined TEE populations before generating configs and
    # binaries so node roles, runtime thresholds, and compile-time capacities
    # all use the same value.  Only HybridTEE honors --totaltee.
    args.totaltee = protocol_totaltee(
        protocol, args.faults, total_nodes, args.totaltee
    )
    if args.config_all_tee and protocol != "HybridTEE":
        parser.error("--config-all-tee is only valid for HybridTEE")
    if args.totaltee < 0 or args.totaltee > total_nodes:
        parser.error(f"--totaltee must be between 0 and the replica count ({total_nodes})")
    if args.leader_id < 0 or args.leader_id >= total_nodes:
        parser.error(f"--leader-id must be between 0 and {total_nodes - 1}")
    build_totaltee = total_nodes if args.local and args.config_all_tee else args.totaltee
    # Local mode always regenerates `config` via genLocalConf(...), so skip mkConfig here.
    # This avoids an intermediate config written with mkConfig's instance-rounding policy.
    if not args.local:
        mkConfig(total_nodes, args.totaltee)
    makeInstance(protocol, args.debug, args.batchsize, args.payload, args.faults, build_totaltee, args.pct)
    if args.local:
        prepare_local_runtime_files(args.debug)

    if args.local:
        if getattr(args, "fault_local", False):
            experiment_fault_local(
                protocol,
                args.debug,
                args.batchsize,
                args.payload,
                args.faults,
                args.totaltee,
                args.pct,
                dead_node_id=args.fault_node_id,
                kill_after_sec=args.fault_after_sec,
                num_views=args.views,
                num_cl_trans=args.cl_trans,
                num_clients=max(1, args.cl_num),
                cl_sleep_us=max(0, args.cl_sleep),
                repeats=args.repeats,
                config_by_totaltee=not args.config_all_tee,
                local_opdist=args.opdist,
                leader_mode=args.leader_mode,
                leader_id=args.leader_id,
                print_vals_means=args.print_vals_mean,
                cutoff_sec=args.cutoff_sec,
                live_plot_reference_replica=args.live_plot_reference_replica,
                live_plot_exclude_fault_node=not args.live_plot_include_fault_node,
                live_plot_aggregate_median=args.live_plot_median,
                stats_summary_label=args.stats_summary_label,
                redis_enabled=args.redis,
            )
        else:
            experiment_local(
                protocol,
                args.debug,
                args.batchsize,
                args.payload,
                args.faults,
                args.totaltee,
                args.pct,
                num_views=args.views,
                num_cl_trans=args.cl_trans,
                num_clients=max(1, args.cl_num),
                cl_sleep_us=max(0, args.cl_sleep),
                repeats=args.repeats,
                config_by_totaltee=not args.config_all_tee,
                local_opdist=args.opdist,
                leader_mode=args.leader_mode,
                leader_id=args.leader_id,
                print_vals_means=args.print_vals_mean,
                cutoff_sec=args.cutoff_sec,
                stats_summary_label=args.stats_summary_label,
                redis_enabled=args.redis,
            )
    else:
        if getattr(args, "fault_cloud", False):
            experiment_fault_cloud(
                protocol,
                args.debug,
                args.batchsize,
                args.payload,
                args.faults,
                args.totaltee,
                args.pct,
                num_views=args.views,
                num_cl_trans=args.cl_trans,
                num_clients=max(1, args.cl_num),
                cl_sleep_us=max(0, args.cl_sleep),
                local_opdist=args.opdist,
                dead_node_id=args.fault_node_id,
                kill_after_sec=args.fault_after_sec,
                view_timeout=args.view_timeout,
                leader_mode=args.leader_mode,
                leader_id=args.leader_id,
                cutoff_sec=args.cutoff_sec,
                live_plot_reference_replica=args.live_plot_reference_replica,
                live_plot_exclude_fault_node=not args.live_plot_include_fault_node,
                live_plot_aggregate_median=args.live_plot_median,
                stats_summary_label=args.stats_summary_label,
                redis_enabled=args.redis,
            )
        else:
            experiment(
                protocol,
                args.debug,
                args.batchsize,
                args.payload,
                args.faults,
                args.totaltee,
                args.pct,
                num_views=args.views,
                num_cl_trans=args.cl_trans,
                num_clients=max(1, args.cl_num),
                cl_sleep_us=max(0, args.cl_sleep),
                local_opdist=args.opdist,
                view_timeout=args.view_timeout,
                leader_mode=args.leader_mode,
                leader_id=args.leader_id,
                repeats=args.repeats,
                stats_summary_label=args.stats_summary_label,
                redis_enabled=args.redis,
            )


if __name__ == "__main__":
    main()
