# Experiment 1: WAN scalability

本实验在所有远程服务器的 `eth0` 上配置 `50ms` netem delay，然后运行以下组合：

- 协议：`p0`、`p01`、`p1`、`p5`、`p6`
- faults：`1`、`2`、`4`、`8`、`16`、`32`
- 固定参数：`--batchsize 400 --payload 256`

共运行 30 组实验。脚本退出时会自动移除远程服务器上的 netem delay。

## 运行

从仓库任意位置执行：

```bash
bash /root/Raftel/experiments_reproduction/experiment1/script/run_wan.sh
```

运行前请确认：

- `/root/Raftel/ip_list` 包含远程服务器 IP；
- `/root/Raftel/TShard` 是可用的 SSH 私钥；
- 远程项目目录与 `run.py` 使用的 `DAMYSUS_REMOTE_ROOT` 一致，默认是 `/root/Raftel`；
- 远程服务器允许通过 `sudo tc` 设置 `eth0` 的网络延迟。

如远程项目位于其他目录，可在运行前设置，例如：

```bash
export DAMYSUS_REMOTE_ROOT=/root/another-directory
bash /root/Raftel/experiments_reproduction/experiment1/script/run_wan.sh
```

## 输出结构

- `results/summary.csv`：所有 30 组实验的全局吞吐量和延迟汇总；
- `results/run.py-summary-raw.txt`：`run.py` 生成的原始汇总；
- `results/<protocol>_f<faults>/`：每组实验下载的原始 stats；
- `log/<protocol>_f<faults>/orchestrator.log`：该组实验的完整控制端输出；
- `log/<protocol>_f<faults>/remote/`：该组实验所有远程副本的 `out*` 日志。

脚本会继续执行后续组合，并在 `summary.csv` 中标记失败的运行；只要有一组失败，脚本最终退出码就不是 0。
