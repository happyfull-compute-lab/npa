# NPA RISC-V QEMU Probe — Design

> Status: design first, implement after review.  
> Goal: run an NPA-shaped stack on RISC-V QEMU and stress the frozen spec.

---

## 1. Topology (map to NPA)

```text
NPA domain tree                         QEMU / RISC-V role
────────────────────────────────────────────────────────────
root domain (id=0)                      custom minimal firmware (root sec / RoT)
  └─ hyp domain (id=1)                  hypervisor **layer** (HS on every hart)
       ├─ vmA domain (id=2)             U-Boot (EFI) → Linux, 2 vCPU
       └─ vmB domain (id=3)             simple bare-metal firmware, 1 vCPU
```

**Model A + asymmetric 3 harts (chosen):**

- Hyp is **not** a dedicated core; it is the HS privilege layer on each hart
  (trap lands locally, no IPI-to-manager).
- Physical: `-smp 3` only — **no** spare housekeeping hart.
- vCPU quota: vmA=2, vmB=1, total 3; root shares boot hart then yields.

| Domain | vCPU quota | Console | Boot media |
|--------|------------|---------|------------|
| root | boot hart, then yield | `:0 root` | custom firmware |
| hyp | layer on all 3 harts | `:1 hyp` | hyp.elf / linked in root or HS payload |
| vmA Linux | **2** | `:2 linux` | U-Boot → EFI → Linux + rootfs |
| vmB firmware | **1** | `:3 vmfw` | tiny ELF |

`domain ≠ hart`: a domain may run on multiple harts; C1 `child` is a domain
link, not one-core-one-child. Cross-hart scheduling stays software (hyp).

---

## 2. Console / tmux layout

Each logical console maps to one QEMU serial / virtio-console, one tmux pane.

```text
tmux session: npa-qemu
┌───────────────┬───────────────┐
│ 0 root        │ 1 hyp         │
├───────────────┼───────────────┤
│ 2 linux (2c)  │ 3 vmfw (1c)   │
└───────────────┴───────────────┘
```

Implementation sketch:

- `qemu ... -serial mon:stdio` only for debug (not used)
- Prefer **4× virtio-serial / chardev** → 4 PTYs or unix sockets
- tmux `new-session` + `split-window` + `send-keys` / `pipe-pane` to attach each console
- Script: `scripts/npa_tmux.sh` creates the 4-pane layout and attaches chardevs

RISC-V `virt` typically uses `8250` / `sifive_uart` per machine; for multiple
guests under one QEMU, consoles are **per vCPU VM backend** (see §3).

---

## 3. Virtualization strategy (two options)

### Option A — One QEMU, NPA-shaped (chosen)

- QEMU `virt`, **3 harts**, RISC-V H if available (else TCG HS mapping).
- **root** firmware sets up DCBs, then yields to hyp layer.
- **hyp** is HS layer on every hart; guests (vmA, vmB) are VS/child domains.
- vmA two vCPUs + vmB one vCPU **fill the three harts** (asymmetric stress).
- True nesting: `descend`/`ascend` cross domains on the **current** hart.

### Option B — Multi-instance QEMU (fallback if H/TCG gap)

- Separate QEMU processes for smoke boot only.
- NPA transitions modeled via SBI/chardev shim.
- **Not** the target; use only if A blocks on tooling.

**Recommendation:** implement **A** as designed; keep B scripts as emergency
console bring-up.

---

## 4. NPA primitive transport (probe layer)

We do **not** patch QEMU TCG in phase 1.

| Primitive | RISC-V carrier (phase 1) |
|-----------|---------------------------|
| `descend(dcb)` | SBI extension or custom `ecall` from HS → target VS |
| `ascend(reason,x)` | SBI ecall / hypercall from VS → HS |
| DCB | Shared memory page (root-owned), passed in `a0` |
| lifecycle | hyp software state (probe), later HW |

Later (QEMU phase 2): encode `descend`/`ascend` as real instructions and walk
DCB in the emulator.

---

## 5. Root firmware (minimal)

Responsibilities:

1. Early init, claim DCB arena (identity map)
2. Create hyp DCB (`entry`, `ipa`, `edel=0` until probed)
3. `descend(hyp)`
4. Handle `ascend` from hyp (services, EXIT/reap)
5. Keep **root sec** identity (preset list: hyp/vmA/vmB ids)

Console: pane `:0`.

---

## 6. Hyp (simple)

1. Create vmA and vmB DCBs
2. Schedule loop: `descend` one VM, on `ascend` service, resume or switch
3. C1 single `child` link: software `rebind` when switching vmA ↔ vmB
4. vmA: hand off to U-Boot; vmB: jump to firmware ELF entry

Console: pane `:1`.

### vmA path (U-Boot → Linux)

```text
hyp descend(vmA) → u-boot → (EFI stub later) → Linux (2 vCPU)
Linux / SBI ecall → hyp (ascend SERVICE) → hyp or root
```

Phase 1 may let Linux use stock OpenSBI while we only *model* NPA transitions
around boot; full syscall→ascend mapping is phase 2.

### vmB path (firmware)

Bare-metal: write console, issue `ascend(SERVICE)` once, `ascend(EXIT)` or loop.

---

## 6b. Image sources (simplest path)

