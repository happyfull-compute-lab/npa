# NPA 核心理论（总卷）

> 版本：v0.1 — 理论梳理稿（先于实现）  
> 作用：**唯一权威**的概念模型。实现（pysim / QEMU / 论文）只允许与本卷对齐；冲突以本卷为准并回写修订记录。  
> 详卷：`SPEC_A_D_EVENTS_CALL.md`（事件与调用）、`SPEC_B_DCB.md`（DCB 与上下文）。  
> 本文吸收 A/D/B 结论，并闭合 C（宽度）的最小解；不再展开已否决设计。

---

## 0. 一句话

> **递归特权 = 相对域树上的降特权调用；特权状态在内存 DCB，执行状态在 ISA Context；向上只有 `ascend`。**

口号（编程模型）：**共享即信任，信任省检查。**  
架构口号（机制）：**`descend` 降特权进入；`ascend` 永远进父异常入口。**

---

## 1. 设计宗旨（优先级从高到低）

> **元原则（先于 P1–P6）：** 本卷宗旨是导航，不是教条。理论未经过实践必有漏洞；**实现与场景若与理论冲突，及时暴露并与作者讨论修订**，禁止静默迁就或死守条文。修订记入 §15。

| # | 宗旨 | 含义 |
|---|------|------|
| P1 | **最小概念闭集** | 无明显区别、或对编程无帮助，不拆概念；禁止驾驶舱 |
| P2 | **一名一义** | 双名、别名堆叠视为缺陷；传统术语只作脚注 |
| P3 | **特权与执行分离** | DCB ≠ 上下文 ≠ ABI |
| P4 | **递归视角一致** | 每域自视为 self（δ=0），不引入绝对特权级编号进架构 |
| P5 | **ISA 无关** | Spec 不绑定寄存器名、EL、Ring |
| P6 | **可执行规范优先于修辞** | 概念必须能被模型打脸；说不清的不做大 |
| P7 | **NPA 只碰 DCB** | 硬件仅读写 DCB；Context/入口/ABI 归 ISA 软件 |

传统名映射（**非架构词汇**）：

| 传统 | 架构 |
|------|------|
| syscall / hypercall / SMC / HVC | `ascend(SERVICE, …)` |
| VM enter / process switch(域级) | `descend` / 再 `descend` |
| exception return | Context 恢复 + 继续（ISA） |
| “trap to hypervisor” | `ascend` 进父异常入口 |

---

## 2. 域模型

### 2.1 域与树

- **Domain（域）**：拥有（可选）地址空间、异常入口、执行上下文的隔离单元。  
- 域之间 **树** 结构：唯一父，可有子（宽度见 §6）。  
- **相对视角**（只用 §2.3 词表：self / parent / child / δ）：
  - `δ=0`：自身
  - `δ=+1,+2,…`：子域、孙域
  - `δ=−1,−2,…`：父域、祖域
- **深度 depth**：树深度，仅受内存（DCB/Context）限制，**无硬件固定层号**。

### 2.2 根域

- 启动后第一个执行上下文；`ascend` 在根域非法。  
- 根域 `exc=0` 时异常进入实现定义的终止路径（不允许无入口）。

### 2.3 域编号与称呼（统一词表）

系统同时有 **绝对身份** 与 **树上相对位置**。两套概念必须使用不同称呼，禁止用同一套 “Domain N” 指代两样东西。

#### 2.3.1 词表（唯一合法称呼）

| 概念 | 记号 | 英文称呼 | 中文称呼 | 用途 |
|------|------|----------|----------|------|
| 绝对域标识 | `id` | domain id / Domain ID | **域 ID** / **域标识** | 安全认证、DMA、调试、预设登记 |
| 当前域 | `self` | self / current domain | **当前域** / **自身** | 控制流叙述 |
| 上级 | `parent` | parent domain | **父域** | 树关系、ascend 目标 |
| 下级 | `child` | child domain | **子域** | 树关系、descend 目标 |
| 相对层差 | `δ` | relative depth / delta | **相对层差** / **相对深度** | 递归视角、页表链、信息隔离 |
| 树根 | `root` | root domain | **根域** | 绝对树的起点 |

