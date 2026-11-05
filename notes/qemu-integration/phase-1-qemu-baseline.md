# Phase 1 设计文档：QEMU + Alpine 基线启动

> **项目**：Recursive Privilege Architecture (RPA)
> **阶段**：Phase 1 — QEMU + Alpine 基线环境
> **状态**：设计草案，待主 agent 评审
> **日期**：2026-07-20
> **作者**：Phase 1 设计子 agent

---

## 0. 背景与定位

RPA 此前以 `rpa-pysim`（Python 可执行规范）验证功能正确性，但 Python 模拟器无法承载真实 Linux 启动、无法测量 cycle 级开销、也无法支撑后续论文 evaluation 章节所需的「真实 workload 在 RPA 上的端到端运行」叙事。Phase 1 的目标是把模拟栈切换到 QEMU（TCG 模式），先建立一条**最小可启动、可交互、可复现**的 ARM64 Linux 基线，作为 Phase 2 起注入 RPA 原语、页表叠加、安全域等机制的载体。

本阶段**不**做任何 RPA 相关的硬件修改，仅产出基线。任何 RPA 修改留待 Phase 2 在 QEMU 的 `target/arm/` 目录中以 TCG helper 形式注入。

---

## 1. 目标与验收标准

### 1.1 功能目标

| 编号 | 目标 | 验收方式 |
|------|------|----------|
| G-1 | 在 x86_64 Linux host 上启动 QEMU-system-aarch64 | `qemu-system-aarch64 --version` 正常输出 |
| G-2 | 启动到 Alpine busybox shell（不依赖 systemd） | 串口/SSH 看到 `localhost:~#` 提示符 |
| G-3 | 通过串口 (`-nographic`) 或 SSH 可交互 | 能执行 `uname -a`、`poweroff` |
| G-4 | 总启动时间 < 30 秒 | 从 QEMU 进程启动到 shell 出现的 wall-clock 时间 |
| G-5 | 镜像 + rootfs 总大小 < 100 MB | `du -sh` 统计 `build/` 目录 |
| G-6 | 一键构建与启动 | `make boot` 在干净环境下可复现 |

### 1.2 非目标（Non-Goals）

- 不做 KVM 加速（Phase 4 再切换，因为 KVM 要求 host = guest 架构）
- 不做 RPA 机制注入（Phase 2）
- 不做性能精确测量（Phase 3 引入 gem5 联合仿真后再做）
- 不做跨架构发行版（仅 arm64）

### 1.3 与论文 evaluation 的对应

Phase 1 对应 `en/mcsoc2026/` evaluation 章节的「实验环境」小节，提供：

- baseline 启动时间数据
- baseline 内存占用数据
- 后续 RPA-vs-baseline 对比所需的对照系

---

## 2. 组件选型

### 2.1 QEMU 版本

**推荐：QEMU 9.2**（2024-12 发布，stable branch）

- 9.x 系列对 `virt` 机器的 GICv3、virtio-mmio、PCIe 支持已稳定
- 9.2 起对 ARM TCG 的 `cortex-a72` / `max` CPU 模型修复了若干 SError 处理 bug
- 10.x（若已发布）可作为备选，但需在 `notes/` 中记录回归测试结果
- 安装方式优先 distro 包（`apt install qemu-system-arm`），源码编译留作 fallback

### 2.2 ARM 机器型号

**推荐：`virt`**

| 机器 | 优点 | 缺点 | 适用性 |
|------|------|------|--------|
| `virt` | QEMU 官方维护，virtio 支持完善，GICv3 默认，文档最全 | 非真实 SoC | **首选** |
| `raspi3b` / `raspi4b` | 贴近树莓派真实硬件 | 外设驱动有限，启动链复杂 | 备选 |
| `sbsa-ref` | Server Base System Architecture，UEFI 标准化最强 | 启动较慢，依赖 ACPI | Phase 4 候选 |

RPA 的递归特权是 ISA 层抽象，与具体 SoC 外设无关，因此 `virt` 是最干净的选择。

### 2.3 ARM CPU 型号

**开发期：`-cpu max`；贴近真实 SoC：`-cpu cortex-a72`**

- `cortex-a72`：ARMv8.0，AArch64，4-issue out-of-order，被树莓派 4、HiKey 960 等真实板卡使用，TCG 支持成熟
- `cortex-a53`：ARMv8.0，in-order，简单但偏旧
- `max`：QEMU 启用所有 ARMv8.x 扩展（SVE、PAuth、BTI 等），适合功能验证，但与真实 SoC 不对应
- **决策**：Phase 1 用 `cortex-a72`，便于后续在 `target/arm/cpu64.c` 中以 `cortex-a72` 为基线注入 RPA TCG helper

