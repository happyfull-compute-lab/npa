# Phase 2：RPA 在 QEMU TCG 中的实现设计

> **文档定位**：rpa-pysim -> QEMU 迁移计划的核心技术设计文档
> **目标读者**：RPA 项目实现者、QEMU TCG 二次开发者
> **版本**：v1.0（2026-07-20）
> **关联文档**：`TECHNICAL_SPEC.md`、`DESIGN_NOTES.md`、`rpa-spec/`、`rpa-pysim/`

---

## 0. 背景与目标

`rpa-pysim` 已用 90+ 测试用例验证了 RPA 三大原语（`descend` / `ascend` / `return`）、页表叠加、IPA 边界检查、安全域机制的语义正确性，但它是 Python 概念模拟器，无法提供：

1. **时序数据**：INHERIT 模式 "1-10 cycles vs 传统 100-500 cycles" 的论断需要真实微架构或周期级模拟器背书。
2. **软件生态**：无法跑标准 ARM/RISC-V 二进制（Linux、KVM、KVM-on-KVM 嵌套虚拟化）。
3. **架构完整性**：pysim 用 Python 字典模拟页表，与 ARM VMSAv8 真实 4 级页表完全不同。

迁移到 QEMU TCG（Tiny Code Generator）后可获得：

- 直接复用 QEMU 的 ARMv8 译码器、VMSAv8 MMU walker、GICv3 中断控制器、PCIe/IOMMU（SMMUv3）模型
- 可运行未修改的 Linux/UEFI 二进制
- 与 KVM 同源的语义（便于交叉验证）
- TCG 虽非周期精确，但能给出"指令数 + 内存访问次数"等代理指标

本设计文档详细说明在 QEMU 中支持 RPA 的全部修改点。

---

## 1. 实现策略总览

### 1.1 三个候选方案

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A. 侵入式修改 target/arm/** | 直接修改 QEMU ARM 目标代码，添加 `ARM_FEATURE_RPA` 特性、新指令、MMU walker 分支 | 功能完整；可运行真实二进制；可上游合并 | 修改面广；需跟随 QEMU 主线 |
| **B. TCG Plugin** | 用 QEMU 5.0+ 引入的 TCG Plugin API 拦截指令和内存访问 | 零侵入；可动态加载 | 仅能"观察"不能"修改"语义；无法注入新指令；TLB/cache 不可控；不满足 RPA 需求 |
| **C. 基于 RISC-V** | 在 `target/riscv/` 加 RPA，利用 RISC-V 自定义指令编码空间 | RISC-V 自定义指令编码更宽松 | 用户偏好 ARM；RISC-V 虚拟化扩展（H-extension）生态弱于 ARM；与现有论文 ARM 案例不一致 |

### 1.2 推荐方案：**A（侵入式 target/arm/ 修改）**

**理由**：

1. RPA 必须修改 MMU walker 才能实现页表叠加，Plugin API 只能观测不能干预 TLB 填充流程。
2. RPA 需要新增 `descend` / `ascend` / `return` 指令，必须在译码阶段接入，Plugin 不支持。
3. 项目目标是论文级评估，可保留本地 fork，不强行上游；侵入式方案的"修改面广"反而是可接受代价。
4. ARM 是 RPA 论文案例的主 ISA（参见 `TECHNICAL_SPEC.md` §11），保持一致。
5. RISC-V 方案留作未来工作（论文 §13 待研究问题）。

### 1.3 fork 策略

- 基于 QEMU **v9.1 LTS**（论文撰写时点最新稳定版），不做跨版本兼容
- 维护分支：`rpa-dev`，rebase 跟随上游 stable
- 上游合并：Phase 2 不以上游为目标；如未来寻求上游化，需将 RPA 包装为 `ARM_FEATURE_RPA` 特性门控，默认关闭，并准备 RFC 寄至 `qemu-devel@nongnu.org`

---

## 2. RPA 状态在 CPU 中的表示

### 2.1 设计原则

RPA 状态与 ARM 原生 EL0/EL1/EL2/EL3 **正交**，不复用 EL 寄存器：

- ARM EL 仍然存在，RPA 运行时 EL=EL1（或可配置 EL2）
- RPA 的"域切换"不走 ARM exception level 切换，而是单独的"DCB 切换"
- 这样的好处：ARM 虚拟化/TrustZone 仍可用作 RPA 之下的"底层支撑"（如用 EL2 实现根域 trap_vector 的物理保护）

### 2.2 CPUARMState 扩展

在 `target/arm/cpu.h` 的 `CPUARMState` 结构体末尾添加 RPA 状态字段：

```c
/* target/arm/cpu.h - CPUARMState 末尾追加 */

/* === RPA State (only valid when ARM_FEATURE_RPA is set) === */
struct ARMCPU;

typedef struct RPADomainState {
    /* 当前 DCB 物理地址（必须 32-byte 对齐）*/
    uint64_t current_dcb_pa;

    /* 当前 domain_id（缓存自 DCB.domain_id，避免每次内存访问都读 DCB）*/
    uint32_t current_domain_id;

    /* 当前 DCB 的 page_table_root（缓存，descend/return 时刷新）*/
    uint64_t current_pagetable;

    /* 当前 DCB 的 ipa_regions 表地址（缓存）*/
    uint64_t current_ipa_regions;

    /* 当前 DCB 的 trap_vector（缓存，0 = propagate）*/
    uint64_t current_trap_vector;

    /* 当前 DCB 的 interrupt_ctrl handle（缓存）*/
    uint64_t current_interrupt_ctrl;

    /* 当前 DCB 的 security_group handle */
    uint64_t current_security_group;

    /* 父域 DCB 物理地址（缓存，用于 ascend）*/
    uint64_t parent_dcb_pa;

    /* 域深度（仅用于调试和报告）*/
    uint32_t domain_depth;

    /* RPA 全局使能位：0 = ARM 原生行为，1 = RPA 模式 */
    bool rpa_active;

    /* 中断屏蔽状态（descend/ascend 时自动管理）*/
    bool irq_masked_by_rpa;

    /* 控制寄存器镜像（可被 MRS 读取）*/
    uint64_t rpa_ctrl_regs[8];  /* 0x800-0x81C see spec doc/integration/interfaces.rst */
} RPADomainState;

