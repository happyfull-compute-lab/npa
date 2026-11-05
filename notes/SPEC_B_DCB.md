# NPA 设计规格 · B 卷：DCB 与执行上下文

> 版本：v0.1（B 收敛稿，依赖 A/D 卷）  
> 范围：**内存驻留特权状态**的结构、命名、边界；执行上下文从 DCB 切出。  
> 不在本卷：多子域宽度策略（C）、pysim 迁移（最后一步）。

---

## 0. 与 A/D 的接口（已锁定）

| 已定 | 含义 |
|------|------|
| `descend(dcb)` | call/enter；恢复点在父域调用点 |
| `ascend(reason, x)` | 唯一向上原语 |
| `entry` | 首次进入子域的 PC |
| `exc` | 本域同步异常入口（0 → `ascend`） |
| 父域服务向量 | **不存在**（回到 descend 恢复点） |
| 上下文 | 架构不规定布局 → **本卷移出 DCB Spec** |

---

## 1. 切分原则

```text
┌─────────────────────────────────────────────────────────┐
│ DCB = 特权域的“配置与边界”                                │
│   父域约束、域身份、翻译入口、父子链接                      │
│   硬件在 descend/translate/权限检查 时要快路径读到          │
├─────────────────────────────────────────────────────────┤
│ Context = “当前在跑的程序”                                 │
│   GPR / PC / PSTATE / 中断帧 / ABI 杂项                   │
│   ISA 规范定义，可放栈、context 指针区、硬件 save area      │
│   与“这个域有什么特权”无关                                  │
└─────────────────────────────────────────────────────────┘
```

**判断某字段进不进 DCB Spec：**

1. 硬件做特权决策/地址翻译是否必须直接读？  
2. 父域约束或系统分配，而不是 ABI 约定？  
3. 换 ISA / 换调用约定是否应保持不变？  

三条都是 → Spec；否则 Context 或 Impdef。

---

## 2. 命名规则

1. **一名一概念**，禁止双名（`exception_vector`/`trap_vector` 等）。  
2. **小写短名**，架构字段名 ≠ 内核结构体名（不用 `ctrlblock_size`、`irq_saved_r0`、`child_block`）。  
3. **名字只描述特权语义**，不出现 `saved_sp`、`saved_lr`、寄存器名。  
4. 实现层 ABI / 内核习惯用语（syscall、hypercall、IRQ frame）**不得**倒灌进 Spec 名。

### 2.1 旧 → 新

| 旧（多来源） | 新 | 备注 |
|--------------|-----|------|
| `ctrlblock_size` / `control_block_size` | `sz` | 单位：word |
| `domain_id` / `id` | `id` | |
| `exception_vector` / `trap_vector` | `exc` | 仅本域同步异常 |
| `exception_mask`（曾否决） | **不恢复 mask** | 改为 1 位委托 `edel` |
| （父域服务向量） | **删除** | A/D：descend 恢复点 |
| `entry` / `saved_lr` 双职 | `entry` | 只表示首次 PC |
| `interrupt_ctrl` / `interrupt_controller` | `irq` | handle |
| `ipa_regions` | `ipa` | 区域表地址 |
| `pagetable` / `page_table` | `ptb` | 页表基址 |
| `child_block` | `child` | 当前子域 DCB 地址 |
| `security_group` / `security_domain` | `sec` | 安全组 handle |
| `access_id` | **删除** | DMA 用 `id` |
| `saved_sp/lr/psr` | **移出** | → Context |
| `irq_saved_*` | **移出** | → Context |
| `isa_tag` | `isa` | Impdef，非 Spec |

---

## 3. DCB 结构（Spec Field）

### 3.1 布局（32-bit word；64-bit 平台字段语义不变，宽度加倍）

```text
偏移   名     设置者   权        语义
────   ──     ──────   ──        ────
0x00   sz     parent   R         大小（word 数），校验用；最小 = Spec 长
0x04   id     system   R         域身份（DMA / 调试 / 安全绑定）
0x08   entry  parent   R         首次 descend 的 PC
0x0C   edel   parent   R         异常委托：1=子可自管，0=一律上交
0x10   exc    child    RW        自管时的同步异常入口；0=仍上交
0x14   irq    system   R         中断实例 handle；0 = 无中断能力
0x18   ipa    parent   R         地址约束表（见形态表）
0x1C   ptb    child    RW        页表基址；0 = 继承父翻译
0x20   child  parent   RW        当前子域 DCB；0 = 无
0x24   sec    system   R         安全组 handle；0 = 继承/无

Spec Field = 0x00–0x27（10 words / 40 bytes）
```

