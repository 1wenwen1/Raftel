# Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World

This repository contains the code accompanying the paper ["Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World"](doc/Breaking_Fault_Lines__Unifying_BFT_Consensus_in_a_Partially_Trusted_World.pdf), which was accepted to EuroSys 2027.

## Contents

- [Current status](#current-status)
- [Description](#description)
- [Dependencies](#dependencies)
  - [Required versions](#required-versions)
  - [System packages](#system-packages)
  - [SGX kernel support](#sgx-kernel-support)
  - [Intel SGX SDK](#intel-sgx-sdk)
  - [Python packages](#python-packages)
  - [Salticidae](#salticidae)
- [Experiments](#experiments)
  - [Local experiments](#local-experiments)
    - [Minimal local test](#minimal-local-test)
  - [Ali Cloud experiments](#ali-cloud-experiments)
    - [Launch instances](#launch-instances)
    - [Configure the nodes](#configure-the-nodes)
    - [Run a cloud experiment](#run-a-cloud-experiment)
    - [Experiments Reproduction](#experiments-reproduction)

## Current status

The software is under ongoing development.

## Description

Raftel is an SGX-based, TEE-assisted Byzantine Fault Tolerance (BFT) protocol designed for partially trusted systems in which only a subset of replicas is equipped with a TEE. This implementation is built on top of the [Damysus](https://github.com/vrahli/damysus) codebase.

The implementation is organized as follows:

- `App/Handler.cpp` implements the host-side consensus logic, including message handling, protocol phases, quorum processing, and communication with the enclave.
- `Enclave/EnclaveComb.cpp` implements the trusted operations for the basic Raftel protocol, including protocol-state transitions, proposal validation, signing, quorum-certificate validation, and vote accumulation.
- `Enclave/EnclaveChComb.cpp` implements the trusted operations for Chained-Raftel.
- `App/params.h` selects the protocol at compile time. Raftel and Chained-Raftel are enabled by the `BASIC_HYBRID_TEE` and `CHAINED_HYBRID_TEE` macros, respectively.
- `run.py` generates the protocol parameters and node configuration, compiles the selected implementation, and orchestrates local or distributed experiments.

## Dependencies

The documented and deployment-tested environment is Ubuntu 20.04 x86-64 with Python 3.8.10. The default build uses Intel SGX simulation mode (`SGX_MODE=SIM`), so SGX-capable hardware is not required for the minimal local test. The SGX SDK and SGX SSL are still required to compile it.

### Required versions

- Ubuntu 20.04 x86-64
- Python 3.8.10
- CMake >= 3.9 and a C++14 compiler
- Intel SGX SDK 2.23.100.2
- OpenSSL 1.1.x and libuv >= 1.10.0
- `pkg-config` 0.29.1
- hiredis 0.14.0 and Redis 5.0.7 (only required for experiment reproduction)

Use the SGX SSL package and Salticidae source included in this repository; neither has a separate release version recorded here.

### System packages

Install the packages required by the test:

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake git libssl-dev libuv1-dev pkg-config python3 python3-pip
```

The Redis-backed experiment path additionally requires hiredis and Redis:

```bash
sudo apt-get install -y libhiredis-dev redis-server
pkg-config --modversion hiredis
redis-server --version
```

Use `--redis` when running an experiment that should use this backend. The default local test uses the in-memory backend and does not start Redis.

### SGX kernel support

Hardware-mode experiments require an SGX-capable machine and the Linux in-kernel SGX driver. On Ubuntu 20.04, run the included setup check:

```bash
cd /root/Raftel
sudo bash deployment/sourcefile/SGX_init.sh
```

If it installs the HWE kernel, reboot and run the command again. A successful setup exposes both devices:

```bash
ls /dev/sgx_enclave /dev/sgx_provision
```

The minimal local test uses SGX simulation mode and does not require SGX hardware or these device nodes.

### Intel SGX SDK

Extract the bundled installers and install Intel SGX SDK 2.23.100.2 under `/opt/intel/sgxsdk`:

```bash
cd /root/Raftel/deployment/sourcefile
tar -xzf archive.tar.gz
printf 'no\n/opt/intel\n' | sudo ./sgx_linux_x64_sdk_2.23.100.2.bin
source /opt/intel/sgxsdk/environment
```

Run the final `source` command in each new shell before building or running an experiment.

### Python packages

- `matplotlib`
- `paramiko`
- `scp`
- `aliyun-python-sdk-core` (Ali Cloud deployment only)

### Salticidae

If you decide to install Salticidae locally, you will need Git and CMake. After cloning the repository, initialize the Salticidae Git submodule:

```bash
git submodule init
```

followed by:

```bash
git submodule update
```

Salticidae has the following dependencies:

- CMake >= 3.9
- C++14
- libuv >= 1.10.0
- OpenSSL >= 1.1.0

Install these dependencies with:

```bash
sudo apt install cmake libuv1-dev libssl-dev
```

Then, to install Salticidae, run:

```bash
(cd salticidae; cmake . -DCMAKE_INSTALL_PREFIX=.; make; make install)
```

## Experiments

> **Note:** If you are using a server on which all dependencies and the SGX environment have already been configured, start from this section.

`run.py` compiles the selected protocol, generates the local configuration, starts the replicas and client, and prints the aggregated throughput and latency. Run it from the repository root.

### Local experiments

The protocol selectors implemented by `run.py` are:

- `--p0`: Raftel
- `--p1`: Chained
- `--p2`: Achilles
- `--p3`: Hotstuff
- `--p4`: Basic-Damysus

If no protocol selector is supplied, `run.py` defaults to `--p0`.

Common local options are:

- `--local`: run all replicas on the current machine.
- `--faults N`: set the number of tolerated faults (default: `1`). The protocol determines the replica count.
- `--totaltee N`: set the number of TEE replicas for Raftel (default: `0`). Protocols with a fixed TEE population ignore this option.
- `--payload N`: set the payload size in bytes (default: `256`).
- `--batchsize N`: set the compile-time maximum transactions per batch (default: `400`).
- `--views N`: set the number of views passed to each replica (default: `10`).
- `--redis`: use the Redis-backed KV path instead of the in-memory backend.
- `--debug`: build and run the non-enclave server executable.

Run `python3 run.py --help` for fault-injection, leader-selection, workload-mix, and plotting options.

#### Minimal local test

```bash
cd /root/Raftel
source /opt/intel/sgxsdk/environment
python3 run.py --local --p0 --faults 1 --totaltee 2
```

This compiles Raftel in SGX simulation mode and runs four local replicas, two of which are configured as TEE replicas. The experiment typically takes about two minutes. A successful run finishes all processes and prints throughput and latency summaries similar to:

```text
Raftel_1_2_256_400_0 thr_view= 314.6285385 lat_view= 1.27134375 e2e_reply_tps= 0.425713 e2e_p95= 2.324 e2e_p99= 2.324
```

The exact values depend on the machine; successful process completion and non-empty throughput/latency results are the relevant smoke-test criteria.

### Ali Cloud experiments

Check out the repository at `/root/Raftel` on the coordinator machine. Cloud deployment uses Ubuntu 20.04 ECS instances, root SSH access, private-network connectivity from the coordinator to every instance, and the SSH private key `/root/Raftel/TShard`.

Create the local `aliyun/config.json` from `aliyun/config.example.json`, then configure the region, access key, image, security group, VPC, vSwitch, instance type, and key-pair name for the target Ali Cloud account. `aliyun/config.json` is excluded from Git and must remain local because it contains account credentials and resource identifiers. Ali Cloud instance-management scripts are in `aliyun/`; cluster deployment scripts are in `deployment/`; and the archive and initialization script copied to each node are in `deployment/sourcefile/`.

#### Launch instances

Install the Aliyun SDK, then create the instances from the coordinator:

```bash
cd /root/Raftel
python3 aliyun/create_run_instances.py
```

The default `instance_count` in `aliyun/config.json` is `7`. Instance IDs are appended to `aliyun/instances.txt`. Wait for every instance to enter the `Running` state, acquire a private IP address, and accept SSH connections:

```bash
python3 aliyun/wait_instances_ready.py
```

The polling script reads `aliyun/instances.txt` and writes `aliyun/priv_ip.txt` only after all listed instances pass every check. By default it polls every 10 seconds for up to 15 minutes. Use `--interval`, `--timeout`, `--key`, or `--user` to override those settings. `run.py` later reads `aliyun/priv_ip.txt` and, for every cloud run, calls `mkConfig(...)` to generate the replica configuration and the repository-root `config`, `clients`, and `ip_list` files from the selected protocol and fault parameters.

Transfer the deployment archives and initialization scripts to every address in `aliyun/priv_ip.txt`:

```bash
bash deployment/cloud_deploy.sh
```

`deployment/cloud_deploy.sh` performs file transfer only. It invokes `deployment/transfer.py`, which copies `deployment/sourcefile/archive.tar.gz` and `deployment/sourcefile/init.sh` to `/root/` on each instance. Therefore, instance creation and readiness polling must be run explicitly first.

#### Configure the nodes

Start one background tmux setup session per instance:

```bash
bash deployment/cloud_config.sh
```

Each session connects to a node and runs `/root/init.sh`. Inspect a particular setup session with:

```bash
tmux list-sessions
tmux attach -t setup1
```

Detach without stopping the remote installation by pressing `Ctrl-b`, then `d`. Do not type `exit` merely to detach: it terminates the SSH shell in that session. When all installations have completed, close the setup sessions with:

```bash
bash deployment/close.sh
```

Warning: `deployment/close.sh` kills every tmux session on the coordinator, not only sessions named `setup*`.

For Redis-backed reproduction, install hiredis on all configured nodes after the SGX setup:

```bash
bash deployment/install_hiredis_on_ips.sh
```

#### Run a cloud experiment

Run `run.py` from `/root/Raftel` without `--local`. It reads the generated node files and deploys the compiled binaries to the remote nodes. For example:

If `--experiment-number` is omitted, the run is treated as a minimal cloud smoke test and its generated artifacts and collected results are written under `experiments_reproduction/experiment0/`. Passing `--experiment-number N` continues to select `experiments_reproduction/experimentN/`.

```bash
cd /root/Raftel
source /opt/intel/sgxsdk/environment
python3 run.py --p0 --faults 1 --totaltee 2
```

Add `--redis` to reproduce the Redis-backed KV path. For each selected experiment directory, `run.py` stores compiled binaries and generated `params.h` files under `exe/`, the latest raw node results under `results/current/`, remote and client logs under `log/current/`, and computed statistics in `stats.txt`. To fetch remote `out<N>` logs manually into `log/manual/`, run:

```bash
python3 deployment/fetch_remote_logs.py
```

Ali Cloud resources incur charges. When the experiment is complete, verify the IDs in `aliyun/instances.txt` and release those instances with:

```bash
cd /root/Raftel
python3 aliyun/delete_instances.py
```

#### Experiments Reproduction

The following scripts reproduce the main experiments corresponding to Figures 3, 4, and 6 in the paper. Run them after completing the Ali Cloud deployment and node configuration above. Before running a script, verify that `/root/Raftel/ip_list` contains the remote node IPs and `/root/Raftel/TShard` is a valid SSH private key.

At the start of each experiment, its script removes the previous contents of that experiment's `exe/`, `log/`, `out/`, and `results/` directories (except `.gitkeep`) and starts a new `stats.txt`. Copy any results that you want to retain before rerunning an experiment.

**Experiment 1 — WAN scalability (Figure 3)**

This experiment applies a 50 ms network delay to the remote nodes and measures the throughput and latency of five protocols plus the Raftel-Worst configuration, with fault thresholds of 1, 2, 4, 8, 16, and 32. Raftel-Worst uses `--p0`, `totaltee=faults`, and fixed leader replica `faults+1`.

Estimated running time: approximately 2 hours.

```bash
cd /root/Raftel
bash experiments_reproduction/experiment1/script/run_wan.sh
```

View the results in:

- `experiments_reproduction/experiment1/stats.txt`: throughput and latency for every protocol/fault-threshold combination.
- `experiments_reproduction/experiment1/exe/`: compiled executables and generated `params.h` files.
- `experiments_reproduction/experiment1/results/<protocol>_f<faults>/`: raw statistics for each run.
- `experiments_reproduction/experiment1/log/<protocol>_f<faults>/`: orchestrator and remote-replica logs.

**Experiment 2 — TEE leader and quorum combinations (Figure 4)**

This LAN experiment evaluates Raftel under four combinations: a TEE or non-TEE leader, with or without enough TEE replicas to form a TEE quorum. Each set is evaluated with fault thresholds of 1, 2, 4, 8, 16, and 32, using a batch size of 400 and a 256-byte payload.

Estimated running time: approximately 1.5 hours.

```bash
cd /root/Raftel
bash experiments_reproduction/experiment2/script/run_lan.sh
```

View the results in:

- `experiments_reproduction/experiment2/stats.txt`: computed throughput and latency for all 24 combinations, labeled `set<1-4>_f<faults>`.
- `experiments_reproduction/experiment2/exe/`: compiled executables and generated `params.h` files.
- `experiments_reproduction/experiment2/results/set<1-4>_f<faults>/`: raw statistics for each combination.
- `experiments_reproduction/experiment2/log/set<1-4>_f<faults>/`: orchestrator and remote-replica logs.

**Experiment 3 — Redis end-to-end performance (Figure 6)**

This experiment applies a 50 ms network delay and runs a Redis-backed, 100% SET workload with 1 KB values. It compares the end-to-end throughput and latency of the five protocols with `faults=8`, four clients, and three repetitions per protocol.

Estimated running time: approximately 1.5 hours.

```bash
cd /root/Raftel
bash experiments_reproduction/experiment3/script/run_redis_wan.sh
```

View the results in:

- `experiments_reproduction/experiment3/stats.txt`: final mean E2E metrics grouped by protocol.
- `experiments_reproduction/experiment3/exe/`: compiled executables and generated `params.h` files.
- `experiments_reproduction/experiment3/results/raw/<protocol>_repeat<n>/`: raw statistics and client E2E measurements.
- `experiments_reproduction/experiment3/log/<protocol>_repeat<n>/`: orchestrator and remote-replica logs.

Each experiment directory also contains a dedicated `README.md` with its complete configuration and output layout.