### 2.4 Linux kernel 版本

**推荐：Linux 6.12 LTS**（2024-11 发布，维护至 2026 年底）

- 下载：<https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.${PATCH}.tar.xz>
- 备选：6.6 LTS（维护至 2026 年底，更保守）
- 不用 6.13+ mainline：非 LTS，回归风险高
- 最小 config：`defconfig` + virtio + virtiofs + 9pnet + devtmpfs + serial

### 2.5 Alpine 版本

**推荐：Alpine 3.20**（2024-05 发布，mini rootfs tarball ~3 MB）

- 下载：<https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/alpine-minirootfs-3.20.${PATCH}-aarch64.tar.gz>
- 备选：3.21（若已发布且 musl + busybox 兼容性已验证）
- 不用完整 `alpine-standard` ISO：体积 > 150 MB，违反 < 100 MB 约束
- musl libc + busybox：启动快、依赖少、systemd-free，符合验收 G-2

### 2.6 UEFI 固件

**推荐：AAVMF (edk2-armvf)，来自 `qemu-efi-aarch64` 包**

- Debian/Ubuntu 路径：`/usr/share/AAVMF/AAVMF_CODE.fd`（或 `/usr/share/qemu-efi-aarch64/QEMU_EFI.fd`）
- 备选：U-Boot `qemu_arm64` defconfig（需自行编译或下载 `u-boot-qemu_arm64.bin`）

---

## 3. 启动方案对比

### 3.1 三种方案

#### 方案 A：UEFI（AAVMF） + 直接 kernel

```
AAVMF_CODE.fd → EFI loader → Image (kernel) → Alpine rootfs
```

- 优点：UEFI 运行时服务可用，未来支持 ACPI、Secure Boot、变量存储
- 缺点：固件加载耗时 2-5 秒，镜像多一个 fd 文件

#### 方案 B：U-Boot + boot.scr + kernel + dtb

```
u-boot.bin → boot.scr → Image + dtb → Alpine rootfs
```

- 优点：贴近嵌入式真实启动链，可移植到真实 SoC
- 缺点：需自行维护 `boot.scr`、dtb，启动链调试成本高

#### 方案 C：QEMU `-kernel` 直接启动

```
qemu-system-aarch64 -kernel Image -append "root=..." -dtb ...
```

- 优点：最简、最快（< 1 秒进 kernel），无固件依赖
- 缺点：跳过固件层，UEFI 运行时服务缺失，与真实硬件启动链不符

### 3.2 推荐方案

**Phase 1 默认采用方案 C**，理由：

1. **目标导向**：验收标准 G-4（< 30 秒）和 G-5（< 100 MB）对方案 C 最友好
2. **RPA 影响最小**：RPA 修改在 `target/arm/` TCG 层，固件层（AAVMF/U-Boot）本身不参与 RPA 原语执行；跳过固件层不损失 RPA 验证有效性
3. **可演进**：Phase 2 引入 RPA 页表叠加后，固件层的早期页表初始化反而会干扰 RPA 域 0 的建立；先用 `-kernel` 干净启动，等 RPA 域管理稳定后再考虑引入固件
4. **保留升级路径**：在 `Makefile` 中提供 `BOOT_MODE=direct|uefi|uboot` 变量，Phase 4 评估真实硬件时切到方案 A 或 B

**方案 A（UEFI）作为备选**，在 `notes/qemu-integration/` 中保留一份等价的 AAVMF 启动命令，用于未来对比和论文 evaluation 的「真实启动链」叙事。

---

## 4. 构建步骤设计

### Step 1：安装 QEMU 与交叉编译工具链

```bash
# Debian/Ubuntu host
sudo apt install -y \
    qemu-system-arm qemu-utils \
    gcc-aarch64-linux-gnu \
    build-essential bc bison flex libssl-dev libelf-dev \
    cpio wget

# 验证
qemu-system-aarch64 --version
aarch64-linux-gnu-gcc --version
```

### Step 2：获取/编译 Linux kernel

```bash
# 下载
wget https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.${PATCH}.tar.xz
tar xf linux-6.12.${PATCH}.tar.xz
cd linux-6.12.${PATCH}

# 最小 config
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- defconfig
# 叠加 RPA 所需 fragment（见 configs/kernel.config）
scripts/kconfig/merge_config.sh -m .config configs/kernel.config

# 编译（仅 kernel + dtb，不编译模块以节省体积）
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) Image dtbs

# 产物
arch/arm64/boot/Image
arch/arm64/boot/dts/arm/qemu-arm64-virt.dtb  # 或由 QEMU -machine dumpdtc 生成
```