**相对层差写法：**

- `δ=0`：自身（self）
- `δ=+1`：直接子域；`δ=+2`：孙域；…
- `δ=−1`：直接父域；`δ=−2`：祖域；…

#### 2.3.2 禁止的称呼

| 禁止 | 原因 | 改用 |
|------|------|------|
| “Domain 0 / 1 / 2” 指根/子/孙 | 与 δ=0、id 混淆 | root / child / grandchild，或 `δ=+n` |
| “Domain −1” 指父域 | 同上 | parent domain 或 `δ=−1` |
| “第 0 层 / 第 1 层” 指绝对特权 | NPA 无绝对特权层 | 树深度 `depth` 或 `δ` |
| 用 `id` 数值大小表示高低特权 | `id` 只是身份 | 特权来自树位置 + DCB 约束 |
| 用 δ / 深度做安全身份 | 安全只认绝对锚点 | **域 ID** + 安全子系统登记 |

#### 2.3.3 标准句式（可直接进论文）

| 场景 | 写法 |
|------|------|
| 引入根 | the **root domain** boots first; its **domain id** is assigned by the system |
| 创建子域 | the **parent** allocates a DCB and **descend**s into the **child** |
| 递归一致 | from `δ=0`, the child appears at `δ=+1` and the parent at `δ=−1` |
| 页表叠加 | the translation of `δ=+1` lands on the address view of `δ=0` |
| 安全校验 | the security subsystem checks the domain’s **absolute domain id** against its **preset security-domain registry** |
| 绝对 vs 相对 | **domain id** is global and stable; **δ** is meaningful only relative to `self` |

#### 2.3.4 与安全登记的关系

- **域 ID**：绝对、全局、可校验；安全域预设表以它为键（或以可度量身份槽绑定它）。
- **δ / parent / child**：运行时结构；可随调度/树操作变化，**不能**当身份。
- 一句话：**身份看 id，关系看 parent/child，递归看 δ。**

**例（五层 JIT）：**

```text
root domain (id=0)
  └─ hyp (id=1)     relative to root: δ=+1
       └─ gk (id=2) relative to hyp: δ=+1; to root: δ=+2
            └─ gu (id=3)
                 └─ jit (id=4)  relative to gu: δ=+1

inside jit:
  self   = jit (δ=0)
  parent = gu  (δ=−1)
  parent.parent = gk (δ=−2)
```

特权来自 **树上位置 + DCB 约束**，不来自 `id` 数值大小；EL 仅可作场景类比脚注。

### 2.4 域生命周期（对齐进程 create/exit）

DCB 在 **父域地址空间** 由父创建；子退出后 **回收 DCB 是父的责任**（同 wait/reap）。

```text
parent                          child
  |                               |
  |  alloc DCB + configure        |   // create（含 entry/edel/ipa/…）
  |  descend(dcb)  ─────────────► |   // first entry: PC ← entry
  |  (suspended at call site)     |
  |                               |  ... run ...
  |  ◄─────────── ascend(SERVICE) |   // 可多次，resume = 再 descend
  |  handle; descend(dcb)  ─────► |
  |                               |
  |  ◄────────────── ascend(EXIT) |   // 子声明结束，不可再 resume
  |  reap: 清 child 链接、回收/重写 DCB  // parent duty
```

| 阶段 | 谁 | 架构语义 |
|------|----|----------|
| **create** | 父 | 在父可见内存写好 DCB；`id` 由系统唯一分配 |
| **run** | 子 | `descend` 首进 `entry`；`ascend` 后可再 `descend` resume |
| **exit** | 子 | `ascend(EXIT)`：本域 **终止**，Context 不得再 resume |
| **reap** | 父 | 清理 `child` 链接（若仍指向自己）、**回收或重初始化 DCB**；未 reap 前为僵尸 |

