# Best Artifact Evaluation：经典案例分析与得奖经验

> 本文档服务于 Raftel AE 团队，分析历届 EuroSys / SOSP / OSDI 最佳 artifact 得奖原因，提炼可复用的技术路线。

---

## 一、背景：EuroSys Gilles Muller Best Artifact Award

EuroSys 设有以已故 INRIA 教授 Gilles Muller 命名的最佳 artifact 奖。评审逻辑是：

- 所有投递 artifact 的论文，先通过 AE 委员会评审，拿到三个 ACM badge（Available / Functional / Results Reproduced）中的一个或多个
- 拿到 **Results Reproduced** 的论文，才有资格被提名最佳 artifact
- AEC 主席和委员会在所有 Reproduced 论文里，评选出 artifact 质量最突出的一篇或几篇

所以**拿奖的前提是通过 Reproduced**，然后在此基础上比其他人做得更好。

---

## 二、经典案例

### 案例 1：Virtines — EuroSys 2022 Gilles Muller Award

**论文**：Isolating Functions at the Hardware Limit with Virtines  
**仓库**：https://github.com/virtines/wasp  
**AE 页面**：https://sysartifacts.github.io/eurosys2022/summaries/virtines

**系统背景**：WASP 是一个嵌入式微型 hypervisor，让函数级别的隔离可以在普通硬件上运行。

**为什么得奖：**

- **两条独立入口**：提供了完整的运行时 API 和 Clang/LLVM 编译器扩展路径，reviewer 可以从两个维度独立验证系统行为，不是单一通道
- **环境封装完整**：Docker 或 OVF 打包，reviewer 不需要手动处理任何依赖
- **获得全三个 ACM badge**：Available + Functional + Results Replicated

**核心经验**：多入口验证 + 零摩擦环境 = 最高信任度。

---

### 案例 2：Fail through the Cracks — EuroSys 2023 Gilles Muller Award

**论文**：Fail through the Cracks: Cross-System Interaction Failures in Modern Cloud Systems  
**主仓库**：https://github.com/xlab-uiuc/csi-ae  
**测试仓库**：https://github.com/xlab-uiuc/csi-test-ae  
**论文**：https://dl.acm.org/doi/10.1145/3552326.3587448

**系统背景**：研究分布式云系统中跨组件交互失败的规律，属于系统可靠性研究。

**为什么得奖：**

- **拆成两个独立 repo，对应论文的不同 section**：`csi-ae` 复现研究层发现，`csi-test-ae` 复现具体的测试失败案例。reviewer 可以选择只验证某部分 claim
- **Jupyter Notebook 驱动**：Docker 起好之后，打开 `reproduce_study.ipynb` 从头跑到尾，所有 table 和 figure 全部自动生成
- **claim 粒度到 section 级别**：README 明确说明"Section 6 的结论对应 `csi-ae`，Section 8 对应 `csi-test-ae`"
- **结果可部分验证**：不需要全部跑完才能得到有意义的输出

**核心经验**：**把 claim 拆开是决定性的设计**。reviewer 最怕的是"要么全部成功要么全部失败"。CSI 让他们可以增量验证。

---

### 案例 3：Eg-walker — EuroSys 2025 Gilles Muller Award

**论文**：Collaborative Text Editing with Eg-walker: Better, Faster, Smaller  
**Benchmark 仓库**：https://github.com/josephg/egwalker-paper  
**Reference 实现**：https://github.com/josephg/eg-walker-reference  
**EuroSys 2025 奖项页**：https://2025.eurosys.org/awards.html

**系统背景**：协作文本编辑算法（CRDT 领域），论文声称比所有现有方案更快、更小。

**为什么得奖：**

- **性能实现和算法参考实现分开放**：`egwalker-paper` 是用于跑 benchmark 的生产级代码，`eg-walker-reference` 是刻意写慢、写清楚的 TypeScript 参考实现——目的是让 reviewer 能读懂算法本身，而不是去啃优化代码
- **算法验证和性能验证可以独立进行**："这个算法是否正确"和"这个系统是否更快"可以分别验证
- **极低的理解门槛**：reference 实现大约几百行，任何熟悉编程的 reviewer 都能通读

**核心经验**：**把"算法正确性"和"性能声明"分离**，是 Eg-walker 最聪明的设计。大多数作者只有一个复杂的生产代码，让 reviewer 读代码来确认算法正确性几乎不可能。

---

### 案例 4：Verus — SOSP 2024 Distinguished Artifact Award

**论文**：Verus: A Practical Foundation for Systems Verification  
**仓库**：https://github.com/verus-lang/paper-sosp24-artifact  
**CMU 新闻**：https://www.ece.cmu.edu/news-and-events/story/2024/12/sosp-award.html

**系统背景**：Rust 系统程序的形式化验证框架，论文声称可以实际应用于大规模系统代码。

**为什么得奖：**

- **规模和完整性**：5 个 case study，6000+ 行可运行 Rust 代码，35000+ 行 proof/spec 代码，全部真实通过 verifier
- **每个 case study 对应论文的一个 section**：reviewer 拿着论文，README 告诉他"Section 5.2 → `case-studies/page-table/`"
- **验证类论文的唯一标准**：proof 必须真的能过 verifier——他们做到了
- **Companion 网站**：`verus-lang.github.io/paper-sosp24-artifact` 提供额外的展示和说明

**核心经验**：**对于不同类型的论文，"可复现"的定义不同**。Verus 是验证论文，所以他们的 artifact 标准不是"重现实验数据"，而是"证明这些 proof 真的能过 verifier"。理解这一点，才能设计正确的 artifact。

