# Experiment 2: LAN Leader and Quorum Combinations

This experiment corresponds to Figure 4 in the paper. It evaluates Raftel under four combinations of leader type and TEE-quorum availability in a LAN environment. The script does not add network delay and removes any root `qdisc` left on `eth0` by an earlier WAN experiment.

The fixed parameters are:

```text
--batchsize 400 --payload 256
```

The experiment evaluates fault thresholds `1`, `2`, `4`, `8`, `16`, and `32` for each set, for 24 runs in total.

Estimated running time: approximately 1.5 hours, assuming the configured nodes are available and no failed runs need to be repeated.

## Configurations

| Set | `totaltee` | Fixed leader | TEE quorum |
| --- | --- | --- | --- |
| `set1` | `faults + 1` | replica 0 (TEE) | available |
| `set2` | `faults` | replica 0 (TEE) | unavailable |
| `set3` | `faults + 1` | replica `faults + 1` (non-TEE) | available |
| `set4` | `faults` | replica `faults + 1` (non-TEE) | unavailable |

Replica IDs start at 0. TEE replicas occupy IDs from 0 through `totaltee - 1`, so replica `faults + 1` is non-TEE in sets 3 and 4. All four sets use a fixed leader; the leader does not rotate between views.

## Prerequisites

- `/root/Raftel/ip_list` must contain the remote host IP addresses.
- `/root/Raftel/TShard` must be a valid SSH private key for the remote root user.
- The remote project path must match `DAMYSUS_REMOTE_ROOT`; it defaults to `/root/Raftel`.

## Run

Before starting, the script removes the previous contents of `exe/`, `log/`, `out/`, and `results/` (except `.gitkeep`) and clears `stats.txt`. Copy any results that you want to retain before rerunning it.

```bash
cd /root/Raftel
bash experiments_reproduction/experiment2/script/run_lan.sh
```

## Results

All paths below are relative to `experiments_reproduction/experiment2/`:

- `stats.txt`: computed throughput and latency for all 24 combinations, labeled `set<1-4>_f<faults>`.
- `exe/`: compiled executables and generated `params.h` files, grouped by build configuration.
- `results/set<1-4>_f<faults>/`: raw statistics preserved for each combination.
- `results/current/`: raw node statistics for the most recently executed case.
- `log/current/`: client and remote-replica logs for the most recently executed case.
- `log/set<1-4>_f<faults>/orchestrator.log`: complete coordinator output for each combination.
- `log/set<1-4>_f<faults>/remote/`: `out*` logs collected from the remote replicas.

The script's final exit status is nonzero if any case fails. Check the corresponding `orchestrator.log` for error details.
