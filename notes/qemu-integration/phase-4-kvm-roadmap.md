# Phase 4：ARM-on-ARM KVM 加速路线图

> **状态**：未来计划（Phase 1-3 完成后启动）
> **前置条件**：Phase 2 QEMU TCG + RPA 扩展已实现，Phase 3 测试套件已通过
> **目标读者**：RPA 项目维护者、后续硬件实验协作者
> **撰写日期**：2026-07-20

---

## 0. 定位澄清（重要）

KVM 加速在 RPA 研究方法论中的角色需要明确，避免与 gem5 / RTL 阶段混淆：

| 维度 | QEMU TCG (Phase 1-3) | QEMU KVM (Phase 4) | gem5 (未来) | RTL (未来) |
|------|----------------------|---------------------|-------------|------------|
| **主要价值** | 逻辑/功能收敛 | 真实 workload 跑通 | 时序收敛 | 硬件最终收敛 |
| **RPA 操作时序** | 不可信（软件翻译） | **不可信**（RPA 走 trap 软件模拟） | 可信（cycle-accurate） | 完全可信 |
| **标准 ARM 操作时序** | 不可信 | 可信（硬件辅助） | 可信 | 完全可信 |
| **速度** | 慢（10-100x slowdown） | 快（接近原生） | 很慢（100-1000x） | 极慢（仿真） |
| **能跑的 workload** | 最小 Linux + 测试程序 | 完整发行版 + 真实应用 | 启动测试 + 微基准 | 仅单元测试 |

**关键结论**：Phase 4 的 KVM 加速让 QEMU 阶段能跑真实 workload（生态软件验证），但 RPA 自身操作的时序数据（如 `descend` 的 cycles 数）**仍然不可信**——因为 RPA 在修改版 KVM 中是通过 HVC trap 软件模拟的，trap 自身开销（150-300 cycles）远大于真实硬件实现的 RPA 原语（目标 1-10 cycles）。

论文 evaluation 的 RPA 时序论断需等待 gem5（RPA-aware 模型）或 RTL 验证。Phase 4 KVM 数据仅用于：
- 标准 ARM 操作的对比基线
- RPA 功能在真实 workload 下的端到端可用性验证
- RPA 与非 RPA 路径的**归一化比值**（如 INHERIT vs 独立页表的相对开销比）

详见 README.md 的"研究方法论与迭代机制"章节。

---

## 1. 动机与目标

### 1.1 TCG 模拟的性能瓶颈

Phase 1-3 采用 `qemu-system-arm` TCG（Tiny Code Generator）在 x86 host 上模拟 ARM 指令集。TCG 将 ARM guest 指令动态翻译为 x86 host 指令，存在两类不可消除的开销：

| 开销来源 | 量级 | 说明 |
|----------|------|------|
| 指令翻译 | 5-20x 慢于原生 | 每条 ARM 指令展开为多条 x86 指令 |
| 寄存器映射 | 1.5-3x 额外慢化 | ARM 的 31 个通用寄存器需溢出到栈 |
| 内存语义模拟 | 2-5x | MMU/TLB 软件走查、stage-2 翻译软件模拟 |
| 总体 slowdown | 10-100x | 复杂 workload（如 Linux 内核启动）偏低端，纯计算偏高 |

业界基准：QEMU TCG 在 x86-64 host 上模拟 ARM64 guest，SPEC CPU2017 整数性能约为原生的 1-5%；启动一个最小 Linux 约需 30-120 秒（KVM 下 1-3 秒）。这意味着 TCG 路径下：
- 无法评测"真实 workload"性能（如 LAMP stack、Redis、LLM 推理）
- 无法验证 RPA 在高频 `descend`/`ascend` 场景下的真实开销
- 无法收集论文 evaluation 章节所需的端到端基准数据

### 1.2 KVM 加速对 RPA 项目的价值

KVM（Kernel-based Virtual Machine）在 ARM host 上利用 ARMv8 虚拟化扩展（EL2 + VHE + Stage-2 MMU）让 guest 代码以接近原生速度执行。对 RPA 项目而言，KVM 加速解锁两类工作：