typedef struct CPUARMState {
    /* ... 原有 ARM 状态 ... */

    RPADomainState rpa;
} CPUARMState;
```

### 2.3 DCB 在内存中的硬件数据结构

完全遵循 `rpa-spec/doc/dcb/layout.rst` 与 `rpa-pysim/rpa_sim/rpa_logic.py` 的三段式布局，但 AArch64 实现中 word=64 位：

```
偏移    字段                大小    设置者      说明
────    ──────              ────    ──────      ────
RPA Spec Field (固定 8 words = 64 字节，64 位系统)
0x00    ctrlblock_size      8       父域        控制块大小（单位：word，最小 8）
0x08    domain_id           8       系统        域 ID（DMA/故障归属用）
0x10    trap_vector         8       子域        Trap 处理入口（0 = 传播到父域）
0x18    interrupt_ctrl      8       系统        中断控制器 handle
0x20    ipa_regions         8       父域        IPA 区域表地址（子域只读）
0x28    pagetable           8       子域        页表地址（子域可写）
0x30    child_block         8       父域        子域 DCB 地址
0x38    security_group      8       系统        安全组 handle

RPA Impdef Field（可变，从 0x40 起）
0x40    isa_tag             2       父域        ISA 标识（0=继承父域）
0x42    translation_mode    2       父域        0=OWN, 1=INHERIT
0x44    encryption_mode     1       系统        0/1/2/3 见 encryption.rst
0x45    encryption_key_id   3       系统        密钥 ID
0x48    reserved            8       -           保留

ISA Context Field（可变，0x50 起，ARMv8 映射）
0x50    saved_pc            8       硬件        descend/ascend 时保存
0x58    saved_sp            8       硬件        栈指针
0x60    saved_pstate        8       硬件        PSTATE 寄存器
0x68    saved_x0..x30       248     硬件        通用寄存器（可选，部分保存）
0x100   irq_saved_ctx       256     硬件        中断现场保存区（X0-X30 + SP + PC + PSTATE）
```

**对齐**：DCB 必须 64 字节对齐（即 8-word 对齐，对 64 位系统而言）。

### 2.4 与 ARM EL0/EL1/EL2/EL3 的关系

| ARM EL | 在 RPA 模式下的角色 |
|--------|---------------------|
| **EL3** | 仍用于 TrustZone Secure Monitor；RPA 不复用 |
| **EL2** | 可选：RPA 根域（Domain 0）运行在 EL2，使用 VHE（Virtualization Host Extension）；或运行在 EL1 |
| **EL1** | RPA 各域运行时的 EL（推荐配置） |
| **EL0** | RPA 不直接使用 EL0（域本身就是特权层，不需要再分用户/内核） |

**关键设计**：RPA 域切换不修改 ARM `PSTATE_EL`，仅修改 `rpa.current_dcb_pa` 等缓存字段。所有域都在 EL1 运行，避免 ARM exception level 切换的开销。

### 2.5 Security Group 状态

```c
/* target/arm/rpa_internal.h */

typedef struct RPASecurityGroup {
    uint32_t handle;
    uint32_t owner_domain_id;
    uint32_t flags;  /* bit 0: isolated, bit 1: encrypted, bit 2: confidential */
    /* 加密区域表（PA -> key_id 映射）*/
    QLIST_HEAD(, RPAEncryptedRegion) regions;
    /* 允许的 DMA accessor 列表 */
    GArray *accessors;  /* array of uint32_t accessor_id */
} RPASecurityGroup;

typedef struct RPAEncryptedRegion {
    hwaddr start;
    hwaddr size;
    uint32_t key_id;
    QLIST_ENTRY(RPAEncryptedRegion) link;
} RPAEncryptedRegion;

/* 全局 security controller（每个 CPU 地址空间一份）*/
typedef struct RPASecurityController {
    bool enabled;
    GHashTable *groups;  /* handle -> RPASecurityGroup */
    uint32_t next_handle;
} RPASecurityController;
```

`SecurityController` 挂在 `AddressSpace` 上而非 `CPUState`，因为安全域需要覆盖 DMA 旁路访问。

---

## 3. 新增指令的实现

### 3.1 指令编码选择

ARMv8 AArch64 编码空间分析：

- `0xD4xxxxxx`：Exception Generation（SVC/HVC/SMC/BRK/HLT）。`opc[23:21]` 取值 0/1/2/3/5 已被占用，剩 4/6/7 可用。
- `0xD5xxxxxx`：System instructions（MRS/MSR/SYS/SYSL）。编码空间紧。
- `0xC0xxxxxx - 0xCExxxxxx`：loads and stores（被占用）。
- `0x00000000`：UNALLOC。

**推荐编码**：复用 Exception Generation 类，使用 `opc=0x6` 和 `opc=0x7`：

```
descend Xn:  0xD4600080 | (Rn << 5)   // opc=0x6, op2=0x00, LL=0x2
                                        实际 32 位值：(0xD4 << 24) | (0x6 << 21) | (imm16 << 5) | LL
                                        其中 imm16=0x0000, LL=0b10 (用于区分 RPA 子类)

ascend  Xn:  0xD46000A0 | (Rn << 5)   // imm16=0x0001, LL=0b10
return  Xn:  0xD46000C0 | (Rn << 5)   // imm16=0x0002, LL=0b10
exit    :    0xD46000E0               // imm16=0x0003, LL=0b10
sysop   :    0xD4600041 | (sub_op << 8) | ... // 扩展用，imm16 编码 op/subop
```

**备选方案**：使用完全 UNALLOC 的 `0x3Fxxxxxx` 空间（自定义 6 位 opcode = 0x3F），参考 `rpa-spec/doc/integration/interfaces.rst` 的建议。但 ARM 解码树不会自然路由到这种编码，需要在 `disas_a64()` 顶层加分支。

### 3.2 译码器接入点

在 `target/arm/translate-a64.c` 的 `disas_exception` 函数（处理 0xD4xxxxxx）中扩展：

```c
static void disas_exception(DisasContext *s, uint32_t insn)
{
    int opc = extract32(insn, 21, 3);
    int imm16 = extract32(insn, 5, 16);
    int LL = extract32(insn, 0, 5);
    /* ... 原有 SVC/HVC/SMC/BRK/HLT 处理 ... */

    if (opc == 0x6 && LL == 0x2 && arm_dc_feature(s, ARM_FEATURE_RPA)) {
        switch (imm16) {
        case 0x0000:  /* DESCEND */
            disas_rpa_descend(s, insn);
            return;
        case 0x0001:  /* ASCEND */
            disas_rpa_ascend(s, insn);
            return;
        case 0x0002:  /* RETURN */
            disas_rpa_return(s, insn);
            return;
        case 0x0003:  /* EXIT */
            disas_rpa_exit(s, insn);
            return;
        }
        /* fall through to unallocated if imm16 not recognized */
    }
    /* ... unallocated handling ... */
}
```

AArch32 译码（`target/arm/translate.c`）：在 `disas_coproc_insn` 或 `disas_svc` 路径中添加类似分支，编码使用 SVC 的 cond=0xF + 自定义 immediate 模式。

### 3.3 TCG IR 实现

以 `descend Xn` 为例（伪 TCG op 序列）：

```c
static void disas_rpa_descend(DisasContext *s, uint32_t insn)
{
    int Rn = extract32(insn, 5, 5);
    TCGv_i64 dcb_addr = tcg_temp_new_i64();
    TCGv_i64 new_pc = tcg_temp_new_i64();

    /* 读 Rn 寄存器作为 DCB 地址 */
    gen_read_dword_reg(dcb_addr, Rn);

    /* 调用 C helper：完成 DCB 验证、域切换、上下文保存 */
    gen_helper_rpa_descend(new_pc, cpu_env, dcb_addr);

    /* helper 返回新 PC，跳转到子域入口 */
    tcg_gen_mov_i64(cpu_pc, new_pc);

    /* 结束当前 TB，从新 PC 重新翻译 */
    s->base.is_jmp = DISAS_EXIT;

    tcg_temp_free_i64(dcb_addr);
    tcg_temp_free_i64(new_pc);
}
```

### 3.4 C Helper 函数签名

```c
/* target/arm/rpa_helper.c */