**硬性约定：**

1. `EXIT` 后硬件 **禁止** 再按 resume 进入该域（防止僵尸上下文）。  
2. **销毁/复用 DCB 内存是父软件责任**（free / memset / 重配），架构不隐式释放父内存。  
3. 复用同一 DCB 地址 = **新域**；必须重新 create（写 `entry` 等），不得沿用旧 Context。  
4. 与 `RESULT` 区别：`RESULT` 表示“一次调用返回”，可 resume；`EXIT` 表示“域结束”。

**失效位 / lifecycle（fail-fast，自动挡）**

每个域有 **lifecycle**（硬件域状态，2 bit 即可；Impdef，子不可写）：

| 值 | 含义 | `descend` | 变迁 |
|----|------|-----------|------|
| **FREE** | 未用或已 reap | **first**：`PC←entry` | create/reap |
| **LIVE** | 运行中，有 Context | **resume**：`PC←Context` | 首次 descend |
| **TERM** | 已 EXIT，未 reap | **拒绝** | `ascend(EXIT)` |

```text
descend:  FREE → first → LIVE
          LIVE → resume
          TERM → fault（父 reap → FREE）
```

- `ascend(EXIT)` 置 **TERM**（sticky），硬件清父 `child`（若仍指向自己）。  
- 对 TERM 再 `descend` **必须失败**；软件不必判断 first/resume（I18）。  
- 父 **reap**：回收/重写 DCB → **FREE**；同址再用 = 新域。  
- 审计：reap 前可读 lifecycle/DCB/`reason,x`（见 2.4）；TERM 只禁执行，不抹痕迹。  
- **不**把 lifecycle 塞进返回地址 bit（避免 `IRQ_RETURN_FLAG` 类污染）。

**类比：** `descend`≈创建并进入，`ascend(EXIT)`≈`exit`，父 reap≈`wait`+释放；**TERM≈僵尸/不可再调度**，**FREE≈task 已释放**。

### 2.5 DCB 与 task_info 的边界（定论）

| | **DCB** | **task_info** |
|--|---------|----------------|
| 性质 | **架构 / 硬件状态** | **内核软件数据结构** |
| 何时必须动 | 要影响硬件行为（descend、翻译、权限、EXIT…） | 调度、资源、审计、进程语义 |
| 字段来源 | NPA Spec（+ Impdef） | OS 自定 |
| 谁维护 | 父创建/reap；硬件改 lifecycle/Context 相关 | 内核 |

**原则：**

1. **DCB 不 cover task_info**：不把 pid、runqueue、文件表、信号等塞进 Spec。  
2. **lifecycle 不是 task state 镜像**：它是硬件为了 first/resume/TERM 与编程方便的 **冗余/自服务状态**；OS 不必与 task state 做双写一致性维护。  
3. **怎么摆是 OS 的选择**：内核可把 DCB 内嵌在 `task_struct`、用指针、或完全分开——架构只要求「影响硬件前 DCB 写对」。  
4. 成对更新（create/exit）是 **软件工程问题**，不是 Spec 字段问题；可用 helper 单点写入。  
5. 安全/调试若要「像 pid 的锚」，用 **绝对域 ID**（§2.3 / I16），不是 task 字段。

### 2.6 最小化软件触碰 DCB（编程模型定论）

**目标：** 调度 / 调用路径上 **不要求软件大规模改写 DCB**；切换 ≈ **选一个 DCB 对象**。

| 时机 | 软件对 DCB | 说明 |
|------|------------|------|
| **create / 重配** | 允许集中写一次 | `entry`/`edel`/`ipa`/`ptb`… |
| **调度 / 切换 / 调用** | **只 `descend(dcb)`**（换对象） | 不改字段、不重写 Context |
| **resume** | 同上 | 硬件管 first/resume（lifecycle） |
| **exit → reap** | 一次回收/重配 | 之后当新域再 create |

