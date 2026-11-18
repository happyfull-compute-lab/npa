#!/usr/bin/env bash
# vmA: OpenSBI + Linux (2-3 vCPU). U-Boot path is experimental (run_uboot_only).
# Full U-Boot -> booti chain needs Image on a bootable medium (M3 follow-up).
set -euo pipefail
BR=/home/dev/git/npa/qemu-probe/images/buildroot-2025.02.19/output/images
QEMU=${QEMU:-/home/dev/git/qemu-npa/build/qemu-system-riscv64}
SMP=${SMP:-2}
exec "$QEMU" -machine virt -smp "$SMP" -m 512M -nographic \
  -bios "$BR/fw_jump.bin" -kernel "$BR/Image" \
  -append "console=ttyS0 root=/dev/vda ro" \
  -drive file="$BR/rootfs.ext2",format=raw,if=none,id=hd0 \
  -device virtio-blk-device,drive=hd0