/* descend: 进入子域
 * 输入：env, dcb_addr (子域 DCB 物理地址)
 * 输出：返回新 PC（子域入口）
 * 副作用：
 *   - 验证 DCB（对齐、大小）
 *   - 保存父域上下文到父域 DCB 的 ISA Context Field
 *   - 更新 env->rpa.current_dcb_pa 等缓存字段
 *   - 分配 domain_id 并写回子域 DCB
 *   - 设置 env->rpa.parent_dcb_pa
 * 抛出：DCB_ALIGNMENT_ERROR / DCB_SIZE_ERROR / IPA_FAULT
 */
uint64_t helper_rpa_descend(CPUARMState *env, uint64_t dcb_addr);

/* ascend: 返回父域请求服务
 * 输入：env, service_type
 * 输出：返回新 PC（父域 trap_vector）
 * 副作用：
 *   - 保存子域 PC/SP/PSTATE 到子域 DCB
 *   - 切换到父域（更新 rpa.current_dcb_pa 等）
 *   - 沿 DCB 链向上查找 trap_vector != 0 的祖先
 */
uint64_t helper_rpa_ascend(CPUARMState *env, uint64_t service_type);

/* return: 父域返回子域
 * 输入：env, child_dcb_addr (可选，0 表示用 current_dcb.child_block)
 * 输出：返回新 PC（子域保存的 PC）
 */
uint64_t helper_rpa_return(CPUARMState *env, uint64_t child_dcb_addr);

/* exit: 子域退出并释放资源
 * 等价于 ascend(release=true) + 清理
 */
uint64_t helper_rpa_exit(CPUARMState *env);

/* sysop: 系统操作（中断、页表、安全域管理）*/
void helper_rpa_sysop(CPUARMState *env, uint32_t op, uint32_t subop,
                      uint64_t arg1, uint64_t arg2);
```

### 3.5 异常处理路径

DCB 验证失败时通过 ARM 原生异常机制抛出：

```c
/* rpa_helper.c 内部 */
static void rpa_fault(CPUARMState *env, uint32_t fault_code)
{
    /* 构造 syndrome（使用 ARM 未分配 syndrome 空间）*/
    uint32_t syndrome = syn_rpa_fault(fault_code);  /* 自定义：bit24=1 标记 RPA */

    /* 触发 ARM 同步异常（走到 EL1 的 vector）*/
    raise_exception_ra(env, EXCP_UDEF, syndrome, exception_target_el(env), 0);
    /* 注意：RPA 模式下 exception_target_el 总是返回 EL1
     * 因为 RPA 不依赖 ARM EL 切换；EL1 的 vector 应由
     * firmware 配置为跳转到 rpa.current_trap_vector
     */
}
```

`syn_rpa_fault` 在 `target/arm/syndrome.h` 中新增：

```c
/* target/arm/syndrome.h */
static inline uint32_t syn_rpa_fault(uint32_t code)
{
    /* 使用 ARM ARM 中 IL=1, EC=0x00 (Unknown reason) 的格式
     * 但保留 bit [23:20] = 0x1 标识 RPA 类异常
     * bit [19:0] = fault_code（与 spec 的 Fault Codes 一致）
     */
    return (1 << 25) | (1 << 24) | (0x1 << 20) | (code & 0xFFFFF);
}
```

---

## 4. MMU / 页表叠加的实现

这是 RPA 实现中最复杂的部分。

### 4.1 QEMU ARM 的 MMU walker 代码位置

QEMU v9.x 中 ARM MMU 翻译关键函数：

| 函数 | 位置 | 作用 |
|------|------|------|
| `arm_cpu_tlb_fill` | `target/arm/mmu_helper.c` | TLB miss 时回调，调用 `get_phys_addr` |
| `get_phys_addr` | `target/arm/mmu_helper.c` | 顶层地址翻译分发：根据 EL/安全状态选择路径 |
| `get_phys_addr_with_secure` | 同上 | 增加安全状态参数 |
| `get_phys_addr_lpae` | 同上 | VMSAv8 4 级页表 walk |
| `get_phys_addr_v6` | 同上 | ARMv6 简化页表 |
| `get_phys_addr_v5` | 同上 | ARMv5 页表 |
| `ptw` | `target/arm/ptw.c` | 实际页表 walk 原语（v9.0+ 重构） |

调用栈：
```
tlb_fill (TCG softmmu)
  └─> arm_cpu_tlb_fill
        └─> get_phys_addr
              ├─> get_phys_addr_lpae  (for EL1/0 stage1)
              ├─> get_phys_addr_lpae  (for EL2 stage2 if HCR_EL2.VM)
              └─> S1 + S2 串联
```

### 4.2 RPA 翻译路径插入点

在 `get_phys_addr` 顶层添加 RPA 分支：

```c
bool get_phys_addr(CPUARMState *env, vaddr address,
                   MMUAccessType access_type, int mmu_idx,
                   bool s1_is_el0, ARMMMUFaultInfo *fi,
                   hwaddr *phys_ptr, MemTxAttrs *attrs, int *prot,
                   target_ulong *page_size, bool mmu_idx_is_res0)
{
    ARMCPU *cpu = env_archcpu(env);

    /* === RPA 模式：所有地址翻译走 RPA walker === */
    if (cpu->rpa_active && env->rpa.rpa_active) {
        return rpa_get_phys_addr(env, address, access_type, mmu_idx,
                                  fi, phys_ptr, attrs, prot, page_size);
    }

    /* === 原 ARM 翻译路径保持不变 === */
    /* ... EL3 / EL2 / EL1 / EL0 分支 ... */
}
```

### 4.3 RPA Walker 实现

```c
/* target/arm/rpa_mmu.c */

