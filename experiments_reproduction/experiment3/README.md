# Experiment 3: Redis WAN end-to-end performance

本实验在远程服务器上设置 `50ms` netem delay，测试五种协议的 Redis-backed KV workload：

- 协议：`p0`、`p01`、`p1`、`p5`、`p6`；
- `faults=8`，请求 `totaltee=9`；
- 100% SET，value 大小为 1 KB，keyspace 为 10,000；
- batchsize 400，payload 256；
- 4 个并发客户端，每个客户端发送 2,000 条请求，无发送间隔；
- 30 views，每种协议重复 3 次；
- 固定节点 0 为 leader；
- 使用 `--redis` 显式启动并使用远程 Redis backend。

`run.py` 只允许 HybridTEE 自定义 TEE 数量。实际配置为：HybridTEE 9 个 TEE、Chained-HybridTEE 9 个 TEE、Achilles 全部 17 个副本为 TEE、Hotstuff 0 个 TEE、Basic-Damysus 全部 17 个副本为 TEE。

## 运行

```bash
cd /root/Raftel
./experiments_reproduction/experiment3/script/run_redis_wan.sh
```

如远程项目不在 `/root/Raftel`，请先设置 `DAMYSUS_REMOTE_ROOT`。脚本结束或中断时会移除远程服务器上的 netem delay。

## 测量指标

- 系统端到端 reply throughput（KTPS）：所有客户端完成请求数除以它们共同的 reply 时间窗口；
- E2E latency：average、p50、p95、p99，单位为 ms；
- 每轮完成请求数。

## 输出

- `results/per-run.csv`：15 次运行各自的 E2E 指标；
- `results/summary.csv`：按协议对成功运行取均值；
- `results/raw/<protocol>_repeat<n>/`：每次运行的原始 stats 和 client E2E 文件；
- `log/<protocol>_repeat<n>/orchestrator.log`：控制端完整输出；
- `log/<protocol>_repeat<n>/remote/`：所有远程副本的 `out*` 日志。
