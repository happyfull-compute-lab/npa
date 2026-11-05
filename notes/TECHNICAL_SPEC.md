# Recursive Privilege Architecture (RPA)
## 递归特权架构技术规范 v2.0

---

## 摘要

本文提出递归特权架构（Recursive Privilege Architecture, RPA），一种将特权等级从硬件固定转变为内存可配置的新型特权模型。RPA通过两个对称原语（`descend`和`ascend`）实现特权域间的灵活转换，支持理论无限的特权层级。与现有架构（x86 Ring、ARM TrustZone、RISC-V PMP）相比，RPA统一了虚拟化、机密计算、沙箱隔离等需求的特权管理机制，避免了在传统架构上为每种新需求打补丁的困境。本文定义了RPA的原语语义、控制块结构、页表叠加机制，并通过Python概念验证展示了其在嵌套虚拟化、系统调用、异常处理等场景的应用。

**关键术语更新**：本文使用"Domain"（特权域）替代早期版本的"Level"，使用"DomainBlock"（域控制块）替代早期版本的"LevelConfig"，以更准确地反映架构特性。

---

## 1. 引言

### 1.1 问题背景

现有处理器架构的特权模型存在根本性局限：

| 架构 | 特权层数 | 特点 |
|------|----------|------|
| x86 | 固定4层 (Ring 0-3) | 扩展需硬件改版（如VMX root模式） |
| ARM TrustZone | 固定2层 | 仅支持单一TEE |
| RISC-V | 固定3层 (M/S/U) | PMP数量有限 |
| 虚拟化扩展 | 固定-1, -2层 | 每次扩展需新的硬件机制 |

**核心问题**：特权层数由硬件固定，无法按需扩展。每种新需求（虚拟化、TEE、MPK、SGX）都需要新的硬件机制，导致架构日益复杂。

### 1.2 设计目标

RPA的设计目标：

1. **可扩展性**：特权层数由系统资源决定，而非硬件固定
2. **递归性**：每层视角一致，自视为Level 0
3. **统一性**：一套机制支持虚拟化、机密计算、沙箱等场景
4. **ISA无关性**：可叠加在ARM/RISC-V/x86等现有指令集之上

### 1.3 核心创新

RPA的核心创新在于将特权配置从硬件寄存器转变为内存数据结构：

```
传统架构：
    特权等级 = 硬件寄存器固定值
    层数 = 硬件决定

RPA架构：
    特权等级 = 内存中的配置结构
    层数 = 配置决定（受资源限制）
```

---

## 2. 架构概述

### 2.1 递归特权模型

RPA采用递归特权模型，核心概念是**相对视角**：

```
┌─────────────────────────────────────────────┐
│ 当前域视角：                                 │
│   - 自己 = Domain 0                         │
│   - 子域 = Domain 1, 2, 3, ...              │
│   - 父域 = Domain -1                        │
└─────────────────────────────────────────────┘
```

**域编号约定**：
- Domain 0：根域（最高特权，Root of Trust）
- Domain N+1：Domain N的子域
- 编号越大，特权越低（子域权限由父域授予）

### 2.2 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│ Domain 0 (Root of Trust)                                     │
│   由外部认证建立信任                                         │
│   控制块：由硬件/固件管理                                    │
│   子域：Domain 1, Domain 2, ...                              │
├─────────────────────────────────────────────────────────────┤
│ Domain 1                                                      │
│   控制块：由Domain 0管理，Domain 1不可修改自己               │
│   子域：Domain 1.1, Domain 1.2, ...                          │
├─────────────────────────────────────────────────────────────┤
│ Domain 2                                                      │
│   控制块：由Domain 1管理                                     │
│   ...                                                        │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 与传统架构对比

| 维度 | 传统架构 | RPA |
|------|----------|-----|
| 特权层数 | 硬件固定 | 按需配置 |
| 特权配置存储 | 寄存器/MSR | 内存数据结构（DomainBlock） |
| 层间转换 | trap/return | descend/ascend |
| 视角 | 绝对编号 | 相对视角 |
| 扩展性 | 需新硬件机制 | 配置即可扩展 |
| 层间关系 | 固定父子关系 | 动态树状结构 |

---

## 3. 原语定义

RPA定义两个对称原语，形成简洁的上下行模型：

### 3.1 descend原语

```python
descend(block_addr):
    """
    进入子域（首次或恢复）

    语义：
    1. 从 block_addr 读取 DomainBlock
    2. 验证控制块有效性（对齐、大小）
    3. 检查 child_block 字段判断首次进入还是恢复执行
    4. 首次进入：保存当前上下文，加载新 DomainBlock，跳转到入口
    5. 恢复执行：恢复子域的保存上下文继续执行

    执行后：
    - 当前域变为子域的父域（Domain -1）
    - 子域成为新的当前域（视角为Domain 0）

    参数：
        block_addr: DomainBlock 的内存地址

        DomainBlock 是内存中的控制块结构，包含：
            - ctrlblock_size: 控制块大小（必须为32的倍数）
            - exception_vector: 异常处理入口
            - interrupt_ctrl: 中断控制器handle
            - ipa_regions: IPA区域表地址（父域设置）
            - pagetable: 页表地址（子域设置）
            - child_block: 子域控制块地址（用于判断首次/恢复）
            - ...（详见第4节）

    首次进入 vs 恢复执行：
        - child_block == 0：首次进入子域
          硬件保存父域上下文到父域控制块，加载子域控制块，跳转到 saved_lr
        - child_block != 0：恢复已存在的子域
          硬件恢复子域保存的上下文，继续执行
    """
```

