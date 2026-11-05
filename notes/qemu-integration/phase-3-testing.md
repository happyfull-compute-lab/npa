# Phase 3：RPA-QEMU 测试套件与自动化设计

**版本**：v1.0
**日期**：2026-07-20
**作者**：RPA 项目组
**依赖**：Phase 2 RPA-QEMU 设计（TCG 扩展、DomainBlock 译码、MMU walker 改造）

---

## 1. 测试目标与覆盖矩阵

### 1.1 测试目标

Phase 3 测试套件服务于三个层面：

1. **语义等价性**：QEMU TCG 上的 RPA 行为必须与 `rpa-pysim` 的可执行规范一致，作为规范的"硬件级再实现"参考。
2. **硬件级真实性**：捕获 Python 模拟器无法暴露的细节，如 TLB 行为、PMC 计数、指令时序、并发竞态。
3. **可发表评估数据**：为论文 evaluation 章节提供可在 Alpine Linux 上端到端运行的实验数据，包括与原生 ARM Linux 的对比基线。

### 1.2 可测试机制清单

从 `TECHNICAL_SPEC.md` 提取的可测试行为如下：

| 编号 | 机制 | 规范章节 | 可测试属性 |
|------|------|----------|------------|
| M1 | descend 原语 | §3.1 | 首次/恢复分支、上下文保存、控制块校验 |
| M2 | ascend 原语 | §3.2 | trap_vector 跳转、根域拒绝、上下文恢复 |
| M3 | return 原语 | §3.2 | 父域→子域恢复、与 EXIT 区分 |
| M4 | EXIT 原语 | §3.3 | 资源释放、控制块重用 |
| M5 | DomainBlock 字段权限 | §4.4 | 父域/子域/系统设置者约束 |
| M6 | 页表叠加翻译 | §5.1 | 单层/多层链式 walk |
| M7 | IPA 边界检查 | §5.2 | ipa_regions 表、多区域、INHERIT 下检查 |
| M8 | INHERIT 模式 | §5.3 | pagetable=0、共享父域视角、低开销 |
| M9 | 页表权限位 | §5/§6 | control 区域、r/w 分离 |
| M10 | 中断控制器 | §8 | handle 传递、sysop irq 接口 |
| M11 | 中断现场保存 | §7.4/§8.4 | 自动保存/恢复、IRQ_RETURN_FLAG |
| M12 | 域间中断隔离 | §7.4 | 各域独立中断状态 |
| M13 | Security Group 生命周期 | §9.2 | create/destroy/force_destroy |
| M14 | DMA 访问控制 | §9.4 | 同组允许、跨组拒绝、accessor 增减 |
| M15 | 加密内存 | §9.4 | 加密区设置、读写透明性 |
| M16 | 机密计算域 | §9.5 | confidential 标志、root 不可访问 |
| M17 | 机密域销毁授权 | §9.6 | 父域/root 授权、非父域拒绝 |
| M18 | ISA Tag 继承 | heterogeneous | INHERIT 解析、显式不被覆盖、多层传播 |
| M19 | 跨 ISA 上下文切换 | heterogeneous | 序列化大小差异、ARM/x86 互转 |
| M20 | 故障传播 | §6.3 | 异常→父域、fault 归属正确域 |
| M21 | 多核同步 | §7.2/§7.3 | 自上而下同步规则 |
| M22 | sysop 指令族 | §4.6/§8/§9 | irq/memtable/secgroup 子操作 |

### 1.3 测试维度与覆盖矩阵

每个机制沿四个维度验证：

| 维度 | 含义 |
|------|------|
| F (Functional) | 功能正确性：规范定义的行为是否实现 |
| B (Boundary) | 边界条件：极值、空值、首末次 |
| E (Exception) | 异常路径：违规操作是否触发正确的 fault |
| P (Performance) | 性能：cycles、TLB miss、上下文切换开销 |

完整覆盖矩阵（M × 维度，✓=必测，△=可选）：

| 机制 | F | B | E | P |
|------|---|---|---|---|
| M1 descend | ✓ | ✓ | ✓ | ✓ |
| M2 ascend | ✓ | ✓ | ✓ | ✓ |
| M3 return | ✓ | ✓ | ✓ | △ |
| M4 EXIT | ✓ | ✓ | ✓ | △ |
| M5 字段权限 | ✓ | △ | ✓ | — |
| M6 页表叠加 | ✓ | ✓ | ✓ | ✓ |
| M7 IPA 边界 | ✓ | ✓ | ✓ | △ |
| M8 INHERIT | ✓ | ✓ | ✓ | ✓ |
| M9 页表权限 | ✓ | △ | ✓ | — |
| M10 中断控制器 | ✓ | ✓ | ✓ | △ |
| M11 中断现场 | ✓ | ✓ | ✓ | ✓ |
| M12 中断隔离 | ✓ | △ | ✓ | — |
| M13 SG 生命周期 | ✓ | ✓ | ✓ | — |
| M14 DMA 控制 | ✓ | △ | ✓ | — |
| M15 加密内存 | ✓ | △ | ✓ | ✓ |
| M16 机密域 | ✓ | △ | ✓ | — |
| M17 销毁授权 | ✓ | △ | ✓ | — |
| M18 ISA Tag | ✓ | ✓ | ✓ | — |
| M19 跨 ISA 切换 | ✓ | △ | △ | ✓ |
| M20 故障传播 | ✓ | △ | ✓ | — |
| M21 多核同步 | ✓ | ✓ | ✓ | △ |
| M22 sysop | ✓ | ✓ | ✓ | — |

