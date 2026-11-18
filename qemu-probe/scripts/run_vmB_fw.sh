#!/usr/bin/env bash
# Smoke: vmB bare-metal firmware ELF (1 vCPU).
set -euo pipefail
BR=/home/dev/git/npa/qemu-probe/images
QEMU=${QEMU:-/home/dev/git/qemu-npa/build/qemu-system-riscv64}

exec "$QEMU" \
  -machine virt \
  -smp 1 \
  -m 128M \
  -nographic \
  -bios none \
  -kernel "$BR/vmb.elf"