### 3.2 ascend原语

```python
ascend(reason):
    """
    返回父域

    语义：
    1. 保存当前域上下文到控制块
    2. 切换到父域
    3. 跳转到父域的 exception_vector
    4. R0 传递原因/参数

    执行后：
    - 控制权转移给父域
    - 父域决定如何处理请求

    参数：
        reason: 原因编码

        用途：
        - 服务请求：子域请求父域执行特权操作
        - 异常上报：子域发生异常，请求父域处理
        - 正常返回：子域执行完毕，返回结果
    """
```

### 3.3 EXIT指令

```python
exit():
    """
    退出子域并释放资源

    语义：
    1. 等效于 ASCEND + 释放子域
    2. 清空父域的 child_block 字段
    3. 清空子域的 domain_id

    与 ASCEND 的区别：
    - ASCEND：返回父域，子域状态保留，可恢复
    - EXIT：终止子域，释放资源，不可恢复
    """
```

### 3.4 多子域场景

当父域配置了多个子域时，通过不同的控制块地址区分：

```python
# 父域管理多个子域
block_addr_1 = 0x10000  # 子域1的控制块
block_addr_2 = 0x20000  # 子域2的控制块

# 进入子域1
descend(block_addr_1)

# 进入子域2
descend(block_addr_2)
```

**首次进入与恢复**：`descend(block_addr)` 通过检查 `child_block` 字段区分两种语义：
- `child_block == 0`：首次进入子域，硬件初始化子域状态
- `child_block != 0`：恢复已存在的子域，从保存的上下文继续执行

### 3.5 当前域深度获取

获取当前域深度的实现方式：

**方式一：栈式内存（连续存储）**

```
控制块布局：
    base_addr ──► Domain 0 控制块
    base + N   ──► Domain 1 控制块
    base + 2N  ──► Domain 2 控制块
    ...

计算当前域深度：
    depth = (current_block_ptr - base_addr) / sizeof(DomainBlock)

特点：
    - O(1) 时间复杂度
    - 需要预分配连续内存
    - 适合层数固定的场景
```

**方式二：链式内存（指针链接）**

```
控制块布局：
    Domain 0 ──► parent: null, child_block: addr1, addr2, ...
    Domain 1 ──► parent_block: addr0, child_block: ...
    ...

计算当前域深度：
    depth = 0
    ptr = current_block_ptr
    while ptr.parent_block != null:
        depth += 1
        ptr = ptr.parent_block

特点：
    - O(depth) 时间复杂度
    - 内存分配灵活
    - 适合动态层数场景
```

---

## 4. 控制块结构

### 4.1 DomainBlock 概述

DomainBlock 是 RPA 的核心数据结构，位于内存中，用于域切换时的上下文传递和状态保存。

**关键设计原则**：
1. 控制块位于内存中，通过普通读写指令操作
2. 控制块大小固定（128字节），便于硬件解析
3. DESCEND 指令使控制块配置生效
4. 控制块由父域创建和管理，子域不可修改自己的控制块

### 4.2 DomainBlock 结构定义

控制块大小：128 字节（对齐要求：32字节边界）

```
偏移    字段名                大小    设置者      说明
────    ──────                ────    ──────      ────
0x00    ctrlblock_size        4       父域        控制块大小（必须为32的倍数）
0x04    exception_vector      4       子域        异常处理入口
0x08    reserved_08           4       -           保留
0x0C    interrupt_ctrl        4       系统        中断控制器handle
0x10    ipa_regions           4       父域        IPA区域表地址（子域只读）
0x14    domain_id             4       系统        域ID（系统分配）
0x18    pagetable             4       子域        页表地址（子域可写）
0x1C    child_block           4       父域        子域控制块地址
0x20    security_domain       4       系统        安全域handle
0x24    access_id             4       系统        访问ID（DMA用）
0x28    ctx_save_area         96      硬件        ISA相关上下文保存区
                                        （偏移0x28-0x87，具体映射由ISA定义）
0x40-0x83 irq_saved_context    64      硬件        中断现场保存区
```

### 4.3 字段详解

#### ctrlblock_size (0x00)
- 控制块大小，必须为32的倍数
- DESCEND 时硬件验证对齐和大小有效性
- 最小值：32字节，典型值：128字节

#### exception_vector (0x04)
- 异常处理入口地址
- 所有非中断异常（包括 ASCEND）跳转到此地址
- 值为 0 表示禁用异常处理，异常直接传播到父域
- **子域设置，用于接收子域的异常**

#### interrupt_ctrl (0x0C)
- 中断控制器 handle
- 值为 0：子域不能操作中断控制器
- 值为 非0：子域可以通过 `sysop irq` 操作中断

#### ipa_regions (0x10)
- IPA 区域表地址
- **父域设置，子域只读**
- 定义子域可用的 IPA（中间物理地址）范围约束
- 值为 0：不建立新映射（try-catch 场合）
- 子域创建页表时，IPA 必须在 ipa_regions 定义的范围内

#### domain_id (0x14)
- 域 ID，由系统自动分配
- 用于调试、安全子系统和 DMA 访问控制
- 每个新域分配唯一 ID

