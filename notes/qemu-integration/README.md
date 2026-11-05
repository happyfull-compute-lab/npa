# RPA QEMU/KVM 集成计划

本目录包含 RPA（Recursive Privilege Architecture）项目从 Python 模拟器（`rpa-pysim`）迁移到 QEMU + KVM 平台的完整设计文档。

## 背景与动机

`rpa-pysim` 已停滞一段时间。它作为"可执行规范"覆盖了 RPA 的语义验证（90+ 测试用例），但存在以下不足：

- 非 cycle-accurate，无法用于性能评测
- 非真实 ARM ISA，无法对接 Linux 工具链
- 无真实 OS，无法验证 RPA 在系统软件栈中的可用性

迁移到 QEMU + KVM 后可获得：
- 硬件级准确的 ARM 模拟（TCG 路径）
- 真实 Linux kernel + Alpine 用户态环境
- 后续 arm-on-arm KVM 加速时接近原生的性能

## 研究方法论与迭代机制

### 三阶段收敛策略

RPA 的验证不依赖单一模拟平台，而是采用"逐步收敛"的三阶段方法论，每个阶段解决不同维度的问题：

```
  Stage 1                Stage 2              Stage 3
QEMU (TCG/KVM)  ──>  gem5 (RPA-aware)  ──>  RTL (最终)
   │                    │                    │
   │ 功能收敛            │ 时序收敛            │ 硬件收敛
   │ 生态软件跑通        │ cycle-accurate     │ 实现-accurate
   │ 逻辑 bug 暴露       │ 性能论断验证        │ 流片前验证
   ▼                    ▼                    ▼
```

| Stage | 工具 | 收敛维度 | RPA 时序可信度 | 能跑的 workload |
|-------|------|----------|----------------|-----------------|
| 1 | QEMU TCG (Phase 1-3) | 功能/逻辑 | 不可信（软件翻译） | 最小 Linux + 测试程序 |
| 1' | QEMU KVM (Phase 4) | 生态/规模 | 不可信（RPA 走 trap） | 完整发行版 + 真实应用 |
| 2 | gem5 | 时序 | 可信（cycle-accurate） | 启动测试 + 微基准 |
| 3 | RTL | 硬件 | 完全可信 | 仅单元测试 |

**关键原则**：每个阶段的输出是下一阶段的输入。前一阶段的 bug 不带到下一阶段。

### 为什么不直接从 RTL 入手（评审预防性回应）

预期评审者会问：既然最终要收敛到 RTL，为什么不直接从 RTL 开始？答案是**避免项目初期长时间无进展**。

从 RTL 直接入手的代价：
- **设计验证滞后**：RPA 的递归特权模型、页表叠加、INHERIT 模式等设计决策需要快速试错。RTL 一次迭代周期以周计（综合 + 仿真），QEMU 以分钟计
- **生态对接延迟**：RTL 无法跑 Linux 发行版，无法验证 RPA 在真实软件栈（glibc、busybox、systemd）下的兼容性。等到 RTL 能跑 Linux，可能已经过了大半年，期间积累的设计错误难以回溯
- **问题归因困难**：RTL 上发现一个 bug，可能是 RPA 设计问题、ISA 实现问题、kernel 适配问题、或 RTL 本身的实现 bug。没有 QEMU/gem5 阶段的逻辑收敛，难以定位
- **协作摩擦大**：RTL 修改需要硬件工程师介入；QEMU/gem5 修改软件工程师即可。早期阶段多迭代、快迭代，软件平台更合适

从 QEMU 入手的好处：
- **快速试错**：每次修改分钟级反馈
- **生态早期对接**：第一天就能跑 Linux + Alpine，发现 RPA 与现有软件栈的不兼容点
- **设计错误前置**：在 QEMU 阶段就把"语义错误"暴露完，gem5/RTL 阶段只需关注"时序/硬件实现"问题
- **论文叙事完整**：QEMU 提供功能验证数据，gem5 提供时序数据，RTL 提供最终可信度--三段递进，评审容易接受

### 快速迭代机制

本计划采用快速迭代机制，而非瀑布式推进：

1. **快速 review**：每完成一个子任务（如 Phase 1 的 QEMU 启动脚本），立即 review
2. **无硬伤即推进**：只要没有架构性、安全性、或方向性硬伤，立即进入下一步
3. **问题后置修复**：发现的问题记录到对应 Phase 文档的"修订记录"章节，不阻塞当前进度
4. **定期回扫**：每个 Phase 完成时，回扫前序 Phase 的待修问题，批量处理