`configs/kernel.config` 关键项（fragment 形式）：

```
CONFIG_VIRTIO=y
CONFIG_VIRTIO_MMIO=y
CONFIG_VIRTIO_BLK=y
CONFIG_VIRTIO_NET=y
CONFIG_VIRTIO_CONSOLE=y
CONFIG_9P_FS=y
CONFIG_VIRTIOFS_FS=y
CONFIG_DEVTMPFS=y
CONFIG_DEVTMPFS_MOUNT=y
CONFIG_SERIAL_AMBA_PL011=y
CONFIG_SERIAL_AMBA_PL011_CONSOLE=y
CONFIG_BLK_DEV_INITRD=y
# 关闭非必需子系统以减小体积
CONFIG_SOUND=n
CONFIG_DRM=n
CONFIG_WIRELESS=n
```

### Step 3：准备 Alpine rootfs

```bash
# 下载并解压
wget https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/aarch64/\
    alpine-minirootfs-3.20.${PATCH}-aarch64.tar.gz
mkdir -p build/rootfs
sudo tar -xzf alpine-minirootfs-*.tar.gz -C build/rootfs

# chroot 定制（安装 openssh、配置 root 密码、网络）
sudo mount --bind /dev build/rootfs/dev
sudo mount --bind /proc build/rootfs/proc
sudo chroot build/rootfs /bin/sh <<'EOF'
apk update
apk add openssh busybox-extras
echo "root:root" | chpasswd
echo "PermitRootLogin yes" >> /etc/ssh/sshd_config
rc-update add sshd default
EOF
sudo umount build/rootfs/dev build/rootfs/proc

# 打包为 ext4 镜像（或直接用 virtiofs 挂目录）
dd if=/dev/zero of=build/rootfs.img bs=1M count=64
mkfs.ext4 -F build/rootfs.img
sudo mount -o loop build/rootfs.img /mnt
sudo cp -a build/rootfs/. /mnt/
sudo umount /mnt
```

### Step 4：准备启动固件（仅方案 A/B 需要）

```bash
# 方案 A：使用 distro 自带 AAVMF
cp /usr/share/AAVMF/AAVMF_CODE.fd firmware/
cp /usr/share/AAVMF/AAVMF_VARS.fd firmware/  # 可写副本

# 方案 B：编译 U-Boot
git clone https://source.denx.de/u-boot/u-boot.git
cd u-boot
make qemu_arm64_defconfig CROSS_COMPILE=aarch64-linux-gnu-
make -j$(nproc) CROSS_COMPILE=aarch64-linux-gnu-
cp u-boot.bin ../firmware/
```

Phase 1 默认方案 C 跳过此步。

### Step 5：QEMU 启动命令（方案 C，直接 kernel）

```bash
qemu-system-aarch64 \
    -M virt \
    -cpu cortex-a72 \
    -smp 2 \
    -m 512M \
    -nographic \
    -kernel build/linux-6.12.${PATCH}/arch/arm64/boot/Image \
    -append "root=/dev/vda console=ttyAMA0 rw earlyprintk=serial" \
    -drive if=none,file=build/rootfs.img,format=raw,id=hd0 \
    -device virtio-blk-device,drive=hd0 \
    -netdev user,id=net0,hostfwd=tcp::2222-:22 \
    -device virtio-net-device,netdev=net0 \
    -rtc base=utc
```

关键参数说明：

- `-M virt`：QEMU 虚拟 ARM 平台
- `-cpu cortex-a72`：与 2.3 节选型一致
- `-nographic`：串口重定向到 stdout，符合 G-3
- `-device virtio-blk-device` / `virtio-net-device`：virtio-mmio 总线设备
- `hostfwd=tcp::2222-:22`：host 2222 端口转发到 guest 22，支持 `ssh root@localhost -p 2222`

方案 A（UEFI）等价命令骨架（备选）：

```bash
qemu-system-aarch64 \
    -M virt -cpu cortex-a72 -m 512M -nographic \
    -drive if=pflash,format=raw,readonly=on,file=firmware/AAVMF_CODE.fd \
    -drive if=pflash,format=raw,file=firmware/AAVMF_VARS.fd \
    -drive if=none,file=build/disk.img,id=hd0 \
    -device virtio-blk-device,drive=hd0 \
    -netdev user,id=net0,hostfwd=tcp::2222-:22 \
    -device virtio-net-device,netdev=net0
```

### Step 6：验证

