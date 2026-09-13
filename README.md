# Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World

Artifact for ["Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World"](doc/Breaking_Fault_Lines__Unifying_BFT_Consensus_in_a_Partially_Trusted_World.pdf), accepted at EuroSys 2027.

Raftel is an SGX-TEE-assisted BFT consensus protocol for partially trusted environments, where only a subset of replicas holds a TEE. It builds on the [Damysus](https://github.com/vrahli/damysus) codebase and shows that a minority TEE quorum suffices for safety and liveness, with throughput and latency competitive with state-of-the-art TEE-free BFT protocols. This artifact reproduces Figures 3, 4, and 6 from the paper: WAN scalability across six protocols, LAN TEE-leader and quorum-size effects, and Redis end-to-end performance.

See [doc/ARTIFACT_APPENDIX.md](doc/ARTIFACT_APPENDIX.md) for the EuroSys AE appendix and [doc/AE_USAGE.md](doc/AE_USAGE.md) for the complete reviewer workflow.

---

## Contents

- [Prerequisites](#prerequisites)
- [Reviewer Workflow](#reviewer-workflow)
- [Complete AE usage](doc/AE_USAGE.md)
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
> `--mode sim` runs the complete workflow in SGX simulation mode on
> seven multiplexed hosts. It validates usability and result generation, but
> it is not hardware evidence and cannot establish a paper performance claim.

- Ubuntu 20.04 x86-64 on coordinator and all replica nodes
- Intel SGX SDK 2.23.100.2 (bundled in `deployment/sourcefile/archive.tar.gz`)
- Python ≥ 3.8 with packages: `matplotlib paramiko scp`
- Salticidae (Git submodule): `git submodule update --init && (cd salticidae; cmake . -DCMAKE_INSTALL_PREFIX=.; make; make install)`
- hiredis + Redis (for experiment 3): `sudo apt-get install -y libhiredis-dev redis-server`
- An author-provided SSH credential on the pre-provisioned coordinator

Full paper topology needs up to 97 replica VMs for both Figures 3 and 4
(f=32, 3f+1), and 25 for Figure 6 (f=8). Simulation mode uses seven hosts
and maps up to 15 logical replicas to distinct ports on each host, so the full
`f={1,2,4,8,16,32}` sweep (including `n=97`) remains available. Simulation
results are explicitly labelled and are useful for pipeline and trend
validation; Full is the SGX HW, one-replica-per-VM claim configuration.

---

## Reviewer Workflow

The authors provide a runner with the repository, SGX dependencies, and the
cloud configuration/SSH credential outside this repository. Reviewers do not
need an Alibaba Cloud account or any cloud credentials. If no replica inventory
exists, either reviewer entry point creates and initializes its disposable
replica cluster before starting measurements.

```bash
# Cost-saving complete sweep on seven hosts
./ae run all --mode sim

# Or: paper topology, one replica per VM
./ae run all --mode full
```

Choose one command. Simulation runs all six fault points on seven hosts,
with 97 logical replicas at `f=32`, and uses one Fig. 6 repeat. Its report is
labelled as SGX SIM and is not eligible for hardware or full paper claims. Full
uses SGX HW with the dedicated-VM topology, every paper fault point, and three
Fig. 6 repeats. Each command automatically checks its environment, runs all
experiments, plots the results, and writes a standalone
`runs/<RUN_ID>/index.html` report. A cluster created by the command is released
when the run ends; an existing author-prepared cluster is retained.

---

## Reproducibility Scope

| Figure | Claim | Mode |
|---|---|---|
| Fig 3 (WAN scalability) | Achilles ≥ Chained ≥ Raftel > Damysus > HotStuff throughput; Raftel-Worst is comparable to HotStuff | Full reproduction: ±40% absolute PASS band and material ordering checks |
| Fig 4 (LAN TEE configs) | S1 highest; S2 slightly outperforms S3; S4 lowest; S1 at f=32 = 31.5 kTPS | Full reproduction: same criteria; the original script's positional S2 mapping is preserved |
| Fig 6 (Redis E2E WAN) | Achilles 95 TPS, Chained 92 TPS, Raftel 84 TPS, Hotstuff 44 TPS (peak) | Full reproduction: same criteria |

SGX enclave overhead and cloud network jitter may vary across AE windows. The
artifact records deviations and applies the author-defined ±40% PASS band. The
prototype does not implement remote attestation, as stated in paper §7.1.

Author-supplied reference values are in `runs/reference/original/`;
PASS/WARN/FAIL criteria are in `runs/reference/EXPECTED_RANGES.md`.

---

## Figure → Script Mapping

| Figure | Experiment | Script | Output |
|---|---|---|---|
| Figure 3 | WAN scalability | `experiments_reproduction/experiment1/script/run_wan.sh` | `experiment1/stats.txt` |
| Figure 4 | LAN TEE configs | `experiments_reproduction/experiment2/script/run_lan.sh` | `experiment2/stats.txt` |
| Figure 6 | Redis E2E WAN | `experiments_reproduction/experiment3/script/run_redis_wan.sh` | `experiment3/stats.txt` |

Simulation uses seven hosts, up to 15 replicas per host, all six fault points,
SGX SIM, and one Fig. 6 repeat. Full keeps all paper fault points with one SGX HW
replica per host.

---

## AE CLI Reference

```
./ae doctor                            # diagnose an existing environment
./ae run <fig3|fig4|fig6|all> [--mode sim|full]
./ae report [RUN_ID]                   # generate figures + HTML report
./ae status [RUN_ID]                   # show run completion status
./ae cloud check                       # optional replica-cluster preflight
```

Each `./ae run` creates `runs/<RUN_ID>/` with:
- `manifest.json` — git commit, timestamp, cluster IPs, mode
- `events.jsonl` — timestamped event log
- `checksums.txt` — SHA256 of all scripts and `run.py`
- `figures/` — auto-generated PDFs
- `index.html` — standalone HTML report with PASS/WARN/FAIL

---

## Dependencies

```bash
# System packages (coordinator and nodes)
sudo apt-get install -y build-essential cmake git libssl-dev libuv1-dev \
    pkg-config python3 python3-pip libhiredis-dev redis-server

# Python packages (coordinator)
pip3 install matplotlib paramiko scp

# SGX SDK (already installed on the author-prepared nodes)
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

**`mkConfig` reports insufficient replica capacity**
Run `./ae doctor` and send its output to the authors; the
provided cluster inventory does not match the selected mode.

**`make SGX_MODE=HW failed`**
Verify the SGX SDK is sourced (`source /opt/intel/sgxsdk/environment`) and that `/dev/sgx_enclave` exists on the build node.

**WAN netem setup fails on one node**
The script exits immediately. Run `./ae cloud check` and send the failed host
and run ID to the authors.

**`./ae cloud check` reports `hiredis:MISSING` on a node**
Send the check output to the authors; the prepared node is incomplete.

**Zero completions in experiment 3**
Verify Redis is running on all nodes (`./ae cloud check`) and that
`aliyun/priv_ip.txt` has at least 25 entries in Full mode. The experiment script
sets `--payload 1100 --kv-value-len 1024` automatically.

**SGX devices missing after reboot**
Re-run `sudo bash deployment/sourcefile/SGX_init.sh` on the affected node. On some kernels the in-kernel SGX driver requires a second boot after installing the HWE kernel.