---

## 2. rpa-pysim 测试盘点

`rpa-pysim/tests/` 共 5 个测试文件，约 90+ 用例。下表给出文件→验证行为→迁移性分类。

### 2.1 test_rpa.py（核心原语，约 25 用例）

| 测试类/方法 | 验证行为 | QEMU 迁移性 |
|-------------|----------|-------------|
| TestDomainBlock.test_create_block | DomainBlock 字段 | 直接迁移（DCB 布局一致） |
| TestRPALogic.test_create_core | 根域初始化、depth=0 | 直接迁移 |
| test_descend_needs_memory | 无 memory 时 descend 报错 | 重新设计（QEMU 中 memory 总存在，改为 invalid DCB addr） |
| test_ascend_from_root_fails | 根域 ascend 拒绝 | 直接迁移（异常路径） |
| test_descend_conflict_child_block | 父域有子域时 DESCEND 到不同子域被拒 | 直接迁移 |
| TestSimpleISA.test_descend_ascend | DESCEND→子域执行→ASCEND→父域 trap_vector | 直接迁移（核心 TC-001 原型） |
| TestIntegration.test_descend_ascend_return_cycle | 完整 DESCEND→ASCEND→RETURN 闭环 | 直接迁移（TC-002 原型） |
| TestExitInstruction.test_exit_releases_child_domain | EXIT 清空 child_block、domain_id | 直接迁移 |
| test_exit_allows_reuse_of_child_block | EXIT 后控制块可重用 | 直接迁移 |
| test_exit_vs_ascend_difference | ASCEND 可 RETURN vs EXIT 不可 | 直接迁移 |

### 2.2 test_isa_simple.py（ISA 与中断，约 15 用例）

| 测试 | 验证行为 | QEMU 迁移性 |
|------|----------|-------------|
| TestMemory.* | 字节/字/字节数组读写、边界检查 | 重新设计（C 库函数验证） |
| TestSimpleISA.test_execute_mov/add/loop | 基础指令 | 不迁移（基础 ISA 由 QEMU 已有测试覆盖） |
| TestMemoryTranslation.test_ldr/str_with_page_table | LDR/STR 经过页表翻译 | 直接迁移（TC-010 原型） |
| TestInterruptReturn.test_irq_return_flag_in_lr | IRQ 设置 LR 的 IRQ_RETURN_FLAG | 直接迁移（TC-040 原型） |
| test_bx_lr_returns_from_interrupt | bx lr 从中断返回 | 直接迁移 |
| test_interrupt_preserves_context | 中断保存/恢复所有寄存器 | 直接迁移 |

### 2.3 test_security_group.py（安全组，约 20 用例）

| 测试类 | 验证行为 | QEMU 迁移性 |
|--------|----------|-------------|
| TestSecurityGroupController.* | 创建、attestation、继承、多域共享、销毁、force_destroy | 直接迁移（通过 sysop secgroup 接口） |
| test_dma_access_control | 同组允许、跨组拒绝、accessor 增减 | 重新设计（需 DMA 引擎设备模型） |
| test_confidential_domain | confidential 标志、外部访问禁止 | 重新设计（需加密内存控制器） |
| test_encrypted_memory | 加密区设置、读写透明性 | 重新设计（需内存加密设备） |
| TestSecurityGroupWithRPALogic.* | DESCEND 时绑定/解绑安全组 | 直接迁移 |
| TestSecurityGroupSysop.* | sysop secgroup create/destroy/get_handle | 直接迁移 |
| TestConfidentialDomainDestruction.* | 父域授权销毁机密子域 | 直接迁移（TC-031 原型） |

### 2.4 test_thread_exception.py（线程/异常/IPA，约 25 用例）

| 测试类 | 验证行为 | QEMU 迁移性 |
|--------|----------|-------------|
| TestDescendAscend.test_first_descend_jumps_to_saved_lr | 首次 DESCEND 跳转到 saved_lr | 直接迁移 |
| test_ascend_jumps_to_trap_vector | ASCEND 跳转到父域 trap_vector | 直接迁移 |
| test_descend_updates_page_table_chain | DESCEND 更新 page_table_chain，ASCEND 恢复 | 直接迁移 |
| test_shared_memory_between_domains | ipa_regions=0 共享内存 | 直接迁移 |
| test_child_block_tracking | child_block 字段正确跟踪 | 直接迁移 |
| TestMultiLevelTranslation.test_two_level_translation | 两级页表翻译 | 直接迁移（TC-011 原型） |
| test_fault_attribution_to_correct_domain | 翻译失败归属到失败域 | 直接迁移 |
| TestPermissionChecking.* | 控制区/只读/只写权限 | 直接迁移 |
| TestSysopMemtable.* | sysop memtable query/count | 直接迁移 |
| TestIPABoundsChecking.* | IPA 在/不在范围内、INHERIT 下检查 | 直接迁移（TC-013 原型） |

### 2.5 test_heterogeneous.py（异构 ISA，约 15 用例）