```bash
# 1. 串口：启动后直接看到 kernel log 和 busybox 提示符
# 2. SSH
ssh root@localhost -p 2222  # 密码 root
# 3. 在 guest 内执行
uname -a           # 应显示 aarch64
poweroff -f        # 干净退出
# 4. 测量启动时间
time make boot
```

---

## 5. 目录与文件结构

```
papers/rpa-architecture/rpa-qemu/
├── Makefile                  # 一键入口：build / boot / clean / shell
├── README.md                 # 使用说明、依赖、快速开始
├── configs/
│   ├── kernel.config         # Linux kernel fragment（叠加在 defconfig 上）
│   ├── kernel-rpa.config     # Phase 2 预留：RPA 相关 CONFIG 项
│   └── alpine/
│       ├── apk.list          # chroot 内 `apk add` 的包清单
│       └── rc.conf           # Alpine rc 配置（网络、hostname）
├── scripts/
│   ├── build-kernel.sh       # 下载 + 配置 + 编译 Image
│   ├── build-rootfs.sh       # 下载 minirootfs + chroot 定制 + 打 ext4
│   ├── build-firmware.sh     # 可选：编译 U-Boot 或复制 AAVMF
│   ├── run-qemu.sh           # 封装 qemu-system-aarch64 启动命令
│   └── verify.sh             # 验收 G-1..G-6 自动化检查
├── firmware/                 # AAVMF / U-Boot binary（git-ignored）
├── build/                    # 编译产物（git-ignored）
│   ├── linux-6.12.${PATCH}/
│   ├── rootfs/
│   ├── rootfs.img
│   └── Image
└── notes/
    └── boot-time-log.md      # 每次构建后的启动时间记录，用于追踪回归
```

### 5.1 文件职责

| 文件 | 作用 | Phase 1 是否必须 |
|------|------|------------------|
| `Makefile` | 唯一入口，封装所有脚本 | 是 |
| `configs/kernel.config` | kernel fragment | 是 |
| `configs/alpine/apk.list` | rootfs 包清单 | 是 |
| `scripts/build-kernel.sh` | kernel 构建 | 是 |
| `scripts/build-rootfs.sh` | rootfs 构建 | 是 |
| `scripts/run-qemu.sh` | QEMU 启动 | 是 |
| `scripts/verify.sh` | 自动验收 | 是 |
| `configs/kernel-rpa.config` | RPA CONFIG 预留 | 否（Phase 2） |
| `scripts/build-firmware.sh` | 固件构建 | 否（方案 C 不用） |
| `notes/boot-time-log.md` | 启动时间追踪 | 推荐 |

### 5.2 .gitignore 关键项

```
build/
firmware/*.fd
firmware/*.bin
*.img
```

源码仓库只保留配置和脚本，二进制产物本地生成。

---

## 6. 风险与开放问题

### 6.1 TCG 性能预估

ARM-on-x86 TCG 模拟典型 slowdown：**5-20 倍**，取决于指令类型：

- 整数运算、分支：~5-8x
- 内存密集型（memcpy、页表操作）：~10-15x
- 浮点 / SIMD：~15-20x（TCG 向量化有限）

对 Phase 1 验收（启动到 shell < 30 秒）足够。对 Phase 3 性能测量需切换到 gem5 或 KVM（host=ARM 时）。**结论：TCG 仅用于功能验证，不用于 cycle 级论文数据。**

### 6.2 UEFI vs U-Boot 对 RPA 的影响

| 维度 | UEFI (AAVMF) | U-Boot | 直接 -kernel |
|------|--------------|--------|--------------|
| 早期页表初始化 | 在 EFI 内完成，RPA 域 0 需 post-EFI 接管 | 在 U-Boot 内完成 | 由 kernel head.S 完成 |
| 对 RPA 页表叠加干扰 | 高（EFI 自有页表） | 中 | 低 |
| 调试复杂度 | 高 | 中 | 低 |
| 与真实硬件差距 | 小 | 中 | 大 |

**结论**：Phase 1 用方案 C 最大化 RPA 注入的干净度；Phase 4 评估真实部署时再引入 UEFI。RPA 域 0 的页表叠加入口设在 kernel `paging_init()` 之后，与固件层解耦。

### 6.3 KVM 切换时机

- **Phase 1-3**：TCG，因为 RPA TCG helper 在 `target/arm/` 内，KVM 会绕过 TCG
- **Phase 4**：当 RPA 原语在 TCG 验证完毕、需要真实硬件性能数据时，切换到 ARM host + KVM。但 KVM 模式下 RPA 原语需以 hypervisor trap 形式实现，是另一套工程
- **开放问题**：KVM 路径下 RPA 原语是否可以纯软件 trap 实现，还是必须修 KVM hypervisor 代码？留待 Phase 4 设计

