# Experiment 1: WAN Scalability

This experiment corresponds to Figure 3 in the paper. It adds a 50 ms `netem` delay to `eth0` on every remote host and evaluates WAN throughput and latency as the fault threshold increases.

## Configuration

- Protocol configurations: Raftel (`p0`), Chained (`p1`), Achilles (`p2`), Hotstuff (`p3`), Basic-Damysus (`p4`), and Raftel-Worst (`p0` with the worst-case leader configuration)
- Fault thresholds: `1`, `2`, `4`, `8`, `16`, and `32`
- Fixed parameters: `--batchsize 400 --payload 256`
- Repetitions: one run per protocol/fault-threshold combination
- Raftel uses `totaltee = faults + 1`; Raftel-Worst uses `totaltee = faults` and fixed leader replica `faults + 1`; the other protocols use their protocol-defined TEE populations

The script runs 36 combinations: six configurations at each of the six fault thresholds. A run that produces zero throughput or zero latency is treated as failed. The remote `netem` configuration is removed when the script exits or is interrupted.

Estimated running time: approximately 2 hours, assuming the configured nodes are available and no failed runs need to be repeated.

Before the full experiment starts, the script removes the previous contents of `exe/`, `log/`, `out/`, and `results/` (except `.gitkeep`) and clears `stats.txt`. Copy any results that you want to retain before rerunning it. Before each individual run, `run.py` also clears `results/current/` locally and `stats/` on every remote host so that measurements from different combinations are not mixed.

## Prerequisites

- `/root/Raftel/ip_list` must contain the remote host IP addresses.
- `/root/Raftel/TShard` must be a valid SSH private key for the remote root user.
- The remote project path must match `DAMYSUS_REMOTE_ROOT`; it defaults to `/root/Raftel`.
- The remote root user must be allowed to configure `eth0` with `tc`.

If the remote project uses another path, set it before starting the experiment:

```bash
export DAMYSUS_REMOTE_ROOT=/root/another-directory
```

## Run

Run the script from any directory:

```bash
bash /root/Raftel/experiments_reproduction/experiment1/script/run_wan.sh
```

## Results

All paths below are relative to `experiments_reproduction/experiment1/`:

- `stats.txt`: final computed throughput and latency rows for completed combinations.
- `exe/`: compiled executables and generated `params.h` files, grouped by build configuration.
- `results/<protocol>_f<faults>/`: raw statistics preserved for each combination.
- `results/current/`: raw node statistics for the most recently executed combination.
- `log/current/`: client and remote-replica logs for the most recently executed combination.
- `log/<protocol>_f<faults>/orchestrator.log`: complete coordinator output for each combination.
- `log/<protocol>_f<faults>/remote/`: `out*` logs collected from the remote replicas.

The script continues after an individual failure. Check its console output and the corresponding `orchestrator.log` for the failed case; its final exit status is nonzero if any combination fails.

Ali Cloud resources incur charges. When the experiment is complete, verify the IDs in `aliyun/instances.txt` and release those instances with:

```bash
cd /root/Raftel
python3 aliyun/delete_instances.py
```