bool rpa_get_phys_addr(CPUARMState *env, vaddr va,
                       MMUAccessType access_type, int mmu_idx,
                       ARMMMUFaultInfo *fi,
                       hwaddr *phys_ptr, MemTxAttrs *attrs,
                       int *prot, target_ulong *page_size)
{
    *page_size = TARGET_PAGE_SIZE;  /* 4KB 默认 */
    *prot = 0;

    /* 1. 准备 DCB 链：从 current_dcb 向上遍历到根域 */
    RPAWalkContext ctx = {
        .va = va,
        .current_addr = va,
        .r = true, .w = true, .x = true, .c = false,
        .fault_owner = -1,
    };

    uint64_t cur_dcb = env->rpa.current_dcb_pa;
    int level = 0;  /* 0 = 最内层（当前域），递增向上 */

    while (cur_dcb != 0) {
        /* 从 DCB 读取 pagetable 和 ipa_regions（每次访问 DCB 字段都
         * 必须用 rpa_read_dcb_field，该函数会用父域页表翻译 DCB 自身
         * 所在的物理地址——这是 RPA 递归性的关键 */
        uint64_t pagetable = rpa_read_dcb_field(env, cur_dcb, OFF_PAGETABLE);
        uint64_t ipa_regions = rpa_read_dcb_field(env, cur_dcb, OFF_IPA_REGIONS);

        if (pagetable == 0) {
            /* INHERIT 模式：跳过本层翻译 */
            /* 但仍需检查 IPA 边界（仅最内层）*/
            if (level == 0 && ipa_regions != 0) {
                if (!rpa_check_ipa_bounds(env, ctx.current_addr,
                                          ipa_regions, fi)) {
                    ctx.fault_owner = env->rpa.current_domain_id;
                    goto fault;
                }
            }
        } else {
            /* OWN 模式：调用 ARM 原生 get_phys_addr_lpae 翻译一层 */
            hwaddr layer_pa;
            int layer_prot;
            target_ulong layer_size;
            if (!rpa_walk_single_level(env, pagetable, ctx.current_addr,
                                       access_type, fi,
                                       &layer_pa, &layer_prot, &layer_size)) {
                /* 翻译失败：fault 归属为该层 pagetable 的 owner */
                ctx.fault_owner = rpa_get_pagetable_owner(env, pagetable);
                goto fault;
            }

            /* 合并权限（取交集，越内层越严格）*/
            ctx.r = ctx.r && (layer_prot & PAGE_READ);
            ctx.w = ctx.w && (layer_prot & PAGE_WRITE);
            ctx.x = ctx.x && (layer_prot & PAGE_EXEC);

            ctx.current_addr = layer_pa;

            /* 第一层翻译后检查 IPA 边界 */
            if (level == 0 && ipa_regions != 0) {
                if (!rpa_check_ipa_bounds(env, ctx.current_addr,
                                          ipa_regions, fi)) {
                    ctx.fault_owner = env->rpa.current_domain_id;
                    goto fault;
                }
            }

            if (layer_size < *page_size) {
                *page_size = layer_size;
            }
        }

        /* 向上一层（父域）*/
        cur_dcb = rpa_read_dcb_field(env, cur_dcb, OFF_PARENT_DCB);
        level++;
    }

    /* 翻译完成，ctx.current_addr 为最终 PA */
    *phys_ptr = ctx.current_addr;
    *prot = (ctx.r ? PAGE_READ : 0) |
            (ctx.w ? PAGE_WRITE : 0) |
            (ctx.x ? PAGE_EXEC : 0);
    attrs->secure = false;  /* RPA 不复用 TrustZone secure state */
    attrs->user = false;    /* RPA 域非 ARM user mode */
    attrs->rpa_domain_id = env->rpa.current_domain_id;  /* DMA 用 */

    return true;

fault:
    fi->type = ARMFault_RPAFault;
    fi->level = level;
    fi->domain_id = ctx.fault_owner;
    return false;
}
```

### 4.4 INHERIT 模式的快速路径

`pagetable == 0` 是 INHERIT 模式。两种优化：

**优化 1：TLB 缓存继承**

如果当前域 pagetable == 0 且 ipa_regions == 0，则 TLB 查找可直接使用父域 ASID：

```c
/* target/arm/rpa_mmu.c - rpa_get_phys_addr 开头 */
if (env->rpa.current_pagetable == 0 && env->rpa.current_ipa_regions == 0) {
    /* INHERIT 无约束：直接使用父域翻译结果
     * 实现：构造一个"借用父域 ASID"的 TLB 查找
     */
    env->rpa.tlb_borrow_parent = true;
    /* 让 tlb_fill 走父域的 TLB 路径 */
    /* 实际实现：递归调用 rpa_get_phys_addr 但用父域状态 */
}
```

**优化 2：TB 内联**

在 TCG 翻译块（Translation Block）级别，如果一段代码运行在 INHERIT 模式下，可以生成与父域共享的 TB：

- TB 哈希键加入 `rpa_domain_depth` 和 `pagetable == 0` 标记
- INHERIT 模式的 TB 可被多个子域共享（性能接近父域原生执行）

### 4.5 IPA 边界检查

```c
/* target/arm/rpa_mmu.c */

