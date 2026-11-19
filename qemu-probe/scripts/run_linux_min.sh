#!/usr/bin/env bash
# Minimal Linux on NPA QEMU — no OpenSBI / U-Boot / EFI.
# Root firmware is the first domain; ecall=ascend to root SBI subset.
set -euo pipefail
BR=/home/dev/git/npa/qemu-probe/images/buildroot-2025.02.19/output/images
QEMU=${QEMU:-/home/dev/git/qemu-npa/build/qemu-system-riscv64}
ROOT_ELF=${ROOT_ELF:-/home/dev/git/npa/qemu-probe/images/root.elf}
SMP=${SMP:-1}

# Build root if missing
if [ ! -f "$ROOT_ELF" ]; then
  make -C /home/dev/git/npa/qemu-probe CROSS=riscv64-buildroot-linux-gnu- \
    images/root.elf 2>/dev/null || true
fi

exec "$QEMU" -machine virt -smp "$SMP" -m 512M -nographic \
  -bios none \
  -kernel "$ROOT_ELF" \
  -append "console=ttyS0 root=/dev/ram0 rw" \
  -initrd "$BR/rootfs.cpio" \
  -dtb /dev/null 2>/dev/null || \
exec "$QEMU" -machine virt -smp "$SMP" -m 512M -nographic \
  -bios none \
  -kernel "$BR/Image" \
  -append "console=ttyS0 root=/dev/ram0 rw" \
  -initrd "$BR/rootfs.cpio"