Goal: **one defconfig**, few moving parts, U-Boot (EFI) → Linux on vmA.

### Chosen: Buildroot LTS + `qemu_riscv64_virt_defconfig`

| Item | Choice | Why |
|------|--------|-----|
| Builder | **Buildroot 2025.02.x LTS** (until 2028-03) | Stable line; matches “simple, keep working” |
| Defconfig | `configs/qemu_riscv64_virt_defconfig` | Upstream-tested for QEMU `virt` |
| Boot chain | OpenSBI → **U-Boot** → Linux Image + rootfs | Matches vmA story (EFI optional later) |
| rootfs | initramfs (cpio) first; ext4 later | No block stack required at M3 |
| Console | `ttyS0` (8250) + `console=ttyS0` | Simplest; virtio-console later if needed |

```bash
# illustrative — implement in M3
wget https://buildroot.org/downloads/buildroot-2025.02.19.tar.xz
tar xf buildroot-2025.02.19.tar.xz
cd buildroot-2025.02.19
make qemu_riscv64_virt_defconfig
make -j$(nproc)
# images/: opensbi fw, u-boot.bin, Image / rootfs.cpio
```

### Firmware pieces

| Image | Source | Used by |
|-------|--------|---------|
| OpenSBI (`fw_jump` / `fw_dynamic`) | Buildroot output | all guests / `-bios` |
| U-Boot | Buildroot | **vmA** only |
| Linux `Image` + `rootfs.cpio` | Buildroot | **vmA** |
| **vmB firmware** | **hand-written ELF** in `firmware/vmB/` | **vmB** |
| **root firmware** | **hand-written** in `firmware/root/` | root domain |

### vmA kernel cmdline (draft)

```
console=ttyS0 earlycon root=/dev/ram0 rw
```

### Explicitly not using (for now)

- Distro cloud images (qcow2) — heavier disk path
- Custom Yocto — overkill for probe
- Prebuilt third-party blobs — keep build reproducible in-tree

### Host packages (build)

Need a riscv64 toolchain **inside Buildroot** (it builds its own by default),
so host only needs: `gcc g++ make git wget cpio python3 unzip rsync file bc`.

### EFI note

`qemu_riscv64_virt` U-Boot can do EFI; for **M3** we first boot
U-Boot → `booti`/`bootm` the Buildroot Image. Full **EFI stub** can be a
follow-up checkbox once the 3-hart bring-up works.

---

## 7. Memory / isolation (first probe)

| Check | How |
|-------|-----|
| vmA cannot write hyp/root data | PMP or hyp page tables / separate QEMU addr spaces (B) |
| vmB cannot read vmA | separate images (B); later PMP regions |
| DCB not writable by child | root maps DCB RW, children RO or absent |
| csec later | optional region + key stub in hyp |

Phase 1 with Option B = **process isolation**; record that as a *proxy* and
note I21–I28 not fully proven until Option A.

---

## 8. Artifacts to produce

```text
npa/qemu-probe/
  DESIGN.md              ← this file
  scripts/
    npa_tmux.sh          ← 4-pane session
    run_vmA_linux.sh     ← QEMU -smp 2 + U-Boot + Linux
    run_vmB_fw.sh        ← QEMU -smp 1 + firmware
    run_root_hyp.sh      ← control plane (phase 1)
  firmware/
    root/                ← minimal root
    hyp/                 ← simple hyp
    vmB/                 ← tiny guest
  config/
    npa-domain.map       ← id ↔ console ↔ cmdline
```

Build: host `gcc` + `gcc-riscv64-unknown-elf` or clang; U-Boot/Linux binaries
via existing images or buildroot (phase 1 can use upstream prebuilts).

### QEMU source policy

- **Do not** use distro `apt` QEMU for this probe.
- Build **from source** in a dedicated tree: `~/git/qemu-npa` (clone
  `stable-10.2` / `v10.2.4`), so we can patch TCG/HS later.
- **LTS choice:** `v10.2.4` is the current QEMU LTS line (11.2 not tagged
  yet). Rebase to 11.2 LTS when it ships if needed.
- Configure at least: `riscv64-softmmu` (or `--target-list=riscv64-softmmu`),
  virtio, tracing/debugging as required.

---

## 9. Milestones

| M | Deliverable | Pass |
|---|-------------|------|
| M0 | Design reviewed | this doc |
| M1 | tmux 4 panes + **one** QEMU (`-smp 3`) consoles alive | panes show boot logs |
| M2 | vmB firmware boots on **1** vCPU | console prints banner |
| M3 | vmA Linux boots on **2** vCPU via U-Boot | `smp` in Linux console |
| M4 | root+hyp stub, `descend`/`ascend` on current hart | hyp console shows enters |
| M5 | Isolation negative tests (asymmetric 3-hart) | denied access logged |
| M6 | Map findings back to NPA spec I* | update SPEC if clash |

---

## 10. Open points (need author OK)

1. ~~Option A vs B~~ — **A chosen**, 3-hart asymmetric (2+1 vCPU).
2. ~~Linux/U-Boot image source~~ — **Buildroot 2025.02 LTS**
   `qemu_riscv64_virt_defconfig`; EFI stub later.
3. Whether `descend/ascend` must be SBI vs custom CSR in QEMU phase 2.
4. Console: virtio-console vs 8250-only (**8250 first**).