| 测试类 | 验证行为 | QEMU 迁移性 |
|--------|----------|-------------|
| TestISATag.* | 标签常量、DomainBlock 字段、默认 INHERIT | 直接迁移 |
| TestISATagInheritance.* | INHERIT 解析为父域 ISA、显式不被覆盖 | 直接迁移 |
| TestNestedISATags.* | 多层传播、混合 ISA 域 | 重新设计（QEMU 单二进制不支持真正异构，需多 QEMU 实例协作） |
| TestISAImplementation.* | ARM/x86 ISA 属性、调用约定 | 不迁移（Python 层抽象） |
| TestCrossISAContextSwitch.* | 序列化大小、ARM/x86 上下文 | 重新设计（验证 ctx_save_area 大小） |

### 2.6 迁移性汇总

- **直接迁移**：约 60 用例（语义不变，仅改写为 C/汇编 + 测试框架）
- **重新设计**：约 20 用例（涉及 Python 抽象层或需 QEMU 设备模型）
- **不迁移**：约 10 用例（基础 ISA、纯 Python 抽象）

---

## 3. QEMU 测试架构设计

采用四层测试金字塔，自底向上覆盖从译码到端到端的全栈行为。

```
        ┌──────────────────────────┐
        │  Layer 4: 集成测试 (E2E)  │  Alpine 启动→跑测试→收集
        ├──────────────────────────┤
        │  Layer 3: 内核态测试      │  Kselftest 风格内核模块
        ├──────────────────────────┤
        │  Layer 2: 用户态测试      │  C/汇编程序 + /dev/rpa
        ├──────────────────────────┤
        │  Layer 1: QEMU TCG 单元   │  源码内译码/walker 测试
        └──────────────────────────┘
```

### 3.1 Layer 1：QEMU TCG 单元测试

- **位置**：`tests/tcg/rpa/` （QEMU 源码内）
- **形式**：QTest 框架 + 直接调用 `rpa_translate()` / `rpa_mmu_walk()` 内部 API
- **覆盖**：
  - DESCEND/ASCEND/RETURN/EXIT 指令译码正确性
  - DomainBlock 字段读取与权限校验
  - page_table_chain walker 的单层/多层/INHERIT 分支
  - IPA 边界检查算法
  - IRQ_RETURN_FLAG 解析
- **特点**：不依赖 Linux 启动，毫秒级反馈，CI 友好

### 3.2 Layer 2：用户态测试（Alpine 内）

- **位置**：`papers/rpa-architecture/rpa-qemu/tests/user/`
- **形式**：C + 内联汇编，静态链接 musl，通过两种通道访问 RPA：
  - **通道 A**：`/dev/rpa` 字符设备（内核 driver 暴露 `ioctl` 发起 DESCEND/ASCEND）
  - **通道 B**：直接 `SVC` + 自定义立即数触发新指令（需内核配置 `CONFIG_RPA_USERSPACE=1`）
- **覆盖**：所有 F/B/E 维度的用户视角行为
- **输出**：TAP 14 格式到 stdout，由 runner 抓取

### 3.3 Layer 3：内核态测试（Kselftest 风格）

- **位置**：`papers/rpa-architecture/rpa-qemu/tests/kernel/`
- **形式**：可加载内核模块（.ko），通过 `printk` 输出结果
- **覆盖**：
  - 内核内部 RPA API（如 `rpa_domain_switch()`）
  - 中断控制器内核侧接口
  - Security Group 内核侧对象生命周期
  - 多核同步原语
- **加载方式**：`insmod rpa_test.ko`，结果写入 `/proc/rpa_test`

### 3.4 Layer 4：端到端集成测试

- **位置**：`papers/rpa-architecture/rpa-qemu/tests/integration/`
- **形式**：Python 编排脚本，通过 QEMU monitor 串口交互
- **流程**：
  1. 启动 QEMU + Alpine 内核镜像
  2. 等待 init 完成，scp 测试二进制到 guest
  3. 在 guest 内执行测试套件
  4. 通过串口日志抓取 TAP 输出
  5. 关机，runner 解析结果生成报告
- **覆盖**：完整启动→运行→关机链路，验证 RPA 在真实 OS 中的可用性

---

## 4. 测试用例设计

每个机制至少 3 个 TC，共设计 30 个核心测试用例。编号规则：`TC-XXX`，XXX 按机制分块。

### 4.1 descend/ascend/return/exit（M1-M4）

