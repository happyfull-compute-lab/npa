# RPA → QEMU/KVM 迁移：Phase 0 现状与生态调研

> 子任务：Phase 0 - 现状与生态调研
> 范围：rpa-pysim 现状、QEMU ARM 生态、ARM Linux 启动链、Alpine rootfs、Gap 与风险
> 产出：调研文档（无代码）

---

## 1. 现状梳理

### 1.1 RPA 设计要点回顾

RPA（Recursive Privilege Architecture）的核心是把"特权层数"从硬件固定改为内存可配置的递归结构。关键概念来自 `/home/dev/git/academic/papers/rpa-architecture/notes/DESIGN_NOTES.md` 与 `TECHNICAL_SPEC.md`：

- **三个原语**：`descend(block_addr)` 进入子域、`escalate(reason)`/`ascend` 返回父域、`exit()` 终止子域。
- **DomainBlock 控制块**：128 字节、32 字节对齐，由父域创建并管理；含 `exception_vector`、`ipa_regions`、`pagetable`、`child_block`、`security_domain` 等字段（见 `TECHNICAL_SPEC.md` 第 4 节）。
- **页表叠加**：`VA → PT_{N+1} → IPA_N → PT_N → ... → PA`，逐层翻译；`ipa_regions` 用于子域 IPA 边界检查。
- **INHERIT 模式**：`pagetable=0` 时子域共享父域地址空间，`descend/escalate` 成本接近函数调用（~1-10 cycles vs 传统 trap ~100-500 cycles）。
- **安全域**：管理权（配置 ipa_regions）与访问权（读取内存内容）分离，机密计算域内存由内存控制器强制加密。
- **中断控制器**：每域独立实例，通过 `interrupt_ctrl` handle 传递；`sysop irq` 操作；中断现场保存在 `irq_saved_context` 区。
- **多核同步**：自上而下同步，各核心域状态独立。

RPA 明确不追求形式化证明，定位为系统架构论文（参考设计、非顶会导向），见 `DESIGN_NOTES.md` D4 节。

### 1.2 rpa-pysim 子模块现状

仓库位置：`papers/rpa-architecture/rpa-pysim/`

**已实现内容**（参考 `README.md` 与 `rpa_sim/` 目录）：

| 模块 | 路径 | 内容 |
|------|------|------|
| `rpa_logic.py` | `rpa_sim/` | 50 KB，RPA 核心原语：descend/ascend/return/exit、DomainBlock 解析 |
| `memory.py` | `rpa_sim/` | 27 KB，内存模型 + 页表叠加翻译 + IPA 边界检查 |
| `isa_simple.py` | `rpa_sim/` | 58 KB，简化 ISA 解释器（非 ARM），含中断、sysop 指令 |
| `interrupt.py` | `rpa_sim/` | 17 KB，优先级中断控制器，域隔离 |
| `security_group.py` | `rpa_sim/` | 21 KB，安全组、加密内存、DMA 访问控制 |
| `machine.py` | `rpa_sim/` | 6 KB，整机集成 |
| `stdio.py` | `rpa_sim/` | 5 KB，控制台 I/O 设备 |
| `isa/` | `rpa_sim/` | 异构 ISA 子目录 |

**测试覆盖**（`tests/`，共 90+ 用例，pytest 驱动）：

- `test_rpa.py`（18 KB）：域操作、页表翻译、IPA 边界
- `test_isa_simple.py`（12 KB）：指令执行、内存翻译、中断
- `test_security_group.py`（25 KB）：安全组、attestation、加密、DMA
- `test_thread_exception.py`（34 KB）：线程异常、多级翻译、故障处理
- `test_heterogeneous.py`（10 KB）：异构 ISA

**关键不足**：

1. **非 cycle-accurate**：README 明确指出 "not a cycle-accurate simulator"，无法获得可信性能数据。
2. **非真实 ISA**：使用 `SimpleISA`，不执行 ARM/RISC-V 二进制；无法跑现有 OS/工具链。
3. **无 Linux 内核**：无完整 OS 栈，无法验证实际系统调用、虚拟化、应用兼容性。
4. **无 KVM 路径**：纯 Python 解释器，无法对接真实硬件加速。

