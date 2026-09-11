# Raftel AE 设计方案与 TODO 清单

> 参考 EuroSys/SOSP/OSDI 历届 Best Artifact 经验（详见 `doc/BEST_AE_ANALYSIS.md`），
> 为 Raftel AE 制定完整的技术设计和落地路径。

---

## 一、当前状态快照

### 已完成 ✅
- `./ae` 统一 CLI（doctor / smoke / run / report / status / cloud）
- Run-ID 审计目录（manifest.json + events.jsonl + checksums.txt + raw logs）
- 自动绘图脚本（plot_fig3/4/6.py）
- HTML 报告生成器（gen_report.py）
- `--scale mini`（SIM 模式，小规模快速通道）
- `--scale full`（HW 模式，论文规模完整通道）
- Figure → Script 对应表（README）
- P0-1 修复：Redis payload/value-len 对齐
- P0-2 修复：`--sgx-mode {SIM,HW}` 参数
- P0-3 修复：mkConfig 断言（含双模式说明）
- P0-4 修复：WAN netem SSH 失败改为 fatal
- P0-5 修复：run_redis_wan.sh load sweep
- P0-6 修复：Raftel-Worst 改为 `--totaltee 0`
- P0-7 修复：make 返回码检查；summarize_e2e.py 零完成抛异常
- `init.sh` 补全 hiredis + Python 依赖
- `config.example.json` 写明推荐机型和规格注释
- P0-3 双模式说明：7 台快速版（有意为之）vs 按论文规模的完整版

### 已知待修复 Bug（继续跟踪）
- P0-6 深度核实：`Handler.cpp` 的 leader rotation 是否完整复现论文 S1-S4 设定
  - 标记：**需要在 SGX HW 机器上对照论文 §7.2 验证**

---

## 二、设计目标

目标层次从低到高：

```
Level 1: 通过 Results Reproduced badge（基础门槛）
Level 2: 在所有 Reproduced 论文里脱颖而出（Gilles Muller 候选）
Level 3: 让 reviewer 觉得"这是他见过最好的 artifact 之一"
```

Level 1 已基本达到（P0 全部修完后）。  
Level 2-3 需要以下设计。

---

## 三、核心设计原则

根据 `doc/BEST_AE_ANALYSIS.md` 的分析，得奖 artifact 共同满足：

1. **一条命令走完主路径**（已有 `./ae run all --scale full`）
2. **Docker 容器消除环境摩擦**（待做，最高优先级）
3. **包含参考输出 / expected ranges**（待做）
4. **claim 拆分到 figure 粒度**（已有 README 对应表）
5. **声明可复现范围**（待做：哪些 figure 完整复现、哪些用 mini 验证趋势）
6. **快速通道 + 完整通道**（已有 `--scale mini` / `--scale full`）

---

## 四、待做事项（TODO）

优先级：P0 = 必须做 | P1 = 强烈建议 | P2 = 锦上添花

---

### P0: Docker 容器

**为什么最重要**：SGX SDK 2.23 的安装流程复杂，reviewer 在依赖安装阶段失败会直接影响 badge 评级。Docker 是唯一可靠的消除摩擦的方式。

**设计**：

```
Dockerfile          ← 基于 ubuntu:20.04，预装 SGX SDK(SIM)、salticidae、Python 依赖
docker-compose.yml  ← 方便 reviewer 一行启动
.dockerignore
```

**使用流程**：

```bash
# Reviewer 拿到代码后
docker build -t raftel-ae .
docker run -it --rm raftel-ae ./ae smoke          # smoke test
docker run -it --rm raftel-ae ./ae doctor         # 环境检查

# 云端运行（HW mode）不走 Docker，直接在 ECS 节点上跑
# Docker 主要用于 mini-scale 验证和 reviewer 本地体验
```

**注意**：SGX HW 模式需要 `/dev/sgx_enclave`，Docker 里用 SIM 模式。论文规模的复现仍需云端 HW 节点。README 里要说清楚这个区别。

**文件**：`Dockerfile`，`.dockerignore`，`docker-compose.yml`

---

### P0: 参考输出 / Expected Ranges

**为什么重要**：reviewer 跑完实验后需要知道结果是否在合理范围内。没有参考输出，他们无法判断。

**设计**：

```
runs/reference/
├── manifest.json         ← 记录参考结果是在什么环境跑的（机型、时间、git commit）
├── fig3.csv              ← 论文原始数据（从论文图表中提取）
├── fig4.csv
├── fig6.csv
├── figures/
│   ├── fig3.pdf          ← 论文原始图
│   ├── fig4.pdf
│   └── fig6.pdf
└── EXPECTED_RANGES.md    ← 说明各指标的预期范围（±30%？±50%？）
```

**EXPECTED_RANGES.md 内容示例**：

```markdown
## 可接受的复现范围

由于 SGX enclave 性能、Aliyun 网络抖动、实例负载等因素，
复现结果与论文数据的偏差在以下范围内视为通过：

| 指标 | 可接受偏差 |
|---|---|
| 吞吐量（kTPS） | 论文值 ±40% |
| 平均延迟（ms） | 论文值 ±40% |
| 相对排序 | 协议间排序必须与论文一致 |
| 趋势方向 | f 增大时吞吐下降、延迟上升的趋势必须可见 |

mini-scale（SIM 模式）仅用于验证趋势，绝对值与论文不可比。
```