static bool rpa_check_ipa_bounds(CPUARMState *env, uint64_t ipa,
                                  uint64_t ipa_regions_table_addr,
                                  ARMMMUFaultInfo *fi)
{
    /* IPA 区域表项格式（与 rpa-pysim 一致，每项 12 字节）：
     *   [base:8] [size:8] [attr:8] -- 实际 AArch64 用 24 字节
     * 结束标记：base=size=attr=0
     */
    uint64_t entry_addr = ipa_regions_table_addr;
    while (true) {
        uint64_t base, size, attr;
        /* rpa_read_physical 在物理地址直接读（不再走 RPA 翻译，
         * 因为 ipa_regions 表本身位于父域地址空间，由父域配置）*/
        base = rpa_read_physical_qword(env, entry_addr);
        size = rpa_read_physical_qword(env, entry_addr + 8);
        attr = rpa_read_physical_qword(env, entry_addr + 16);

        if (base == 0 && size == 0 && attr == 0) break;  /* 结束 */
        if (base <= ipa && ipa < base + size) return true;  /* 在范围内 */
        entry_addr += 24;
    }
    return false;  /* 不在任何区域 */
}
```

### 4.6 TLB 标签设计

QEMU TLB 条目（`CPUTLBEntry`）扩展，加入 RPA domain_id 作为 tag：

```c
/* include/exec/cpu-defs.h 中 CPUPTE 修改 */
typedef struct CPUTLBEntry {
    /* ... 原有字段 ... */
    uint64_t addr_read;
    uint64_t addr_write;
    uint64_t addr_code;
    /* RPA 扩展 */
    uint32_t rpa_domain_id;  /* 0 = 非RPA 或 root 域 */
} CPUTLBEntry;
```

**TLB 失效策略**：

| 事件 | TLB 操作 |
|------|----------|
| `descend` | **不刷新**：子域使用新 ASID-like 的 domain_id，与父域 TLB 共存 |
| `ascend` | **不刷新**：同上，父域 TLB 仍有效 |
| `return` | **不刷新**：子域 TLB 仍有效 |
| `exit` | **强制 flush**：清空被释放子域的 TLB 条目 |
| 修改 DCB.pagetable | `tlb_flush_by_domain_id(env, child_domain_id)` |
| 修改 ipa_regions | 同上 |
| `sysop irq, setvec` | **不刷新** TLB |

新增 API：

```c
/* target/arm/rpa_tlb.c */
void tlb_flush_by_domain_id(CPUARMState *env, uint32_t domain_id);
/* 遍历 TLB，删除所有 rpa_domain_id == domain_id 的条目 */
```

### 4.7 与 ARM Stage-2 翻译的关系

ARM 虚拟化 Stage-2（IPA -> PA）在概念上与 RPA 页表叠加相似，但**不复用**：

| 维度 | ARM Stage-2 | RPA 页表叠加 |
|------|-------------|--------------|
| 层数 | 固定 2 层（S1+S2） | 任意层（受 DCB 链长度限制） |
| 翻译表格式 | VMSAv8 一致 | VMSAv8 一致（可复用 `get_phys_addr_lpae` 单层 walk） |
| 控制寄存器 | VTCR_EL2 / VTTBR_EL2 | DCB 中的 pagetable 字段 |
| 故障归属 | 仅 EL2 | 每层独立（spec §6.3） |
| 上下文切换 | 切 VMID 时全 TLB flush | RPA 仅 flush 单个 domain_id |

**实现选择**：RPA 模式下，禁用 ARM Stage-2（`HCR_EL2.VM = 0`），所有翻译走 RPA walker。Stage-2 的代码路径保留供"RPA 关闭"模式使用。

---

## 5. 中断与异常路由

### 5.1 GIC 与 RPA 域的交互

QEMU GICv3 模型位置：

- `hw/intc/arm_gicv3.c` - 主体
- `hw/intc/arm_gicv3_cpuif.c` - CPU interface（与 CPU 紧密交互）

GIC 的 IRQ 投递目标是物理 CPU，不区分 EL。RPA 需要在 IRQ 被投递到 CPU 后再决定路由到哪个域。

### 5.2 RPA 中断路由层

新增 `target/arm/rpa_irq.c`：

```c
/* 在 ARM CPU 收到 IRQ 时（arm_cpu_exec_interrupt 之后）调用 */
bool rpa_handle_irq(CPUARMState *env, int irq_id)
{
    if (!env->rpa.rpa_active) {
        return false;  /* 走 ARM 原生 IRQ 路径 */
    }

    /* Step 1: 检查当前域是否屏蔽中断 */
    if (env->rpa.irq_masked_by_rpa) {
        return false;  /* 暂存 pending，等解屏蔽 */
    }

    /* Step 2: 检查当前域是否有 interrupt_vector
     * 沿 DCB 链向上查找（与 trap_vector 类似但独立）
     */
    uint64_t cur_dcb = env->rpa.current_dcb_pa;
    while (cur_dcb != 0) {
        uint64_t int_vec = rpa_read_dcb_field(env, cur_dcb, OFF_INTERRUPT_VECTOR);
        if (int_vec != 0) {
            /* 找到处理者：保存当前域上下文，切换到该祖先域 */
            rpa_switch_to_ancestor(env, cur_dcb, int_vec + (irq_id << 4));
            return true;
        }
        cur_dcb = rpa_read_dcb_field(env, cur_dcb, OFF_PARENT_DCB);
    }

    /* 没有域处理：fallback 到 ARM 原生 IRQ 路径（EL1 vector）*/
    return false;
}
```

### 5.3 异常优先级

| 优先级 | 事件 | 处理路径 |
|--------|------|----------|
| 高 | ARM SError | ARM 原生 EL3 / EL2 路径（不可被 RPA 拦截）|
| ↑ | RPA Fault（DCB 错误、IPA 违规） | 走 `rpa_fault`，路由到当前域 trap_vector |
| ↑ | ARM 同步异常（除 0、未对齐、page fault） | 先尝试当前域 trap_vector，若 = 0 则 propagate |
| ↑ | RPA ascend 请求 | 同上，路由到父域 trap_vector |
| 低 | 普通外设 IRQ | 经 `rpa_handle_irq` 路由 |

### 5.4 中断现场保存

按 spec §7.4，descend/ascend 时自动屏蔽中断。在 helper 中实现：

```c
uint64_t helper_rpa_descend(CPUARMState *env, uint64_t dcb_addr)
{
    /* 进入子域前自动屏蔽中断 */
    bool prev_mask = env->rpa.irq_masked_by_rpa;
    env->rpa.irq_masked_by_rpa = true;

    /* ... DCB 验证、上下文保存、域切换 ... */

    /* 切换完成后恢复中断状态 */
    env->rpa.irq_masked_by_rpa = prev_mask;

    return new_pc;
}
```

中断返回机制（spec §7.4）：通过 `bx lr` + `IRQ_RETURN_FLAG` 检测，在 `disas_bx` 中添加：

```c
static void disas_bx(DisasContext *s, uint32_t insn)
{
    /* ... 原有 BX 处理 ... */

    if (arm_dc_feature(s, ARM_FEATURE_RPA)) {
        /* 检查 LR bit 63 (IRQ_RETURN_FLAG) */
        TCGLabel *no_irq_ret = gen_new_label();
        TCGv_i64 tmp = tcg_temp_new_i64();
        tcg_gen_shri_i64(tmp, cpu_reg(14), 63);  /* LR[63] */
        tcg_gen_brcondi_i64(TCG_COND_EQ, tmp, 0, no_irq_ret);

        /* IRQ 返回路径：调用 helper_rpa_irq_return */
        gen_helper_rpa_irq_return(cpu_env);

        gen_set_label(no_irq_ret);
        tcg_temp_free_i64(tmp);
    }
}
```

---

## 6. 内存加密模拟

### 6.1 Phase 2 范围

**包含**：基础加密模拟（XOR 或 AES-CTR 单 block），用于验证语义正确性。

**不包含**：周期精确的加密引擎建模、真实密钥管理硬件、完整性校验（MAC）。

### 6.2 实现方式：QEMU MemoryRegion hook

利用 QEMU 的 `MemoryRegion` + `AddressSpace` 机制：

```c
/* target/arm/rpa_encrypted_memory.c */