#### pagetable (0x18)
- 页表地址
- **子域设置，子域可写**
- 定义 VA → IPA 的映射
- 子域创建页表后更新此字段
- 更新动作表示新页表生效

#### child_block (0x1C)
- 子域控制块地址
- 由父域维护
- 用于首次进入子域或恢复子域执行
- DESCEND 时硬件自动更新父域的此字段

#### security_domain (0x20)
- 安全域 handle
- 用于内存加密和 DMA 访问控制
- 详见第8节"安全域机制"

#### access_id (0x24)
- 访问 ID
- 用于 DMA 访问控制
- 同一安全域内的设备可以互相访问

#### ctx_save_area (0x28-0x87)
- ISA相关上下文保存区域（96字节）
- 存储域转换时需要保存的处理器状态
- **具体映射由各ISA定义**，例如：
  - ARM: 栈指针(SP)、链接寄存器(LR)、程序状态寄存器(PSR)等
  - x86: 栈指针(RSP)、指令指针(RIP)、标志寄存器(RFLAGS)等
  - RISC-V: 栈指针(sp)、返回地址(ra)、状态寄存器(sstatus)等
- ASCEND 时保存，首次 DESCEND 时恢复

#### irq_saved_context (0x40-0x83)
- 中断现场保存区域
- 保存 R0-R15 和 PSR
- 中断进入时由硬件自动保存

### 4.4 字段权限总结

| 字段 | 设置者 | 权限 | 用途 |
|------|--------|------|------|
| ctrlblock_size | 父域 | 只读 | 验证控制块有效性 |
| exception_vector | 子域 | 读写 | 异常处理入口 |
| interrupt_ctrl | 系统 | 读写 | 中断控制器操作 |
| ipa_regions | 父域 | 只读 | IPA 范围约束 |
| domain_id | 系统 | 只读 | 域标识 |
| pagetable | 子域 | 读写 | VA→IPA 映射 |
| child_block | 父域 | 读写 | 子域管理 |
| security_domain | 系统 | 只读 | 安全域绑定 |
| access_id | 系统 | 只读 | DMA 访问控制 |

### 4.5 页表配置选项

```python
# 选项1：共享父域地址空间（无页表）
pagetable = 0  # 无独立页表，共享父域视角

# 选项2：独立页表
pagetable = 0x80000  # 页表基址
```

### 4.6 中断配置

中断控制器通过 handle 传递给子域：

```python
# 父域配置
domain_block = {
    "interrupt_ctrl": 0xFFFF0000,  # 中断控制器handle
}

# 子域使用 sysop 指令操作
sysop irq, enable, #irq_id    # 启用中断
sysop irq, disable, #irq_id   # 禁用中断
sysop irq, setvec, #vector    # 设置中断向量
```

**中断下发机制**：

```
场景：子域想在全局高精度timer中注册通知事件

Step 1: 子域发起请求
    子域执行: ascend({request: "register_timer", callback: addr})

Step 2: 父域处理请求
    父域收到请求，注册到中断控制器
    父域返回确认给子域

Step 3: 中断触发时
    中断控制器触发软中断
    软中断注入到子域的中断控制器
    子域收到中断通知
```

---

## 5. 页表叠加机制

### 5.1 基本原理

RPA支持页表叠加，每域的页表翻译上一域的"物理地址"：

```
Domain N+1 的虚拟地址 VA
    │
    │ PT_{N+1} 翻译
    ▼
Domain N 的物理地址（实际是Domain N-1的虚拟地址，即IPA）
    │
    │ PT_N 翻译
    ▼
Domain N-1 的物理地址
    │
    │ ...
    ▼
真实物理地址
```

**术语说明**：
- **VA (Virtual Address)**：当前域的虚拟地址
- **IPA (Intermediate Physical Address)**：中间物理地址，翻译链中的中间结果
- **PA (Physical Address)**：最终物理地址

### 5.2 IPA边界检查

子域创建页表时，IPA 必须在 `ipa_regions` 定义的范围内：

```
父域分配给子域的地址空间：
    ipa_regions = [
        {base: 0x10000000, size: 0x10000000, attr: RWX},  // 256MB
        {base: 0x20000000, size: 0x08000000, attr: RW},   // 128MB
    ]

子域创建页表：
    有效：VA → IPA (0x10000000-0x1FFFFFFF) ✓
    无效：VA → IPA (0x30000000) ✗ 超出范围，触发翻译错误
```

**翻译流程**：

```python
def translate_address(va, domain):
    """
    将虚拟地址翻译为最终物理地址
    """
    pa = va
    current = domain

    while current is not None:
        # 检查 ipa_regions（第一层之后）
        if current.parent is not None:
            ipa_regions = current.parent.read_ipa_regions(current)
            if ipa_regions != 0:
                if not check_ipa_in_regions(pa, ipa_regions):
                    raise TranslationError(pa, "IPA out of bounds")

        # 页表翻译
        pt = current.pagetable
        if pt == 0:  # 无独立页表，共享父域视角
            current = current.parent
            continue

        pa = translate_single_level(pt, pa)
        current = current.parent

    return pa
```

### 5.3 三种模式

**模式1：共享地址空间（无页表）**