**允许（借用，非义务）：**

- 软件 **可以** 读域 ID、lifecycle 等硬件位做快捷映射/调试（例如 `task->dcb`、用 `id` 当哈希键）。  
- 软件 **可以** 自建 id↔task 映射表；架构不禁止也不强制。  
- Impdef 区可放平台专用，仍不应要求热路径每条指令都写。

**禁止（热路径）：**

- 每次 syscall / schedule / yield 批量改 `ipa`/`ptb`/`entry`/…  
- 让软件维护 first/resume 或写返回点  
- 用 DCB 当通用 task_struct 热字段仓  

**一句话：** *DCB 是特权配置与硬件锚点，不是调度时的数据热更新区；软件最多 create 时配置，切换只递指针。*

---

## 3. 原语闭集

```text
descend(dcb, entry)    进入子域（entry=首次 PC，按 ISA 传参）
ascend(reason, x)      进入父异常入口（唯一向上原语）
```

| 不设 | 原因 |
|------|------|
| escalate / return_to_parent / return_to_child | 服务 = ascend + 父再 descend |
| RETURN | resume 即再 descend |
| exit（独立原语） | `ascend(EXIT)` 或 EXIT reason |
| descend_n | 选哪个子域是调用约定/参数，非架构第三原语 |
| syscall / hypercall 指令 | reason + 服务号 |
| 硬件自动回调用点 | 续体归软件；handler 按 reason 恢复 |
| LR 兼 entry | saved_lr 双职 |

### 3.1 `descend` 语义

1. 校验 `dcb.sz`（及实现定义完整性）。  
2. **首次**：`PC ←` 软件传入的 `entry` 参数（非 DCB 字段）。  
3. **再次**（resume）：恢复子域 Context，**不读** `entry`。  
4. 父域**不**被硬件自动挂到「descend+4」；函数式续体由父软件在 descend 前自行保存。  
5. 切换地址空间：按 `ptb`/`ipa`（§5）。

**first/resume 对软件透明（定论）：**

- 软件永远只调用 **`descend(dcb)`**，不区分首次/恢复，不传 `entry` 参数。  
- 首次入口由软件按 **ISA PCS** 传入（RISC-V：`a0`=dcb，`a1`=entry）。  
- **禁止**用 LR/返回地址兼作 `entry`（避免 `saved_lr` 双职）。  
- first 判定 = lifecycle（FREE/LIVE/TERM），对 API 不可见。

### 3.2 `ascend` 语义（异常入口模型）

1. 保存子域 Context（resume 点 = `ascend` 之后）。  
2. 切换回父域地址空间。  
3. **`PC ←` 父域异常入口**（handler），**不是** descend 调用点。  
4. `reason, x` 依 ABI 传给 handler。  
5. 子域是否存活由父域策略决定（`EXIT` / 丢弃 Context / 再 descend）。

**调用点返回 = 软件约定：**

```text
父软件（若要函数式）:
  saved = save_continuation()    # 记下「descend 之后」
  descend(dcb)

handler(reason, x):
  RESULT  → restore(saved)      # 软件恢复调用点续体
  SERVICE → ... ; descend(dcb)
  EXIT    → reap ; 调度
```

### 3.3 reason 闭集

| reason | 含义 |
|--------|------|
| `SERVICE` | 请求服务（含全部传统“陷入父域”） |
| `RESULT` | 正常结束，带返回值 |
| `EXCEPTION` | 同步异常上报（含软件判定的 fault） |
| `EXIT` | 结束，不再 resume |

服务号、错误码、参数 → **`x` 与 ABI**，不扩 reason。

### 3.4 控制流形状

