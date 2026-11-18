#!/usr/bin/env bash
set -euo pipefail
BR=/home/dev/git/npa/qemu-probe/images/buildroot-2025.02.19/output/images
QEMU=${QEMU:-/home/dev/git/qemu-npa/build/qemu-system-riscv64}
exec "$QEMU" -machine virt -smp 1 -m 512M -nographic -bios "$BR/fw_jump.bin" -kernel "$BR/u-boot.bin"