1. **真实 workload 跑通**：能在 guest 中启动完整 Linux 发行版、运行 nginx/Redis/Python 等真实软件栈，验证 RPA 在复杂软件生态下的功能可用性
2. **大数据量验证**：能跑 LLM 推理、数据库 TPC-C 等计算/内存密集场景，发现 rpa-pysim 与 QEMU TCG 路径下无法触达的边界 bug

**注意**：KVM 不提供 RPA 操作的可信时序数据（理由见 §0）。RPA 时序收敛需等待 gem5 / RTL 阶段。

### 1.3 阶段目标

在 ARM host 上启用 KVM 跑通"RPA 修改版 QEMU + 修改版 Linux kernel"，使 RPA 域切换路径走硬件辅助 trap 而非 TCG 软件模拟。最终产物：一份可直接对外发布的 RPA 性能评测报告。

---

## 2. ARM host 选型

### 2.1 候选平台对比

| 平台 | 架构 | 核心/RAM | KVM 可用性 | 自定义 kernel | 单价 | 适用阶段 |
|------|------|----------|-----------|---------------|------|----------|
| Raspberry Pi 4 | Cortex-A72 | 4C / 2-8GB | ✅ 需自编译 | ✅ 完全开放 | ~$55-75 | M1-M2 开发 |
| Raspberry Pi 5 | Cortex-A76 | 4C / 4-8GB | ✅ 官方支持 | ✅ 完全开放 | ~$60-80 | M1-M3 主力 |
| AWS Graviton3/4 | Neoverse V1/N2 | 16-96 vCPU | ✅ 但 kernel 受限 | ⚠️ 仅自定义 AMI | 按小时计费 | M3-M4 性能评测 |
| Ampere Altra Max | Neoverse N1 | 128C | ✅ 裸金属可定制 | ✅ 裸金属可改 | ~$3000+ | M4 性能评测 |
| Apple Silicon M1/M2/M3 | Firestorm/Icestorm | - | ❌ 禁止 | ❌ 封闭 | - | 不采用 |

### 2.2 推荐配置

**开发机**：Raspberry Pi 5 8GB
- 理由：
  1. 性价比最高，Cortex-A76 性能足够跑 KVM guest
  2. 完全开放的 bootloader 和 kernel，可任意修改 KVM 代码
  3. 官方 Raspberry Pi OS 5.x 内核已默认启用 KVM 模块
  4. 社区文档丰富（如 `kvm-on-raspberry-pi` 教程成熟）
  5. 8GB RAM 足以同时跑 host + 单个 2-4GB guest
- 限制：仅 4 核，无法测多核扩展性；无 SVE/SME 等新扩展

**性能评测机**：AWS Graviton4（`c7g.4xlarge` 起步）
- 理由：
  1. Neoverse V2 核心性能强，接近服务器级 ARM
  2. 按小时计费，评测期成本可控
  3. 16 vCPU 足以测多核扩展性
- 限制：
  1. AWS 不允许用户修改 hypervisor（Nitro），但允许自定义 AMI 中的 guest kernel
  2. RPA-aware KVM 路径需在"裸金属实例"（`c7g.metal`）上跑，成本较高
- 备选：Ampere Altra Max Developer Platform（如预算允许购买开发板）

### 2.3 不采用 Apple Silicon 的理由

任务约束：Apple Silicon 平台禁止。技术理由补充：
1. macOS 锁定启动链，无法替换 hypervisor
2. Apple 的虚拟化框架（Hypervisor.framework）不暴露 KVM 等价物
3. M 系列芯片的 EL2 行为未公开文档化
4. 即使 Asahi Linux 也无法获得稳定 KVM 支持

---

## 3. KVM/ARM 架构与 RPA 的关系

### 3.1 KVM/ARM 的 EL2 利用

ARMv8 异常级别模型：

