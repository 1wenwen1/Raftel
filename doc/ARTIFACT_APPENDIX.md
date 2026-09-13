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
| Exact author-supplied reference data | `runs/reference/original/` |
| Initialization script for cloud nodes | `deployment/sourcefile/init.sh` |
| Replica lifecycle and inventory | `aliyun/` |

### What Is Not Delivered

- Coordinator provisioning instructions and cloud account credentials. The
  authors prepare the coordinator before evaluation; the reviewer command
  creates disposable replica instances through its preconfigured account.
- The cluster SSH private key. It is delivered to the coordinator through the
  review access channel and is never tracked in this repository.
- Binary blobs (SGX SDK, PSW, SGX SSL) — bundled in `deployment/sourcefile/archive.tar.gz`
  (tracked via Git LFS).

---

## Hardware Dependencies

- **Ubuntu 20.04 x86-64** on every node (coordinator and replicas).
- **Intel SGX-capable CPU** with the in-kernel SGX driver enabled.
  Cloud instance: Alibaba Cloud `ecs.g7t.2xlarge` (8 vCPU / 32 GB / SGX-TEE).
  Verify SGX devices are present: `ls /dev/sgx_enclave /dev/sgx_provision`.
- **Network**: the paper used a 10 Gbps private network between nodes.
  WAN experiments emulate 50 ms one-way delay using `tc netem` on each node.

Maximum instance counts by figure:
- Figure 3: up to 97 instances (f=32, 3×32+1 replicas).
- Figure 4: up to 97 instances (f=32, 3×32+1 replicas).
- Figure 6: 25 instances (n = 3×8+1).

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

---

## Reproducibility Scope

| Figure | Claim | Expected |
|---|---|---|
| Fig 3 | WAN scalability: Achilles ≥ Chained ≥ Raftel > Hotstuff ≈ Raftel-Worst | **Full reproduction** — all six protocols at f∈{1,2,4,8,16,32}. Absolute values within ±40% of reference; ordering must match. |
| Fig 4 | LAN TEE-config effect: S1 > S2 ≥ S3 > S4 throughput, S1 ≤ … ≤ S4 latency | **Full reproduction** — four configurations at f∈{1,2,4,8,16,32}. Paper-exact: S1 at f=32 = 31.5 kTPS. |
| Fig 6 | Redis E2E: Achilles 95 TPS, Chained 92 TPS, Raftel 84 TPS, Hotstuff 44 TPS (peak) | **Full reproduction** — load sweep clients∈{1,2,4,8,16,32}, 3 repeats. Absolute values within ±40%; ordering must match. |

Absolute throughput and latency numbers depend on SGX enclave overhead,
cloud network jitter, and instance placement within the Alibaba Cloud region.
We consider the artifact successfully reproduced when the **ordering** of
protocols is consistent with the paper and absolute values fall within the
±40% PASS band defined in `runs/reference/EXPECTED_RANGES.md`.

---

## Experiment Workflow

### Reviewer workflow on the pre-provisioned coordinator

```
./ae run all --mode sim       # complete SGX SIM sweep, 7 multiplexed hosts
# or
./ae run all --mode full      # paper topology, one replica per VM
```

Both commands produce `runs/<RUN_ID>/index.html` automatically. Simulation
executes the full fault/load sweep in SGX SIM mode on seven hosts, with up to 15
replicas per host (97 logical replicas at f=32). It verifies the pipeline and
trends but is not eligible for a hardware reproduction verdict. Full uses SGX
HW, one replica per VM, and three Fig. 6 repeats.
The entry point automatically creates, initializes, checks, and releases the
required replica resources when no prepared replica inventory exists. Reviewers
do not handle cloud credentials or invoke lifecycle commands themselves.

---

## Notes on AE Fixes

The original artifact required the following correctness and hardware-runtime
fixes for an auditable AE workflow:

1. **SGX SIM mode hardcoded** (`run.py` line 127): original `sgxmode = "SIM"` was
   never overridden for cloud runs. Fixed by adding `--sgx-mode {SIM,HW}` CLI flag;
   Full passes `--sgx-mode HW`; Simulation passes `--sgx-mode SIM`.

2. **Raftel-Worst wrong `totaltee`** (Figure 3): original script used
   `--totaltee f`, but §7.2 defines Raftel-Worst as `m=0` (no TEE fast path).
   Fixed to `--totaltee 0`.

3. **Redis payload silent failure** (Figure 6): original `--payload 256
   --kv-value-len 1024` caused `KVAppCodec::encode` to silently drop every
   request (key + 1024 B value + 14 B header = 1043 B > 256 B).
   Fixed to `--payload 1100 --kv-value-len 1024`.

4. **Hardware enclave initialization:** chained-protocol state hashing ran
   during enclave global construction, before the trusted runtime was ready
   for its C++/OpenSSL work. It now runs from `initialize_variables()` after
   enclave creation. Protocol transitions and message flow are unchanged.

5. **Hardware enclave stack:** `StackMaxSize` is raised from 256 KiB to 1 MiB
   to prevent the real SGX path from exhausting the enclave stack.

See `doc/CODE_OVERVIEW.md` for implementation details.
