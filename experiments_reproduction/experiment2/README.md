# Experiment 2: LAN leader/quorum combinations

本实验不增加网络延迟。脚本开始时会删除远程服务器 `eth0` 上可能由 WAN 实验遗留的 root qdisc，然后运行 HybridTEE（`p0`）的四种组合。固定参数为：

```text
--batchsize 400 --payload 256 --faults 32
```

## 实验组合

| Case | totaltee | Leader mode | 实际 leader 类型 | TEE quorum |
|---|---:|---|---|---|
| `tee-leader_no-tee-quorum` | 32 | fixed，节点 0 | TEE | 不可组成 |
| `tee-leader_tee-quorum` | 33 | fixed，节点 0 | TEE | 可以组成 |
| `nontee-leader_no-tee-quorum` | 32 | fixed，节点 33 | non-TEE | 不可组成 |
| `nontee-leader_tee-quorum` | 33 | fixed，节点 33 | non-TEE | 可以组成 |

节点编号从 0 开始。`totaltee=33` 表示节点 `0–32` 是 TEE，因此节点 `33` 是 non-TEE。

四组实验都显式使用固定 leader：前两组使用 TEE 节点 `0`，后两组使用 non-TEE 节点 `33`，因此 leader 在整个实验期间不会随 view 轮换。

## 运行

```bash
cd /root/Raftel
./experiments_reproduction/experiment2/script/run_lan.sh
```

如远程项目不在 `/root/Raftel`，请先设置 `DAMYSUS_REMOTE_ROOT`。

## 输出

- `results/summary.csv`：四种组合的全局吞吐量、延迟和运行状态；
- `results/run.py-summary-raw.txt`：`run.py` 的原始汇总行；
- `results/<case>/`：对应组合的原始 stats；
- `log/<case>/orchestrator.log`：控制端完整输出；
- `log/<case>/remote/`：从所有远程服务器收集的 `out*` 日志。