---

### 案例 5：Boki — SOSP 2021（全三个 Badge，社区公认最佳之一）

**论文**：Boki: Stateful Serverless Computing with Shared Logs  
**仓库**：https://github.com/ut-osa/boki  
**AE 页面**：https://sysartifacts.github.io/sosp2021/summaries/boki

**系统背景**：基于共享日志的有状态 serverless 计算系统，需要多节点云集群才能运行。

**为什么出色：**

- **多节点 serverless 是公认最难做 artifact 的类别之一**，但他们做到了全三个 badge
- **系统实现和 evaluation harness 分离**：reviewer 可以跑单个实验，对比预期输出范围，不需要精确复现数字
- **cloud provisioning 脚本完整**：作者提供 AWS 集群访问，reviewer SSH 进去直接跑，不需要自己开账号
- **明确的 expected output ranges**：不说"应该得到 X"，而是说"应该在 X ± 20% 范围内"，尊重硬件差异

**核心经验**：**提供 expected output ranges 而不是精确数字**，是分布式系统 artifact 的关键。这既诚实，又让 reviewer 能判断是否通过。

---

## 三、共同模式：得奖的技术路线

对上面五个案例做横向分析，得到以下共同规律：

### 1. 一条命令走完主路径（或接近）

| 案例 | 入口 |
|---|---|
| Virtines | Docker + run script |
| CSI | `docker-compose up` → 打开 notebook，从头跑到尾 |
| Eg-walker | `cargo bench` / `node bench.js` |
| Verus | `make verify-all` |
| Boki | `./run_all.sh` |

**结论**：reviewer 的第一步不应该是困惑。第一步应该是一条命令，然后等待。

---

### 2. Docker / VM 消除环境摩擦

EuroSys AE 指南明确推荐 Dockerfile 或 OVF 预配置环境。所有获奖 artifact 都不需要 reviewer 手动安装依赖。

**对 Raftel 的意义**：SGX SDK 安装流程复杂（2.23 特定版本、PSW、SGXSSL），如果不提供 Docker，reviewer 在依赖安装阶段就会遇到大量问题，影响 badge 评级。

---

### 3. 包含参考输出或 expected ranges

Reviewer 跑完之后需要知道结果是否正确。最好的 artifact 包含：
- 预期输出文件（精确值或范围）
- 参考图表（让 reviewer 做视觉对比）
- 或"在什么范围内视为通过"的说明

---

### 4. claim 拆分到 section 粒度

| 案例 | 拆分方式 |
|---|---|
| CSI | 两个独立 repo 对应两类 claim |
| Verus | 每个 case study 对应一个 section |
| Eg-walker | benchmark repo vs. reference repo |

**结论**：reviewer 需要能部分验证 claim。"要么全部成功要么全部失败"是最坏的设计。

---

### 5. README 里有 figure → script 的对应表

所有获奖 artifact 都有类似下面的表格：

```
Figure 3 → experiments/experiment1/script/run_wan.sh → stats.txt
Figure 4 → experiments/experiment2/script/run_lan.sh → stats.txt
Figure 6 → experiments/experiment3/script/run_redis_wan.sh → stats.txt
```

Reviewer 拿着论文找脚本，不需要猜。

---

### 6. 声明可复现范围（不过度承诺）

最好的 artifact 明确写出：
- 哪些 figure 可以完整复现
- 哪些需要特定硬件（如 SGX HW 实例）
- 哪些提供了 mini-scale 替代方案用于趋势验证
- 硬件差异导致的数值浮动范围是多少

**这是诚实的体现，AEC 非常看重这一点**。

---

### 7. 快速通道（mini scale）+ 完整通道（paper scale）

所有需要大规模集群的论文，都有一个"在 reviewer 的普通机器上验证趋势"的快速版本：

| 案例 | 快速通道 |
|---|---|
| Boki | 单节点模拟模式 |
| IODA | 提供预生成结果用于对比 |
| Virtines | 完整脚本分级运行 |

**对 Raftel 的意义**：`--scale mini`（SIM 模式，小规模 f 值）提供快速通道，`--scale full`（HW 模式，论文规模）提供完整通道。

---

## 四、对 Raftel AE 的直接建议

基于以上分析，Raftel AE 目前具备：
- ✅ 一键 `./ae` CLI
- ✅ Run-ID 审计目录（manifest + checksums + raw logs）
- ✅ 自动出图（plot_fig3/4/6.py）
- ✅ HTML 报告（gen_report.py）
- ✅ `--scale mini` 快速通道
- ✅ Figure → Script 对应表（README）

**还差的关键点**（按优先级）：

| 优先级 | 缺口 | 对标案例 | 解决方案 |
|---|---|---|---|
| P0 | Docker 容器 | Virtines / CSI | 加 `Dockerfile`，一行进入可运行环境 |
| P0 | `init.sh` 缺 hiredis | - | 补充 hiredis 安装（当前只有 redis-server） |
| P1 | 参考输出 / expected ranges | Boki / Eg-walker | 把论文原始数据放进 `runs/reference/`，README 里说明 ±30% 范围内视为通过 |
| P1 | `config.example.json` 无规格注释 | - | 写明 `ecs.g7t.2xlarge`，说明为什么是这个机型 |
| P1 | 实例数量 vs 实验说明不完整 | - | 双模式说明（7台快速版 vs 按论文规模的完整版） |
| P2 | 可复现范围声明 | 所有案例 | 在 README 加一个表：哪些 figure 完整复现、哪些 mini 验证趋势 |

---

*本文档基于 2026 年 9 月调研结果，参考案例均有公开链接可访问。*