/* 加密内存区域作为独立 MemoryRegion，叠加在物理内存之上 */
typedef struct RPAEncryptedMR {
    MemoryRegion parent;  /* 底层物理内存 */
    MemoryRegion overlay; /* 加密层 */
    uint8_t key[32];      /* AES-256 key */
    uint32_t security_handle;
} RPAEncryptedMR;

static uint64_t rpa_encrypted_read(void *opaque, hwaddr addr, unsigned size)
{
    RPAEncryptedMR *emr = opaque;
    uint64_t cipher = memory_region_dispatch_read(emr->parent, addr, size);
    return rpa_decrypt(cipher, emr->key, addr);
}

static void rpa_encrypted_write(void *opaque, hwaddr addr, uint64_t val, unsigned size)
{
    RPAEncryptedMR *emr = opaque;
    uint64_t cipher = rpa_encrypt(val, emr->key, addr);
    memory_region_dispatch_write(emr->parent, addr, cipher, size);
}

static const MemoryRegionOps rpa_encrypted_ops = {
    .read = rpa_encrypted_read,
    .write = rpa_encrypted_write,
    .endianness = DEVICE_NATIVE_ENDIAN,
};
```

### 6.3 创建加密区域

`sysop secdomain, set_encryption, #handle, #addr, #size` 触发：

```c
void helper_rpa_sysop(CPUARMState *env, uint32_t op, uint32_t subop,
                      uint64_t arg1, uint64_t arg2)
{
    if (op == SYSOP_SECDOMAIN && subop == SUB_SET_ENCRYPTION) {
        uint32_t handle = arg1;
        uint64_t addr = arg2 & ~0xFFFULL;
        uint64_t size = arg2 >> 32;

        RPASecurityGroup *g = rpa_get_security_group(env, handle);
        if (!g || !(g->flags & RPA_GROUP_ENCRYPTED)) {
            rpa_fault(env, FAULT_PERMISSION_DENIED);
            return;
        }

        /* 在物理地址空间上覆盖加密 MemoryRegion */
        rpa_install_encrypted_mr(env, addr, size, g->key, handle);
    }
    /* ... 其他 sysop ... */
}
```

---

## 7. 修改文件清单

### 7.1 修改文件列表

| 文件路径 | 修改类型 | 修改行数估算 | 内容 |
|---------|----------|------------|------|
| `target/arm/cpu.h` | 修改 | +60 | `CPUARMState` 添加 `RPADomainState rpa` |
| `target/arm/cpu64.c` | 修改 | +30 | 新增 `ARM_FEATURE_RPA`、`aarch64_rpa` CPU 型号 |
| `target/arm/internals.h` | 修改 | +20 | RPA 内部声明 |
| `target/arm/syndrome.h` | 修改 | +10 | `syn_rpa_fault` |
| `target/arm/translate-a64.c` | 修改 | +120 | `disas_rpa_descend/ascend/return/exit`、`disas_rpa_sysop`、`disas_bx` IRQ_RETURN_FLAG 检测 |
| `target/arm/translate.c` | 修改 | +60 | AArch32 译码路径（可选，论文优先 AArch64） |
| `target/arm/mmu_helper.c` | 修改 | +40 | `get_phys_addr` 顶层添加 RPA 分支 |
| `target/arm/op_helper.c` | 修改 | +20 | 异常处理：RPA fault 路由 |
| `target/arm/rpa_internal.h` | 新增 | +200 | 内部数据结构声明 |
| `target/arm/rpa_helper.c` | 新增 | +800 | `helper_rpa_descend/ascend/return/exit/sysop` |
| `target/arm/rpa_mmu.c` | 新增 | +600 | `rpa_get_phys_addr`、IPA 边界检查 |
| `target/arm/rpa_tlb.c` | 新增 | +150 | `tlb_flush_by_domain_id` |
| `target/arm/rpa_irq.c` | 新增 | +200 | `rpa_handle_irq`、中断返回 |
| `target/arm/rpa_security.c` | 新增 | +500 | 安全组管理、`RPASecurityController` |
| `target/arm/rpa_encrypted_memory.c` | 新增 | +200 | 加密 MemoryRegion |
| `target/arm/rpa_dcb.c` | 新增 | +300 | DCB 读写、验证、链遍历 |
| `target/arm/meson.build` | 修改 | +10 | 新源文件编译规则 |
| `target/arm/cpregs.def` | 修改 | +20 | RPA 系统控制寄存器声明（`CURRENT_DCB` 等）|
| `include/exec/cpu-defs.h` | 修改 | +5 | TLB 加 `rpa_domain_id` 字段 |
| `hw/intc/arm_gicv3_cpuif.c` | 修改 | +30 | IRQ 投递时调用 `rpa_handle_irq` |
| `docs/devel/rpa.rst` | 新增 | +200 | RPA 实现文档 |

**总修改量**：约 3,500 行新增代码 + 200 行修改。

### 7.2 工程量估算

| 阶段 | 工作内容 | 人月 |
|------|---------|------|
| 1. 基础设施 | CPU 状态、特性、DCB 数据结构 | 0.5 |
| 2. 指令译码 | descend/ascend/return/exit + 异常处理 | 0.5 |
| 3. MMU walker | 页表叠加、IPA 边界、TLB tag | 1.5 |
| 4. 中断路由 | GIC 集成、IRQ_RETURN_FLAG | 0.5 |
| 5. 安全域 + 加密 | RPASecurityController、EncryptedMR | 0.5 |
| 6. 测试与对齐 | rpa-pysim 测试矩阵迁移到 QEMU | 0.5 |
| **总计** | | **4.0 人月** |

单人专职约 4 个月可完成；与 rpa-pysim 的 90+ 测试用例对齐是关键里程碑。

---

## 8. 与 rpa-pysim 的语义对齐

### 8.1 测试覆盖矩阵

| rpa-pysim 测试 | QEMU 对应行为 | 验证方法 |
|---------------|--------------|---------|
| `test_rpa.py::TestDomainBlock::test_create_block` | `MRS CURRENT_DCB` 读取 | guest 程序读取控制寄存器，对比值 |
| `test_rpa.py::TestRPALogic::test_descend_conflict_child_block` | descend 时 DCB 冲突检查 | guest 触发冲突，期望 EXCP_UDEF + syndrome |
| `test_rpa.py::TestRPALogic::test_ascend_from_root_fails` | root 域 ascend 抛异常 | guest 调用，期望 fault |
| `test_rpa.py::TestSimpleISA::*` | AArch64 指令执行 | 直接复用，pysim ISA 简化为 ARM 子集 |
| `test_security_group.py::*` | 安全组 create/bind/destroy | guest 用 sysop，结果对比 |
| `test_thread_exception.py::*` | 嵌套异常传播 | 多层 descend 后异常，验证沿链传播 |
| `test_heterogeneous.py::*` | 异构 ISA（ARM/RISC-V）| **Phase 2 不支持**（仅 ARM）|