| TC ID | 标题 | 输入 | 预期输出 | 判定标准 |
|-------|------|------|----------|----------|
| TC-001 | 单层 descend→ascend→return 闭环 | 父域代码：DESCEND R0（R0=子域 DCB 地址）；子域代码：MOV R1,#5; ASCEND R1；父域 handler：MOV R3,#99; RETURN R0 | R1=5（子域执行）、R3=99（父域 handler 执行）、R2=42（RETURN 后子域继续）、depth=1 | 4 个寄存器值 + depth 全部匹配 |
| TC-002 | 10 层嵌套 descend | 构造 10 个 DCB，链式 DESCEND 到最深处，逐层 ASCEND 返回 | 每层 depth 递增 1 至 10，再递减回 0；每层 saved_lr/saved_sp 正确恢复 | depth 序列 = [1,2,...,10,9,...,1,0]；无 fault |
| TC-003 | descend 到无效 DCB（地址未对齐） | R0=0x1001（非 32 字节对齐）；DESCEND R0 | 触发 fault，类型=alignment，va=R0 | fault_info.type=="alignment" |
| TC-004 | descend 到无效 DCB（ctrlblock_size=0） | DCB 偏移 0x00 写 0；DESCEND R0 | 触发 fault，类型=invalid_ctrlblock | fault_info.type=="invalid_ctrlblock" |
| TC-005 | 根域 ascend 拒绝 | 根域内执行 ASCEND R0 | 触发 fault，类型=ascend_from_root | fault_info.type=="ascend_from_root" |
| TC-006 | EXIT 释放子域并允许重用 | DESCEND→子域 EXIT R0；再次 DESCEND 到同一 DCB | 第一次 EXIT 后 child_block=0、domain_id=0；第二次 DESCEND 的 is_first=true | DCB 字段清零 + is_first 标志 |
| TC-007 | 父域有子域时 DESCEND 到不同 DCB 被拒 | 父域已有子域 A，DESCEND 到 DCB B | 触发 DomainBlockError "already has child" | 异常类型匹配 |

### 4.2 页表叠加（M6/M7/M9）