```
┌─────────────────────────────────────────────┐
│ Domain N                                      │
│   pagetable: 0（无独立页表）                  │
└─────────────────────────────────────────────┘
         ↓ 共享父域视角
┌─────────────────────────────────────────────┐
│ Domain N+1                                    │
│   与父域共享地址空间                          │
│   ascend成本: ≈函数调用                   │
└─────────────────────────────────────────────┘
```

**无独立页表模式下低开销的原因**：
- 无页表切换：父子域共享同一地址空间
- 无 TLB 刷新：地址映射不变，TLB 条目有效
- 无额外状态保存：descend/ascend 仅涉及寄存器状态切换
- 中断状态自动管理：见 7.4 节

**模式2：独立页表**

```
┌─────────────────────────────────────────────┐
│ Domain N                                      │
│   pagetable: PT_N                            │
│   ipa_regions: 定义子域IPA范围               │
└─────────────────────────────────────────────┘
         ↓ 独立地址空间
┌─────────────────────────────────────────────┐
│ Domain N+1                                    │
│   pagetable: PT_{N+1}（完全独立）            │
│   ascend成本: ≈传统trap                   │
└─────────────────────────────────────────────┘
```

### 5.4 应用场景

| 场景 | 页表模式 | 说明 |
|------|----------|------|
| 系统调用 | 无独立页表 | 共享地址空间，快速切换 |
| Try-catch | 无独立页表 | 共享地址空间，零开销异常 |
| 嵌套虚拟化 | 独立页表 | 每域独立地址空间 |
| 机密计算 | 独立页表 | 父域无法访问子域内容 |

### 5.5 页表叠加示例

**叠加翻译示例**：

```
Domain 2 发起内存访问：VA = 0x1000

Step 1: Domain 2 翻译
    VA(0x1000) ──PT_D2──► IPA_D1(0x2000)   # Domain 2视角的"物理地址"

Step 2: 检查 IPA 边界
    IPA(0x2000) 在 ipa_regions 范围内 ✓

Step 3: Domain 1 翻译
    IPA_D1(0x2000) ──PT_D1──► IPA_D0(0x3000)

Step 4: Domain 0 翻译
    IPA_D0(0x3000) ──PT_D0──► PA(0x4000)

结果：Domain 2 访问 0x1000 实际访问物理地址 0x4000
```

**无独立页表示例**：

```
Domain 2 发起内存访问：VA = 0x1000
Domain 2 的 pagetable = 0

Step 1: Domain 2 跳过翻译（无独立页表）
    VA(0x1000) 保持不变

Step 2: Domain 1 翻译
    0x1000 ──PT_D1──► IPA_D0(0x2000)

Step 3: Domain 0 翻译
    IPA_D0(0x2000) ──PT_D0──► PA(0x3000)

结果：Domain 2 访问 0x1000 实际访问物理地址 0x3000
```

---

## 6. 安全机制

### 6.1 配置保护

**语义约束**：
- Domain N+1的控制块由Domain N创建和管理
- Domain N+1不应修改自己的控制块
- Domain N可以管理Domain N+1的控制块

**实现细节**：
- 控制块存储在父域的内存空间
- 如果父域主动将控制块放在共享区域，子域可修改
- 这种情况视为父域默许，不违反语义

### 6.2 内存访问隔离

RPA通过内存隔离机制实现父域对子域内容的访问控制：

**基本原理**：
- 控制块存储在父域内存空间，子域无法直接访问
- 子域的私有内存由子域自己管理，父域没有地址引用
- 子域需要共享数据时，显式传递指针作为参数

**实现方式**（由实现层决定）：
1. 页表隔离：父域不映射子域的私有内存区域
2. 内存控制器：支持机密计算的内存控制器可强制隔离
3. Tagged Memory：类似CHERI的标记内存保护

**语义约束**：
- 父域可以配置子域的页表（通过 ipa_regions）
- 父域不一定能访问子域的内存内容
- "管理权"（配置）与"访问权"（内容）分离

### 6.3 故障传播

**异常与故障的关系**：

```
异常 (Exception) = 突发事件
    ├── 故意的陷阱 (Trap)
    │   └── 页错误、系统调用、断点等 → 可恢复，处理后继续
    └── 故障 (Fault)
        └── 总线无响应、内存耗尽等 → 确定后由父域决定终止或恢复

处理流程：
    异常发生 → exception_vector
        ├── 判断为可恢复 → 处理后返回子域继续
        └── 判断为故障 → 父域决定处理方式
```

**故障传播机制**：

```
故障发生时：
    1. 当前域停滞
    2. 所有子域停滞
    3. ascend到父域
    4. 父域判断故障来源（包含域ID信息）
    5. 父域决定处理方式
```

**根域故障**：
- 若故障传播至根域仍无法处理，系统无法继续
- 处理策略：尽量保存现场，上报外部观察者（如硬件看门狗、管理程序），或等待外部干预
- 根域故障处理超出本文范围，依赖系统设计时的外部保障

**父域处理选项**：

| 情况 | 处理方式 |
|------|----------|
| 子域故障，可恢复 | 终止子域进程/虚拟机，恢复执行 |
| 子域故障，下层可处理 | 委托下层处理 |
| 系统级故障，不可恢复 | 上报RAS模块，系统重启 |
| 当前域故障 | ascend到更上层域 |

**系统设计时的故障分配**：

```
系统设计初需确定：
    - 哪些故障由哪域处理
    - 系统级故障（总线无响应等）通常由根域处理
    - 根域在初始化时注册故障处理器，不委托给子域
```

