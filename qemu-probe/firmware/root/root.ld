OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
  RAM (rwx) : ORIGIN = 0x80200000, LENGTH = 16M
}
SECTIONS {
  .text : {
    *(.text._start)
    *(.text*)
  } > RAM
  .rodata : { *(.rodata*) } > RAM
  .data : { *(.data*) } > RAM
  .bss : { *(.bss*) *(COMMON) } > RAM
  _stack_top = ORIGIN(RAM) + LENGTH(RAM) - 0x1000;
}
