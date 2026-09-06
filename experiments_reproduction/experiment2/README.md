# Experiment 2: LAN Leader and Quorum Combinations

This experiment corresponds to Figure 4 in the paper. It evaluates HybridTEE under four combinations of leader type and TEE-quorum availability in a LAN environment. The script does not add network delay and removes any root `qdisc` left on `eth0` by an earlier WAN experiment.

The fixed parameters are:

```text
--batchsize 400 --payload 256 --faults 32
```

## Configurations

| Case | `totaltee` | Leader | TEE quorum |
| --- | ---: | --- | --- |
| `tee-leader_no-tee-quorum` | 32 | fixed TEE replica 0 | unavailable |
| `tee-leader_tee-quorum` | 33 | fixed TEE replica 0 | available |
| `nontee-leader_no-tee-quorum` | 32 | fixed non-TEE replica 33 | unavailable |
| `nontee-leader_tee-quorum` | 33 | fixed non-TEE replica 33 | available |

Replica IDs start at 0. With `totaltee=33`, replicas 0 through 32 are TEE replicas, so replica 33 is non-TEE. All four cases use a fixed leader; the leader does not rotate between views.

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

- `stats.txt`: computed throughput and latency rows for the four cases.
- `exe/`: compiled executables and generated `params.h` files, grouped by build configuration.
- `results/<case>/`: raw statistics preserved for each case.
- `results/current/`: raw node statistics for the most recently executed case.
- `log/current/`: client and remote-replica logs for the most recently executed case.
- `log/<case>/orchestrator.log`: complete coordinator output for each case.
- `log/<case>/remote/`: `out*` logs collected from the remote replicas.

The script's final exit status is nonzero if any case fails. Check the corresponding `orchestrator.log` for error details.