```text
父:   descend(D)              # call
子:   … 
子:   ascend(SERVICE, req)    # 回到调用点
父:   … 服务 …
父:   descend(D)              # resume
子:   …
子:   ascend(RESULT, ret)
父:   … 调用点之后 …
```

**对称性**：descend/ascend 成对构成 call/return；树上递归无新原语。

---

## 4. 状态模型：DCB vs Context

### 4.1 两类状态

| | **DCB** | **Context** |
|--|---------|-------------|
| 是什么 | 特权域配置与边界 | 当前执行的程序状态 |
| 住在哪 | 内存，父域可见/可写策略见下 | ISA 定义（栈 / slot / 硬件区） |
| 硬件何时读 | descend、翻译、权限、DMA | 每次切换/中断/异常 |
| 换 ISA | 不变 | 必变 |

### 4.2 DCB Spec Field（唯一权威布局）

```text
off   name   owner    meaning
0x00  sz     parent   size in words（校验）
0x04  id     system   domain identity
0x08  edel   parent   exception delegation（1=子可自管，0=一律上交）
0x0C  exc    child    sync exception entry（edel=1 且 exc≠0 → 本地）
0x10  irq    system   interrupt handle（0 → 无）
0x14  ipa    parent   address constraint table（形态见 §5）
0x18  ptb    child    page-table base（0 → 继承）
0x1C  child  parent   current child DCB（0 → none）
0x20  sec    system   security group handle
0x24  rsv    —        reserved (Spec 对齐)

Spec = 10 words (40B)；Impdef 从 0x28 起（如 isa）
```

**字段级权限**：parent/system 字段子域不可写；`exc`/`ptb` 子域可写（`exc` 仅在 `edel=1` 时路由）。

### 4.3 Context（架构只约束动词）

必须保存/恢复完整执行上下文的事件：`descend`、`ascend`、进入 `exc`、进入 IRQ。  
**禁止**在 DCB Spec 内放 `saved_*`、`irq_saved_*`、ABI 参数区。

### 4.4 `entry` 与返回点

- `entry`：只表达“首次从哪跑”。  
- 返回点：硬件随 Context 保存，**禁止**写入 `entry` 或借用 `saved_lr`。

---

## 5. 内存模型

### 5.0 地址视图三种形态（`ptb` / `ipa`）

| `ptb` | `ipa` | 翻译 | 约束 `ipa` 检查对象 | 用途 |
|-------|-------|------|---------------------|------|
| 0 | 0 | 与父相同 | 无（同父权限） | try-catch、信任子域 |
| 0 | ≠0 | 与父相同 | **VA**（权限覆盖） | MCU 沙箱、JIT 共页表 |
| ≠0 | * | 子 VA→父视图，再链到 PA | **父视图地址（IPA）** | 用户 / 客户机 |

不变量：`ptb=0` 不得改写父翻译，只可收紧权限。

### 5.1 叠加翻译

```text
VA_{N+1} --PT_{N+1}--> IPA/PA_N --PT_N--> … --> 物理
```

- `ptb`：本域 VA→（父域视角地址）。  
- `ipa`：父域施加的 **边界**；越界 = 同步异常（→ `exc` 或上交）。

### 5.2 INHERIT 与权限覆盖

```text
ptb == 0 且 ipa == 0  → 纯继承（同父翻译 + 同父权限）
ptb == 0 且 ipa != 0  → 继承翻译 + ipa 权限表（查 VA）
⇒ 均无额外叠加翻译；descend/ascend ≈ call/return
```

### 5.3 隔离（安全边界）

| 边界 | 机制 |
|------|------|
| 子私有内存 | 父不映射；或子 `ptb` 不映射 |
| DCB 配置 | 子不可写 parent/system 字段 |
| 子改自身翻译 | 仅 `ptb`/`exc`；不能放宽 `ipa` |
| DMA | `id`/`sec` |
| 层级信息 | 向上只传递 reason/x 与实现定义的必要 info；不默认穿透孙域身份 |

