# Experiment 3: Redis LAN End-to-End Performance

This modified Figure 6 experiment compares the end-to-end performance of five
protocols using a Redis-backed key-value workload over the cloud hosts' native
LAN. Before running, it removes any root `netem` rule left on `eth0` and does
not inject artificial network delay.

## Configuration

- Protocols: Raftel (`p0`), Chained_Raftel (`p1`), Achilles (`p2`), Hotstuff (`p3`), and Basic-Damysus (`p4`)
- Fault threshold: `8`
- TEE population: all 25 replicas for Raftel and Chained_Raftel; the remaining
  protocols retain their defaults (all 17 for Achilles, zero for Hotstuff, and
  all 17 for Basic-Damysus)
- Workload: 100% SET operations, 1 KB values, and a keyspace of 10,000 keys
- Batch size: `400`
- Payload size: `1100` bytes
- Clients: a load sweep of 1, 2, 4, 8, 16, and 32 concurrent clients; each
  client sends 2,000 requests without an inter-request delay
- Views: `30`
- Repetitions: three per protocol and client-count point, for 90 runs in total
- Leader: rotates across replicas for Raftel and Chained_Raftel; fixed replica 0
  for Achilles, Hotstuff, and Basic-Damysus
- Backend: Redis, enabled with `--redis`

Experiment 3 passes `--config-all-tee` only for Raftel and Chained_Raftel. The
other protocols keep the protocol-specific TEE populations selected by
`run.py`.

The script verifies that no `netem` delay remains on the remote hosts before
starting the first run.

Estimated running time: approximately 1.5 hours, assuming the configured nodes are available and no failed runs need to be repeated.

## Prerequisites

- `/root/Raftel/ip_list` must contain the remote host IP addresses.
- `/root/Raftel/TShard` must be a valid SSH private key for the remote root user.
- The remote project path must match `DAMYSUS_REMOTE_ROOT`; it defaults to `/root/Raftel`.
- Redis and hiredis must be installed on every remote host.

## Run

Before starting, the script removes the previous contents of `exe/`, `log/`, `out/`, and `results/` (except `.gitkeep`) and clears `stats.txt`. Copy any results that you want to retain before rerunning it.

```bash
cd /root/Raftel
bash experiments_reproduction/experiment3/script/run_redis_wan.sh
```

## Metrics

- End-to-end reply throughput (KTPS): the total number of completed client requests divided by their shared reply-time window.
- End-to-end latency: average, p50, p95, and p99 latency in milliseconds.
- Number of requests completed in each run.

## Results

All paths below are relative to `experiments_reproduction/experiment3/`:

- `stats.txt`: final mean E2E metrics across successful repetitions, grouped by protocol.
- `exe/`: compiled executables and generated `params.h` files, grouped by build configuration.
- `results/raw/<protocol>_repeat<n>/`: raw statistics and `client-e2e-*` files preserved for each run.
- `results/current/`: raw node statistics for the most recently executed run.
- `log/current/`: client and remote-replica logs for the most recently executed run.
- `log/<protocol>_repeat<n>/orchestrator.log`: complete coordinator output for each run.
- `log/<protocol>_repeat<n>/remote/`: `out*` logs collected from the remote replicas.

The script's final exit status is nonzero if any run fails. Check the corresponding `orchestrator.log` for error details.

Ali Cloud resources incur charges. When the experiment is complete, verify the IDs in `aliyun/instances.txt` and release those instances with:

```bash
cd /root/Raftel
python3 aliyun/delete_instances.py
```
