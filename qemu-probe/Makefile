# NPA qemu-probe firmware (root / vmB) — host riscv64 gcc or cross
CROSS ?= riscv64-unknown-elf-
CC    := $(CROSS)gcc
CFLAGS := -O2 -ffreestanding -nostdlib -march=rv64gc -mabi=lp64d -mcmodel=medany
LDFLAGS := -nostdlib -static

all: images/root.elf images/vmb.elf

images:
	mkdir -p images

images/root.elf: firmware/root/root.c firmware/root/root.ld | images
	$(CC) $(CFLAGS) $(LDFLAGS) -T firmware/root/root.ld -o $@ firmware/root/root.c

images/vmb.elf: firmware/vmB/vmb.c firmware/root/root.ld | images
	$(CC) $(CFLAGS) $(LDFLAGS) -T firmware/root/root.ld -o $@ firmware/vmB/vmb.c

clean:
	rm -f images/root.elf images/vmb.elf

.PHONY: all clean