### 6.4 根信任

根信任通过外部认证建立：

```
外部认证实验室
    │
    │ 认证硬件设计/初始启动代码
    ▼
Domain 0 (根信任域)
    │ 签名验证下一域
    ▼
Domain 1
    │ 签名验证下一域
    ▼
...
```

根信任的建立不是本文创新点，作为前提假设。

---

## 7. 多核同步

### 7.1 单核工作模式

每个核心独立工作，拥有自己的域状态。

### 7.2 多核启动流程

```
Core 0（启动核心）：
    Domain 0 → 初始化 → descend到工作域

Core 1, 2, 3（从核心）：
    初始状态：未初始化，停留在最高域
    等待Core 0的Domain 0发起多核启动
    必须ascend到父域才能开启
```

### 7.3 同步规则

**核心规则**：各核心工作域必须自上而下同步

```
正确示例：
    Core 0: Domain 0 → Domain 1 → Domain 2
    Core 1: Domain 0 → Domain 1 → Domain 2（与Core 0同步）

禁止：
    Core 0: Domain 0 → Domain 1 → Domain 2
    Core 1: 直接复制状态进入Domain 2（跳过父域初始化）
```

**原因**：每域的ascend处理依赖父域的正确配置。

### 7.4 中断状态管理

**自动中断控制**：

```
descend/ascend 时的中断处理：
    1. 进入子域/父域时：自动禁止新中断进入
    2. 完成状态切换后：恢复中断状态
    3. 域间中断隔离：各域有独立的中断状态
```

**域间隔离特性**：

```
Domain N 的中断状态：
    - 只影响 Domain N 的中断接收
    - 不影响 Domain N+1（子域）的中断
    - 不影响 Domain N-1（父域）的中断

原因：
    - 各域有独立的 SP（栈指针）和上下文空间
    - 各域的 ISR 不会复用或重入
```

**中断返回机制**：

```
中断进入时：
    1. 保存所有寄存器到 irq_saved_context 区域
    2. 清除 pending 位（中断被响应）
    3. LR = saved_pc | IRQ_RETURN_FLAG (bit 31)
    4. irq_disabled = True, in_interrupt = True
    5. PC = interrupt_vector

bx lr 执行时：
    1. 检查 LR 是否有 IRQ_RETURN_FLAG
    2. 如果有且 in_interrupt == True：
       - 从 irq_saved_context 恢复所有寄存器
       - PC 从 saved_pc 恢复
       - irq_disabled = False, in_interrupt = False
    3. 如果有但不在中断上下文：
       - PC = LR & ~IRQ_RETURN_FLAG
    4. 如果没有标志：
       - 普通跳转 PC = LR
```

**优点**：
- ISR 直接使用 `bx lr` 返回，无需特殊指令
- 硬件自动恢复上下文，程序员无需手动处理
- 标志位防止误用

---

## 8. 中断控制器

### 8.1 中断控制器架构

RPA 支持每域独立的中断控制器实例，通过 `interrupt_ctrl` 字段传递。

```
┌─────────────────────────────────────────────┐
│ Domain N                                      │
│   interrupt_ctrl: 中断控制器handle           │
│   exception_vector: 异常入口                 │
└─────────────────────────────────────────────┘
         ↓ descend 时传递
┌─────────────────────────────────────────────┐
│ Domain N+1                                    │
│   interrupt_ctrl: 从父域继承或新分配          │
└─────────────────────────────────────────────┘
```

### 8.2 中断控制器接口

中断控制器通过 handle 访问，子域使用 `sysop irq` 指令操作：

```
sysop irq, request, #irq_id, #perm_flags   ; 请求中断
sysop irq, release, #irq_id                ; 释放中断
sysop irq, enable, #irq_id                 ; 启用中断
sysop irq, disable, #irq_id                ; 禁用中断
sysop irq, setvec, #vector                 ; 设置中断向量
sysop irq, getpending, Rd                  ; 获取待处理中断
sysop irq, clear, #irq_id                  ; 清除中断
sysop irq, sgi, #target_cpu, #irq_id       ; 发送软件中断
```

### 8.3 中断权限控制

中断控制器支持细粒度权限控制：

| 权限 | 说明 |
|------|------|
| CONFIG | 配置中断属性 |
| ENABLE | 启用/禁用中断 |
| SGI | 发送软件中断 |

权限检查：
- 如果 `interrupt_ctrl == 0`，触发异常
- 如果权限不足，触发异常

### 8.4 中断现场保存

中断现场保存在控制块的中断上下文区域（偏移 0x40-0x87）：

```
偏移    字段                说明
────    ─────               ────
0x40    irq_ctx_regs        通用寄存器保存区（ISA相关）
0x70    irq_ctx_sp          中断保存栈指针（ISA相关映射）
0x74    irq_ctx_ret         中断保存返回地址（ISA相关映射）
0x7C    irq_ctx_pc          中断保存程序计数器
0x80    irq_ctx_status      中断保存状态寄存器
```

**注意**：具体寄存器映射由ISA定义。上述偏移为示例，实际实现可根据ISA调整。

---

## 9. 安全域机制

### 9.1 安全域概述

安全域（Security Domain）提供内存加密和 DMA 访问控制能力，支持机密计算场景。