```
EL3  ── Secure Monitor（ TrustZone 切换 ）
EL2  ── Hypervisor（ KVM 运行处，VHE 模式下 host kernel 也在此 ）
EL1  ── Guest Kernel（ KVM guest 运行处 ）
EL0  ── Guest User
```

KVM/ARM 利用三个硬件机制：
1. **VHE (Virtualization Host Extensions)**：让 host kernel 直接在 EL2 运行，避免 host/guest 切换的 EL2↔EL1 抖动。Linux 4.7+ 默认启用。
2. **Stage-2 MMU**：guest 的"物理地址"（IPA）通过 stage-2 页表翻译为 host 物理地址（PA）。这正是 RPA 页表叠加机制的硬件对应物。
3. **Trap 控制**（HCR_EL2）：guest 的特权操作（MMIO、`HLT`、`SMC`、虚拟中断等）可配置 trap 到 EL2 由 KVM 处理。

### 3.2 RPA 递归特权模型与 ARM EL 的映射

RPA 的"域"概念与 ARM EL 不存在一一对应关系，但可借助 EL2 实现：

| RPA 概念 | ARM KVM 实现对应 |
|----------|------------------|
| Domain 0（根域） | Host kernel（EL2 with VHE） |
| Domain 1（一级子域） | KVM guest（EL1） |
| Domain 2+（嵌套子域） | 嵌套虚拟化（Linux 6.5+ ARM 嵌套 KVM 实验性支持） |
| `descend` 原语 | KVM `KVM_RUN` ioctl 进入 guest，硬件切到 EL1 |
| `ascend` 原语 | Guest 触发 trap（如 HVC），KVM 在 EL2 处理 |
| DomainBlock | `struct kvm_vcpu_arch` 的扩展字段 |
| 页表叠加 | Stage-2 MMU（硬件原生支持单层）+ 软件模拟多层 |
| IPA 边界检查 | Stage-2 页表的 IPA 范围约束 |
| 安全域 | ARM CCA RMI / SMMU 配置（如 host 支持） |

### 3.3 三种集成方案

#### 方案 A：RPA 作为 KVM 扩展（修改 KVM hypervisor 代码）

**做法**：在 `arch/arm64/kvm/` 中新增 RPA 模块，让 KVM trap 处理路径识别 RPA 指令（通过未分配 HVC 编码或自定义协处理器寄存器访问）。

```
Guest 在 EL1 执行 `descend block_addr`（编码为 HVC #0xFF00）
  → 硬件 trap 到 EL2
  → KVM 修改后的 handler 识别为 RPA descend
  → 读取 vcpu->arch.rpa_domain_block（用户态通过 ioctl 写入）
  → 切换 stage-2 页表基址寄存器（VTTBR_EL2）
  → 返回 EL1 继续执行 guest
```

- 优点：复用 KVM 全套基础设施（VGIC 虚拟中断控制器、timer 虚拟化、KVM scheduler 集成）
- 缺点：KVM 核心路径侵入式修改，上游合并难度高；嵌套场景下需打通 ARM nested KVM 与 RPA 嵌套
- 工作量：中等（约 3000-6000 LOC）

#### 方案 B：RPA 替换 KVM（在 EL2 实现 RPA 而非 KVM）

**做法**：写一个独立的 type-1 hypervisor（bare-metal EL2 程序），只实现 RPA 原语和最小调度，host kernel 作为 Domain 0 在 EL1 运行。

```
EL2: rpa-hypervisor（自研，~5000-10000 LOC）
  ↓ descend
EL1: Domain 0 = Linux host kernel
  ↓ descend
EL1': Domain 1 = Linux guest kernel（通过 rpa-hypervisor 切换）
```

- 优点：RPA 语义纯净，无 KVM 历史包袱；可充分体现"递归"特性
- 缺点：需自己实现中断虚拟化、timer、VGIC、调度；放弃 Linux KVM 生态
- 工作量：大（约 10000-20000 LOC）
- 类比：Xen 于 KVM 的关系，rpa-hypervisor 类似 Xen hypervisor