---

## 6. 宽度与调度（C：最小闭合）

**决策（C1）**：

- `child` = **当前** 子域（单活跃链接）。  
- 多线程/多 guest = **父域软件** 选择对哪个 `dcb` `descend`；架构不提供 `descend_n` 或子域表。  
- 切换子域：对 A `ascend`/未运行状态后，对 B `descend`；Context 仍各自 ISA 保存。

**不做什么（P1）**：

- 不在 Spec 增加 child 数组、调度队列、优先级。  
- 论文“宽度”表述应指 **树的广度（多父/多子树）** 或 **软件复用单 child 链接**，不承诺硬件多活跃子于单父（除非未来 C2 另立卷）。

**给编程的形状**：

```text
for d in runqueue:
    descend(d.dcb)     # call/resume
    # 每次回来在调用点
```

---

## 7. 事件模型（总表）

| 类型 | 触发 | 入口 | 向上？ |
|------|------|------|--------|
| Ascend | 软件显式 | 父调用点 | 是（唯一） |
| Exception | 同步 | 见 `edel`/`exc` 路由 | 未委托或 `exc=0` 则上交 |
| IRQ | 异步 | `irq` 实例 vector | 实现可注入；不与 ascend 混名 |

**Fault**：exception 的软件分类结果 → `ascend`；非第三硬件入口。

### 7.1 同步异常路由（父域委托，非创建初值堆）

父域在配置子域时用 **`edel`（1 bit）** 决定是否把可自管异常委托给子域（对齐 RISC-V `medeleg` 思想，但不按类型展开 mask）：

```text
if edel == 1 and exc ≠ 0:  本地 exc
else:                      ascend(EXCEPTION, info)
```

| `edel` | `exc` | 行为 | 典型 |
|--------|-------|------|------|
| 0 | * | 一律上交（子写 `exc` 不参与路由） | 隔离 try、严格沙箱、审计 |
| 1 | 0 | 上交 | 已授权但未装 handler |
| 1 | ≠0 | 本地；处理不了可再 `ascend` | Guest 页错、语言运行时 |

**安全不变**：无论 `edel`，越权访问只以失败告终，不得静默成功；委托的是“谁收拾残局”，不是“能否越权”。

**优先级（实现建议，非 Spec 强制）**：同步异常 > ascend 响应 > IRQ；Spec 只要求“IRQ 不得破坏 ascend/exception 的 Context 完整性”。

---

## 8. 安全与信任

- 根信任：外部度量/启动链建立；NPA 不发明远程证明。  
- 域间：隔离靠翻译 + DCB 权限 + 可选 `sec`。  
- **不承诺**：侧信道、Spectre 类、DMA 旁路的完整解法（实现用 SMMU/`sec` 缓解）。

### 8.1 绝对 `id` 与安全域登记（预设分配）

安全子系统 **不是** 在 `descend` 时随便发一个自增数就当安全身份。它维护 **预设的安全域分配表**（authorized security-domain registry）：

```text
Security Subsystem
  preset:  { id → role / sec_handle / policy, … }   // 启动前或度量后写入
  bind(id, sec):  id ∈ preset 且策略允许 → 成功；否则拒绝
```

| 步骤 | 谁 | 动作 |
|------|-----|------|
| 1. 预设 | 安全子系统 / 启动链 | 写入允许作为安全域的 **绝对 `id` 集合**（或可度量身份槽） |
| 2. 域出现 | 系统 | 分配或写入 DCB `id`（普通域可池分配；安全域应落在预设槽） |
| 3. 成为安全域 | 父域或系统请求 `bind` | 安全子系统 **校验 `id` 是否在预设安全域定义中** |
| 4. 通过 | — | 写入 `sec`，内存加密/DMA 规则生效 |
| 5. 失败 | — | 不得写入有效 `sec`，不得享有安全域属性 |