### 1.3 rpa-spec 子模块现状

仓库位置：`papers/rpa-architecture/rpa-spec/`

文档源码基于 Sphinx + reStructuredText，目录结构覆盖：

- `intro/`：术语、概述、特性
- `primitives/`：`descend.rst`、`ascend.rst`、`return.rst`
- `dcb/`：DomainBlock 字段与布局（`fields.rst`、`layout.rst`）
- `memory/`：`inherit.rst`、`ipa.rst`、`protection.rst`、`translation.rst`
- `interrupt/`：`controller.rst`、`delivery.rst`
- `exception/`：`trap.rst`、`propagation.rst`
- `security/`：`group.rst`、`encryption.rst`、`attestation.rst`、`confidential.rst`
- `integration/`：`boot.rst`、`interfaces.rst`、`diagram.rst`
- `hetero/`：异构扩展

参考 C 头文件 `headers/rpa_mmu.h` 定义 MMU API：`rpa_mmu_set_page_table`、`rpa_mmu_map`、`rpa_mmu_unmap`，标志位 `RPA_MMU_R/W/X/U`。这是后续 QEMU 改造时定义"对内 API"的起点。

---

## 2. QEMU ARM 生态调研

### 2.1 QEMU system-arm 对 ARMv8-A / ARMv9-A 的支持