**`./ae report` 的增强**：生成 HTML 报告时，自动把当前结果和 `runs/reference/` 对比，标注哪些指标在范围内（PASS）哪些不在（WARN）。

**文件**：`runs/reference/EXPECTED_RANGES.md`，以及在 `scripts/gen_report.py` 里加入 diff 逻辑

---

### P0: 可复现范围声明（README）

在 README 里加一个表格，明确说明：

| Figure | 完整复现？ | 需要什么 | mini-scale 验证趋势？ |
|---|---|---|---|
| Figure 3 | ✅ | 97 ECS HW 节点 + TShard | ✅ |
| Figure 4 | ✅ | 49 ECS HW 节点 + TShard | ✅ |
| Figure 6 | ✅ | 25 ECS HW 节点 + TShard | ✅ |
| SIM mode 绝对数值 | ❌ | - | N/A（SIM 仅验证趋势） |

---

### P1: `./ae report` 对比增强

当前 `gen_report.py` 生成的 HTML 只展示当前结果。增强：

- 如果 `runs/reference/` 存在，自动 side-by-side 对比
- 每个 figure 的表格增加"参考值"列、"偏差%"列、"PASS/WARN/FAIL"列
- 颜色标注（绿 / 黄 / 红）

**文件**：`scripts/gen_report.py`

---

### P1: `./ae cloud up` 增加实例数量建议

`./ae cloud up` 在没有 `--count` 参数时，输出：

```
[INFO] Default instance_count from config.json: 7 (quick/smoke mode)
[INFO] For paper-scale reproduction:
  Figure 3 (f=1..32): ./ae cloud up --count 97
  Figure 4 (f=1..16): ./ae cloud up --count 49
  Figure 6 (f=8):     ./ae cloud up --count 25
[INFO] Using 7 instances. To override: ./ae cloud up --count N
```

**文件**：`ae`（CLI 入口）

---

### P1: experiment README 更新

三个 `experiments_reproduction/experiment*/README.md` 需要更新：
- 加入 `./ae run figN` 作为推荐入口
- 说明双模式（7 台快速版 / 论文规模完整版）
- 说明 `--sgx-mode HW` 是云端必需项
- 加入 expected output 格式说明

---

### P1: `./ae doctor` 输出美化

当前 doctor 输出是纯文本，改为有颜色的终端输出：

```
✅  SGX SDK found at /opt/intel/sgxsdk
❌  Missing Python package: paramiko
⚠️  SSH key TShard has loose permissions 664
✅  salticidae submodule present
```

用 ANSI 颜色码实现，不依赖外部库。

**文件**：`ae`

---

### P1: `runs/reference/` 填充

把论文原始数据（从图表中读取）填入 `runs/reference/fig*.csv`，让 `./ae report` 可以做自动对比。这一步需要你手动从论文 PDF 里读数据，或者提供原始实验输出。

---

### P2: GitHub Pages 展示页

`docs/` 目录 + GitHub Pages：
- 论文摘要和 PDF 链接
- 嵌入参考 run 的图表
- 一键 smoke test 说明（`docker run ...`）
- 链接到 artifact appendix

**只在 P0/P1 全部稳定后做。**

---

### P2: Artifact Appendix PDF

EuroSys AE 强制要求一份 artifact appendix，内容包括：
- 声明要复现哪些 figure 和哪些 claim
- 硬件要求（SGX HW ECS，机型，数量）
- 软件依赖和版本
- 访问方式（HotCRP 发 SSH key）
- 如何解读结果偏差

模板在 `doc/ARTIFACT_APPENDIX_TEMPLATE.md`（待创建）。

---

## 五、优先级排序

```
立即做（本次 session）：
  ✅ init.sh 补全 hiredis + Python 依赖
  ✅ config.example.json 写明机型注释
  ✅ P0-3 双模式说明
  ✅ Best AE 分析文档
  □  Dockerfile（P0，最高优先级）
  □  runs/reference/EXPECTED_RANGES.md
  □  README 加可复现范围声明表

下一批：
  □  gen_report.py 加入 reference diff 对比
  □  ./ae cloud up 加实例数量建议
  □  experiment README 更新
  □  ./ae doctor 颜色输出
  □  runs/reference/ 填充论文原始数据（需要你提供数据）

最后：
  □  GitHub Pages
  □  Artifact Appendix PDF
  □  P0-6 深度核实（需要 SGX HW 机器）
```

---

## 六、关键文件索引

| 文件 | 作用 |
|---|---|
| `ae` | 统一 CLI 入口 |
| `run.py` | 核心实验编排 |
| `scripts/plot_fig{3,4,6}.py` | 自动绘图 |
| `scripts/gen_report.py` | HTML 报告生成 |
| `deployment/sourcefile/init.sh` | 节点初始化脚本 |
| `aliyun/config.example.json` | Aliyun 配置模板 |
| `aliyun/create_run_instances.py` | 开实例 |
| `aliyun/wait_instances_ready.py` | 等实例就绪 |
| `runs/reference/` | 参考输出（待填充） |
| `doc/BEST_AE_ANALYSIS.md` | Best AE 经验分析 |
| `doc/AE_DESIGN_AND_TODO.md` | 本文档 |
