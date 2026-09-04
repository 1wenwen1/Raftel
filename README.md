# Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World

This repository contains the code accompanying the paper ["Breaking Fault Lines: Unifying BFT Consensus in a Partially Trusted World"](doc/Breaking_Fault_Lines__Unifying_BFT_Consensus_in_a_Partially_Trusted_World.pdf), which was accepted to EuroSys 2027.

## Contents

- [Current status](#current-status)
- [Description](#description)
- [Dependencies](#dependencies)
  - [Required versions](#required-versions)
  - [System packages](#system-packages)
  - [Python packages](#python-packages)
  - [Salticidae](#salticidae)
- [Experiments](#experiments)
  - [Local experiments](#local-experiments)
    - [Minimal local test](#minimal-local-test)
  - [Ali Cloud experiments](#ali-cloud-experiments)
    - [Launch instances](#launch-instances)
    - [Configure the nodes](#configure-the-nodes)
    - [Run a cloud experiment](#run-a-cloud-experiment)

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

- `--p0`: HybridTEE (Raftel)
- `--p1`: Chained-HybridTEE (Chained-Raftel)
- `--p2`: Achilles
- `--p3`: Hotstuff
- `--p4`: Basic-Damysus

If no protocol selector is supplied, `run.py` defaults to `--p0`.

Common local options are:

- `--local`: run all replicas on the current machine.
- `--faults N`: set the number of tolerated faults (default: `1`). The protocol determines the replica count.
- `--totaltee N`: set the number of TEE replicas for HybridTEE (default: `0`). Protocols with a fixed TEE population ignore this option.
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

This compiles HybridTEE in SGX simulation mode and runs four local replicas, two of which are configured as TEE replicas. The experiment typically takes about two minutes. A successful run finishes all processes and prints throughput and latency summaries similar to:

```text
HybridTEE_1_2_256_400_0 thr_view= 314.6285385 lat_view= 1.27134375 e2e_reply_tps= 0.425713 e2e_p95= 2.324 e2e_p99= 2.324
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

```bash
cd /root/Raftel
source /opt/intel/sgxsdk/environment
python3 run.py --p0 --faults 1 --totaltee 2 --experiment-number 1 \
  --payload 256 --batchsize 400 --views 10 --cl-trans 1
```

Add `--redis` to reproduce the Redis-backed KV path. Experiment statistics are collected under `stats/` and `stats.txt`. To copy remote `out<N>` stdout logs into per-node directories under local `out/`, run:

```bash
python3 deployment/fetch_remote_logs.py
```

Ali Cloud resources incur charges. When the experiment is complete, verify the IDs in `aliyun/instances.txt` and release those instances with:

```bash
cd /root/Raftel
python3 aliyun/delete_instances.py
```