**概念区分**：
- **安全 (Security)**：访问控制、隔离、权限管理
- **机密 (Confidential)**：数据加密、密钥保护、防泄露

### 9.2 安全域创建

父域通过 `sysop secdomain` 指令管理安全域：

```
sysop secdomain, create, #flags, Rd        ; 创建安全域
sysop secdomain, destroy, #handle          ; 销毁安全域
sysop secdomain, bind, #domain_id, #handle ; 绑定域到安全域
sysop secdomain, unbind, #domain_id        ; 解绑域
sysop secdomain, get_id, #handle, Rd       ; 获取安全域的domain_id
sysop secdomain, set_encryption, #handle, #addr, #size  ; 设置加密区域
sysop secdomain, add_accessor, #handle, #accessor_id    ; 添加DMA访问者
sysop secdomain, remove_accessor, #handle, #accessor_id ; 移除访问者
sysop secdomain, force_destroy, #handle    ; 强制销毁（仅根域）
sysop secdomain, get_handle, #domain_id, Rd            ; 获取域的安全域handle
```

### 9.3 安全域属性

| 属性 | 说明 |
|------|------|
| isolated | 独立安全域，不继承父域安全域 |
| encrypted | 内存加密 |
| confidential | 机密计算域，根域无法访问 |

### 9.4 DMA 访问控制

同一安全域内的设备可以互相访问内存：

```
安全域 A:
    - domain_id: 0x0100
    - devices: [DMA引擎, 网卡]
    - 内存区域: 加密

安全域 B:
    - domain_id: 0x0200
    - devices: [GPU]
    - 内存区域: 独立加密

DMA 访问规则：
    - 安全域 A 内的 DMA引擎 可访问安全域 A 的内存
    - 安全域 A 内的 DMA引擎 不可访问安全域 B 的内存
    - 除非显式添加到 allowed_accessors
```

### 9.5 机密计算域

机密计算域具有特殊保护：

```
Domain 0 (根域)
    │
    ├─► Domain 1 (TEE Provider)
    │       │
    │       └─► Domain 2 (机密计算域)
    │               │
    │               │  security_domain: confidential
    │               │  内存加密：密钥由硬件暗号机制生成
    │               │  根域无法访问：即使配置页表也无法读取
    │
    └─► 根域无法访问 Domain 2 的内存内容
```

**实现机制**：
1. 父域创建子域时不映射子域的私有内存
2. 机密计算域的内存由内存控制器强制加密
3. 根域知道哪层是机密域，但无法获取密钥

### 9.6 安全域生命周期

**创建**：
- 子域可与父域在同一安全域内
- 也可创建新的安全域
- 由内存子系统决定

**销毁 (EXIT)**：
- 触发内存子系统的安全域销毁方法
- 彻底清零安全子域数据
- 共享内存段不清除（父域本就可访问）

**回收约束**：
- 安全域创建后，必须经过正常回收才能释放
- 父域释放时需等待安全子域退出完成
- 安全子系统故障时，只能由根域调用 `force_destroy`

---

## 10. 与现有机制的关系

### 10.1 中断处理

中断控制器通过 handle 传递给子域，父域完全控制子域的中断访问。

### 10.2 内存保护位

**原语层语义**：
```python
# 分离表达
access = {
    "readable": True,
    "writable": False,
    "executable": True,
}
```

**实现层映射**：
| 架构 | 映射 |
|------|------|
| ARM | AP[2:0], XN, PXN |
| RISC-V | R, W, X位 |
| x86 | R/W, U/S, XD |

**特殊保护机制**：用创建新域替代

```
传统方案：Ring 0不可执行用户态代码（PXN）
RPA方案：创建子域执行，天然隔离
```

### 10.3 IOMMU

IOMMU不需要理解特权域：
- IOMMU只按照配置好的页表翻译
- 页表由各域配置，逐层叠加
- 最终翻译结果与特权域无关

### 10.4 与CHERI的区别

| 维度 | RPA | CHERI |
|------|-----|-------|
| 关注点 | 特权层级模型 | 内存安全与权限 |
| 核心机制 | 递归特权域 | Capability描述 |
| 层数 | 按需配置 | 无层级概念 |
| 内存权限 | 留待后续研究 | 核心贡献 |

---

## 11. 应用案例

### 11.1 嵌套虚拟化

```
┌─────────────────────────────────────────────┐
│ Domain 0: Host Kernel                        │
│   DomainBlock @ 0x10000:                     │
│     pagetable: PT_D0                         │
│     child_block: 0x20000                     │
└─────────────────────────────────────────────┘
         ↓ descend(0x20000)
┌─────────────────────────────────────────────┐
│ Domain 1: Guest Hypervisor                   │
│   DomainBlock @ 0x20000:                     │
│     exception_vector: hypervisor_handler     │
│     ipa_regions: IPA_TABLE_D1                │
│     pagetable: PT_D1                         │
│     child_block: 0x30000                     │
└─────────────────────────────────────────────┘
         ↓ descend(0x30000)
┌─────────────────────────────────────────────┐
│ Domain 2: Guest VM                           │
│   DomainBlock @ 0x30000:                     │
│     exception_vector: guest_handler          │
│     pagetable: PT_D2                         │
│                                              │
│   发生VM exit: ascend → hypervisor处理    │
└─────────────────────────────────────────────┘
```

**优势**：无需shadow page table或nested virtualization扩展

### 11.2 系统调用

