# Experiment 3: Redis WAN End-to-End Performance

This experiment corresponds to Figure 6 in the paper. It adds a 50 ms `netem` delay to `eth0` on every remote host and compares the end-to-end performance of five protocols using a Redis-backed key-value workload.

## Configuration

- Protocols: HybridTEE (`p0`), Chained-HybridTEE (`p1`), Achilles (`p2`), Hotstuff (`p3`), and Basic-Damysus (`p4`)
- Fault threshold: `8`
- Requested TEE population: `9`
- Workload: 100% SET operations, 1 KB values, and a keyspace of 10,000 keys
- Batch size: `400`
- Payload size: `256` bytes
- Clients: four concurrent clients, each sending 2,000 requests without an inter-request delay
- Views: `30`
- Repetitions: three per protocol, for 15 runs in total
- Leader: fixed replica 0
- Backend: Redis, enabled with `--redis`

Only HybridTEE accepts a configurable `--totaltee` value. The effective TEE populations are nine for HybridTEE, nine for Chained-HybridTEE, all 17 replicas for Achilles, zero for Hotstuff, and all 17 replicas for Basic-Damysus.

The remote `netem` configuration is removed when the script exits or is interrupted.

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