#### 方案 C：RPA 在 EL3（Secure Monitor）层实现，KVM 不变

**做法**：在 EL3 的 Secure Monitor 中实现 RPA 原语，KVM 在 EL2 不变。Domain 0 = Secure World，Domain 1 = Normal World with KVM。

- 优点：KVM 完全不动；EL3 是最高特权，天然适合根域
- 缺点：EL3 应保持精简（ARM 官方建议）；EL3→EL1 切换成本高（~200-500 cycles）；无法体现"递归无限层"特性（EL3 只有一层）
- 工作量：中等（约 2000-4000 LOC，需修改 TF-A）
- 适用：仅机密计算场景，不适合系统调用优化

### 3.4 推荐方案

**首选：方案 A（RPA 作为 KVM 扩展）**

理由：
1. 工作量与方案 C 相当，但表达力远胜（支持任意层数）
2. 复用 KVM 基础设施避免重造轮子，加速 M1-M2 里程碑
3. 论文 evaluation 章节可直接对比"RPA-KVM"vs"原生 KVM"vs"TCG 模拟"，三组数据更有说服力
4. 长期可演进：若上游合并受阻，可 fork 维护；若 Phase 5 真硬件落地，方案 A 的代码可移植到 hardware hypervisor

**备选：方案 B**（在 M2 完成后若发现 KVM 限制过大，可分支启动）

方案 C 仅作为"机密计算域"的子模块实现，不作为主路径。

---

## 4. Linux 内核修改

### 4.1 `arch/arm64/kvm/` 目录结构概览

```
arch/arm64/kvm/
├── hyp/             EL2 hypervisor 代码（VHE/nVHE 两套）
│   ├── vgic-v3-cpu-sr.c
│   ├── timer-sr.c
│   ├── sysreg-sr.c
│   └── entry.S      ★ guest entry/exit 路径
├── vgic/            虚拟中断控制器
├── mmu.c            ★ stage-2 MMU 管理
├── arch.c           ★ vcpu 创建/重置
├── guest.c          vcpu ioctl 处理
├── nested.c         ★ ARM 嵌套虚拟化（Linux 6.5+）
├── handle_exit.c    ★ exit handler 分发
├── inject_fault.c   异常注入
└── trace.c          ftrace 支持
```

### 4.2 需要修改的文件清单

| 文件 | 修改内容 | 对应 Phase 2 |
|------|----------|--------------|
| `hyp/entry.S` | 新增 RPA HVC trap 路径，保存/恢复 DomainBlock 上下文 | QEMU TCG `target/arm/translate-a64.c` 中 RPA 指令处理 |
| `mmu.c` | stage-2 页表叠加支持，多层 IPA 翻译 | QEMU `accel/tcg/` softmmu 内存翻译 |
| `arch.c` | `kvm_vcpu_arch` 新增 `rpa_domain_block` 字段、嵌套深度 | QEMU `CPUARMState` 中的 RPA 状态 |
| `handle_exit.c` | 识别 RPA HVC 编码，分发到 `kvm_handle_rpa_descend` 等 | QEMU `helper_rpa_descend` |
| `vgic/vgic.c` | 域间中断注入路径 | QEMU 中的 `rpa_inject_irq` |
| `nested.c` | 嵌套 KVM 与 RPA 嵌套协作 | QEMU TCG 中 RPA 多层模拟 |
| `include/asm/kvm_host.h` | `struct kvm_vcpu_arch` 扩展 | QEMU `CPUARMState` 扩展 |
| `include/uapi/linux/kvm.h` | 新增 ioctl：`KVM_SET_RPA_DOMAIN_BLOCK` 等 | QEMU KVM ioctl 调用 |
| `virt/kvm/kvm_main.c` | ioctl 分发（架构无关部分） | QEMU KVM 加速器适配 |

### 4.3 RPA 状态在 vcpu 结构中的表示

在 `arch/arm64/include/asm/kvm_host.h` 中扩展：