```
┌─────────────────────────────────────────────┐
│ Domain 0: Kernel                             │
│   DomainBlock @ 0x10000:                     │
│     exception_vector: syscall_handler        │
│     child_block: 0x20000                     │
└─────────────────────────────────────────────┘
         ↓ descend(0x20000) 无独立页表
┌─────────────────────────────────────────────┐
│ Domain 1: User App                           │
│   DomainBlock @ 0x20000:                     │
│     pagetable: 0（共享地址空间）             │
│     ipa_regions: 0                           │
│                                              │
│   syscall: ascend(syscall_num)             │
│   成本: ≈ 函数调用                          │
└─────────────────────────────────────────────┘
```

**优势**：共享地址空间时，系统调用成本接近函数调用

### 11.3 Try-Catch机制

```
┌─────────────────────────────────────────────┐
│ Domain 0: Main Program                       │
│   DomainBlock @ 0x10000:                     │
│     exception_vector: catch_handler          │
│     child_block: 0x20000                     │
└─────────────────────────────────────────────┘
         ↓ descend(0x20000) 共享地址空间
┌─────────────────────────────────────────────┐
│ Domain 1: Try Block                          │
│   DomainBlock @ 0x20000:                     │
│     pagetable: 0（共享）                     │
│     ctx_save_area: try_block_entry               │
│                                              │
│   正常结束: ascend({type: "complete"})    │
│   发生异常: ascend({type: "exception"})   │
└─────────────────────────────────────────────┘
```

**优势**：
- try-catch成为特权域的原生能力，无需软件模拟
- 正常结束和异常都通过 ascend 上报父域处理
- 共享地址空间时几乎零开销

### 11.4 机密计算

```
┌─────────────────────────────────────────────┐
│ Domain 0: Root of Trust (外部认证)           │
│   DomainBlock @ 0x10000:                     │
│     pagetable: PT_D0                         │
│     child_block: 0x20000                     │
│                                              │
│   无法访问 Domain 2 的内存内容               │
│   （页表不映射）                             │
└─────────────────────────────────────────────┘
         ↓ descend(0x20000)
┌─────────────────────────────────────────────┐
│ Domain 1: TEE Provider                       │
│   DomainBlock @ 0x20000:                     │
│     ipa_regions: IPA_TABLE_D2               │
│     pagetable: PT_D1                         │
│     child_block: 0x30000                     │
│                                              │
│   可以管理 Domain 2 的配置                   │
│   但无法访问 Domain 2 的内存内容             │
└─────────────────────────────────────────────┘
         ↓ descend(0x30000)
┌─────────────────────────────────────────────┐
│ Domain 2: Tenant TEE                         │
│   DomainBlock @ 0x30000:                     │
│     security_domain: 0x2000 (confidential)  │
│     pagetable: PT_D2                         │
│                                              │
│   密钥和数据无法被 Domain 0/1 访问           │
│   Domain 1 可以管理 Domain 2 的配置          │
│   （管理权与访问权分离）                     │
└─────────────────────────────────────────────┘
```

**实现机制**：
- Domain 1 配置 Domain 2 的 ipa_regions 时不映射 Domain 2 的私有内存
- Domain 0 配置 Domain 1 的 ipa_regions 时限制 Domain 1 可访问的地址范围
- 私有数据通过页表隔离 + 安全域加密保护
- `security_domain` 字段启用内存加密

---

## 12. 实现考量

### 12.1 硬件需求

最小实现：
- 控制块存储区域（SRAM或专用寄存器）
- 页表叠加支持（可选，可软件模拟）
- Tagged Memory（可选，用于保护控制块）

**DomainBlock 存储需求**：
- 基本控制块：128 字节
- 最大递归深度：受控制块存储空间限制
- IoT 设备可只实现 1-2 层

### 12.2 递归深度限制

理论无限，实际受限于：
- 控制块存储空间
- 页表叠加深度（如TLB缓存）
- 实现层配置

IoT设备可只实现一层：
```
IoT设备：
    只预留一块控制块空间
    descend时检查：无可用控制块 → 异常
    控制块不可放在用户RAM中
```

### 12.3 与现有ISA集成

RPA作为叠加层，复用现有指令集：

```
通用指令：ARM/RISC-V/x86原生执行
特殊指令：descend/ascend/exit 由RPA层处理

实现方式：
1. 解释器模式：软件模拟
2. 硬件扩展：新增指令编码
3. 协处理器：RPA层作为独立模块
```

### 12.4 ISA集成示例：Try-Catch

以下展示使用伪代码配合RPA指令实现try-catch机制：

```
// ============================================
// 伪代码实现 Try-Catch 示例
// ============================================

// Domain 0: Main Program
// DomainBlock 位于 0x10000
main:
    // 设置子域控制块
    block_addr = 0x20000           // 子域控制块地址
    ctx_save_area[block_addr + ENTRY_OFFSET] = try_block_entry   // 入口地址
    exception_vector[block_addr] = catch_handler                 // 异常处理

    // 进入try块
    DESCEND block_addr             // RPA指令

    // try块正常返回后继续执行
    goto continue

catch_handler:
    // 异常处理
    // 参数寄存器包含异常信息（由ASCEND传递）
    switch (exception_type):
        case DIV_ZERO: handle_div_zero()
        case NULL_PTR: handle_null_ptr()
        // ...

handle_div_zero:
    // 处理除零异常
    // ...
    return

// ============================================
// Domain 1: Try Block
// ============================================
try_block_entry:
    // try块代码
    // ...

    // 发生异常时
    arg_reg = exception_info
    ASCEND arg_reg                 // RPA指令，上报到catch_handler

    // 正常执行完毕，返回
    arg_reg = result
    EXIT                           // 退出子域
```