这种机制的权衡：
- ✅ 优点：快速进入实做阶段，早暴露真实问题，避免过度规划
- ⚠️ 风险：可能积累技术债；通过"定期回扫"缓解
- ❌ 不适用场景：架构性决策（如 Phase 2 的指令编码选择）--这类决策一次定，后期改成本高，需要充分 review

## 总体路线

```
Phase 0  调研与现状梳理
   │     （rpa-pysim 盘点、QEMU 生态、ARM Linux 启动、Alpine rootfs）
   ▼
Phase 1  QEMU + Alpine 基线启动（x86 host, TCG）
   │     （最小 Linux kernel + Alpine rootfs + U-Boot/UEFI）
   ▼
Phase 2  RPA 在 QEMU TCG 中的实现（核心）
   │     （target/arm/ 修改：新指令、MMU walker、中断路由）
   ▼
Phase 3  测试套件与自动化
   │     （用户态 / 内核态 / QEMU 单元测试 / E2E）
   ▼
Phase 4  arm-on-arm KVM 路线图（未来）
         （树莓派 5 / AWS Graviton，KVM 扩展）
   │
   ▼  ── Stage 1 (QEMU) 完成 ──
   │
Stage 2  gem5 RPA-aware 模型（未来，未规划）
   │     （cycle-accurate，时序收敛）
   ▼
Stage 3  RTL 仿真（未来，未规划）
         （硬件最终收敛，流片前验证）
```

## 文档清单

| Phase / Stage | 文档 | 状态 | 行数 |
|----------------|------|------|------|
| Phase 0 | [`phase-0-survey.md`](./phase-0-survey.md) | ✅ 完成 | 433 |
| Phase 1 | [`phase-1-qemu-baseline.md`](./phase-1-qemu-baseline.md) | ✅ 完成 | 465 |
| Phase 2 | [`phase-2-rpa-qemu-design.md`](./phase-2-rpa-qemu-design.md) | ✅ 完成 | 1063 |
| Phase 3 | [`phase-3-testing.md`](./phase-3-testing.md) | ✅ 完成 | 601 |
| Phase 4 | [`phase-4-kvm-roadmap.md`](./phase-4-kvm-roadmap.md) | ✅ 完成 | 463 |
| Stage 2 (gem5) | _未规划_ | 🔜 未来 | - |
| Stage 3 (RTL) | _未规划_ | 🔜 未来 | - |

## 关键决策摘要

| 决策点 | 选择 | 出处 |
|--------|------|------|
| QEMU 版本 | 9.2 stable（Phase 2 锁定 9.1 LTS） | Phase 1 / Phase 2 |
| ARM 机器型号 | `virt` | Phase 0 / Phase 1 |
| ARM CPU 型号 | `cortex-a72`（不用 `max`，便于 RPA 注入） | Phase 1 |
| 启动方案 | 方案 C：QEMU `-kernel` 直接启动（Phase 1）；U-Boot + DTB 作为 RPA 调试备选 | Phase 0 / Phase 1 |
| Linux kernel | 6.12 LTS | Phase 1 |
| Alpine rootfs | 3.20 / 3.24 aarch64 mini rootfs | Phase 0 / Phase 1 |
| RPA 实现策略 | 方案 A：侵入式修改 `target/arm/`（不用 TCG Plugin） | Phase 2 |
| RPA 状态与 ARM EL | 正交：所有 RPA 域在 EL1 运行，不修改 `PSTATE_EL` | Phase 2 |
| 指令编码 | 复用 ARMv8 Exception Generation 编码空间（`0xD4xxxxxx`, `opc=0x6/0x7`） | Phase 2 |
| 页表叠加 | RPA walker 顶层分支，不复用 ARM Stage-2 | Phase 2 |
| DCB 读取 | 直接物理访问（避免递归翻译） | Phase 2 |
| 测试架构 | 四层金字塔：QTest 单元 / `/dev/rpa` 用户态 / Kselftest 内核 / Python E2E | Phase 3 |
| 测试用例数量 | 34 功能 + 7 性能 = 41 个 | Phase 3 |
| ARM host（Phase 4） | 树莓派 5 8GB + AWS Graviton4 | Phase 4 |
| KVM 集成方案 | 方案 A：RPA 作为 KVM 扩展 | Phase 4 |

## 风险与开放问题

