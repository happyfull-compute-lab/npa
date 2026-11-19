/* NPA root — minimal Linux boot (no OpenSBI / U-Boot / EFI).
 *
 * ecall == ascend. Linux SBI calls arrive as ascend(SERVICE).
 * Custom DESCEND enters the Linux domain (a0=dcb, a1=entry).
 */
#include <stdint.h>

#define UART0 0x10000000UL
#define EID_NPA 0x4E504100UL

/* SBI a7: legacy console 0x01, base 0x10, TIME 0x54494D45, SRST 0x53525354 */
#define SBI_CONSOLE_PUTCHAR 0x01
#define SBI_EXT_TIME        0x54494D45
#define SBI_EXT_SRST        0x53525354

static void uart_init(void)
{
	volatile uint8_t *u = (volatile uint8_t *)UART0;
	u[1] = 0x00; /* IER */
	u[3] = 0x80; /* LCR DLAB */
	u[0] = 0x01; /* DLL */
	u[1] = 0x00; /* DLM */
	u[3] = 0x03; /* 8n1 */
	u[2] = 0xC7; /* FIFO */
	u[4] = 0x0B; /* DTR RTS OUT2 */
}

static void uart_putc(char c)
{
	volatile uint8_t *u = (volatile uint8_t *)UART0;
	*u = (uint8_t)c;
}

static void uart_puts(const char *s)
{
	while (*s) {
		if (*s == '\n')
			uart_putc('\r');
		uart_putc(*s++);
	}
}

/* Linux entry: a0=hartid, a1=dtb */
typedef void (*linux_entry_t)(unsigned long hartid, unsigned long dtb);

static uint64_t linux_entry_addr;
static uint64_t linux_dtb_addr;
static uint64_t parent_cont;

/* SBI-ish via ascend handler */
static void npa_service(uint64_t a7, uint64_t a6, uint64_t a0)
{
	(void)a6;
	if (a7 == SBI_CONSOLE_PUTCHAR) {
		uart_putc((char)a0);
		return;
	}
	if (a7 == SBI_EXT_SRST) {
		uart_puts("[root] SRST\n");
		for (;;)
			asm volatile("nop");
	}
	/* TIME / others: stub ok for early boot */
}

void npa_c_handler(uint64_t scause, uint64_t sepc)
{
	uint64_t a0, a1, a7;
	asm volatile("mv %0, a0" : "=r"(a0));
	asm volatile("mv %0, a1" : "=r"(a1));
	asm volatile("mv %0, a7" : "=r"(a7));

	if ((scause & 0xff) == 8) {
		/* ecall == ascend; Linux SBI uses a7 as extension */
		npa_service(a7, 0, a0);
		/* return success in a0 */
		asm volatile("mv a0, zero");
		asm volatile("csrw sepc, %0" :: "r"(sepc + 4));
		uint64_t s;
		asm volatile("csrr %0, sstatus" : "=r"(s));
		s |= (1UL << 8); /* SPP=S if we return to S; Linux runs S for now */
		asm volatile("csrw sstatus, %0" :: "r"(s));
		return;
	}
	uart_puts("[root] trap cause sepc\n");
	asm volatile("csrw sepc, %0" :: "r"(sepc + 4));
}

__attribute__((aligned(4), naked)) void npa_trap_entry(void)
{
	asm volatile(
		"addi sp, sp, -128\n"
		"sd ra, 0(sp)\n"
		"sd t0, 8(sp)\n"
		"sd t1, 16(sp)\n"
		"csrr t0, scause\n"
		"csrr t1, sepc\n"
		"mv a0, t0\n"
		"mv a1, t1\n"
		"jal ra, npa_c_handler\n"
		"ld ra, 0(sp)\n"
		"ld t0, 8(sp)\n"
		"ld t1, 16(sp)\n"
		"addi sp, sp, 128\n"
		"sret\n"
	);
}

/* QEMU custom-0 DESCEND: opcode 0x0B, funct3=0 */
static inline long npa_descend_insn(unsigned long dcb, unsigned long entry)
{
	register long a0 asm("a0") = (long)dcb;
	register long a1 asm("a1") = (long)entry;
	register long rd asm("a0");
	asm volatile(".insn r 0x0B, 0, 0, %0, %1, %2"
		     : "=r"(rd)
		     : "r"(a0), "r"(a1)
		     : "memory");
	return (long)rd;
}

void npa_root_main(unsigned long hartid, unsigned long dtb)
{
	uart_init();
	uart_puts("[root] NPA root v0.7 — boot Linux (no SBI/U-Boot/EFI)\n");

	uint64_t tvec = (uint64_t)(uintptr_t)npa_trap_entry;
	asm volatile("csrw stvec, %0" :: "r"(tvec));

	/* Linux Image is loaded by QEMU -device loader at 0x80200000 */
	linux_entry_addr = 0x80200000UL;
	linux_dtb_addr = dtb ? dtb : 0x81000000UL;

	uart_puts("[root] enter Linux entry=");
	/* Print hex briefly */
	for (int i = 0; i < 16; i++) {
		char c = "0123456789abcdef"[(linux_entry_addr >> (60 - 4 * i)) & 0xf];
		uart_putc(c);
	}
	uart_puts("\n");

	/* If Linux image is not this ELF, user loads separately.
	 * This root is the NPA service CPU once Linux ecalls. */
	parent_cont = 0;
	asm volatile("csrw sepc, %0" :: "r"(linux_entry_addr));
	asm volatile("mv a0, %0" :: "r"(hartid));
	asm volatile("mv a1, %0" :: "r"(linux_dtb_addr));
	uint64_t s;
	asm volatile("csrr %0, sstatus" : "=r"(s));
	s &= ~(1UL << 8); /* SPP=U optional; keep S for early Linux */
	s |= (1UL << 8);
	asm volatile("csrw sstatus, %0" :: "r"(s));
	asm volatile("sret");

	for (;;)
		asm volatile("nop");
}

__attribute__((section(".text._start"), naked)) void _start(void)
{
	asm volatile(
		"lla sp, _stack_top\n"
		"j npa_root_main\n"
	);
}
