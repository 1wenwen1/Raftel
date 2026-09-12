# Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World

Artifact for ["Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World"](doc/Breaking_Fault_Lines__Unifying_BFT_Consensus_in_a_Partially_Trusted_World.pdf), accepted at EuroSys 2027.

Raftel is an SGX-TEE-assisted BFT consensus protocol for partially trusted environments, where only a subset of replicas holds a TEE. It builds on the [Damysus](https://github.com/vrahli/damysus) codebase and shows that a minority TEE quorum suffices for safety and liveness, with throughput and latency competitive with state-of-the-art TEE-free BFT protocols. This artifact reproduces Figures 3, 4, and 6 from the paper: WAN scalability across six protocols, LAN TEE-leader and quorum-size effects, and Redis end-to-end performance.

See [doc/ARTIFACT_APPENDIX.md](doc/ARTIFACT_APPENDIX.md) for the EuroSys AE appendix and [doc/CODE_OVERVIEW.md](doc/CODE_OVERVIEW.md) for the code structure and a description of changes relative to Damysus.

---

## Contents

- [Prerequisites](#prerequisites)
- [Path A — Pre-provisioned coordinator](#path-a--pre-provisioned-coordinator)
- [Path B — Bring your own Alibaba Cloud account](#path-b--bring-your-own-alibaba-cloud-account)
- [Reproducibility Scope](#reproducibility-scope)
- [Figure → Script Mapping](#figure--script-mapping)
- [AE CLI Reference](#ae-cli-reference)
- [Dependencies](#dependencies)
- [Code changes: Raftel vs. Damysus](doc/CODE_OVERVIEW.md)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

> **⚠ SGX HARDWARE REQUIRED for paper runs.**
> Every cloud node must be an Intel SGX-capable instance with `/dev/sgx_enclave` and `/dev/sgx_provision` present. The paper uses Alibaba Cloud `ecs.g7t.2xlarge` (8 vCPU / 32 GB, SGX-TEE enabled).
> A local smoke test (SIM mode) works without SGX hardware.

- Ubuntu 20.04 x86-64 on coordinator and all replica nodes
- Intel SGX SDK 2.23.100.2 (bundled in `deployment/sourcefile/archive.tar.gz`)
- Python ≥ 3.8 with packages: `matplotlib paramiko scp aliyun-python-sdk-core`
- Salticidae (Git submodule): `git submodule update --init && (cd salticidae; cmake . -DCMAKE_INSTALL_PREFIX=.; make; make install)`
- hiredis + Redis (for experiment 3): `sudo apt-get install -y libhiredis-dev redis-server`
- SSH private key `TShard` at `/root/Raftel/TShard` (reviewers: distributed via HotCRP)

The cloud workflow provisions 7 hosts and reuses them for all experiments. `run.py`
can start up to 15 replicas per host on distinct ports, giving a total capacity of
105 replicas. This covers the largest configured case (`faults=32`, `3f+1=97`).
Because replicas share hosts, these measurements include same-host CPU, memory,
network, and SGX contention and are not equivalent to a one-replica-per-host setup.

---

## Path A — Pre-provisioned coordinator

The authors provide a configured coordinator ECS, but the 7-node experiment
cluster is not started in advance. The coordinator already contains the
Alibaba Cloud configuration and the SSH private key distributed through
HotCRP. From the coordinator, create the replica nodes and install their
experiment environment before starting a run:

```bash
# 1. Create 7 reusable SGX ECS nodes and wait until SSH is reachable
./ae cloud up --count 7

# 2. Synchronize the generated private IP list used by experiment scripts
cp aliyun/priv_ip.txt ip_list

# 3. Transfer the setup bundle and start environment installation on every node
./ae cloud init

# 4. Installation runs in background tmux sessions; monitor until all finish
tmux list-sessions
# To inspect one node: tmux attach -t setup1
# Detach without stopping it: Ctrl-b, then d

# 5. Verify SGX, SDK, Redis, hiredis, Salticidae, SSH, and coordinator setup
./ae cloud check
./ae doctor --profile paper

# 6. Run all three cloud experiments (~4–6 h)
./ae run all

# 7. Generate figures and the HTML report for the latest run
./ae report
```

`./ae run all` does not create ECS instances or install the remote environment;
it only compiles, deploys, starts, and measures servers on the nodes already
listed in `ip_list`. Do not start the experiment until both checks above pass
for all 7 nodes.

Open `runs/<RUN_ID>/index.html` to see the reproduced figures, comparisons against reference values, experiment parameters, paper claim descriptions, and a checksums audit trail. Apply the documented PASS/WARN/FAIL thresholds when interpreting those comparisons.

For a faster trend check (~30 min, reduced scale):

```bash
./ae run all --scale mini
./ae report
```

---

## Path B — Bring your own Alibaba Cloud account

Required: an Alibaba Cloud account with ECS access, a VPC/vSwitch in the same region, a security group allowing inbound TCP on ports 8760–9800 between nodes, and a key pair registered under the name `TShard`.

```bash
# 1. Fill in your credentials and resource IDs
cp aliyun/config.example.json aliyun/config.json
$EDITOR aliyun/config.json   # set access_key_id, access_key_secret, region_id,
                              # image_id (Ubuntu 20.04 SGX), security_group_id,
                              # vswitch_id, key_pair_name; instance_type is fixed
                              # at ecs.g7t.2xlarge — do not change it

# 2. Provision the 7 reusable hosts
./ae cloud up --count 7

# 3. Deploy code and initialize SGX on all nodes (~20 min)
./ae cloud init

# 4. Verify all dependencies are ready on every node
./ae cloud check

# 5. Run experiments and generate report
./ae run all
./ae report

# 6. Release instances when done
./ae cloud down
```

**Aliyun permissions required:** `ecs:CreateInstance`, `ecs:DeleteInstance`, `ecs:DescribeInstances`, `ecs:StartInstance`, `ecs:RunInstances`, `ecs:AllocatePublicIpAddress`.

**Network requirements:** nodes must be able to reach each other over the private VPC network on TCP ports 8760–9800. Security group must allow inbound traffic on those ports from within the VPC. Outbound internet access is needed on each node during `init` (apt, SGX packages).

---

## Reproducibility Scope

| Figure | Claim | Mode |
|---|---|---|
| Fig 3 (WAN scalability) | Achilles ≥ Chained ≥ Raftel > Hotstuff ≈ Raftel-Worst; Raftel latency ≤ Chained < Basic-Damysus | Full reproduction: ±40% absolute PASS band, ordering must match |
| Fig 4 (LAN TEE configs) | S1 > S2 ≥ S3 > S4 throughput; S1 ≤ S2 ≤ S3 ≤ S4 latency; S1 at f=32 = 31.5 kTPS | Full reproduction: same criteria |
| Fig 6 (Redis E2E WAN) | Achilles 95 TPS, Chained 92 TPS, Raftel 84 TPS, Hotstuff 44 TPS (peak) | Full reproduction: same criteria |

Expected errors: SGX attestation overhead and cloud network jitter typically produce ±10–20% variation from the paper numbers. The ±40% PASS band accounts for inter-run variance across different AE windows.

Reference values are in `runs/reference/fig{3,4,6}.csv`; PASS/WARN/FAIL criteria are in `runs/reference/EXPECTED_RANGES.md`.

---

## Figure → Script Mapping

| Figure | Experiment | Script | Output |
|---|---|---|---|
| Figure 3 | WAN scalability | `experiments_reproduction/experiment1/script/run_wan.sh` | `experiment1/stats.txt` |
| Figure 4 | LAN TEE configs | `experiments_reproduction/experiment2/script/run_lan.sh` | `experiment2/stats.txt` |
| Figure 6 | Redis E2E WAN | `experiments_reproduction/experiment3/script/run_redis_wan.sh` | `experiment3/stats.txt` |

The Figure 3/4 scripts accept `AE_FAULT_VALUES`; the Figure 6 script accepts `AE_LOAD_CLIENTS` and `AE_REPEATS`. The AE CLI sets these variables for `--scale mini`. Scripts pass `--sgx-mode HW` to `run.py` for all cloud runs.

---

## AE CLI Reference

```
./ae doctor [--profile paper|smoke]    # check environment, flag blockers
./ae smoke                             # local 4-node SIM smoke test (~5 min)
./ae run <fig3|fig4|fig6|all> [--scale full|mini]
./ae report [RUN_ID]                   # generate figures + HTML report
./ae status [RUN_ID]                   # show run completion status
./ae cloud <up|init|check|down> [--count N]
```

Each `./ae run` creates `runs/<RUN_ID>/` with:
- `manifest.json` — git commit, timestamp, cluster IPs, scale
- `events.jsonl` — timestamped event log
- `checksums.txt` — SHA256 of all scripts and `run.py`
- `stats/fig3.txt`, `stats/fig4.txt`, `stats/fig6.txt` — snapshots of that run's statistics
- `figures/` — auto-generated PDFs
- `index.html` — standalone HTML report with reference comparisons and ordering checks

After a cloud run, generate and inspect Figure 3/4 with:

```bash
./ae status                              # show the latest run ID and status
./ae report                              # report for the latest run
# or regenerate a specific historical run without mixing newer statistics:
./ae report <RUN_ID>
ls runs/<RUN_ID>/figures/fig{3,4}.pdf
```

Open `runs/<RUN_ID>/index.html` in a browser for the combined report. The source
numerical rows remain available in `runs/<RUN_ID>/stats/fig3.txt` and
`runs/<RUN_ID>/stats/fig4.txt`. The experiment directories also contain the
latest working copies and raw data under `experiments_reproduction/experiment1/`
and `experiments_reproduction/experiment2/`.

---

## Dependencies

```bash
# System packages (coordinator and nodes)
sudo apt-get install -y build-essential cmake git libssl-dev libuv1-dev \
    pkg-config python3 python3-pip libhiredis-dev redis-server

# Python packages (coordinator)
pip3 install matplotlib paramiko scp aliyun-python-sdk-core

# SGX SDK (nodes — handled automatically by ./ae cloud init)
cd deployment/sourcefile && tar -xzf archive.tar.gz
printf 'no\n/opt/intel\n' | sudo ./sgx_linux_x64_sdk_2.23.100.2.bin
source /opt/intel/sgxsdk/environment

# SGX kernel driver for HW mode (cloud nodes)
sudo bash deployment/sourcefile/SGX_init.sh   # reboot if prompted
ls /dev/sgx_enclave /dev/sgx_provision        # verify

# Salticidae submodule (coordinator)
git submodule update --init
(cd salticidae; cmake . -DCMAKE_INSTALL_PREFIX=.; make; make install)
```

---

## Troubleshooting

**The requested replicas exceed the configured host capacity**
Seven hosts support at most 105 replicas (`15` per host). Check that
`aliyun/priv_ip.txt` contains all 7 hosts and keep the configured fault range at
or below `faults=32` for `3f+1` protocols.

**`make SGX_MODE=HW failed`**
Verify the SGX SDK is sourced (`source /opt/intel/sgxsdk/environment`) and that `/dev/sgx_enclave` exists on the build node.

**WAN netem setup fails on one node**
The script exits immediately. Check SSH connectivity (`ssh -i TShard root@<IP>`) and verify that the node is listed in `ip_list`.

**`./ae cloud check` reports `hiredis:MISSING` on a node**
Run `ssh -i TShard root@<IP> 'apt-get install -y libhiredis-dev'` on the affected node. `./ae cloud init` should install it automatically; this indicates `init.sh` did not complete on that node.

**Zero completions in experiment 3**
Verify Redis is running on all nodes (`./ae cloud check` shows `redis:ok`) and that `ip_list` has at least 25 entries. The experiment scripts set `--payload 1100 --kv-value-len 1024` automatically; no manual adjustment is needed.

**SGX devices missing after reboot**
Re-run `sudo bash deployment/sourcefile/SGX_init.sh` on the affected node. On some kernels the in-kernel SGX driver requires a second boot after installing the HWE kernel.
