# NPA 设计规格 · A/D 卷：事件模型与调用语义

> 版本：v0.1（A+D 收敛稿）  
> 范围：只定 **事件如何向上走**、**descend/ascend 如何配对**。  
> 不在本卷：DCB 完整布局（B）、多子域宽度（C）——见文末开放点。

---

## 0. 设计宗旨（约束一切取舍）

1. **一个概念只留一个名字**；syscall / hypercall / trap / 服务请求等，在架构层都是 **`ascend` 的 reason**，不是独立原语。
2. **非有明显区别、或对编程者有直接帮助，不拆概念**。拆出来的每一项，必须能回答：程序员写 handler 时为什么要区分它？
3. 文档不许变成驾驶舱：字段与原语保持最小闭集。

因此：

| 传统叫法 | NPA 架构地位 |
|----------|----------------|
| syscall / SVC / HVC / SMC / hypercall | `ascend(reason=SERVICE)` |
| 异常上报 / 故障上报 | `ascend(reason=EXCEPTION)` 或本地 `exc` |
| 进程退出 / vCPU 停 | `ascend(reason=EXIT)` + release |
| 返回值给父域 | 同上，reason + 参数 |

---

## 1. 原语闭集（D：调用语义）

**只要两个原语**（`exit` 不是第三原语，是 `ascend` 的 reason/形态）：

```text
descend(dcb)        进入子域（call / enter）
ascend(reason, x)   进入父异常入口（唯一向上原语）
```

### 1.1 `descend(dcb)` — 调用，不是“发射后不管”

- 父域执行 `descend` 后 **挂起在该指令之后**（下一条逻辑指令 = 恢复点）。
- 子域从 `dcb.entry` 开始执行（首次）；或从子域上次 `ascend` 保存点恢复（再次 `descend` = resume）。
- **同一语义覆盖**：函数调用、try 入口、vCPU run、JIT sandbox enter。

### 1.2 `ascend(reason, x)` — 返回 + 原因

- 子域保存执行上下文，控制权回到 **父域 `descend` 的恢复点**。
- `reason` 告诉父域为什么回来；`x` 为参数/返回值（约定由 ABI 定，架构不钉寄存器）。
- **同一语义覆盖**：syscall 返回、hypercall、异常上报、正常结束、放弃执行。

### 1.3 服务模式 = ascend + 再 descend（不引入 escalate）

```text
父:  descend(dcb)          # call 子域
子:  ascend(SERVICE, req)   # 请求服务
父:  ...处理...             # 回到 descend 后
父:  descend(dcb)          # resume 子域
子:  ...继续...
子:  ascend(RESULT, ret)    # 正常结束
父:  ...回到 descend 后...
```

- 不需要 `escalate` / `return_to_parent` / `return_to_child` 并行原语。
- “请求后留在子域继续跑”= 父域处理完 **再次 descend**；这是控制流，不是新指令。

### 1.4 结束语义

| 需求 | 写法 |
|------|------|
| 正常做完，父域可回收 | `ascend(EXIT)`；父域不再 resume |
| 资源释放由父域决定 | 始终 `ascend(reason)`，是否销毁子域是父域策略 |
| 架构层可选便利 | `exit` ≡ `ascend(EXIT)` 的别名，**非独立概念** |

> 决策：**不设独立 `exit` 原语**。若汇编助记符需要，仅为 `ascend EXIT` 的别名。

### 1.5 与旧语义对照

| 旧 | 新 |
|----|----|
| `descend` 后父域丢控制权，只有 trap_vector | `descend` 降特权进入；续体若需要则软件存 |
| `ascend` → 父 trap_vector | `ascend` → **父异常入口**（统一） |
| `RETURN` = 又一次 descend | 不需要；resume 就是再 `descend` |
| `escalate` vs `return_to_parent` | 同一 `ascend`，reason 不同 |
| `return_to_child` | 不需要；父域再 `descend` |

---

## 2. 事件模型（A：什么必须分开）

