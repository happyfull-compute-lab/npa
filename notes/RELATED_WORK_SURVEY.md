# RPA 相关文献与行业动态调研

> 调研日期: 2026-06-12
> 目的: 为 ICCNEA 2026 投稿收集相关文献和行业支撑

## 1. 行业动态: IBM × Arm 双架构合作

**来源**: [腾讯云开发者社区](https://cloud.tencent.com/developer/news/3781373) (2026-04-03)

### 核心内容

IBM 与 Arm 合作开发**双架构硬件**，目标是为企业 AI 和数据密集型工作负载提供灵活性。

### 关键技术路线

1. IBM Z 大型机可靠性 + Arm 节能架构 → 统一平台
2. 扩展虚拟化技术 → Arm 软件环境在 IBM 企业计算平台内运行
3. 企业系统识别/执行 Arm 应用程序（跨 ISA 执行）
4. IBM 计划提供整合 Arm 技术的新系统

### 关键引述

- **Christian Jacobi** (IBM 院士/系统开发 CTO): "这一时刻标志着我们为下一代 IBM Z 和 LinuxOne 系统创新之旅的最新步骤，强化了我们端到端系统设计作为强大优势的地位。"
- **Mohamed Awad** (Arm 云AI业务 EVP): "将 Arm 生态系统扩展到关键任务企业环境中，为组织在部署和扩展这些工作负载方面提供更大灵活性。"
- **Tina Tarquinio** (IBM Z/LinuxONE 首席产品官): "扩展软件选择并改善系统性能，同时保持客户期望的可靠性和安全性。"
- **Patrick Moorhead** (Moor Insights & Strategy CEO): "反映了更深层次的长期平台创新和生态系统扩展投资。虽然全面影响需要时间才能显现，但很明显，这反映了我们在这个阶段通常看到的更深层次的长期平台创新和生态系统扩展投资。"

### 技术基础

- 建立在 IBM Z 系列协处理器传统基础上（如 2000 年 Linux 集成设施）
- LinuxOne: 基于 Z 架构的 Linux 系统，在大型机上运行 Linux 工作负载
- Arm Agentic AI CPU: 编排 AI 加速器、管理内存存储、调度工作负载、系统间数据移动

### 与 RPA 的关联分析

| IBM×Arm 双架构 | RPA 对应机制 |
|---|---|
| Z 大型机 + Arm 双架构共存 | 多 ISA 域通过 DCB 管理，递归特权模型统一异构架构 |
| 扩展虚拟化使 Arm 在 IBM 平台运行 | 页表叠加机制（硬件原生多层翻译） |
| 企业系统识别/执行 Arm 应用 | `descend`/`ascend` 跨域切换 + IPA 边界检查 |
| 双架构灵活性 + 企业级安全 | 安全域机制（管理权与访问权分离） |
| Arm 生态系统扩展到关键任务环境 | INHERIT 模式实现低开销跨域调用 (~1-10 cycles) |

**结论**: IBM×Arm 合作是 RPA 最强的行业验证信号——业界正在解决多 ISA 共存问题，而 RPA 提供了统一的抽象层方案。特别是"企业系统识别和执行 Arm 应用程序"这一技术路线，直接对应 RPA 的跨 ISA 域切换机制。

---

## 2. 相关学术文献

### 高度相关 (直接支撑 RPA 核心机制)

#### 2.1 ISA-Grid: Architecture of fine-grained privilege control for instructions and registers

- **来源**: ISCA 2023 | [ACM DL](https://dl.acm.org/doi/abs/10.1145/3579371.3589050)
- **相关性**: ★★★★★
- **核心贡献**: 提出细粒度特权控制架构，将 ISA 划分为不同特权域（ISA domain），每个域对不同指令和寄存器有不同的访问权限。
- **与 RPA 的关联**:
  - ISA-Grid 在**指令粒度**做特权控制，RPA 在**域粒度**做特权递归——两者互补
  - ISA-Grid 的 "ISA domain" 概念与 RPA 的 "domain" 对应，但 RPA 更强调**域间递归关系**
  - **潜在融合**: 如果 DCB 增加 `isa_tag` 字段，ISA-Grid 的指令级控制可作为 RPA 域内进一步细化的机制
- **引用要点**: "each domain having different privileges to access instructions and registers"

#### 2.2 BYOC: "Bring Your Own Core" framework for heterogeneous-ISA research

- **来源**: ASPLOS 2020 | [ACM DL](https://dl.acm.org/doi/abs/10.1145/3373376.3378479)
- **相关性**: ★★★★★
- **核心贡献**: 提出多 ISA 核心集成框架，允许不同 ISA 的核心在同一系统中协同工作。
- **与 RPA 的关联**:
  - BYOC 解决**多 ISA 核心如何共存**，RPA 解决**多 ISA 域如何安全交互**
  - BYOC 是 RPA 在核心层面的**实现前提**——硬件需要支持多 ISA 核心集成
  - BYOC 提到 "compressed and privileged instruction set extensions"，与 RPA 的统一特权原语（descend/escalate/return）思路一致
  - **DCB 扩展建议**: BYOC 的核心标识机制可为 DCB 的 `isa_tag` 字段设计提供参考
- **引用要点**: "architectures with accelerators and domain-specific processors", "hardware heterogeneous-ISA setting"

#### 2.3 Secure Heterogeneous Architecture based on RISC-V and root-of-trust

- **来源**: ACM 2023 | [ACM DL](https://dl.acm.org/doi/abs/10.1145/3606305.3606312)
- **相关性**: ★★★★☆
- **核心贡献**: 基于 RISC-V 的安全异构架构，通过 root-of-trust 核心提供硬件安全机制，在安全域入口控制数据访问。
- **与 RPA 的关联**:
  - "adding a higher privileged layer"——与 RPA 递归特权模型的方向一致
  - 安全域入口数据控制与 RPA 的 `ipa_regions` 边界检查对应
  - 但该工作限于 RISC-V 单一 ISA，RPA 的多 ISA 支持是关键差异
- **引用要点**: "higher privileged layer than existing protection levels", "controlling the access to data entering the secured domain"

### 中度相关 (支撑 RPA 的部分技术机制)

#### 2.4 A framework for software diversification with ISA heterogeneity

- **来源**: RAID 2020 | [USENIX](https://www.usenix.org/conference/raid2020/presentation/wang-xiaoguang)
- **相关性**: ★★★★☆
- **核心贡献**: 利用 ISA 异构性实现软件多样化安全防护，在真实 ISA 异构硬件上运行，利用多域（multi-domain）能力实现安全应用。
- **与 RPA 的关联**:
  - "leverage the heterogeneous ISA, multi-domain capabilities to implement security applications"
  - ISA 异构作为安全手段与 RPA 的安全域机制互补
  - 但该工作关注**安全多样化**而非**统一特权抽象**

#### 2.5 Parallel virtualized memory translation with nested elastic cuckoo page tables

- **来源**: ISCA 2022 | [ACM DL](https://dl.acm.org/doi/abs/10.1145/3503222.3507720)
- **相关性**: ★★★★☆
- **核心贡献**: 提出弹性布谷鸟页表解决虚拟化地址翻译高开销问题，近二十年虚拟化硬件加速后仍然存在的页表遍历瓶颈。
- **与 RPA 的关联**:
  - RPA 的**页表叠加机制**面临同样的嵌套翻译开销问题
  - 弹性布谷鸟页表可作为 RPA 页表叠加的**优化技术**
  - RPA 的 INHERIT 模式（零页表切换）已部分解决了此问题

#### 2.6 IBM Z in a secured hybrid cloud

- **来源**: IEEE 2020 | [IEEE Xplore](https://ieeexplore.ieee.org/abstract/document/9138721/)
- **相关性**: ★★★☆☆
- **核心贡献**: IBM Z 的 PR/SM 虚拟化架构——目前市场上唯一通过 EAL5+ 认证的虚拟化方案。
- **与 RPA 的关联**:
  - PR/SM 是 RPA 递归特权模型在大型机上的**工业级实践参考**
  - IBM Z 的 LPAR 逻辑分区与 RPA 的 domain 概念相似
  - 但 PR/SM 是固定层次（2层），RPA 支持**任意深度递归**

#### 2.7 Security Protection Technology Based on ISA Heterogeneity

- **来源**: IEEE 2025 | [IEEE Xplore](https://ieeexplore.ieee.org/abstract/document/11138395/)
- **相关性**: ★★★☆☆
- **核心贡献**: 利用 ISA 异构冗余技术保护嵌入式设备，但缺少跨架构安全机制。
- **与 RPA 的关联**:
  - 验证了 ISA 异构安全需求的存在性
  - "generally lacks cross-architecture"——恰好是 RPA 要解决的问题

#### 2.8 Confidential Computing with Heterogeneous Devices at Cloud-Scale

- **来源**: IEEE 2025 | [IEEE Xplore](https://ieeexplore.ieee.org/abstract/document/10917655/)
- **相关性**: ★★★☆☆
- **核心贡献**: 云规模异构设备机密计算，提出专用安全控制器（SC）硬件模块。
- **与 RPA 的关联**:
  - 异构 TEE 的安全 IO 问题是 RPA 安全域机制可以覆盖的场景
  - SC 模块与 RPA 的安全域句柄（`security_domain`）概念对应

### 背景参考

#### 2.9 A survey on RISC-V security: Hardware and architecture

- **来源**: arXiv 2021 | [arXiv](https://arxiv.org/abs/2107.04175)
- **相关性**: ★★★☆☆
- **核心贡献**: RISC-V 安全综述，涵盖多架构（ARM + RISC-V）异构安全域。
- **引用要点**: "PolarFire SoC FPGA have adopted heterogeneous architecture to integrate Arm-based co-processors", "cannot be used to elevate privileges"

#### 2.10 When application-specific ISA meets FPGAs: multi-layer virtualization

- **来源**: ASPLOS 2021 | [ACM DL](https://dl.acm.org/doi/abs/10.1145/3445814.3446699)
- **相关性**: ★★☆☆☆
- **核心贡献**: FPGA 上的多层虚拟化框架，处理专用 ISA 在空间硬件上的共享问题。
- **与 RPA 的关联**: 多层虚拟化抽象与 RPA 页表叠加有思路相似性，但应用场景不同。

#### 2.11 TEE by isolated heterogeneous architecture for key scheduling

- **来源**: IEEE 2022 | [IEEE Xplore](https://ieeexplore.ieee.org/abstract/document/9762310/)
- **相关性**: ★★☆☆☆
- **核心贡献**: 通过异构隔离架构实现 TEE，使用硬件 RoT 安全启动。
- **与 RPA 的关联**: 隔离架构的 TEE 与 RPA 安全域机制有概念重叠，但该工作聚焦密钥调度。

---

## 3. DCB ISA 标签扩展建议

### 当前状态

DCB (DomainControlBlock) 目前**没有 ISA 架构标签字段**。ISA 相关信息仅体现在：

- `ctx_save_area` (offset 0x28, 96 bytes): 保存 ISA 相关寄存器状态，但寄存器到偏移量的映射由各 ISA 自行定义
- 整体设计遵循 ISA 无关原则：字段用索引号而非固定字节偏移

### 为什么需要 `isa_tag`

IBM×Arm 双架构合作表明：**多 ISA 域共存**是真实且紧迫的工业需求。在 RPA 中，当 `descend` 从一个 ISA 域切换到另一个 ISA 域时，硬件需要知道：

1. **目标域的 ISA 类型** → 决定 `ctx_save_area` 的寄存器布局
2. **跨 ISA 调用约定** → 参数/返回值如何映射
3. **特权级语义映射** → 不同 ISA 的特权级模型不同（ARM EL0-3 vs x86 Ring 0-3 vs RISC-V U/S/M）

### 建议方案

在 DCB 中增加 `isa_tag` 字段：

| Offset | Field | Size | Set By | Description |
|--------|-------|------|--------|-------------|
| 0x08 (原 reserved) | `isa_tag` | 4 | Parent | 目标域的 ISA 标识 |

**ISA 标签值定义**（示例）:

| 值 | ISA | 特权级映射 |
|----|-----|-----------|
| 0x0000 | 未指定/INHERIT | 使用父域 ISA |
| 0x0001 | x86-64 | Ring 3→0 映射到 RPA domain |
| 0x0002 | AArch64 | EL0→EL3 映射到 RPA domain |
| 0x0003 | RISC-V | U/S/M 映射到 RPA domain |
| 0x0004 | IBM Z | Problem/Supervisor 映射 |
| 0x0100+ | 自定义/扩展 | 用户定义 |

**关键设计考虑**:

1. `isa_tag = 0` (INHERIT): 子域继承父域 ISA，无需 ISA 切换，保持零开销
2. 跨 ISA `descend` 时，硬件根据 `isa_tag` 执行:
   - 保存当前 ISA 上下文到父域 `ctx_save_area`
   - 按目标 `isa_tag` 恢复子域上下文
   - 切换特权级语义映射表
3. `ipa_regions` 和页表格式也需按 `isa_tag` 解释（x86 四级页表 vs ARM TTW vs RISC-V Sv39/x）

### 对现有设计的影响

- **TECHNICAL_SPEC.md**: offset 0x08 的 `reserved_08` 替换为 `isa_tag`
- **页表叠加**: 需要增加 ISA 感知的页表格式解析
- **INHERIT 模式**: 不受影响（`isa_tag = 0` 时无 ISA 切换）
- **安全域**: 跨 ISA 域的加密内存需额外考虑密钥体系

---

## 4. ICCNEA 2026 投稿信息

| 项目 | 详情 |
|------|------|
| **全称** | 9th International Conference on Computer Network, Electronic and Automation |
| **日期** | 2026年9月18-20日 |
| **地点** | 中国西安 |
| **出版** | IEEE Xplore, EI Compendex 收录 |
| **ISSN** | 2770-7695 |
| **官网** | https://cs.xatu.edu.cn/iccnea26/index.html |
| **IEEE认证** | https://conferences.ieee.org/conferences_events/conferences/conferencedetails/70678 |
| **模板** | IEEE 会议 LaTeX 模板 (支持 LaTeX)，已下载至 `papers/rpa-architecture/templates/IEEEtran/` |
| **页数** | 通常 6 页（需确认 CFP） |

### 历届收录情况

- 2017-2023: 全部进入 IEEE Xplore + EI Compendex
- 2024: IOP Publishing, Journal of Physics: Conference Series, EI Compendex
- 2025: IEEE Xplore

### 投稿方向匹配

ICCNEA 涵盖: Computer Network, Electronic and Automation。RPA 论文可投稿方向:
- **Computer Architecture** (体系结构)
- **Network Security** (网络安全)
- **Embedded Systems** (嵌入式系统)

---

## 5. 下一步行动

1. [ ] 确认 ICCNEA 2026 投稿截止日期和 CFP
2. [ ] 在 TECHNICAL_SPEC.md 中更新 DCB 增加 `isa_tag` 字段
3. [ ] 论文中增加"多 ISA 支持"相关章节，引用 IBM×Arm 合作和上述文献
4. [ ] 使用 `bare_conf.tex` 模板开始 6 页论文写作
5. [ ] 补充 ISA-Grid、BYOC 等关键文献的完整引用信息