```c
struct kvm_vcpu_arch {
    /* ... 原有字段 ... */

    /* RPA 扩展：当前 vcpu 的域栈 */
    struct rpa_domain_stack {
        u64 domain_block_addr;       /* 当前 DomainBlock 的 GPA */
        u32 domain_id;
        u32 depth;                   /* 嵌套深度 */
        u64 saved_ctx[12];           /* ctx_save_area 硬件保存区镜像 */
        u64 ipa_regions_gpa;         /* 父域设置的 IPA 区域表 */
    } rpa_stack[RPA_MAX_DEPTH];      /* RPA_MAX_DEPTH = 8 (初始) */

    u32 rpa_current_depth;
    bool rpa_enabled;                /* vcpu 是否启用 RPA */
};
```

### 4.4 与 Phase 2 的代码复用关系

| 模块 | TCG 路径 | KVM 路径 | 复用程度 |
|------|----------|----------|----------|
| DomainBlock 解析 | `hw/rpa/domain_block.c` | 内核 `arch/arm64/kvm/rpa.c` | **数据结构定义**复用，**访问代码**重写（用户态→内核态） |
| 页表叠加 | `accel/tcg/softmmu_rpa.c` | `arch/arm64/kvm/mmu.c` | 算法复用，stage-2 硬件加速替代软件走查 |
| IPA 边界检查 | 同上 | `kvm_rpa_check_ipa_regions()` | 算法完全复用 |
| 中断虚拟化 | `hw/intc/rpa_vgic.c` | 复用 KVM VGIC | 仅薄封装层重写 |
| 测试用例 | QEMU TCG 下运行 | KVM 下运行 | **完全复用**，是迁移最大收益 |

建议在 QEMU 用户态引入抽象层 `rpa_backend_ops`：

```c
struct rpa_backend_ops {
    int (*descend)(CPUState *cs, hwaddr block_addr);
    int (*ascend)(CPUState *cs, uint32_t reason);
    int (*exit_domain)(CPUState *cs);
    /* ... */
};

/* TCG 路径 */
extern struct rpa_backend_ops rpa_tcg_ops;
/* KVM 路径（通过 ioctl 转发到内核） */
extern struct rpa_backend_ops rpa_kvm_ops;
```

---

## 5. 从 TCG 迁移到 KVM 的策略

### 5.1 共享代码设计

QEMU 已有 `accel/tcg/` 与 `accel/kvm/` 双后端架构。RPA 扩展遵循同样模式：

```
target/arm/rpa/
├── rpa_common.c          ← 共享：DomainBlock 数据结构、IPA 检查算法
├── rpa_tcg.c             ← TCG 后端
└── rpa_kvm.c             ← KVM 后端（ioctl 转发）
```

### 5.2 测试复用

Phase 3 测试套件（107 个用例）需在两个路径下都能跑。建议：

1. **测试套件入口**：用户态程序（运行在 guest 内），通过 `descend`/`ascend` 触发 RPA 操作
2. **双路径 CI**：CI 同时跑 TCG 路径和 KVM 路径，对比结果一致性
3. **差异报警**：TCG vs KVM 行为不一致即视为 bug

收益：测试套件成为 TCG→KVM 迁移的回归保障，无需重写测试。

### 5.3 迁移里程碑

| 里程碑 | 目标 | 验收标准 | 预估周期 |
|--------|------|----------|----------|
| **M1** | KVM 在未修改 host 上跑通 RPA-aware QEMU（无 RPA 加速） | guest 内执行 `descend` 不 panic，回退到软件模拟 | 2-4 周 |
| **M2** | KVM 加入 RPA 支持，能用 RPA 指令 | Phase 3 测试套件在 KVM 下全通过 | 8-12 周 |
| **M3** | 性能评测，对比 TCG vs KVM vs 原生 | 收集 syscall、嵌套虚拟化、内存访问微基准数据 | 4-6 周 |
| **M4** | 跑真实 workload | LAMP stack、Redis、小型 LLM 推理可运行 | 4-8 周 |

详细说明：