### 6.4 与 mcsoc2026 论文 evaluation 章节的对应

| 论文小节 | Phase 1 提供 | 后续 Phase 补充 |
|----------|--------------|-----------------|
| 实验环境 | QEMU 版本、kernel 版本、Alpine 版本、CPU 模型 | gem5 配置、FPGA 平台 |
| Baseline 启动时间 | 方案 C 启动 wall-clock | TIA 触发开销对比 |
| Baseline 内存占用 | rootfs 大小 | RPA DomainBlock 开销 |
| 功能正确性 | busybox shell 可交互 | RPA 原语功能测试 |
| 性能对比 | （无，TCG 不算数） | Phase 3 gem5 cycle 数据 |

**重要**：论文中必须明确声明「功能验证在 QEMU TCG 上完成，性能数据在 gem5 / FPGA 上获取」，避免审稿人质疑 TCG slowdown 影响。

### 6.5 其他开放问题

1. **devtmpfs 自动挂载**：kernel fragment 已开 `CONFIG_DEVTMPFS_MOUNT`，但需验证 virtio-mmio 设备节点是否自动创建
2. **Alpine musl 与 RPA 测试程序兼容性**：若 RPA 测试用例依赖 glibc，需在 rootfs 中额外安装 `gcompat` 或切换到 Debian arm64 minimal rootfs
3. **9p vs virtiofs**：Phase 1 用 ext4 镜像，Phase 2 调试 RPA 时切到 virtiofs 共享 host 目录，避免每次改动重打镜像
4. **GIC 版本**：`virt` 默认 GICv3，RPA 中断域隔离设计需对齐 GICv3 的 affinity routing

---

## 7. 参考链接

### 7.1 官方文档

- QEMU 文档：<https://www.qemu.org/docs/master/system/arm/virt.html>
- QEMU ARM CPU 模型：<https://www.qemu.org/docs/master/system/arm/cpu-features.html>
- Linux kernel ARM64 boot：<https://www.kernel.org/doc/html/latest/arch/arm64/booting.html>
- Alpine Linux mini rootfs：<https://alpinelinux.org/downloads/>
- EDK2 AAVMF：<https://github.com/tianocore/edk2/tree/edk2-stable/ArmVirtPkg>

### 7.2 内部参考

- RPA 技术规范：`papers/rpa-architecture/notes/TECHNICAL_SPEC.md`
- RPA 研究分析：`papers/rpa-architecture/notes/research_analysis.md`
- RPA 设计要点：`papers/rpa-architecture/notes/DESIGN_NOTES.md`
- Python 模拟器（参考功能定义）：`papers/rpa-architecture/rpa-pysim/`

### 7.3 后续 Phase 衔接

- Phase 2：在 QEMU `target/arm/` 注入 RPA TCG helper（descend/ascend/EXIT）
- Phase 3：gem5 联合仿真，获取 cycle 级性能数据
- Phase 4：KVM 路径或 FPGA 原型，真实硬件性能数据

---

## 附录 A：验收清单（Copy-paste 到 verify.sh）

```
[ ] G-1: qemu-system-aarch64 --version 正常输出
[ ] G-2: 串口出现 "localhost:~#" 或 "Welcome to Alpine Linux"
[ ] G-3: ssh root@localhost -p 2222 可登录
[ ] G-4: time make boot < 30s
[ ] G-5: du -sh build/ < 100M
[ ] G-6: 在干净 git clone 下 make boot 一次性成功
```

## 附录 B：决策摘要

| 决策项 | 选择 | 理由 |
|--------|------|------|
| QEMU 版本 | 9.2 stable | ARM TCG bug 修复完善 |
| 机器型号 | `virt` | 官方维护，virtio 支持最全 |
| CPU 模型 | `cortex-a72` | 贴近真实 SoC，TCG 支持成熟 |
| Kernel | 6.12 LTS | 维护至 2026 年底 |
| Alpine | 3.20 mini rootfs | 体积小、musl+busybox、无 systemd |
| 启动方案 | 方案 C（-kernel） | 最简、最快、RPA 注入最干净 |
| 固件 | 不用（方案 C 跳过） | Phase 4 评估真实部署再引入 |
| 文件系统 | ext4 镜像 | Phase 2 切 virtiofs 便于调试 |
| KVM | Phase 4 再切 | TCG 路径与 RPA TCG helper 一致 |