### 2.1 仍然分开的三样（对程序员有明显区别）

| 类型 | 谁触发 | 进入哪里 | 为何必须分开 |
|------|--------|----------|--------------|
| **IRQ** | 外部异步 | 中断实例的 vector（不进 DCB 特权字段） | 任意指令点打断，上下文与优先级规则不同 |
| **Exception** | 本域同步异常（页错/非法指令/权限） | 本域 `exc`；`exc=0` 则 `ascend(…)` | “我自己的运行时要先看到”（Guest OS 页错） |
| **Ascend** | 本域软件显式 | **父域** descend 恢复点 | “我主动找父域”（服务/退出/上报） |

**IRQ 不并进 ascend**：异步性是明显区别，硬合成会逼出驾驶舱（I-bit、嵌套、抢占规则渗进服务调用）。

### 2.2 不再分开的概念（统称 ascend reason）

架构 **不** 为下列各设入口或原语：

- syscall / hypercall / smc  
- 服务请求 vs 结果通知  
- “异常上报”与“服务请求”若都是**主动走到父域**，只是 reason 不同  

### 2.3 Exception 与 Fault

```text
Exception = 同步异常事件
  ├── 可处理：本域 exc 处理后返回（软件）
  └── 不可恢复（Fault）：软件判定后 ascend(FAULT/EXIT)
```

- **Fault 不是第三硬件入口**，是 exception 的软件分类结果。
- 硬件只保证：exception 若 `exc=0` 或处理时再故障，则 `ascend` 到父域。

### 2.4 reason 闭集（小枚举，不是开放协议）

```text
SERVICE    0x00   请求父域服务（含传统 syscall/hypercall）
RESULT     0x01   正常结束，带返回值（父域可回收）
EXCEPTION  0x02   同步异常上报（含 fault 时的上报）
EXIT       0x03   结束且不再 resume
```

- 具体服务号放在 `x`（参数），**不**扩展 reason 位宽去编码一切。
- 实现可加少量 reason，但文档只宣传：**向上只有 ascend**。

---

## 3. 入口字段（为 A/D 服务的最小集）

每个域在递归视角下都需要两件“自己的事”：

| 字段 | 谁用 | 含义 | 为 0 |
|------|------|------|------|
| `entry` | 父域写 | 首次 descend 的 PC | 非法（首次必须有入口） |
| `exc`   | 子域写 | 本域同步异常入口 | 异常上交父域 `ascend(EXCEPTION)` |
| `trap`  | 父域用 / 系统 | 本域作为 **父** 时…（见下） | |

**最小化结论（避免驾驶舱）**：

- **不设** `svc_entry` / `hypercall_vector` / `syscall_vector`。
- 父域接子域 `ascend`：**统一进父异常入口**；handler 内可按 reason 软件恢复调用点续体。
- 因此 DCB **不需要** “父域服务向量” 字段；与 hypercall 向量表彻底告别。
- 仅保留两个与控制流相关的入口：`entry`（进子域）、`exc`（本域异常）。  
  二者岗位不同（“从哪开始跑” vs “出错找谁”），属明显区别，故保留。

```text
descend 首次:   PC ← dcb.entry
descend 再入:   PC ← 子域保存点
ascend:         PC ← 父异常入口
exception:      PC ← dcb.exc   （0 → ascend(EXCEPTION)）
irq:            PC ← irq.vector（实例内，非 DCB Spec）
```

### 3.1 上下文（与 B 卷的接口，此处只定语义）

- `descend` / `ascend` / `exception` / `irq` **都必须保存恢复完整执行上下文**。
- **架构不规定**上下文存在 DCB 哪个偏移、含哪些寄存器 → 归 ISA/ABI（B 卷切开）。
- 首次进入：`entry` 显式给出，**禁止**再借用 `saved_lr` 当入口（消除双职）。

---

## 4. 端到端示例（证明不拆概念也够用）

### 4.1 传统 syscall（用户 → 内核）