**要点：**

1. **精确绝对 `id`** 是身份验证锚点；δ、parent/child、树深度 **不能** 代替身份。  
2. “变成安全域”= **登记校验成功并绑定 `sec`**，不是子域自封。  
3. 普通域 `id` 可用于 DMA/调试，但 **不在** 安全预设表内则 **永远不是** 安全域。  
4. 校验在 **bind / 进入安全执行** 路径完成；失败即拒绝，无静默降级。

### 8.2 与 `sec` / DCB 的分工

| 符号 | 角色 |
|------|------|
| `id` | 绝对身份；安全校验的主键 |
| `sec` | 安全组/安全域 handle；bind 成功后的结果 |
| 安全子系统 preset | 权威名单与策略 |
| DCB 约束 `ipa`/`ptb` | 运行时隔离，不代替身份 |

---

## 9. 与场景的对应（证明闭集够用）

| 场景 | 结构 | 用法 |
|------|------|------|
| 系统调用 | D0 内核, D1 用户 | `ascend(SERVICE, nr)` |
| 嵌套虚拟化 | Host→VMM→Guest→App | 链上多次 descend/ascend |
| 机密计算 | 父管理 DCB，不映射子私有 | `ipa`/`ptb`/`sec` |
| JIT 沙箱 | 短命子域 | `descend`；`ascend(EXIT)` |
| try-catch（隔离型） | try 为子域，`edel=0` | 异常必达父 catch |
| try-catch（同域） | 不建子域 | 本域软件异常 |
| Guest 页错 | `edel=1`，子域 `exc` | 处理完继续，父无感 |

---

## 10. 刻意不做清单（总）

1. 多向上原语 / 多服务向量表  
2. 绝对特权级号（Ring/EL）进入 Spec  
3. Context 固定寄存器表进入 DCB  
4. `descend_n`、exit 第三原语、escalate  
5. DCB 作 IRQ 帧仓库  
6. 为“传统架构用户”在 Spec 里保留 syscall 指令名（只在文档脚注对照）  
7. 在概念未闭合前大改 QEMU/KVM 或 RTL  

---

## 11. 不变量（实现验收 / 打脸用）

**I1** 指令级向上控制转移仅有 `ascend`。  
**I2** `ascend` 后控制权进入 **父异常入口**；回到 descend 调用点是软件 handler 策略，非硬件保证。  
**I3** 返回点与首次入口均由 ISA/软件传递；不进 DCB Spec。  
**I4** DCB Spec 无 `saved_*` / `irq_saved_*` / ABI 专有字段。  
**I5** `exc==0` 时同步异常必达父域（或根终止），无静默丢失。  
**I6** INHERIT（`ptb==0`）路径无地址叠加。  
**I7** 子域不能写 `sz/id/entry/edel/ipa/child/sec`（除实现证明旁路）。  
**I8** reason 枚举外的语义不得通过“新原语”偷渡，只能进 `x` 或文档。  
**I9** 同一概念在 Spec/实现/论文中仅一名（对照表除外）。  
**I10** 模型实现若与 I1–I9 冲突，改实现或改理论并记修订，禁止静默偏离。  
**I11** `ptb=0` 不得改写父翻译，仅可由 `ipa` 收紧权限。  
**I12** 纯 INHERIT（`ptb=0,ipa=0`）权限不得宽于父域。  
**I13** `edel=0` 时同步异常不得在子域本地入口结束（必须 `ascend`）。  
**I14** 越权访问在任何 `edel` 下均不得完成；委托不等于放权。  
**I15** 文档与实现统一使用 §2.3 词表：身份=域 ID，关系=parent/child/self，递归=δ；禁止 “Domain N” 与 root=Domain 0。  
**I16** 安全域绑定（写入有效 `sec` / 获安全属性）必须通过安全子系统对 **绝对域 ID** 的预设登记校验；失败不得享有安全域属性。  
**I17** `ascend(EXIT)` → lifecycle=TERM；TERM 不可 resume，reap 前 `descend` 必须失败。  
**I18** `descend(dcb)` 唯一形态；`entry` 不兼返回点；first/resume 由 lifecycle（FREE/LIVE）决定，软件无分支。  
**I19** Spec 不含 task_info 字段；lifecycle 服务硬件判定与编程便利，不要求 OS 双写 task state。  
**I20** 热路径（descend/ascend/调度）不要求软件改写 DCB 字段；切换 = 选择 DCB 对象 + `descend(dcb)`。