> **为何 10 words 而非 8：** `entry` 与 `exc` 岗位不同（A/D 不变量），都是控制流入口；塞回 `saved_lr` 会复活双职。保留 `rsv` 使 Spec 对齐 8 字节，Impdef 从 0x28 起。

### 3.2 所有权（不变量）

| 设置者 | 字段 |
|--------|------|
| parent | `sz`, `entry`, `edel`, `ipa`, `child` |
| child | `exc`, `ptb` |
| system | `id`, `irq`, `sec` |

- 子域 **不可写** parent/system 字段（页表隔离或硬件旁路校验）。  
- 子域 **可写** `exc`、`ptb`（且仅在 `edel=1` 时 `exc` 参与路由）。

### 3.3 字段语义（仅非显然者）

**`sz`**  
- word 计数，含 Spec + Impdef（不含 Context，Context 不在 DCB）。  
- `descend` 时硬件验证对齐与下界；上界实现定义。

**`entry`**  
- 仅 **首次** `descend` 使用；再次 `descend` = resume，从 Context 恢复，**不读** `entry`。  
- 父域在 `descend` 前写好；子域不可改（resume 路径也不改它）。

**`edel`（exception delegation）**  
- **父域**在配置/创建子域时决定：是否把「可自管的同步异常」委托给子域。  
- `0`：**未委托**——同步异常一律 `ascend(EXCEPTION)`，子域写入的 `exc` **不参与路由**。  
- `1`：**已委托**——可用 `exc` 本地处理；未装入口（`exc=0`）或处理不了仍上交。  
- 不做按异常类型的 mask（避免驾驶舱）；要细分策略就拆子域或由父域 handler 里做。

**`exc`**  
- 仅当 `edel=1` 时有效：本域同步异常入口。  
- `0`：上交父域 `ascend(EXCEPTION, info)`。  
- 非 0：本地处理；处理中可 `ascend`。

**`child`**  
- 父域持有的 **当前** 子域 DCB 地址（C 卷可放宽为多子域）。  
- 语义是“特权链接 / resume 哪个”，不是线程表。

**`ipa` / `ptb`**  
- `ptb=0` 且 `ipa=0` → **INHERIT**（共享父地址空间，翻译零叠加）。  
- `ptb≠0` → 叠加翻译；硬件检查产出落在 `ipa` 内（`ipa=0` 表示不限或由实现定，见不变量）。

**`sec`**  
- 内存加密 / DMA 访问组；细粒度策略在安全子系统，DCB 只留 handle。

### 3.4 Impdef Field（可变，0x28 起）

```text
0x28   isa    parent   R   ISA tag；0 = 继承父域
```

- 平台扩展（TLB 代数、性能计数器句柄等）一律 Impdef，**不进** Spec 名。  
- 访问：软件用 `sysop`（或实现定义），硬件快路径可直接读。

---

## 4. Context（移出 DCB）

### 4.1 架构要求（只约束语义）

1. `descend` / `ascend` / 进入 `exc` / 进入 IRQ 必须保存、恢复 **完整执行上下文**。  
2. NPA **不规定** Context 的字节布局、寄存器集合、存放位置。  
3. Context **不得**占用 Spec 字段偏移；DCB 可见内存布局以 `sz` 为界结束。

### 4.2 推荐存放（非规范，便于实现）

| 方案 | 适用 | 说明 |
|------|------|------|
| **C1** 仅栈 | 简单 ISA | 硬件/软件 push 到当前 SP |
| **C2** `ctx` 指针 | 通用 | Impdef 字段 `ctx` 指向 Context 块 |
| **C3** 硬件 save area | 高性能 | 每域 slot，由 ISA 手册定义 |

IRQ 帧属于 Context，故：**嵌套中断由 Context 链/栈解决**，DCB 不做单槽 irq 现场区。

### 4.3 清除的实现债

