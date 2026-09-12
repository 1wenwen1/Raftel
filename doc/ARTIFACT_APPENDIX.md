# Artifact Appendix

## Abstract

This appendix describes the artifact accompanying the paper
*Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World*,
accepted at EuroSys 2027.

The artifact is a public Git repository containing the Raftel protocol
implementation (built on [Damysus](https://github.com/vrahli/damysus)),
experiment scripts for reproducing Figures 3, 4, and 6 from the paper, and
an AE CLI (`./ae`) that automates the full reproduction pipeline.

Paper DOI / preprint: see `doc/Breaking_Fault_Lines__Unifying_BFT_Consensus_in_a_Partially_Trusted_World.pdf`

---

## Description

### What Is Delivered

| Item | Location |
|---|---|
| Raftel and baseline protocol sources | `App/`, `Enclave/` |
| Experiment orchestrator | `run.py` |
| AE CLI | `ae` (executable Python script) |
| Figure 3 script (WAN scalability) | `experiments_reproduction/experiment1/script/run_wan.sh` |
| Figure 4 script (LAN TEE configs) | `experiments_reproduction/experiment2/script/run_lan.sh` |
| Figure 6 script (Redis E2E WAN) | `experiments_reproduction/experiment3/script/run_redis_wan.sh` |
| Plot scripts | `scripts/plot_fig{3,4,6}.py` |
| HTML report generator | `scripts/gen_report.py` |
| Reference values (PDF-read approximations) | `runs/reference/fig{3,4,6}.csv` |
| Initialization script for cloud nodes | `deployment/sourcefile/init.sh` |
| Alibaba Cloud lifecycle scripts | `aliyun/` |

### What Is Not Delivered

- The SSH private key (`TShard`) — distributed to reviewers separately via HotCRP.
- Alibaba Cloud credentials (`aliyun/config.json`) — must be filled in by the reviewer
  for Path B; not required for Path A (pre-provisioned cluster).
- Binary blobs (SGX SDK, PSW, SGX SSL) — bundled in `deployment/sourcefile/archive.tar.gz`
  (tracked via Git LFS).

---

## Hardware Dependencies

- **Ubuntu 20.04 x86-64** on every node (coordinator and replicas).
- **Intel SGX-capable CPU** with the in-kernel SGX driver enabled.
  Cloud instance: Alibaba Cloud `ecs.g7t.2xlarge` (8 vCPU / 32 GB / SGX-TEE).
  Verify SGX devices are present: `ls /dev/sgx_enclave /dev/sgx_provision`.
- **Network**: 10 Gbps private network between hosts (Alibaba Cloud VPC default).
  WAN experiments emulate 50 ms one-way delay using `tc netem` on each host.

The cloud workflow uses 7 reusable hosts. `run.py` assigns up to 15 replicas to
each host using distinct ports, for a total capacity of 105 replicas. Figure 3
and Figure 4 need at most 97 replicas (`f=32`, `3f+1`), while Figure 6 needs 25.
This co-located layout is operationally convenient but is not equivalent to
one replica per physical host; results include same-host resource contention.

---

## Software Dependencies

All dependencies are installed by `deployment/sourcefile/init.sh` on cloud nodes,
and by the manual steps in the README on the coordinator.

| Dependency | Version | Purpose |
|---|---|---|
| Intel SGX SDK | 2.23.100.2 | Build and run SGX enclaves |
| Intel SGX PSW | matching SDK | Runtime enclave loader |
| Intel SGX SSL | (bundled) | Cryptographic primitives inside enclave |
| Salticidae | (submodule) | Async networking library |
| hiredis | 0.14.0 | Redis client for experiment 3 |
| Redis | 5.0.7 | KV store backend for experiment 3 |
| Python ≥ 3.8 | — | run.py, ae, plot scripts |
| matplotlib | — | Figure generation |
| paramiko + scp | — | SSH/SCP orchestration |
| aliyun-python-sdk-core | — | Alibaba Cloud API (Path B only) |

---

## Reproducibility Scope

| Figure | Claim | Expected |
|---|---|---|
| Fig 3 | WAN scalability: Achilles ≥ Chained ≥ Raftel > Hotstuff ≈ Raftel-Worst | **Full reproduction** — all six protocols at f∈{1,2,4,8,16,32}. Absolute values within ±40% of reference; ordering must match. |
| Fig 4 | LAN TEE-config effect: S1 > S2 ≥ S3 > S4 throughput, S1 ≤ … ≤ S4 latency | **Full reproduction** — four configurations at f∈{1,2,4,8,16,32}. Paper-exact: S1 at f=32 = 31.5 kTPS. |
| Fig 6 | Redis E2E: Achilles 95 TPS, Chained 92 TPS, Raftel 84 TPS, Hotstuff 44 TPS (peak) | **Full reproduction** — load sweep clients∈{1,2,4,8,16,32}, 3 repeats. Absolute values within ±40%; ordering must match. |

Absolute throughput and latency numbers depend on SGX attestation overhead,
cloud network jitter, and instance placement within the Alibaba Cloud region.
We consider the artifact successfully reproduced when the **ordering** of
protocols is consistent with the paper and absolute values fall within the
±40% PASS band defined in `runs/reference/EXPECTED_RANGES.md`.

---

## Experiment Workflow

### Path A — Pre-provisioned cluster (recommended for reviewers)

```
./ae doctor --profile paper   # verify all dependencies
./ae run all                   # run Figs 3, 4, 6 (~4–6 h)
./ae report                    # generate figures + HTML report
```

Open `runs/<RUN_ID>/index.html` for reproduced figures, reference comparisons, and ordering checks. Apply the documented thresholds to determine PASS/WARN/FAIL.

### Path B — Reviewer's own Alibaba Cloud account

```
# 1. Copy and fill in credentials
cp aliyun/config.example.json aliyun/config.json   # edit with your account

# 2. Provision and initialise nodes
./ae cloud up --count 7
./ae cloud init
./ae cloud check

# 3. Run experiments and generate report
./ae run all
./ae report
```

### Reduced-scale cloud check (~30 min, HW mode)

```
./ae run all --scale mini
./ae report
```

---

## Notes on AE Fixes

Three correctness bugs in the original code were fixed for this AE:

1. **SGX SIM mode hardcoded** (`run.py` line 127): original `sgxmode = "SIM"` was
   never overridden for cloud runs. Fixed by adding `--sgx-mode {SIM,HW}` CLI flag;
   experiment scripts pass `--sgx-mode HW`.

2. **Raftel-Worst wrong `totaltee`** (Figure 3): original script used
   `--totaltee f`, but §7.2 defines Raftel-Worst as `m=0` (no TEE fast path).
   Fixed to `--totaltee 0`.

3. **Redis payload silent failure** (Figure 6): original `--payload 256
   --kv-value-len 1024` caused `KVAppCodec::encode` to silently drop every
   request (key + 1024 B value + 14 B header = 1043 B > 256 B).
   Fixed to `--payload 1100 --kv-value-len 1024`.

See `doc/CODE_OVERVIEW.md` for full details.
