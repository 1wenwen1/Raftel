# Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World

Artifact for ["Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World"](doc/Breaking_Fault_Lines__Unifying_BFT_Consensus_in_a_Partially_Trusted_World.pdf), accepted at EuroSys 2027.

Raftel is an SGX-TEE-assisted BFT consensus protocol for partially trusted environments, where only a subset of replicas holds a TEE. It builds on the [Damysus](https://github.com/vrahli/damysus) codebase and shows that a minority TEE quorum suffices for safety and liveness, with throughput and latency competitive with state-of-the-art TEE-free BFT protocols. This artifact reproduces Figures 3 and 4 from the paper: WAN scalability across six protocols and LAN TEE-leader and quorum-size effects.

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

> **SGX mode:** all local and cloud experiment scripts use `SGX_MODE=SIM` by
> default. The SGX SDK and SGX SSL are still required to compile simulation-mode
> enclaves, but SGX hardware devices are not used by the experiments.

- Ubuntu 20.04 x86-64 on coordinator and all replica nodes
- Intel SGX SDK 2.23.100.2 (bundled in `deployment/sourcefile/archive.tar.gz`)
- Python ≥ 3.8 with packages: `matplotlib paramiko scp aliyun-python-sdk-core`
- Salticidae (Git submodule): `git submodule update --init && (cd salticidae; cmake . -DCMAKE_INSTALL_PREFIX=.; make; make install)`
- SSH private key `TShard` at `/root/Raftel/TShard` (reviewers: distributed via HotCRP)

The cloud workflow provisions 10 hosts and reuses them for all experiments. `run.py`
can start up to 15 replicas per host on distinct ports, giving a total capacity of
150 replicas. This covers the largest configured case (`faults=32`, `3f+1=97`).
Because replicas share hosts, these measurements include same-host CPU, memory,
network, and SGX contention and are not equivalent to a one-replica-per-host setup.

---

## Path A — Pre-provisioned coordinator

The authors provide a configured coordinator ECS, but the 10-node experiment
cluster is not started in advance. The coordinator already contains the
Alibaba Cloud configuration and the SSH private key distributed through
HotCRP. From the coordinator, create the replica nodes and install their
experiment environment before starting a run:

```bash
# 0. Run a local smoke test before provisioning cloud instances
./ae smoke

# 1. Create 10 reusable SGX ECS nodes and wait until SSH is reachable
./ae cloud up --count 10

# Synchronize the generated private IP list used by experiment scripts
cp aliyun/priv_ip.txt ip_list

# 2. Transfer the setup bundle and start environment installation on every node
./ae cloud init

# Installation runs in background tmux sessions; monitor until all finish
tmux list-sessions
# To inspect one node:
tmux attach -t setup1
# Detach without stopping it: Ctrl-b, then d

# 3. Verify SGX, SDK, Salticidae, SSH, and coordinator setup
./ae cloud check
./ae doctor --profile paper

# 4. Run one small could experiment before starting the full experiments
python3 run.py --p0 --faults 1 --totaltee 2

# 5. Run experiments and then generate their reports
./ae run fig3   # Experiment 1 / Figure 3 (~3 h)
./ae run fig4   # Experiment 2 / Figure 4 (~2 h)

# 6. Generate and view the figures manually

bash
python3 scripts/plot_fig3.py
python3 scripts/plot_fig4.py


#The generated PNG files are available at:

experiments_reproduction/experiment1/results/fig3.png
experiments_reproduction/experiment2/results/fig4.png

# 7. Release instances when done
bash
./ae cloud down
```

The raw summary data can be inspected directly after each experiment:

- Figure 3: `experiments_reproduction/experiment1/stats.txt`
- Figure 4: `experiments_reproduction/experiment2/stats.txt`

 The raw data has the form
`configuration_f<number-of-faults>, throughput_kTPS, latency_ms`. For example:

```text
Chained_Raftel_f16, 0.8582167777777777, 830.3356493055554
```

This means that the **Chained_Raftel** protocol was measured with 16 tolerated faults,
giving a throughput of `0.8582167777777777` kTPS and a latency of
`830.3356493055554` ms.


---

## Path B — Bring your own Alibaba Cloud account

Required: an Alibaba Cloud account with ECS access, a VPC/vSwitch in the same region, a security group allowing inbound TCP on ports 8760–9800 between nodes, and a key pair registered under the name `TShard`.

```bash
# 1. Fill in your credentials and resource IDs
cp aliyun/config.example.json aliyun/config.json
$EDITOR aliyun/config.json   # set access_key_id, access_key_secret, region_id,
                              # image_id (Ubuntu 20.04), security_group_id,
                              # vswitch_id, key_pair_name; instance_type is fixed
                              # at ecs.g7t.2xlarge — do not change it

# 2. Provision the 10 reusable hosts
./ae cloud up --count 10

# 3. Deploy code and initialize the experiment environment (~20 min)
./ae cloud init

# 4. Verify all dependencies are ready on every node (~2 min)
./ae cloud check

# 5. Run all experiment and then generate its report
./ae run fig3   # Experiment 1 / Figure 3(~ 3 h)
./ae run fig4   # Experiment 2 / Figure 4(~ 2 h)

# 6. Release instances when done
./ae cloud down
```

**Aliyun permissions required:** `ecs:CreateInstance`, `ecs:DeleteInstance`, `ecs:DescribeInstances`, `ecs:StartInstance`, `ecs:RunInstances`, `ecs:AllocatePublicIpAddress`.

**Network requirements:** nodes must be able to reach each other over the private VPC network on TCP ports 8760–9800. Security group must allow inbound traffic on those ports from within the VPC. Outbound internet access is needed on each node during `init` (apt, SGX packages).

---

## Reproducibility Scope

| Figure | Claim | Mode |
|---|---|---|
| Fig 3 (WAN scalability) | Achilles ≥ Chained_Raftel ≥ Raftel > Damysus> Hotstuff ≈ Raftel-Worst, with the latency trend generally reversed. | Full reproduction: ±40% absolute PASS band, ordering must match |
| Fig 4 (LAN TEE configs) | S1 > S2 ≥ S3 > S4 throughput, with the latency trend generally reversed. | Full reproduction: same criteria |

Expected errors: SGX attestation overhead and cloud network jitter typically produce ±10–20% variation from the paper numbers. The ±40% PASS band accounts for inter-run variance across different AE windows.

Reference values are in `runs/reference/fig{3,4}.csv`; PASS/WARN/FAIL criteria are in `runs/reference/EXPECTED_RANGES.md`.

---

## Figure → Script Mapping

| Figure | Experiment | Script | Output |
|---|---|---|---|
| Figure 3 | WAN scalability | `experiments_reproduction/experiment1/script/run_wan.sh` | `experiment1/stats.txt` |
| Figure 4 | LAN TEE configs | `experiments_reproduction/experiment2/script/run_lan.sh` | `experiment2/stats.txt` |

The Figure 3/4 scripts accept `AE_FAULT_VALUES`. The AE CLI sets this variable for `--scale mini`. All experiment scripts pass `--sgx-mode SIM` to `run.py`.

---

## AE CLI Reference

```
./ae doctor [--profile paper|smoke]    # check environment, flag blockers
./ae smoke                             # local 4-node SIM smoke test (~5 min)
./ae run <fig3|fig4|all> [--scale full|mini]
./ae report [RUN_ID]                   # generate figures + HTML report
./ae status [RUN_ID]                   # show run completion status
./ae cloud <up|init|check|down> [--count N]
```

For `cloud up`, `--count N` is the target total number of instances. IDs already
listed in `aliyun/instances.txt` count toward that target, so if 7 instances are
tracked, `./ae cloud up --count 10` creates only 3 additional instances. If the
target has already been reached, no new instances are created. Remove stale IDs
from `instances.txt` if the corresponding ECS instances no longer exist.

Each `./ae run` creates `runs/<RUN_ID>/` with:
- `manifest.json` — git commit, timestamp, cluster IPs, scale
- `events.jsonl` — timestamped event log
- `checksums.txt` — SHA256 of all scripts and `run.py`
- `stats/fig3.txt`, `stats/fig4.txt` — snapshots of that run's statistics
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
    pkg-config python3 python3-pip

# Python packages (coordinator)
pip3 install matplotlib paramiko scp aliyun-python-sdk-core

# SGX SDK (nodes — handled automatically by ./ae cloud init)
cd deployment/sourcefile && tar -xzf archive.tar.gz
printf 'no\n/opt/intel\n' | sudo ./sgx_linux_x64_sdk_2.23.100.2.bin
source /opt/intel/sgxsdk/environment

# SGX hardware mode is optional and is not used by the default experiments.

# Salticidae submodule (coordinator)
git submodule update --init
(cd salticidae; cmake . -DCMAKE_INSTALL_PREFIX=.; make; make install)
```

---

## Troubleshooting

**The requested replicas exceed the configured host capacity**
Ten hosts support at most 150 replicas (`15` per host). Check that
`aliyun/priv_ip.txt` contains all 10 hosts and keep the configured fault range at
or below `faults=32` for `3f+1` protocols.

**`make SGX_MODE=SIM failed`**
Verify that the SGX SDK is installed and sourced with
`source /opt/intel/sgxsdk/environment`. SGX hardware devices are not required.

**WAN netem setup fails on one node**
The script exits immediately. Check SSH connectivity (`ssh -i TShard root@<IP>`) and verify that the node is listed in `ip_list`.