- **M1**：核心是 QEMU 的 KVM 后端识别 RPA-aware CPU model。`qemu-system-aarch64 -enable-kvm -cpu rpa-cortex-a76`。RPA 指令在 host 不识别时 trap 到 KVM，KVM 默认行为是 inject undefined exception；M1 改为"转发给 QEMU 用户态的 TCG 模拟器"。这样 Phase 3 测试套件可立即在 KVM 上跑（虽然 RPA 部分仍是 TCG 速度）。
- **M2**：在 KVM 内核态实现 RPA trap handler，避免用户态往返。DomainBlock 通过 ioctl 从 QEMU 传入 KVM，但后续 `descend`/`ascend` 全在内核态完成。
- **M3**：使用 `perf stat`、`kvm_stat`、自定义 `descend` 微基准（10^6 次循环测平均开销）。评测方法论见第 6 节。
- **M4**：跑真实 workload 验证 RPA 不破坏现有软件兼容性。LLM 推理用 llama.cpp + Qwen2.5-0.5B（树莓派 5 8GB 可跑）。

---

## 6. 性能预期

### 6.1 KVM 下 RPA 操作开销预估

基于 ARMv8 trap 开销的公开数据（`HVC` 指令 trap 到 EL2 再返回，约 200-500 cycles）和 stage-2 页表切换成本（`VTTBR_EL2` 写 + TLB 刷新，约 500-2000 cycles）：

| RPA 操作 | TCG 路径（实测预估） | KVM 路径（预估） | 原生 ARM Linux 等价物 |
|----------|---------------------|------------------|-----------------------|
| INHERIT 模式 `descend`/`ascend` | ~500-2000 cyc（软件模拟） | **5-30 cyc**（仅 trap + 寄存器保存，无页表切换） | 函数调用 ~5 cyc |
| 独立页表 `descend` | ~5000-20000 cyc | **200-1500 cyc**（trap + VTTBR 切换 + 部分 TLB flush） | `syscall` ~250-900 cyc |
| 嵌套虚拟化一层 | ~50000 cyc+ | **2000-5000 cyc**（hardware-assisted nested，相对传统软件模拟 10-30% 开销大幅降低） | 嵌套 KVM ~3000-8000 cyc |

### 6.2 INHERIT 模式在 KVM 下是否仍成立

**核心问题**：INHERIT 模式（共享地址空间、无页表切换）在 KVM 下还能保持 5-10 cycles 的优势吗？

**分析**：
- KVM 下 `descend` 必然引发 `HVC` trap（~150-300 cycles 才能到 EL2 handler）
- 但若 DomainBlock 的 IPA = host PA（共享地址空间），可避免 stage-2 切换
- 优化方向：让 KVM 识别 INHERIT 模式，跳过 VTTBR 写和 TLB flush
- 预期结果：INHERIT 模式 KVM 下约 200-500 cycles（受限于 trap 成本），仍远低于独立页表模式

**结论**：INHERIT 模式的"5-10 cycles"只在真硬件（FPGA/ASIC）下成立；KVM 下受 trap 开销限制，但相对独立页表仍有 3-10x 优势。

### 6.3 评测方法论

参考学术界系统性能评测惯例（如 Ben-Yehuda 2010、soares2010flexsc）：

1. **微基准**：单操作延迟，10^6 次循环取中位数 + P99
2. **系统调用 benchmark**：`lmbench` 的 `lat_syscall` 套件，对比 RPA descend vs 传统 syscall
3. **嵌套虚拟化**：`kvm-unit-tests` 扩展，对比 RPA 嵌套 vs ARM nested KVM
4. **应用级**：`nginx` RPS、`redis-benchmark`、`unixbench`、LLM 推理 tokens/s
5. **可重复性**：每次测试 30 次取中位数，公开原始数据与脚本

---

## 7. 风险与未知

### 7.1 高风险项