| 旧做法 | 问题 | 新 |
|--------|------|-----|
| `saved_lr` 既入口又返回 | 父域写子域 Context 像 ABI 后门 | `entry` 与 Context.PC 分离 |
| LR bit31 = `IRQ_RETURN_FLAG` | 架构寄存器编码软件约定 | 专用返回指令或 Context 标志，归 ISA |
| DCB+0x40 存 R0–R15 | 特权状态与中断帧打架、不能嵌套 | Context |

---

## 5. 为 A/D 服务的控制流（B 的读路径）

```text
首次 descend(dcb):
    校验 dcb.sz
    Context ← 初始（清 callee-saved 等策略归 ISA）
    PC ← dcb.entry

再次 descend(dcb):
    恢复 Context
    # 不读 entry

ascend(reason, x):
    保存 Context（含返回点 = 父域调用点）
    交父域，继续调用点之后
    # 不读任何 “服务向量”

exception (sync):
    if dcb.edel == 1 and dcb.exc ≠ 0:  进 exc
    else:                              ascend(EXCEPTION, info)

irq:
    走 dcb.irq 实例的 vector
    Context 入栈/slot
```

---

## 6. 刻意不进 Spec 的（防驾驶舱）

| 不进 Spec | 去处 | 理由 |
|-----------|------|------|
| GPR / PC / PSTATE | Context | 换 ISA 必变 |
| 中断现场 | Context | 打断点任意，应栈化 |
| 调用约定（参数寄存器） | ABI | 非特权 |
| 服务号 / syscall 号 | `ascend` 参数 | 非字段 |
| 加密区域列表 | 安全子系统 | handle 即可 |
| 多子域表 | C 卷 | 先保持 `child` 一名 |
| 中断 pending/enable | 中断实例 | 与 DCB 隔离 |

---

## 7. 硬件 / 软件影响

### 硬件

| 项 | 影响 |
|----|------|
| DCB 解码 | Spec 固定 10 word，热路径字段极少 |
| 特权切换 | 只动 domain 选择 + PT 基址 + Context，不解析寄存器帧格式 |
| INHERIT | `ptb=0,ipa=0` 跳过叠加，路径最短 |
| TLB | 可用 `id` 作 ASID 类标记，避免全局刷 |
| DMA | `id` / `sec` |
| 复杂度 | Context 策略移到 ISA，NPA 核更小 |

### 软件 / 编程

| 项 | 影响 |
|----|------|
| 建域 | 配 DCB（sz/id/entry/ipa/…）即可，不写 `saved_lr` |
| 换 ABI | 不动 Spec |
| 异常 | 读 `exc` 或处理 `ascend(EXCEPTION)` |
| 中断嵌套 | 栈 Context，不再 68B 单槽 |
| 与 A/D 配合 | VMM 循环不依赖 DCB 服务向量 |

---

## 8. 不变量（验收）

1. Spec 内字段名与 A/D 词表一致：`entry`/`exc`，无 `trap_vector`。  
2. DCB 内 **无** `saved_*`、`irq_saved_*`。  
3. `entry` 仅首次进入有效；返回点不写入 `entry`。  
4. `sz` 界定的 DCB 字节 **不含** 执行上下文。  
5. Impdef 不得出现被文档当作架构保证的字段（文档用语分开）。  
6. 旧名不得出现在新规范正文（附录对照表除外）。

---

## 9. 与论文叙事对齐

| 论文说法 | B 卷保证 |
|----------|----------|
| memory-resident **privilege** state | DCB 只含特权状态 |
| two symmetric primitives | 不靠 Context 偷渡第三类转移 |
| INHERIT ≈ function call | Context 由调用约定管理，特权路径零翻译 |
| child cannot modify own DCB | parent/system 字段只读 |

---

## 10. 开放点

| 项 | 备选 | 倾向 |
|----|------|------|
| `entry` 在 DCB vs `descend` 参数 | 参数更像 BL；DCB 更像“域自描述” | **暂定 DCB**（自描述、一次配置） |
| 64-bit 时 Spec 仍是 10×4 还是 10×8 | 语义同、宽度变 | 随 ISA |
| `child` 宽度 | C 卷 | — |
| QEMU 映射 | Context 用 guest regs vs 自定义区 | 实现阶段定 |

---

## 11. 修订记录

| 版本 | 内容 |
|------|------|
| v0.1 | Spec 10 words；命名收敛；Context 切出；删除服务向量/access_id/irq 现场区；对齐 A/D 的 entry/exc |