### 8.2 rpa-pysim 行为映射到 QEMU

| rpa-pysim 概念 | QEMU 对应 |
|----------------|----------|
| `RPALogic.current_domain` (Python 对象) | `env->rpa.current_dcb_pa` + 缓存字段 |
| `Domain.block` (DomainBlock dataclass) | 内存中的 DCB（硬件读取，不缓存到 CPU state）|
| `Domain.parent` (Python 引用) | DCB 的 `parent_dcb` 字段（spec 中是 `parent_block`）|
| `Memory.read_word(addr)` | `cpu_physical_memory_read(addr, ...)`（直接 PA）|
| `MemoryManager.translate_chain(va, chain)` | `rpa_get_phys_addr(env, va, ...)` |
| `PageTable.translate(addr)` | `rpa_walk_single_level` → 复用 `get_phys_addr_lpae` 单层 |
| `Memory.set_encryption(...)` | `rpa_install_encrypted_mr` |
| `SecurityGroupController.bind_domain` | `rpa_security_bind` |
| `SimpleISA.state.pc/sp/regs` | `env->pc`、`env->sp_el[1]`、`env->xregs[]` |
| 中断 pending 位 + IRQ_RETURN_FLAG | `rpa_irq_pending` + `bx lr` 检测 |

### 8.3 无法直接迁移的 pysim 行为

1. **`params` 字段（dict）**：pysim 的 DomainBlock 有 `params: Dict[str, Any]` 字段，QEMU 不支持任意字典；改用"调用约定"——R0/R1 寄存器传参。

2. **`program` 字段**：pysim 的 DCB 有 `program: Dict[str, Any]` 用于关联子域代码块；QEMU 中子域入口通过 `saved_lr` 隐式表达，不需此字段。

3. **`sub_index`（多子域索引）**：pysim 通过 `descend_n(n, params)` 选择不同子域；QEMU 实现中 `descend` 接受 DCB 地址作为参数，天然支持多子域（不同地址 = 不同子域），不需要 `sub_index`。

4. **`_domain_registry`**：pysim 维护 `block_addr -> Domain` 注册表用于 debug；QEMU 不维护此类全局表，每个 CPU 独立。`get_domain_hierarchy()` 接口在 QEMU 中改为 gdb-stub 风格的查询接口。

5. **`FaultInfo` Python 对象**：QEMU 中用 `ARMMMUFaultInfo` 扩展，新增 `domain_id` 字段。

### 8.4 测试框架

使用 QEMU 的 `qtest` 框架 + guest 程序：

```c
/* tests/qtest/rpa-test.c */

static void test_rpa_descend_basic(void)
{
    /* 启动 aarch64 virt 机器，加载测试 kernel */
    /* kernel 内嵌 DCB 初始化 + descend 指令 */
    /* 通过 qtest 协议检查：
     *   - CPU 是否切换到子域 PC
     *   - rpa.current_domain_id 是否更新
     *   - parent_dcb 是否正确保存
     */
}

static void test_rpa_page_table_stacking(void)
{
    /* 3 层 descend + 页表叠加 + IPA 边界 */
    /* 期望：内层 VA 经过 3 次翻译得到最终 PA */
}
```

---

## 9. 风险与依赖

### 9.1 QEMU 版本锁定

| 风险 | 缓解 |
|------|------|
| QEMU 主线重构 `target/arm/`（如 v10.0 已将 ptw.c 拆分）| 锁定 v9.1 LTS；rebase 在 minor 版本内进行 |
| TCG 内部 API 变更（`DisasContextBase` 等）| 把 RPA 译码尽量集中在新增文件，减少对内部 API 依赖 |
| `get_phys_addr` 签名变化 | 包装层：rpa_get_phys_addr 内部调用 ptw 原语，不直接依赖顶层签名 |

### 9.2 上游合并可行性

**Phase 2 不以上游合并为目标**，原因：

1. RPA 是研究性架构，未标准化（无 ARM ARM 条目），上游难以接受
2. 修改涉及 `CPUARMState` 结构和 TLB 条目格式，影响所有 ARM CPU
3. 上游化需要 RFC + 社区讨论，周期 6-12 个月

**未来上游化路径**（如论文发表后）：

1. 将 RPA 包装为 `ARM_FEATURE_RPA` 特性，CPU 型号 `-cpu max,rpa=on` 显式开启
2. 默认不编译（`CONFIG_RPA` 选项）
3. TLB 字段加 `#ifdef CONFIG_RPA` 保护，零开销 when off
4. 寄至 `qemu-devel@nongnu.org`，标题 `[RFC PATCH v1 0/15] target/arm: Add RPA support`

### 9.3 与 ARMv8 ARM 规范的偏离

| 偏离点 | 程度 | 风险 |
|--------|------|------|
| 复用 Exception Generation 编码空间（0xD4xxxxxx opc=0x6/0x7）| 中 | ARM 未来规范可能占用此空间 |
| TLB 条目扩展 `rpa_domain_id` 字段 | 低 | 仅内存占用，无功能冲突 |
| RPA 模式下禁用 Stage-2 翻译 | 中 | 与 KVM 嵌套虚拟化不兼容（但 Phase 2 不需要）|
| 新增 syndrome 类型 `syn_rpa_fault` | 低 | 使用 EC=0x00 (Unknown reason) 兼容 |
| Domain depth 无上限 | 低 | 实际受 DCB 物理内存大小限制 |

### 9.4 性能影响

| 场景 | TCG 译码开销 | 运行时开销 |
|------|-------------|----------|
| 非 RPA 模式（`rpa_active = false`）| +1 条 `if` 判断（预测为 false，几乎零开销）| 0 |
| RPA OWN 模式（独立页表）| 每条指令 TB 重建 | N 层页表 walk，N 倍内存访问（无 TLB 命中时）|
| RPA INHERIT 模式 | 与原生一致（共享 TB）| 单层 walk，TLB 命中时接近原生 |
| descend/ascend 指令 | 一次性 helper 调用 | 不影响后续 TB |

**关键优化**：INHERIT 模式的 TB 共享是性能关键。实现时让 INHERIT 模式 TB 的哈希键不含 `domain_id`，仅含 `pagetable_root`（与父域相同）和 PC。

### 9.5 测试风险