| # | 风险 | 影响 | 缓解 |
|---|------|------|------|
| R1 | **树莓派 5 KVM 稳定性**：博通 BCM2712 的 EL2 实现可能有小 bug，社区报告偶发 guest panic | M1-M2 延期 | 备选 Pine64 RockPro 或 Olimex Teres；及时跟进 rpi-linux kernel 补丁 |
| R2 | **AWS Graviton 不允许修改 KVM**：Nitro hypervisor 是闭源固件 | M3-M4 受限 | 仅用 Graviton 跑未修改 KVM 作为 baseline；修改版 KVM 在树莓派 5 / Ampere 裸金属上跑 |
| R3 | **RPA 上游合并到 Linux 主线难度高**：KVM/ARM 维护者（Marc Zyngier 等）对扩展持保守态度 | 长期维护成本 | 论文中明确标注"prototype kernel fork"，不依赖上游合并；维护独立分支 |
| R4 | **ARM nested KVM 成熟度不足**：Linux 6.5+ 才有 ARM nested KVM 实验性支持，性能数据稀缺 | 嵌套场景评测困难 | 嵌套评测作为论文 future work；M3 仅做单层 + INHERIT |
| R5 | **RPA 指令编码冲突**：自定义 HVC 编码可能与未来 ARM 架构扩展冲突 | 长期兼容性 | 使用 `HVC #0xFF00-0xFFFF` 段（ARM 规范保留给实现定义）；论文中明确声明这是 prototype 编码 |

### 7.2 中等风险项

- **R6**：`stage-2` 多层翻译硬件不支持，需软件模拟（性能可能不如预期）
- **R7**：树莓派 5 8GB 内存可能不足以跑 LLM 推理（即使 0.5B 模型也需要 ~2GB）
- **R8**：VGIC v3 虚拟化与 RPA 域间中断路由集成复杂度超预期

### 7.3 未知问题

- Apple Silicon 平台 M-series 的 EL2 行为（已禁用，但学术上好奇）
- ARM CCA RME 与 RPA 安全域机制能否共存（Phase 5+ 议题）
- 是否需要 FPGA 软核（如 Rocket Chip on Xilinx UltraScale+）作为"准硬件"路径

---

## 8. 与论文 evaluation 的对应关系

### 8.1 MCSOC 2026 论文当前 evaluation 现状

参见 `en/mcsoc2026/sections/evaluation.tex`：当前仅有 Python 可执行规范 + 107 个功能测试用例 + 理论性能数据（5-10 cycles / 200-700 cycles / 250-900 cycles）。

### 8.2 各里程碑对论文 evaluation 的贡献

| 里程碑 | 论文用途 | 数据可信度 |
|--------|----------|------------|
| Phase 1-3（TCG） | 功能正确性验证（已有） | 高（功能层） |
| Phase 4 M1-M2（KVM） | "硬件辅助下 RPA 可行性验证" | 高（实现层） |
| Phase 4 M3（KVM 微基准） | "RPA 操作的实测开销" | **中-高**（受 KVM 实现细节影响） |
| Phase 4 M4（真实 workload） | "RPA 对实际应用的端到端影响" | 高（最有说服力） |

### 8.3 TCG 数据 vs KVM 数据的可信度

- **TCG 数据**：仅适合"功能验证"和"算法正确性"，不适合任何性能宣称
- **KVM 数据**：可对外宣称"硬件辅助下"，但仍需明确"基于 KVM 模拟，非真硬件"
- **真硬件数据**（Phase 5+）：才能作为"RPA 性能优势"的最终证据

**对 MCSOC 2026 论文的建议**：
- 当前论文（仅 Python + 理论数据）已足够投稿，定位为"概念性架构设计论文"
- 若 Phase 4 在投稿前完成 M3，可加入"KVM-based prototype evaluation"一节，显著提升说服力
- 若 Phase 4 仅完成 M1-M2，可在 future work 中提及"KVM prototype underway"

---

## 9. 时间与资源估算

### 9.1 各里程碑工作量