**伪指令说明**：

| 伪指令 | 功能 | 实现参考 |
|--------|------|----------|
| `DESCEND addr` | 进入子域 | 可编码为特权指令或系统调用 |
| `ASCEND arg` | 返回父域 | 可编码为特权指令或系统调用 |
| `EXIT` | 退出子域并释放 | 可编码为特权指令或系统调用 |
| `sysop op, subop, ...` | 系统操作 | ISA特定的系统操作指令 |

**ISA映射说明**：
- 入口地址偏移（ENTRY_OFFSET）由具体ISA定义，通常在ctx_save_area中
- ARM可使用SVC指令编码RPA操作
- x86可使用SYSCALL指令配合立即数
- RISC-V可使用ECALL指令

---

## 13. 待研究问题

以下问题留待后续研究：

1. **内存权限集成**：如何与CHERI等内存权限系统集成
2. **性能优化**：TLB缓存、递归深度优化、硬件加速
3. **形式化验证**：原语语义的形式化定义与安全性证明
4. **操作系统适配**：Linux内核移植、驱动模型
5. **安全分析**：侧信道攻击、配置篡改防护

---

## 14. 总结

RPA提出了一种递归特权架构，将特权等级从硬件固定转变为内存可配置。通过两个对称原语（`descend`和`ascend`）和页表叠加机制，RPA统一了虚拟化、机密计算、沙箱隔离等需求的特权管理。核心价值在于：

1. **可扩展性**：特权域数量按需配置
2. **统一性**：一套机制支持多种场景
3. **递归性**：相对视角，架构一致性
4. **实用性**：可叠加在现有ISA之上

**本文贡献**：
- 定义了递归特权模型和相对视角概念
- 设计了DomainBlock控制块结构（128字节，32字节对齐）
- 实现了IPA边界检查和页表叠加机制
- 提出了安全域机制支持机密计算
- 设计了中断控制器集成方案

---

## 附录A：术语表

| 术语 | 定义 |
|------|------|
| Domain | 特权域，编号越大特权越低 |
| DomainBlock | 域控制块，内存中的配置结构 |
| descend | 进入子域的原语（首次进入或恢复执行）|
| ascend | 返回父域的原语 |
| exit | 退出子域并释放资源的原语 |
| IPA | 中间物理地址，翻译链中的中间结果 |
| 页表叠加 | 逐层翻译地址的机制 |
| 安全域 | 提供内存加密和DMA访问控制的机制 |

---

## 附录B：设计要点提纯

参见 `DESIGN_NOTES.md`。

---

## 附录C：SYSOP 指令集

### C.1 指令格式

```
sysop <op>, <subop>, <arg1>, <arg2>
```

### C.2 操作码定义

| 操作 | 操作码 | 说明 |
|-----|-------|------|
| IRQ | 0x01 | 中断操作 |
| MEMTABLE | 0x02 | IPA 区域表操作 |
| PAGETABLE | 0x03 | 页表操作 |
| SECDOMAIN | 0x04 | 安全域操作 |

### C.3 子操作码定义

| 子操作 | 操作码 | 适用操作 |
|-------|-------|---------|
| REQUEST | 0x00 | IRQ |
| RELEASE | 0x01 | IRQ |
| ENABLE | 0x02 | IRQ |
| DISABLE | 0x03 | IRQ |
| SETVEC | 0x04 | IRQ |
| GETPENDING | 0x05 | IRQ |
| CLEAR | 0x06 | IRQ |
| SGI | 0x07 | IRQ |
| QUERY | 0x10 | MEMTABLE, PAGETABLE |
| COUNT | 0x11 | MEMTABLE, PAGETABLE |
| CREATE | 0x20 | SECDOMAIN |
| DESTROY | 0x21 | SECDOMAIN |
| BIND | 0x22 | SECDOMAIN |
| UNBIND | 0x23 | SECDOMAIN |
| GET_ID | 0x24 | SECDOMAIN |
| SET_ENCRYPTION | 0x25 | SECDOMAIN |
| ADD_ACCESSOR | 0x26 | SECDOMAIN |
| REMOVE_ACCESSOR | 0x27 | SECDOMAIN |
| FORCE_DESTROY | 0x28 | SECDOMAIN |
| GET_HANDLE | 0x29 | SECDOMAIN |

### C.4 寄存器掩码编码

用于 MEMTABLE/PAGETABLE QUERY 操作：

```
sysop memtable, query, #index, #regmask
    ; 读取 ipa_regions 表的第 index 个条目
    ; regmask: 8位位图，每位对应 R0-R7
    ; 结果分配: base→最低位寄存器, size→中间, attr→最高位
```

| regmask | 二进制 | 寄存器分配 |
|---------|-------|-----------|
| 0x07 | 0b00000111 | R0=base, R1=size, R2=attr |
| 0x0E | 0b00001110 | R1=base, R2=size, R3=attr |
| 0x38 | 0b00111000 | R3=base, R4=size, R5=attr |