| 风险 | 应对 |
|------|------|
| rpa-pysim 90+ 测试用例覆盖不足 | 补充边界测试：DCB 跨页边界、ipa_regions 表跨页、深度 > 8 |
| QEMU 已有 ARM 测试套件回归 | 每次 rebase 后跑 `tests/qtest/arm-*` 全套 |
| INHERIT 模式 TB 共享导致语义错误 | TB invalidate 时机严格化：任何 DCB 字段修改都 invalidate 相关 TB |

---

## 10. 参考链接

### 10.1 QEMU 官方资源

- QEMU 主仓库：`https://gitlab.com/qemu-project/qemu`
- QEMU v9.1 release notes：`https://www.qemu.org/2024/09/10/qemu-9-1-0/`
- TCG 内部文档：`docs/devel/tcg.rst`（QEMU 源码内）
- ARM target 文档：`docs/devel/arm.rst`（QEMU 源码内）
- TCG Plugin API：`https://www.qemu.org/docs/master/devel/tcg-plugins.html`

### 10.2 ARM 架构参考

- ARM ARM (ARMv8-A Architecture Reference Manual)：`https://developer.arm.com/documentation/ddi0487/latest`
- ARMv8-A Exception Model：`https://developer.arm.com/architecture/learn-the-architecture/exception-model`
- VMSAv8 page table format：ARM ARM D8.2.4
- AArch64 instruction encoding：ARM ARM C4.1

### 10.3 RPA 项目内部文档

- 形式化规范：`papers/rpa-architecture/notes/TECHNICAL_SPEC.md`
- 设计要点：`papers/rpa-architecture/notes/DESIGN_NOTES.md`
- 规范文档树：`papers/rpa-architecture/rpa-spec/doc/`
- 可执行模拟器：`papers/rpa-architecture/rpa-pysim/`
- 主要源码：
  - `rpa-pysim/rpa_sim/rpa_logic.py` - 域管理原语
  - `rpa-pysim/rpa_sim/memory.py` - 页表叠加翻译
  - `rpa-pysim/rpa_sim/isa_simple.py` - 指令执行（含 descend/ascend 译码）
  - `rpa-pysim/rpa_sim/security_group.py` - 安全域机制
  - `rpa-pysim/rpa_sim/interrupt.py` - 中断控制器

### 10.4 关键 QEMU 源码位置（v9.1）

| 路径 | 作用 |
|------|------|
| `target/arm/cpu.h` | `CPUARMState` 定义 |
| `target/arm/cpu64.c` | AArch64 CPU 型号定义 |
| `target/arm/translate-a64.c` | AArch64 译码主循环 |
| `target/arm/translate.c` | AArch32 译码主循环 |
| `target/arm/mmu_helper.c` | `get_phys_addr` 顶层分发 |
| `target/arm/ptw.c` | 页表 walk 原语（v9.0+）|
| `target/arm/op_helper.c` | 异常 helper（`raise_exception` 等）|
| `target/arm/syndrome.h` | ESR/syndrome 计算 |
| `target/arm/internals.h` | 内部声明 |
| `hw/intc/arm_gicv3_cpuif.c` | GICv3 CPU 接口 |
| `include/exec/cpu-defs.h` | TLB 数据结构 |

---

## 附录 A：关键设计决策摘要

| # | 决策 | 理由 |
|---|------|------|
| D1 | 侵入式修改 `target/arm/`，不用 TCG Plugin | RPA 需要新增指令和 MMU walker 修改，Plugin API 不支持 |
| D2 | RPA 状态与 ARM EL 正交，不复用 EL0-EL3 | 保持 ARM 原生机制（TrustZone、KVM）可用 |
| D3 | DCB 8-word Spec Field 在 64 位下扩展为 64 字节 | 与 ARMv8 64 位字长对齐，避免 packed struct |
| D4 | 复用 Exception Generation 编码空间（0xD4 opc=0x6/0x7）| 符合 ARM 编码风格，自然进入 `disas_exception` |
| D5 | RPA walker 在 `get_phys_addr` 顶层分支，不复用 Stage-2 | RPA 支持任意层叠加，Stage-2 固定 2 层 |
| D6 | TLB 条目加 `rpa_domain_id` 字段 | 域间 TLB 隔离，避免全量 flush |
| D7 | INHERIT 模式 TB 共享（哈希键不含 domain_id）| 实现性能近似原生，是论文 "1-10 cycles" 论断的实现基础 |
| D8 | 加密模拟用 MemoryRegion overlay，不修改 RAM 核心 | 复用 QEMU 内存模型，可旁路 DMA |
| D9 | Phase 2 锁定 QEMU v9.1 LTS | 平衡版本稳定性和新特性 |
| D10 | 不以上游合并为目标 | 研究性质架构，先论文后上游化 |

## 附录 B：风险登记册

| 编号 | 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|------|
| R1 | QEMU v9.x 在开发期间 EOL | 低 | 中 | 锁定 LTS，必要时跟随升级 |
| R2 | INHERIT 模式 TB 共享导致语义错误 | 中 | 高 | TB invalidate 严格化；增加跨域测试 |
| R3 | ARM 未来规范占用选定的指令编码 | 低 | 高 | 保留备选编码（UNALLOC 空间）|
| R4 | 安全组 / 加密模拟与 rpa-pysim 行为不一致 | 中 | 中 | 移植 rpa-pysim 测试套件为 qtest |
| R5 | 嵌套深度过大导致 stack overflow（helper 递归）| 低 | 高 | 限制最大深度 32，超过则 fault |
| R6 | GIC 集成导致 IRQ 投递延迟 | 中 | 中 | `rpa_handle_irq` 路径保持轻量，hot path 内联 |
| R7 | DMA 旁路问题（设备直接访问 PA，绕过 RPA）| 高 | 高 | Phase 2 暂用 SMMUv3 模拟；DMA 限制为 root 域 |
| R8 | 多核同步语义未在 Phase 2 实现 | 中 | 中 | Phase 2 仅单核；多核列入 Phase 3 |
| R9 | DCB 所在物理地址翻译的递归（DCB 自身需要翻译）| 高 | 高 | DCB 读取用 `rpa_read_physical_*` 直接物理读，不走 walker |
| R10 | 性能评估指标与论文论断不一致 | 中 | 高 | 用 TCG `-d exec` 输出指令数作为代理指标；明确非周期精确 |

---

**文档结束**

下一步行动项：

1. 创建 `rpa-dev` 分支，基于 QEMU v9.1.0
2. 实现 §2.2 的 `CPUARMState` 扩展，跑通现有 ARM 测试套件确认无回归
3. 实现 §3 的 `descend` 指令 + helper，能从根域 descend 到 Domain 1（不涉及页表）
4. 实现 §4.3 的 RPA walker 单层翻译（先不支持 INHERIT 优化）
5. 移植 `test_rpa.py::TestRPALogic` 为 `tests/qtest/rpa-test.c`