| 里程碑 | 主要工作 | 人月 | 关键路径 |
|--------|----------|------|----------|
| M1 | QEMU KVM 后端适配 RPA CPU model | 1-2 人月 | QEMU KVM 代码熟悉度 |
| M2 | KVM 内核 RPA trap handler + stage-2 扩展 | 3-5 人月 | ARMv8 异常处理 + KVM mmu 内部 |
| M3 | 性能评测套件 + 数据收集 | 1-2 人月 | benchmark 工具链搭建 |
| M4 | 真实 workload 适配 + 调优 | 2-3 人月 | guest 内核稳定性 |
| **合计** | | **7-12 人月** | 单人 7-12 个月，双人 4-6 个月 |

### 9.2 硬件成本

| 项目 | 单价 | 数量 | 小计 |
|------|------|------|------|
| Raspberry Pi 5 8GB | $80 | 2 台（一主一备） | $160 |
| 树莓派主动散热器 + 电源 | $25 | 2 套 | $50 |
| 128GB microSD（系统盘） | $20 | 4 张 | $80 |
| USB SSD 1TB（性能评测用） | $80 | 1 个 | $80 |
| AWS Graviton4（c7g.4xlarge，~$1.45/h） | 按需 | 100 小时评测 | $145 |
| **硬件小计** | | | **~$515** |

可选：Ampere Altra Max Developer Platform（~$3000），用于深度多核评测。

### 9.3 外部协作需求

- **ARM 官方技术支持**：非必需。KVM/ARM 文档与代码足够透明；ARM Architectural Reference Manual 公开覆盖 EL2 行为
- **KVM/ARM 维护者社区**：建议 M2 完成后向 `linux-arm-kernel@lists.infradead.org` 邮件列表发 RFC patch，获取早期反馈
- **Raspberry Pi 社区**：树莓派 KVM 配置问题可从 `raspberrypi/linux` GitHub issue 找到答案
- **学术协作**：若需 ARM FastModels 仿真许可（~$数万/年），可联系高校 ARM University Program 申请教育版

---

## 10. 参考链接

### 10.1 KVM/ARM 官方文档
- Linux kernel `arch/arm64/kvm/`：https://kernel.org/doc/html/latest/virt/kvm/arm/
- KVM/ARM design paper（Dall & Nieh, 2014）：https://doi.org/10.1145/2649063
- ARMv8 Architecture Reference Manual：https://developer.arm.com/documentation/ddi0487

### 10.2 树莓派 KVM 教程
- Raspberry Pi 4 KVM：https://github.com/raspberrypi/linux/issues/3261
- Raspberry Pi 5 KVM：https://forums.raspberrypi.com/viewforum.php?f=134

### 10.3 QEMU KVM 加速器
- QEMU KVM backend：https://qemu-project.gitlab.io/qemu/system/invocation.html#accelerators
- `accel/kvm/` 源码：https://gitlab.com/qemu-project/qemu/-/tree/master/accel/kvm

### 10.4 ARM 嵌套虚拟化
- Linux 6.5 ARM nested KVM：https://lwn.net/Articles/935630/
- Nested virtualization overhead（Ben-Yehuda 2010）：https://doi.org/10.1145/1855742.1855759

### 10.5 RPA 项目内部文档
- `papers/rpa-architecture/notes/TECHNICAL_SPEC.md`：RPA 规范 v2.0
- `papers/rpa-architecture/en/mcsoc2026/sections/evaluation.tex`：MCSOC 2026 论文 evaluation 章节
- `papers/rpa-architecture/notes/DESIGN_NOTES.md`：设计要点提纯

---

## 附录 A：决策摘要

- **首选 ARM host**：Raspberry Pi 5 8GB（开发）+ AWS Graviton4（性能评测）
- **首选集成方案**：方案 A（RPA 作为 KVM 扩展）
- **TCG→KVM 迁移关键**：复用 Phase 3 测试套件作为回归保障
- **总工作量**：7-12 人月（单人）或 4-6 人月（双人）
- **硬件预算**：~$515（不含可选 Ampere 开发板）
- **论文影响**：MCSOC 2026 投稿不依赖 Phase 4，但 Phase 4 M3 完成可显著加强 evaluation