```text
D0 内核   D1 用户程序
          entry = user_main
descend(D1)
          ...
          ascend(SERVICE, SYS_write, args)
# 回到内核 descend 之后
          内核处理 write
descend(D1)          # resume
          ...
          ascend(RESULT, ret)
```

文档可以写“相当于 syscall”，但 **架构指令表里只有 ascend**。

### 4.2 Hypercall / 虚拟化

与 4.1 同构，D0=host，D1=guest，reason=SERVICE，服务号=hypercall 号。  
**零新原语。**

### 4.3 Try-catch

```text
D0 try 的父   D1 try 块
descend(D1)
              ...异常...
              # exc=0 → ascend(EXCEPTION, info)
# 回到 D0，catch 处理
```

### 4.4 Guest 自己的页错（本域消化）

```text
D1.exc = guest_pgfault
exception → guest_pgfault 处理 → 返回 D1
# 不离开 D1，父域无感
```

### 4.5 无法恢复的故障

```text
exception → exc 发现不可恢复 → ascend(FAULT/EXIT)
# 或 exc=0 直接 ascend(EXCEPTION)
```

---

## 5. 刻意不拆的清单（防驾驶舱）

| 不拆 | 理由 |
|------|------|
| syscall / hypercall / smc / svc | 都是 ascend(SERVICE) + 服务号 |
| escalate / return_to_parent | 都是 ascend；resume = 再 descend |
| return_to_child / RETURN | 再 descend 即可 |
| exit 作为第三原语 | ascend(EXIT) |
| trap_vector vs exception_vector 双表 | 仅 `exc` + ascend 恢复点 |
| fault 硬件第三入口 | 软件分类后走 ascend |
| DCB 里 irq 全寄存器帧 | 属执行上下文（B 卷），非事件路由 |

---

## 6. 硬件 / 软件影响（A/D）

### 硬件

| 项 | 影响 |
|----|------|
| 控制转移 | `descend`/`ascend` 对称，保存/恢复父 PC 到 **调用点**，不是向量表 |
| 向量 | 仅 `exc` + IRQ 向量；无 hypercall 表 |
| 热路径 | INHERIT 下 ≈ call/return；与“5–10 cycle”叙事一致 |
| 原因传递 | `reason`/`x` 走 ABI 寄存器或 DCB Impdef，架构不锁死 |

### 软件 / OS

| 项 | 影响 |
|----|------|
| VMM | `while (ascend=SERVICE) { handle; descend(); }` |
| libc syscall | 一次 `ascend(SERVICE)` |
| 异常 | 本域 `exc` 或上交；与服务路径可分离（reason） |
| 调度 | call 语义下可把子域当可 suspend 的调用（宽度仍受 `child` 约束，C 卷） |

---

## 7. 不变量（验收用）

1. 架构指令级向上控制转移 **只有** `ascend`。  
2. `descend` 恢复点唯一；不存在“进 trap_vector 而不回调用点”的第二条父域路径（IRQ 除外）。  
3. `entry` 不承担返回地址职责；返回点由硬件保存。  
4. reason 为小枚举；具体服务放参数。  
5. 任何新概念必须能证明：在不区分它的情况下，程序员会写错或写不出来。

---

## 8. 开放点（留给 B/C，不在此决策）

| 卷 | 问题 |
|----|------|
| B | 上下文块放哪、DCB Spec 字段命名与尺寸、`isa_tag` |
| C | `child` 单指针是否满足多线程/多 guest |
| B/C | `entry` 放在父域写的子 DCB 还是 descend 参数 |
| — | QEMU 中 call 语义与 ARM EL 的映射（降 EL / ERET vs 自定义） |

---

## 9. 修订记录

| 版本 | 内容 |
|------|------|
| v0.1 | A/D 收敛：统一 ascend；descend=call；去掉 escalate/RETURN/exit 原语分裂；入口仅 entry+exc；reason 闭集 4 值 |