### 高优先级风险

| ID | 风险 | 缓解 |
|----|------|------|
| P2-R7 | DMA 旁路 RPA 翻译 | Phase 2 暂用 SMMUv3 模拟 + DMA 限制为 root 域 |
| P2-R9 | DCB 自身翻译递归 | 直接物理读路径（`rpa_read_physical_*`） |
| P2-R10 | TCG 非周期精确，论文性能论断可信度 | 论文明确声明"QEMU TCG 估算"，gem5/FPGA 后续验证 |
| P3-Perf | QEMU TCG 性能数据不能反映真实硬件 | 主打归一化比值与事件计数，绝对 cycles 不对外宣称 |
| P4-R5 | INHERIT 模式 5-10 cycles 在 KVM 下不成立（HVC trap 自身 150-300 cycles） | 论文性能宣称需谨慎，KVM 下 INHERIT 优势缩水到 3-10x |
| P4-R2 | AWS Graviton 不允许修改 KVM | 修改版 KVM 限定树莓派 5 / Ampere 裸金属 |

### 与 MCSOC 2026 论文的关系

- **投稿不依赖** Phase 4（KVM 路径），现有 Python 模拟 + 理论数据足够定位为概念性架构论文
- 若 Phase 2 + Phase 3 在投稿前完成，可加入"QEMU TCG 功能验证"小节
- 性能数据若要支撑论文核心 cycles 论断，需要 gem5 或 FPGA 验证，QEMU TCG 仅作功能侧证据
- Phase 4 KVM 数据若能在投稿前完成 M3（性能评测），可显著加强论文说服力

## 阶段依赖与并行性

```
Phase 0 (调研) ──┬─→ Phase 1 (基线启动)
                 └─→ Phase 2 (RPA 实现)  ←─ 依赖 Phase 0 的 QEMU 生态调研
                          │
                          ▼
                       Phase 3 (测试)    ←─ 依赖 Phase 2 的接口设计
                          │
                          ▼
                       Phase 4 (KVM)     ←─ 依赖 Phase 2 + 3 的代码与测试
```

Phase 0 与 Phase 1 设计可并行（文档已并行产出）；Phase 2 必须在 Phase 1 完成后开始（需要可启动的 QEMU 基线）；Phase 3 与 Phase 2 部分并行（测试架构设计可先于实现）。

## 工程量估算

| Phase | 工作量（人月） | 备注 |
|-------|----------------|------|
| 0 | 已完成 | 文档已产出 |
| 1 | 0.5-1 | 主要是环境搭建与脚本 |
| 2 | 3-6 | QEMU 修改 9-22 KLOC（Phase 0 估算） |
| 3 | 1.5-2 | 33 人日测试迁移（Phase 3 估算） |
| 4 | 7-12 | KVM 修改 + 性能评测（Phase 4 估算） |
| **合计** | **12-21** | 单人估算 |

## 后续行动

1. **立即**：审阅 5 份文档，确认决策方向
2. **Phase 1 启动**：搭建 QEMU 基线环境（可独立于 Phase 2 推进）
3. **Phase 2 准备**：熟悉 QEMU `target/arm/` 源码，验证 Phase 2 设计中提到的关键文件路径
4. **Phase 3 准备**：盘点 `rpa-pysim/tests/`，确认迁移优先级

## 文档维护

- 文档版本：v1.1（2026-07-20 增补研究方法论与迭代机制）
- 维护方式：实现过程中发现的设计偏差，应回写到对应 Phase 文档的"修订记录"章节
- 一致性原则：Phase 2 设计文档为技术权威；如其他文档与 Phase 2 冲突，以 Phase 2 为准并同步更新

## 修订记录

| 版本 | 日期 | 修订内容 |
|------|------|----------|
| v1.0 | 2026-07-20 | 5 个 Phase 文档首次产出 |
| v1.1 | 2026-07-20 | README 增补"研究方法论与迭代机制"章节；Phase 4 增补"定位澄清"章节，明确 KVM 不提供 RPA 时序数据 |

## 参考索引

- RPA 设计要点：`../DESIGN_NOTES.md`
- RPA 技术规范：`../TECHNICAL_SPEC.md`
- 研究分析：`../research_analysis.md`
- Python 模拟器：`../../rpa-pysim/`（submodule）
- 形式化规范：`../../rpa-spec/`（submodule）
- MCSOC 2026 论文：`../../en/mcsoc2026/`