| TC ID | 标题 | 输入 | 预期输出 | 判定标准 |
|-------|------|------|----------|----------|
| TC-010 | 单层页表翻译 | pt: VA 0x1000→PA 0x2000；LDR R0,[#0x1000] | R0 = mem[0x2000] | R0 值匹配 + access_log 显示 PA=0x2000 |
| TC-011 | 三层叠加翻译 | pt_D2: VA→IPA_D1；pt_D1: IPA_D1→IPA_D0；pt_D0: IPA_D0→PA | LDR 读到的值 = mem[最终 PA] | 翻译链 3 层逐级匹配 |
| TC-012 | 父子页表冲突，子域映射覆盖 | 父域映射 VA→PA_A；子域映射 VA→PA_B | 子域视角读到的 = mem[PA_B] | 子域映射生效，父域不可见 |
| TC-013 | IPA 超出 ipa_regions 触发 fault | ipa_regions 只允许 [0x2000,0x5000)；子域页表 VA→IPA 0x6000 | 触发 translation fault，va=VA | fault_info.type=="translation"，owner=子域 |
| TC-014 | IPA 多区域匹配 | ipa_regions 有两个区域；IPA 在第二个区域内 | 访问成功 | 无 fault + 数据正确 |
| TC-015 | 控制区 LDR 被拒 | pt 标记 control=true；LDR 该 VA | 触发 permission fault | fault_info.type=="permission" |
| TC-016 | 只读页 STR 被拒 | pt: r=true,w=false；STR 该 VA | 触发 permission fault | fault_info.type=="permission" |

### 4.3 INHERIT 模式（M8）

| TC ID | 标题 | 输入 | 预期输出 | 判定标准 |
|-------|------|------|----------|----------|
| TC-020 | INHERIT 下系统调用开销 < 100 cycles | pagetable=0；测量 1000 次 ascend+return 的 PMC cycle 数 | 平均 cycles < 100 | 见 §5 性能测试 |
| TC-021 | INHERIT 下页表修改传播 | 父域修改共享页表项；子域读取 | 子域立即看到新映射 | 无需 TLB flush |
| TC-022 | INHERIT ↔ 独立页表切换 | 子域先 pagetable=0，运行中改写 pagetable 字段；触发新页表生效 | 切换后访问走新页表 | 切换前后同一 VA 读到不同 PA |
| TC-023 | INHERIT 下 IPA 边界仍检查 | pagetable=0；ipa_regions 限制 [0x2000,0x5000)；访问 0x6000 | 触发 translation fault | fault_info.type=="translation"，va=0x6000 |

### 4.4 Security Group（M13-M17）

| TC ID | 标题 | 输入 | 预期输出 | 判定标准 |
|-------|------|------|----------|----------|
| TC-030 | 跨 Security Group DMA 访问被拒 | SG_A 含 DMA 引擎；SG_B 含内存区；DMA 引擎尝试访问 SG_B 内存 | check_dma_access 返回 false | 返回值=false |
| TC-031 | 管理权与访问权分离 | 父域配置子域 ipa_regions（管理权）；父域尝试读取子域内存内容（访问权） | 配置成功 + 读取失败/读到加密数据 | 两行为结果独立 |
| TC-032 | 机密域销毁：父域授权成功 | 父域请求 destroy_confidential(子域 handle) | success=true，实例被移除 | success=true + get_instance==None |
| TC-033 | 机密域销毁：非父域拒绝 | 恶意域请求 destroy_confidential | success=false，message 含 "denied" | success=false + 实例仍存在 |
| TC-034 | force_destroy 仅 root 可用 | 非 root 域调用 force_destroy | 返回 false | 返回值=false |
| TC-035 | 加密内存读写透明性 | 设置加密区；write_bytes(encrypt=true)；read_bytes(decrypt=true) | 读到的 == 写入的；raw（不解密）≠ 写入的 | 两条件同时成立 |

### 4.5 中断机制（M10-M12）

| TC ID | 标题 | 输入 | 预期输出 | 判定标准 |
|-------|------|------|----------|----------|
| TC-040 | 中断投递到正确 domain | 域 A 申请中断并 setvec；trigger_irq | PC 跳转到域 A 的中断向量 | PC==vector + in_interrupt==True |
| TC-041 | 嵌套 domain 中断屏蔽 | 域 A disable 中断；域 B（子域）仍可接收中断 | 域 A 不响应、域 B 响应 | 各域 in_interrupt 独立 |
| TC-042 | bx lr 从中断返回 | ISR 末尾 bx lr | PC 恢复到被中断指令的下一条；所有寄存器恢复 | PC + R0-R15 全部匹配 |
| TC-043 | interrupt_ctrl=0 时 sysop irq 触发异常 | DCB.interrupt_ctrl=0；执行 sysop irq enable | 触发 fault | fault_info.type=="no_irq_controller" |
| TC-044 | IRQ_RETURN_FLAG 误用检测 | 非中断上下文执行 bx lr，且 LR 高位被人为置位 | 不触发中断返回路径，按普通跳转处理 | PC = LR & ~FLAG |

### 4.6 ISA Tag 与异构（M18-M19）

| TC ID | 标题 | 输入 | 预期输出 | 判定标准 |
|-------|------|------|----------|----------|
| TC-050 | INHERIT 解析为父域 ARM | 根域 isa_tag=ARM；子域 isa_tag=INHERIT；DESCEND | 子域 isa_tag 被解析为 ARM | block.isa_tag==ARM + 内存中 DCB 字段更新 |
| TC-051 | 显式 ISA 不被覆盖 | 根域 ARM；子域显式 X86；DESCEND | 子域保持 X86 | block.isa_tag==X86 |
| TC-052 | 三层 ISA 传播 | 根 X86 → 子 INHERIT → 孙 INHERIT | 孙域 isa_tag=X86 | 三层均匹配 |
| TC-053 | 跨 ISA ctx_save_area 大小 | ARM 域 vs X86 域 DESCEND | ARM 保存 12 字节，X86 保存 24 字节 | 大小匹配 + 偏移范围正确 |

### 4.7 故障与多核（M20-M21）

| TC ID | 标题 | 输入 | 预期输出 | 判定标准 |
|-------|------|------|----------|----------|
| TC-060 | 翻译 fault 归属到失败域 | pt_D1 映射 VA→IPA，pt_D0 不映射 IPA→PA | fault_info.owner=0（D0 翻译失败） | owner 字段精确匹配 |
| TC-061 | 总线错误（访问超出物理内存） | LDR 超出 RAM 范围的 PA | fault_info.type=="memory" | 类型匹配 |
| TC-062 | 多核自上而下同步 | Core 0 完整 DESCEND 到 D2；Core 1 跳过 D1 直接进 D2 | Core 1 操作被拒绝或触发 fault | 拒绝/fault 发生 |
| TC-063 | 多核独立域状态 | Core 0 在 D1，Core 1 在 D2，各自中断 | 中断只影响各自核心的当前域 | 互不干扰 |

**TC 总数：30 个**（机制覆盖：M1-M22 全部）。

---

## 5. 性能测试设计

### 5.1 评测指标

| 指标 | 测量方法 | 单位 | 论文章节用途 |
|------|----------|------|-------------|
| 系统调用 cycles | INHERIT 模式 ascend+return，PMC cycle counter | cycles | §6.2 INHERIT 优势 |
| 页表翻译延迟 | 单层/两层/三层 walk 的 PMC cycles | cycles | §5 页表叠加开销 |
| TLB miss 率 | PMC 事件 `L1D_TLB_REFILL` / `MEM_ACCESS` | 比率 | §5.3 INHERIT 无 TLB flush 论证 |
| 上下文切换开销 | descend+ascend 闭环 PMC cycles | cycles | §6 与传统 trap 对比 |
| 中断响应延迟 | IRQ trigger→ISR 第一条指令的 PMC cycles | cycles | §8 中断机制评估 |
| 加密内存带宽开销 | memcpy 大块加密区 vs 非加密区，计时 | MB/s | §9.4 加密开销 |

### 5.2 测量方法

- **PMC 访问**：ARMv8 PMU cycle counter (`PMCCNTR_EL0`)，用户态通过 `mrs x0, pmccntr_el0` 读取（内核启用 `CONFIG_PERF_EVENTS` + `perf_event_paranoid=0`）
- **采样策略**：每项测量重复 ≥10000 次，取中位数 + 99 百分位
- **缓存预热**：测量前 100 次预热，避免冷启动噪声
- **CPU 绑核**：`taskset -c 0` 避免调度抖动

### 5.3 基线对比

| 基线 | 用途 | 数据来源 |
|------|------|----------|
| 原生 ARM Linux syscall | INHERIT ascend+return 对比 | 同一 QEMU 版本，无 RPA 扩展，跑 `getpid()` 测量 |
| ARM vHE 嵌套虚拟化 | 多层页表翻译开销对比 | QEMU `-enable-kvm` + KVM 嵌套 |
| rpa-pysim 功能时序 | 语义等价性回归 | pysim 计数指令数，与 QEMU PMC 比例对比 |
| 传统 trap (SMC/HVC) | 中断响应对比 | 同 QEMU 测量 SMC 调用 cycles |

### 5.4 性能测试用例

| Perf ID | 标题 | 测量目标 | 判定标准（论文可发表阈值） |
|---------|------|----------|----------------------------|
| P-001 | INHERIT 系统调用 cycles | ascend+return 闭环 | 中位数 < 100 cycles（规范目标） |
| P-002 | 独立页表 ascend cycles | 含 TLB flush 的切换 | 与原生 syscall 比值 < 5x |
| P-003 | 三层页表翻译延迟 | walk 3 层 | 中位数 < 1000 cycles |
| P-004 | TLB miss 率（INHERIT vs 独立） | 对比两种模式 | INHERIT miss 率 < 独立模式的 10% |
| P-005 | 中断响应延迟 | IRQ→ISR | < 500 cycles |
| P-006 | 加密内存带宽开销 | memcpy 加密 vs 明文 | 开销 < 15% |
| P-007 | 10 层嵌套 descend 累积开销 | 深度 vs cycles 线性度 | 线性相关系数 R² > 0.95 |

### 5.5 数据可信度声明

QEMU TCG 为功能级模拟器，无真实流水线时序。性能数据的**绝对值不可代表真实硬件**，但：
- **相对趋势可信**：INHERIT vs 独立页表、单层 vs 多层、RPA vs 传统 trap 的比例关系成立
- **TLB 行为可信**：TCG 维护软件 TLB，flush 事件可精确计数
- **论文表述建议**：以"归一化比值"和"事件计数"为主，绝对 cycles 标注"QEMU TCG 估算"

---

## 6. 自动化框架

### 6.1 目录结构

```
papers/rpa-architecture/rpa-qemu/tests/
├── user/                    # Layer 2 用户态测试
│   ├── tc_001_descend_ascend.c
│   ├── tc_010_single_pt.c
│   ├── tc_020_inherit_syscall.c
│   ├── tc_030_dma_isolation.c
│   ├── tc_040_irq_delivery.c
│   ├── tc_050_isa_inherit.c
│   ├── common/
│   │   ├── rpa_syscalls.h   # /dev/rpa ioctl 封装
│   │   ├── rpa_asm.h        # 内联汇编宏
│   │   ├── pmu.h            # PMC 读取封装
│   │   └── tap.h            # TAP 输出宏
│   └── Makefile
├── kernel/                  # Layer 3 内核态测试
│   ├── rpa_test_core.c
│   ├── rpa_test_irq.c
│   ├── rpa_test_sg.c
│   └── Makefile
├── integration/             # Layer 4 端到端
│   ├── run_alpine.py        # 启动 QEMU+Alpine
│   ├── deploy_and_run.py    # scp + 执行 + 抓串口
│   └── conftest.py
├── perf/                    # 性能测试
│   ├── p_001_inherit_syscall.c
│   ├── p_004_tlb_miss.c
│   ├── analyze.py           # 统计中位数/百分位
│   └── Makefile
├── tcg/                     # Layer 1 QTest（链接到 QEMU 源码树）
│   └── README.md
├── runner.py                # 统一运行器
├── report_template.html     # 报告模板
└── Makefile                 # 顶层入口
```

### 6.2 测试输出格式

采用 **TAP 14** 流式输出，便于工具链解析：

```
TAP version 14
1..30
ok 1 - TC-001 descend_ascend_return_cycle depth=1 R3=99 R2=42
ok 2 - TC-002 nested_descend_10_layers depth_seq=[1..10..0]
not ok 3 - TC-003 invalid_dcb_alignment expected=alignment actual=none
  ---
  fault_type: none
  expected: alignment
  ...
```

每个 TC 同时输出 JSON sidecar（`tc_001.json`），包含 PMC 数据、寄存器快照、access_log，供 `analyze.py` 聚合。

### 6.3 统一运行器 `runner.py`

```python
# 伪代码（不实现）
class RpaTestRunner:
    def __init__(self, layer, filter_regex=None):
        self.layer = layer  # 'tcg' | 'user' | 'kernel' | 'integration' | 'perf'
    def run(self) -> TestReport:
        # 1. 构建 QEMU + Alpine 镜像（如需）
        # 2. 按 layer 启动对应执行环境
        # 3. 抓取 TAP 输出 + JSON sidecar
        # 4. 生成 HTML 报告 + JUnit XML（供 CI）
        ...
```

支持命令行：
- `python runner.py --layer user --filter 'TC-001|TC-010'`
- `python runner.py --layer integration --alpine-version 3.20`
- `python runner.py --layer perf --repeats 10000`

### 6.4 CI 集成

**GitHub Actions 方案**（`.github/workflows/rpa-qemu-tests.yml`）：

| Job | Runner | 耗时估算 | 触发 |
|-----|--------|----------|------|
| `tcg-unit` | ubuntu-22.04，编译 QEMU + 跑 QTest | 8-12 min | 每次 push |
| `user-kernel` | 自托管（KVM 可用），启动 Alpine 跑 Layer 2/3 | 15-20 min | PR 合并到 main |
| `integration` | 自托管，完整 E2E | 25-35 min | 每日 cron |
| `perf` | 自托管，固定绑核 | 40-60 min | 每周 cron + tag |

资源消耗风险见 §8。CI 资源不足时降级为 `tcg-unit` only。

### 6.5 测试报告

`runner.py` 生成三种产物：
1. **HTML 报告**：`report_<timestamp>.html`，含每个 TC 的通过/失败、寄存器快照、access_log 表格
2. **JUnit XML**：`junit.xml`，供 GitHub Actions PR check 显示
3. **性能 CSV**：`perf_<timestamp>.csv`，含每个 Perf ID 的中位数/p99/原始数据，供论文绘图

---

## 7. 迁移计划

### 7.1 rpa-pysim → QEMU 测试映射表

| pysim 测试 | QEMU TC | 优先级 | 工作量 | 说明 |
|------------|---------|--------|--------|------|
| test_rpa.py::test_descend_ascend | TC-001 | P0 | 1d | 核心，先验证 E2E 链路 |
| test_rpa.py::test_descend_ascend_return_cycle | TC-001 扩展 | P0 | 0.5d | 同上 |
| test_thread_exception.py::test_first_descend_jumps_to_saved_lr | TC-001 变体 | P0 | 0.5d | |
| test_rpa.py::test_ascend_from_root_fails | TC-005 | P0 | 0.5d | 异常路径 |
| test_rpa.py::test_descend_conflict_child_block | TC-007 | P1 | 0.5d | |
| test_rpa.py::TestExitInstruction.* | TC-006 | P0 | 1d | EXIT 语义关键 |
| test_thread_exception.py::test_two_level_translation | TC-011 | P0 | 1d | 多层翻译核心 |
| test_thread_exception.py::TestIPABoundsChecking.* | TC-013, TC-014, TC-023 | P0 | 1.5d | IPA 边界 |
| test_thread_exception.py::TestPermissionChecking.* | TC-015, TC-016 | P1 | 1d | |
| test_isa_simple.py::TestInterruptReturn.* | TC-040, TC-042, TC-044 | P0 | 2d | 中断机制关键 |
| test_security_group.py::TestSecurityGroupController.* | TC-030, TC-034 | P1 | 2d | 需 SG 设备模型 |
| test_security_group.py::TestConfidentialDomainDestruction.* | TC-032, TC-033 | P1 | 1d | |
| test_security_group.py::TestEncryptedMemory.* | TC-035 | P2 | 1.5d | 需加密设备 |
| test_heterogeneous.py::TestISATagInheritance.* | TC-050, TC-051 | P2 | 1d | 单 QEMU 实例可验证 |
| test_heterogeneous.py::TestNestedISATags.* | TC-052 | P3 | 2d | 需多实例协作 |
| test_thread_exception.py::test_fault_attribution_to_correct_domain | TC-060 | P1 | 1d | |
| 无对应 pysim 测试 | TC-002, TC-020, TC-062 等 | P0-P2 | 见下 | 新增 QEMU 专属 |

### 7.2 优先级与工作量估算

| 阶段 | 范围 | 估时 | 累计 |
|------|------|------|------|
| **Sprint 1** | P0 用例：TC-001/005/006/010/011/013/023/040/042 + runner.py 骨架 | 10 人日 | 10 |
| **Sprint 2** | P1 用例：TC-007/015/016/030/032/033/060 + 性能 P-001/004 | 9 人日 | 19 |
| **Sprint 3** | P2 用例：TC-035/050/051 + 性能 P-002/003/005/006/007 | 8 人日 | 27 |
| **Sprint 4** | P3 用例：TC-052/062/063 + CI 完善 + 论文数据生成 | 6 人日 | 33 |

总计约 33 人日（按 1 人投入），含调试与文档。

---

## 8. 风险

### 8.1 性能数据可信度

**风险**：QEMU TCG 是功能级模拟，无真实流水线、cache 层次、DRAM 时序。论文 evaluation 仅基于 TCG 可能被审稿人质疑。

**缓解**：
- 在论文中明确标注"QEMU TCG 估算"，不声称绝对性能数据
- 主打**归一化比值**与**事件计数**（如 TLB flush 次数、walk 层数）
- §5.5 提供可信度声明，并列出未来在 gem5/FPGA 上验证的路线图
- 长期目标：补充 gem5 RPA 扩展模型作为 cycle-accurate 二次验证

### 8.2 测试覆盖盲区

**已知盲区**：
1. **真实硬件并发竞态**：TCG 单线程翻译，无法暴露 SMP 下的 DomainBlock 竞态、TLB shootdown 时序
2. **DMA 设备模型**：QEMU 默认 DMA 引擎不感知 Security Group，需自研设备模型，否则 TC-030 只能测内核侧 API 而非真实 DMA
3. **内存加密**：QEMU 无硬件加密引擎，TC-035 只能验证软件模拟的加密路径
4. **异构 ISA**：单 QEMU 二进制只能跑一种 ISA，TC-052/053 需多 QEMU 实例 + 共享内存通道，复杂度高
5. **功耗/温度**：不在测试范围

**缓解**：在报告 HTML 中明确标注每个 TC 的"覆盖等级"（Full / Partial / Software-only），避免过度声称。

### 8.3 CI 资源消耗

**风险**：
- 自托管 runner 编译 QEMU 需 ~20 min，跑全集 ~60 min
- Alpine 镜像构建 + 测试 binary scp 链路脆弱
- 性能测试对环境噪声敏感，CI 共享 runner 数据不可用

**缓解**：
- 分层触发：push 只跑 `tcg-unit`，PR 跑 `user-kernel`，main 跑 `integration`，weekly 跑 `perf`
- 缓存 QEMU 编译产物 + Alpine rootfs（`actions/cache`）
- 性能测试只在专用 runner（固定绑核、禁用超线程）执行
- 提供 `--smoke` 模式，每 TC 只跑 1 次，用于快速回归

### 8.4 其他风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| Phase 2 设计未完成 | TCG 扩展接口未定，Layer 1 测试无法启动 | Layer 1 推迟到 Phase 2 完成；先做 Layer 2/4 |
| Alpine 内核 RPA patch 不稳定 | 集成测试 flaky | kernel test 先在最小 initramfs 跑通，再切 Alpine |
| `/dev/rpa` 接口设计未定 | 用户态测试 API 不稳定 | 接口先于测试实现，作为 Phase 2 交付物 |
| PMC 在 QEMU 中不可靠 | 性能数据噪声大 | 改用指令计数（instrument TCG），作为 PMC 不可用时的 fallback |

---

## 9. 参考链接

### 项目内
- RPA 技术规范：`papers/rpa-architecture/notes/TECHNICAL_SPEC.md`
- rpa-pysim README：`papers/rpa-architecture/rpa-pysim/README.md`
- rpa-pysim 测试目录：`papers/rpa-architecture/rpa-pysim/tests/`
- pysim DomainBlock 规范：`papers/rpa-architecture/rpa-pysim/docs/CONTROL_BLOCK_SPEC.md`
- pysim 安全组规范：`papers/rpa-architecture/rpa-pysim/docs/SECURITY_GROUP_SPEC.md`
- Phase 2 设计（待生成）：`papers/rpa-architecture/notes/qemu-integration/phase-2-rpa-qemu-design.md`

### 外部
- QEMU QTest 框架：https://qemu.readthedocs.io/en/latest/devel/testing/qtest.html
- Linux Kselftest：https://www.kernel.org/doc/html/latest/dev-tools/kselftest.html
- TAP 14 规范：https://testanything.org/tap-version-14-specification.html
- ARM PMU 架构参考：ARM DDI 0487 (ARMv8-A Architecture Reference Manual), Chapter D11
- Alpine Linux ARM 镜像：https://alpinelinux.org/cloud/

---

## 附录 A：TC 编号索引

| TC ID | 机制 | 优先级 | pysim 来源 |
|-------|------|--------|------------|
| TC-001 | M1-M3 | P0 | test_descend_ascend_return_cycle |
| TC-002 | M1 | P0 | 新增（多层） |
| TC-003 | M1 | P0 | test_descend_needs_memory 改写 |
| TC-004 | M1 | P1 | 新增 |
| TC-005 | M2 | P0 | test_ascend_from_root_fails |
| TC-006 | M4 | P0 | TestExitInstruction.* |
| TC-007 | M1 | P1 | test_descend_conflict_child_block |
| TC-010 | M6 | P0 | test_ldr_with_translation |
| TC-011 | M6 | P0 | test_two_level_translation |
| TC-012 | M6 | P1 | 新增 |
| TC-013 | M7 | P0 | test_ipa_out_of_bounds |
| TC-014 | M7 | P1 | test_ipa_multiple_regions |
| TC-015 | M9 | P1 | test_control_area_requires_sysop_for_read |
| TC-016 | M9 | P1 | test_read_only_page_blocks_write |
| TC-020 | M8 | P0 | test_inherit_mode_ipa_bounds_check + 新增性能 |
| TC-021 | M8 | P1 | 新增 |
| TC-022 | M8 | P1 | 新增 |
| TC-023 | M7/M8 | P0 | test_inherit_mode_ipa_bounds_check |
| TC-030 | M14 | P1 | test_dma_access_control |
| TC-031 | M5/M16 | P1 | 新增（管理权/访问权分离） |
| TC-032 | M17 | P1 | test_confidential_destroy_authorized_parent |
| TC-033 | M17 | P1 | test_confidential_destroy_unauthorized_domain |
| TC-034 | M13 | P1 | test_force_destroy |
| TC-035 | M15 | P2 | test_encrypted_write_read |
| TC-040 | M10 | P0 | test_irq_return_flag_in_lr |
| TC-041 | M12 | P1 | 新增（域间隔离） |
| TC-042 | M11 | P0 | test_bx_lr_returns_from_interrupt |
| TC-043 | M10 | P1 | 新增 |
| TC-044 | M11 | P2 | 新增（FLAG 误用） |
| TC-050 | M18 | P2 | test_inherit_isa_from_parent_arm |
| TC-051 | M18 | P2 | test_explicit_isa_not_overridden |
| TC-052 | M18 | P3 | test_multi_level_inheritance |
| TC-053 | M19 | P3 | test_context_save_area_different_sizes |
| TC-060 | M20 | P1 | test_fault_attribution_to_correct_domain |
| TC-061 | M20 | P1 | test_bus_error |
| TC-062 | M21 | P2 | 新增（多核同步） |
| TC-063 | M21 | P2 | 新增（多核独立） |

**总计：34 个 TC**（含 7 个性能测试 P-001~P-007 在 §5.4 单独列出）。