QEMU 的 ARM 系统模拟器（`qemu-system-aarch64` / `qemu-system-arm`）对 A-profile 架构有"良好支持"（参考 [QEMU Arm System emulator 文档](https://www.qemu.org/docs/master/system/target-arm.html)）。具体到 RPA 关心的特性：

- **ARMv8-A 基础**：cortex-a53、cortex-a57、cortex-a72、cortex-a76 等 CPU 模型可选；`-cpu max` 暴露 TCG 所支持的全部特性（参见 [Arm CPU Features](https://www.qemu.org/docs/master/system/arm/cpu-features.html)）。
- **虚拟化扩展 (EL2)**：`-machine virtualization=on` 启用 HCR/EL2 模拟；GICv4 需要 EL2。
- **TrustZone (EL3)**：`-machine secure=on` 启用安全世界、第二 UART、secure flash、16 MB secure RAM。
- **ARMv8.1-8.6 扩展**：SVE/SVE2、SME、PAUTH、BTI、MTE（`-machine mte=on`）、RME（[RME CPU Properties](https://www.qemu.org/docs/master/system/arm/cpu-features.html#rme-cpu-properties)）。
- **GIC**：v2（≤8 CPUs）、v3（≤512 CPUs）、v4（需 virtualization）、v5（实验性，Armv9）。
- **SMMUv3**：machine-wide 或 user-creatable，支持嵌套翻译（`accel=on`）。
- **virtio-mmio 与 virtio-pci**：virt 板默认 32 个 virtio-mmio transports；PCIe host 通用驱动。

QEMU 当前版本（11.x）对 ARMv9-A RME 已有部分支持，这为 RPA 的"机密计算域"实现提供了参考路径——RME 的 Realm 与 RPA 的 security_domain 概念上同源。

### 2.2 QEMU virt 板：RPA 目标硬件模型

[virt 文档](https://www.qemu.org/docs/master/system/arm/virt.html) 明确指出 virt 是"为虚拟机设计的、不对应任何真实硬件"的板型，"如果你只是想跑 Linux，这是最佳选择"。RPA 用作"参考设计"，virt 几乎是默认选择：

- RAM 起始 `0x4000_0000`，Flash 起始 `0x0000_0000`。
- 支持 UEFI（via edk2/AAVMF pflash）与 U-Boot（via `-bios`）。
- ACPI（ARM64 默认开启）或 Device Tree（ARM32 默认）。
- 32 个 virtio-mmio transports，PCIe 总线，SMMUv3，GPIO，RTC，flash，watchdog。
- 版本化板型（`virt-5.0` 等）保证迁移兼容性。

启动协议方面：
- Linux kernel boot protocol：DTB 地址通过 `r2`（32-bit）或 `x0`（64-bit）寄存器传递。
- Bare-metal / UEFI：DTB 位于 RAM 起始（`0x4000_0000`）。

### 2.3 QEMU TCG 扩展点

QEMU 的 TCG（Tiny Code Generator）将 guest 指令翻译成 host 上可执行的中间表示。RPA 想做的修改对应三个层面：

| 扩展层 | QEMU 实现 | RPA 需求 |
|--------|-----------|----------|
| 自定义指令 | `target/arm/translate-a64.c`（A64 译码）、`target/arm/translate.c`（A32/T32） | `descend`、`ascend`、`exit`、`sysop` 需要新指令编码 |
| 自定义 CSR / 系统寄存器 | `target/arm/cpregs.h`、`target/arm/helper.c` 的 `cpreg` 列表 | 当前域深度、当前 DomainBlock 指针、控制状态 |
| 自定义 MMU 行为 | `target/arm/ptw.c`（页表漫游，11.x 拆分）、`target/arm/tlb_helper.c` | 页表叠加、IPA 边界检查、INHERIT 模式短路 |

`target/arm/` 主要源文件（基于公开仓库 master 分支结构）：

- `translate-a64.c`：A64 指令译码主入口，使用 `decodetree` 机制（见 [Decodetree Specification](https://www.qemu.org/docs/master/devel/decodetree.html)）
- `translate.c` / `translate.h`：A32/T32 译码与共享逻辑
- `helper.c`、`op_helper.c`、`helper-a64.c`：TCG helper 函数
- `cpu.h`、`cpu64.c`、`cpu-models.c`：`CPUARMState` 结构、CPU 模型表
- `ptw.c`（page table walk）：ARM MMU 翻译，含 IPA→PA、EL2/EL3 嵌套
- `tlb_helper.c`：TLB fill / flush
- `arm-powerctl.c`：电源与多核启动控制
- `kvm-arm.c`、`kvm64.c`：KVM 加速后端
- `pauth_helper.c`、`sve_helper.c`、`sme_helper.c`、`mte_helper.c`、`crypto_helper.c`：扩展特性 helper
- `gdbstub*.c`、`arch_dump.c`：调试支持
- `hw/intc/arm_gic*.c`（在 `hw/` 子树）：GIC 设备模型

### 2.4 QEMU vs gem5：自定义 ISA 扩展对比

业界和学界做"自定义 ISA 扩展"时的常见选择：

| 维度 | QEMU TCG | gem5 |
|------|----------|------|
| 速度 | 快（JIT，接近 native 1/2-1/5） | 慢（10-100× slower than QEMU） |
| 修改门槛 | 高（target/arm 耦合深，需理解 TCG IR） | 中（ISA 描述 DSL，可生成 decoder） |
| 真实 OS 兼容 | 强（能跑完整 Linux 发行版） | 弱-中（Linux 可跑但驱动覆盖窄） |
| 工具链对接 | 强（GCC/LLVM 标准支持） | 中（需自行 patched toolchain） |
| 周边生态 | 强（KVM、VFIO、设备模型丰富） | 弱（设备模型较少） |
| 学术先例 | 较少（多为 fork，无统一上游） | 多（很多论文用 gem5 做架构探索） |

**先例**：

- **RISC-V 自定义指令**：多在 Spike（[riscv-isa-sim](https://github.com/riscv-software-src/riscv-isa-sim)）上做，QEMU RISC-V fork 也常见。
- **ARM HVC/SMC 模拟**：QEMU 已经原生实现，是 RPA 实现陷阱式原语可参考的现成路径。
- **Hexagon target**：QEMU 中完整的新 ISA 实现，可作为"如何在 QEMU 中加入自定义 ISA"的范本。
- **CHERI**：在 QEMU MIPS/ARM fork 上加 capability，工程量大但学术价值证明可行。

对 RPA 而言，QEMU 速度快、能跑 Alpine+Linux 内核、KVM 路径明确——这些都是 gem5 缺的优势；代价是 ISA 改造工程量较大。

### 2.5 QEMU TCG Plugin 机制：能做什么、不能做什么

参考 [QEMU TCG Plugins](https://www.qemu.org/docs/master/devel/tcg-plugins.html)：

- **能做**：注册翻译、指令执行、内存访问、vCPU idle/resume 回调；inline 操作 + scoreboard 线程本地存储；统计指令数、内存 trace 等。
- **关键限制**：文档明确"plugin 架构主动避免泄漏 QEMU 翻译的实现细节给插件"；插件只能"查询"，**不能修改指令语义、不能拦截改变控制流、不能改变 MMU 行为**。
- **API 版本化**：上游保留改 API 的权利；out-of-tree 插件需跟随 QEMU 版本维护。

**对 RPA 的结论**：TCG Plugin **不足以实现 RPA**。RPA 需要改变 `descend/escalate` 的语义、改变 MMU 翻译流程、新增 CPU 状态——这些都超出 plugin API 的设计范围。Plugin 顶多用作"性能计数器"或"事件 logger"，辅助 RPA 测量。

---

## 3. ARM Linux 启动链

### 3.1 最小 ARM Linux kernel 配置（QEMU virt）

参考 [virt 文档 Linux guest kernel configuration 节](https://www.qemu.org/docs/master/system/arm/virt.html#linux-guest-kernel-configuration)：

- ARM64 `defconfig` 通常已包含 virtio/PCI 所需驱动；旧 32-bit ARM 内核可能缺项。
- 关键配置：

  ```
  CONFIG_PCI=y
  CONFIG_VIRTIO_PCI=y
  CONFIG_PCI_HOST_GENERIC=y
  # 若用 virtio-gpu-pci：
  CONFIG_DRM=y
  CONFIG_DRM_VIRTIO_GPU=y
  ```

- RPA 后续需要的额外内核配置：`CONFIG_ARM64_SW_TTBR0_PAN`、`CONFIG_RANDOMIZE_BASE` 等可能需关闭以便调试；`CONFIG_EFI_STUB=y`、`CONFIG_EFI=y` 若走 UEFI 路径。

### 3.2 启动协议：U-Boot vs UEFI

| 维度 | U-Boot | UEFI (edk2/AAVMF) |
|------|--------|--------------------|
| 加载方式 | `-bios u-boot.bin` | `-pflash QEMU_EFI.fd -pflash QEMU_VARS.fd`（两片 pflash） |
| 引导加载器 | U-Boot 自身 | GRUB2 / systemd-boot / 直接 EFI Stub |
| 与 Linux EFI Stub 配合 | 需手动 `booti`/`bootm` | 原生支持 |
| Device Tree | U-Boot 传递 dtb | UEFI 通过 EFI 配置表传递 dtb（或用 ACPI） |
| ACPI vs DTB | DTB 为主 | 默认 ACPI，可强制 DTB |
| 与 distro 兼容 | 弱（需手工 chain-load） | 强（标准 EFI 流程，distro 安装器原生支持） |
| 调试便利 | 高（U-Boot 命令行丰富） | 中（需 EFI Shell 或 GRUB） |
| 二进制大小 | 小（<1 MB） | 大（~2-4 MB CODE + 256 KB VARS） |

**对 RPA 的建议**：

- **阶段一**：U-Boot + DTB。理由：U-Boot 命令行方便调试；DTB 更直观可控；不依赖 EFI Stub。
- **阶段二**：切到 UEFI（edk2） + ACPI。理由：distro 安装器兼容性更好；后续对接真实 ARM 服务器（同样走 UEFI+ACPI）。
- **arm-on-arm + KVM 切换**：UEFI 路径更平滑（KVM 在 ARM 上需要 EFI Stub 支持）。

### 3.3 edk2 / AAVMF UEFI 固件支持

"AAVMF"（ARM AMD Virtual Machine Firmware）是早期称呼，现在归入 [edk2](https://github.com/tianocore/edk2) 项目的 `ArmVirtPkg`，对应 `OvmfPkg` 的 ARM 版本。

- **二进制包名**：
  - Debian/Ubuntu：`qemu-efi-aarch64` 包，路径 `/usr/share/qemu-efi-aarch64/QEMU_EFI.fd`
  - Fedora/RHEL：`edk2-aarch64-os` 包，路径 `/usr/share/edk2/aarch64/QEMU_EFI.fd`
  - openSUSE：`qemu-uefi-aarch64`
  - Arch：`edk2-aarch64`（AUR）
- **典型用法**：两片 pflash——CODE.fd（只读）+ VARS.fd（可写）。`-pflash` 顺序：先 CODE 后 VARS。
- **secure boot**：edk2 默认带 Secure Boot 支持；RPA 若做机密计算可基于此扩展。

### 3.4 Device Tree vs ACPI

| 维度 | DTB | ACPI |
|------|-----|------|
| QEMU 默认 | ARM32 默认 | ARM64 默认（`-machine acpi=on`） |
| 大小 | 小（KB 级） | 中（数百 KB） |
| 描述能力 | 硬件拓扑、寄存器、中断 | 硬件 + 电源管理 + 热插拔 |
| 内核要求 | `CONFIG_OF=y` | `CONFIG_ACPI=y` |
| 可读性 | `.dts` 源码可读 | AML 字节码，工具依赖 |
| RPA 自定义节点 | 容易（在 `/chosen` 加节点） | 难（需定义新 ACPI 表） |
| 对 RPA 测试友好度 | **高**（可在 dtb 里直接放 DomainBlock 基址） | 中（需 SSDT 注入） |

**RPA 阶段一建议**：强制 DTB（`-machine acpi=off`），方便在 dtb 中放置 RPA 专用节点（如 `/rpa { domain-block-base = <0x...>; max-depth = <8>; }`）。

---

## 4. Alpine rootfs 选项

### 4.1 Alpine mini rootfs tarball

[Alpine 官方下载](https://alpinelinux.org/downloads/) 提供 `alpine-minirootfs-3.24.1-aarch64.tar.gz`，体积仅 ~4 MB（来自 [dl-cdn.alpinelinux.org 目录](https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/aarch64/)）。

**包含**：

- `musl libc`（轻量 C 库）
- `busybox`（核心命令、init、shell）
- `apk-tools`（Alpine 包管理器）
- `/etc/inittab`、`/etc/init.d/`（OpenRC 服务管理）

**不包含**：

- Linux kernel（需从 `-kernel` 提供）
- bootloader（需 `-bios`/`-pflash` 提供）
- GCC、Python、systemd（按需 apk add）

### 4.2 最小化包集合

RPA 测试需要的最小包集：

```
busybox           # 已含于 rootfs
musl              # 已含于 rootfs
apk-tools         # 已含于 rootfs
openrc            # 默认 init
linux-virt        # 可选：若想用 Alpine 自带内核（QEMU virt 优化）
util-linux        # 基础工具
e2fsprogs         # ext4 文件系统工具
```

后续测试按需追加：`gcc`、`make`、`musl-dev`、`linux-headers`、`dtc`（设备树编译器）、`qemu-tools`（`qemu-aarch64-static` 用于 chroot）。

### 4.3 与 QEMU virtio 设备的兼容性

Alpine Linux `aarch64` 镜像默认开启的驱动：

- `virtio-mmio`、`virtio-pci`：块设备、网络、控制台
- `virtio_blk`、`virtio_net`、`virtio_console`：标准设备
- `9p`、`9pnet_virtio`：分享 host 目录（开发期极便利）
- ext4：rootfs 文件系统

virt 板默认 32 个 virtio-mmio transports（`-machine virtio-mmio-transports=32`），无需额外配置即可挂载 rootfs。

**典型命令行（示意）**：

```
-drive file=rootfs.ext4,if=none,id=hd0 -device virtio-blk-device,drive=hd0
-netdev user,id=net0 -device virtio-net-device,netdev=net0
-fsdev local,id=fsdev0,path=./shared -device virtio-9p-device,fsdev=fsdev0,mount_tag=hostshare
```

---

## 5. Gap 分析与风险

### 5.1 RPA spec → QEMU 修改映射

| RPA spec 部分 | QEMU 实现路径 | 难度 | 估算代码量 |
|---------------|---------------|------|------------|
| 三个原语（descend/escalate/exit） | 新指令编码 + `translate-a64.c` decodetree + `op_helper.c` | 中 | 1000-3000 LOC |
| `sysop` 指令（IRQ/MEMTABLE/SECDOMAIN） | 同上，子操作码 dispatch | 中 | 500-1500 LOC |
| DomainBlock 解析与字段权限 | `helper.c` 新增 helper，CPU 状态扩展 | 中 | 500-1000 LOC |
| 当前域状态（深度、当前控制块指针） | `CPUARMState` 新字段 + cpreg | 低-中 | 200-500 LOC |
| 页表叠加翻译 | `target/arm/ptw.c` 改造，新增递归层 | **高** | 2000-5000 LOC |
| IPA 边界检查 | `ptw.c` 内插入 ipa_regions 验证 | 中 | 300-800 LOC |
| INHERIT 模式（pagetable=0 短路） | `ptw.c` 增加分支 | 低 | 100-300 LOC |
| 中断控制器域隔离 | `hw/intc/arm_gic*.c` 改造 | **高** | 1000-3000 LOC |
| 安全域 / 内存加密 | `memory.c`（QEMU 内存层）+ DMA 路径 | **极高** | 3000-8000 LOC |
| 多核域状态同步 | `arm-powerctl.c` + per-CPU state | 中 | 500-1500 LOC |
| **总计** | | | **~9-22 KLOC** |

### 5.2 可直接映射 vs 需新设计

**可直接映射（spec 已明确）**：

- DomainBlock 字段布局、对齐、设置者权限 → QEMU 内存读写 + 硬件 helper 验证
- IPA 边界检查算法 → `ptw.c` 内 `ipa_regions` 表查询
- INHERIT 模式（pagetable=0 时跳过翻译） → `ptw.c` 分支
- descend/escalate 的"保存上下文到 DomainBlock" → helper 函数

**需新设计（spec 留白）**：

- **指令编码**：spec 用伪代码 `descend Rn`，但具体 A64 编码（SVC/HVC/SMC 复用？还是新 system register 写？）需选择。建议复用 `MSR` 写专用 system reg 触发，避免触碰 opcode 空间。
- **TLB 标签**：页表叠加每层有独立 TLB？还是用 ASID 区分？需要新 TLB 设计。
- **GIC 域视图**：每域独立的 GIC view 如何实现？是软件模拟多个 GIC 实例，还是给 GIC 加 `domain_id` 过滤？
- **DMA 访问控制**：SMMUv3 已有 Stage-1/Stage-2 翻译，但 RPA 的多层翻译超出 SMMUv3 设计；可能需要新设备模型。
- **机密计算域加密**：QEMU 没有原生内存加密原语（x86 上 SEV 是 KVM 路径，ARM 上 RME 是新特性）；软件模拟加密只能做语义验证。

### 5.3 工程复杂度与子系统的耦合

QEMU 内部耦合较深的几处：

1. **`CPUARMState` 与 TCG**：新增字段需同步到 migration、GDB stub、KVM 同步路径。
2. **`ptw.c` 与 TLB**：修改翻译路径影响 TLB fill/flush、Self-Modifying Code 检测、watchpoint。
3. **GIC 与多核**：GICv3 ITS 涉及大量命令队列处理；域隔离改动易引入死锁。
4. **KVM 后端**：若想 arm-on-arm 时切到 KVM，KVM 也需要同步扩展（host kernel 侧 EL2 改造），工作量翻倍。

### 5.4 更轻量的替代方案

考虑 RPA 当前的阶段（架构探索、需要 OS 跑起来、需要可信性能数据但不必上 hardware-fidelity），有几个替代路径：

**方案 A：纯 TCG 源码改造**（前文所述，~9-22 KLOC）
- 优点：最贴近真实硬件语义，能跑 Alpine+Linux。
- 缺点：工程量大；需长期维护 QEMU fork。

**方案 B：TCG Plugin + 用户态软件模拟**
- 用 plugin 拦截 descend/escalate 的"假指令"（编码为 `MSR` 写未用 system reg），在 plugin 回调中软件实现 RPA 语义。
- 优点：不改 QEMU 源码，插件级动态加载。
- 缺点：**plugin API 不允许改变控制流**——这条路径实际不可行（参见 §2.5）。Plugin 只能"观察"，不能"接管"。

**方案 C：HVC/SMC 陷阱 + 监控模式（trap-and-emulate）**
- 把 `descend/escalate` 编码为 `HVC #imm`，在 EL2 / EL3 的 trap handler 中软件实现 RPA 语义。
- 优点：完全不碰 QEMU ISA 层；RPA 逻辑全在 EL2 firmware 里。
- 缺点：失去"零开销 INHERIT 模式"（HVC 本身就是 trap）；页表叠加需要在 EL2 软件 shadow。
- 适用：**阶段一可行性验证**——证明 RPA 语义正确，先不管性能。

**方案 D：gem5 + RPA ISA 扩展**
- 切回 gem5，用 ISA description DSL 加 RPA 指令。
- 优点：学术先例多；cycle-accurate。
- 缺点：跑 Alpine+Linux 慢得难以接受；KVM 路径不存在。

**推荐路径**：

1. **Phase 1**：方案 C（HVC 陷阱 + EL2 firmware），快速跑通"Alpine + Linux + RPA 原语"，验证语义。
2. **Phase 2**：方案 A 的子集——只改 `ptw.c` 实现 INHERIT 模式 + 单层页表叠加，验证性能数据。
3. **Phase 3**：完整方案 A，加安全域、多级叠加、GIC 域隔离，对接论文的完整案例（嵌套虚拟化、机密计算）。

### 5.5 风险清单

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| QEMU 版本快速演进，fork 维护成本高 | 高 | 高 | 选定 LTS 版本（如 8.2/9.x）作 baseline；尽量用 helper hook 而非大段替换 |
| TCG 内部 API 不稳定（ptw.c 在 8.x→9.x 重构过） | 高 | 中 | 减小 patch surface；用 helper 函数包装 |
| GIC 域隔离引入死锁 / 中断丢失 | 中 | 高 | 先做单 CPU + GICv2；逐项加压测 |
| KVM 路径需要 host kernel 同步改造 | 中 | 高 | Phase 1-2 只用 TCG；KVM 留到 Phase 3 |
| edk2/AAVMF 固件与 RPA 启动协议冲突 | 低 | 中 | 阶段一走 U-Boot + DTB 绕开 |
| Alpine musl 与某些测试工具链不兼容 | 低 | 低 | 切到 Debian arm64 mini rootfs（更大但兼容性好） |
| 学术 review 质疑"QEMU 改造不等于硬件实现" | 高 | 中 | 论文中明确声明 QEMU 修改为"语义验证"而非"硬件 prototype"；性能数据归一到 cycle 估算 |

---

## 6. 参考链接

### QEMU 官方文档
- [QEMU Arm System emulator](https://www.qemu.org/docs/master/system/target-arm.html)
- ['virt' generic virtual platform](https://www.qemu.org/docs/master/system/arm/virt.html)
- [Arm CPU Features](https://www.qemu.org/docs/master/system/arm/cpu-features.html)
- [Arm emulation support (A/R/M profile)](https://www.qemu.org/docs/master/system/arm/emulation.html)
- [QEMU TCG Plugins](https://www.qemu.org/docs/master/devel/tcg-plugins.html)
- [Decodetree Specification](https://www.qemu.org/docs/master/devel/decodetree.html)
- [Translator Internals](https://www.qemu.org/docs/master/devel/tcg.html)
- [TCG Intermediate Representation](https://www.qemu.org/docs/master/devel/tcg-ops.html)
- [QEMU invocation reference](https://www.qemu.org/docs/master/system/invocation.html)

### QEMU 源码（GitLab）
- [target/arm/ tree](https://gitlab.com/qemu-project/qemu/-/tree/master/target/arm)
- [hw/intc/ (GIC)](https://gitlab.com/qemu-project/qemu/-/tree/master/hw/intc)
- [docs/system/arm/virt.rst](https://gitlab.com/qemu-project/qemu/-/blob/master/docs/system/arm/virt.rst)

### edk2 / UEFI
- [TianoCore edk2 project](https://github.com/tianocore/edk2)
- [ArmVirtPkg (AAVMF successor)](https://github.com/tianocore/edk2/tree/master/ArmVirtPkg)

### Alpine Linux
- [Alpine Downloads](https://alpinelinux.org/downloads/)
- [Alpine aarch64 releases directory](https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/aarch64/)
- [Alpine wiki: QEMU](https://wiki.alpinelinux.org/wiki/Qemu)

### Linux 内核
- [ARM64 Linux boot protocol](https://www.kernel.org/doc/Documentation/arm64/booting.txt)
- [Linux ARM/ARM64 kernel config](https://www.kernel.org/doc/html/latest/arm/index.html)

### RISC-V / 学术参考
- [Spike RISC-V ISA Simulator](https://github.com/riscv-software-src/riscv-isa-sim)
- gem5: <https://www.gem5.org/>（对比参考）

### 项目内部文档
- `papers/rpa-architecture/notes/DESIGN_NOTES.md` - RPA 设计要点
- `papers/rpa-architecture/notes/TECHNICAL_SPEC.md` - RPA 技术规范 v2.0
- `papers/rpa-architecture/notes/research_analysis.md` - 学术论文角度分析
- `papers/rpa-architecture/rpa-pysim/README.md` - Python 模拟器说明
- `papers/rpa-architecture/rpa-spec/README.md` - 形式化规范说明
- `papers/rpa-architecture/rpa-spec/headers/rpa_mmu.h` - MMU API 头文件

---

## 附录：调研摘要（给主 agent 的简报）

**关键发现**：

1. **rpa-pysim 是"可执行规范"非"性能模拟器"**——已实现 90+ 测试覆盖原语语义、页表叠加、安全组、中断控制器，但无 cycle-accurate 性能数据、非真实 ARM ISA、无 Linux。迁移到 QEMU 是为了"对接真实 OS 与工具链 + 获得 KVM 加速路径"。

2. **QEMU virt 板是 RPA 的天然目标**——支持 UEFI+ACPI / U-Boot+DTB 双路径，TrustZone 与 virtualization 可独立开关，SMMUv3 已有嵌套翻译（Stage-1/Stage-2）作为 RPA 页表叠加的参考实现。

3. **QEMU TCG Plugin 不足以实现 RPA**——plugin API 设计上"只观察不修改"，无法改变指令语义或 MMU 行为。RPA 必须走 target/arm 源码改造路径（`translate-a64.c` + `ptw.c` + `op_helper.c`），估算工程量 9-22 KLOC。

4. **存在更轻量的阶段一方案**——用 HVC 陷阱 + EL2 firmware 实现 trap-and-emulate，不碰 QEMU ISA 层，可快速验证 RPA 语义正确性；INHERIT 模式 + 单层页表叠加留到 Phase 2 用 TCG 改造；完整安全域/GIC 域隔离留到 Phase 3。

5. **Alpine mini rootfs (~4MB) + U-Boot + DTB 是阶段一最佳启动组合**——比 UEFI+ACPI 调试便利，dtb 可直接放置 RPA 专用节点（domain-block-base、max-depth）；阶段二切 UEFI 以获得 distro 安装器兼容性。