---

## 12. 概念依赖图

```text
相对域树
    │
    ├─ 原语: descend/ascend  (call/return)
    │         │
    │         ├─ reason: SERVICE/RESULT/EXCEPTION/EXIT
    │         └─ x: ABI 参数
    │
    ├─ DCB Spec: sz,id,entry,exc,irq,ipa,ptb,child,sec
    │         │
    │         └─ Impdef: isa, ctx?, 平台扩展
    │
    ├─ Context: ISA（GPR/PC/PSTATE/IRQ 帧）
    │
    ├─ 内存: ptb 叠加, ipa 边界, INHERIT
    │
    └─ 安全: 只读约束 + sec + 不承诺侧信道
```

---

## 13. 理论阶段待决（实现前可再收）

| ID | 问题 | 倾向 | 是否阻塞理论 |
|----|------|------|----------------|
| T1 | `entry` 在 DCB vs `descend` 参数 | **DCB**（定论，见 §3.1 / I18） | 否（已定） |
| T2 | 64-bit 下 word=4 还是 8 | 跟 ISA | 否 |
| T3 | resume 判定（child 空 vs Context valid） | Context valid 位归 ISA | 否 |
| T4 | `ascend` 在根的硬件行为 | 实现定义 trap | 否 |
| T5 | C2 多活跃子是否将来要做 | 先 C1 | 否 |
| T6 | `edel` 是否要按异常类型细分 | 否（P1），需要时拆子域 | 否 |

---

## 14. 实现验证计划（理论之后）

**目的**：用“会跑的思想”发现 I1–I10 与场景表的漏洞，**不是**复刻旧 107 测试。

1. **最小内核**：域树 + descend/ascend + Context 三件套 + DCB 校验。  
2. **场景刺探**（每个场景一条路径）：syscall 形、服务-resume、exc 上交、Guest 页错本地消化、INHERIT、越界 `ipa`。  
3. **对照旧 pysim**：只记录“旧模型哪里误导设计”，不迁移无关测试。  
4. **回写**：任何不变量失败 → 开修订记录，更新总卷，再改模型。

旧 pysim 保留为 **历史证据**（证明问题从何而来），不作为目标架构规格。

---

## 15. 修订记录

| 版本 | 内容 |
|------|------|
| v0.1 | 理论总卷：P1–P6；原语闭集；DCB/Context；C1 宽度；I1–I10；与场景对应；实现验证计划 |
| v0.2 | 确认三形态地址视图；`edel` 委托；I11–I14；场景表更新 |
| v0.2.1 | 统一 id / parent-child / δ 表示法；I15 |
| v0.2.2 | 安全域预设分配 + bind 校验绝对 id；I16 |
| v0.2.3 | §2.3 称呼词表（域 ID / parent-child / δ）；禁止 Domain N |
| v0.3 | §2.4 生命周期 + lifecycle FREE/LIVE/TERM（I17）；§3.1 first/resume 透明与 entry/返回点定论 I18 |
| v0.3.1 | §2.5 DCB vs task_info 边界；lifecycle 非 task 镜像；I19 |
| v0.3.2 | §2.6 最小化软件触碰 DCB；切换只换对象；I20 |
| v0.3.3 | 元原则：宗旨为实现让路；发现理论漏洞及时讨论修订 |
