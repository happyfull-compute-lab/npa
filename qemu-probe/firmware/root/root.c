/* NPA root — deprivileged_call: S-mode parent, U-mode child, ecall→stvec. */
#include <stdint.h>

#define UART0 0x10000000UL
#define EID_NPA 0x4E504100UL
#define FID_ASCEND 1
#define REASON_SERVICE 0
#define LIFE_FREE 0
#define LIFE_LIVE 1
#define LIFE_TERM 2

static int cur = -1;
static uint64_t parent_cont;

static void uart_puts(const char *s)
{
	volatile uint8_t *u = (volatile uint8_t *)UART0;
	while (*s) {
		char c = *s++;
		if (c == '\n')
			*u = '\r';
		*u = (uint8_t)c;
	}
}

static void uart_puthex(uint64_t v)
{
	static const char *h = "0123456789abcdef";
	uart_puts("0x");
	for (int i = 60; i >= 0; i -= 4) {
		volatile uint8_t *u = (volatile uint8_t *)UART0;
		*u = (uint8_t)h[(v >> i) & 0xf];
	}
}

void npa_c_handler(uint64_t scause, uint64_t sepc,
		   uint64_t g_a0, uint64_t g_a1, uint64_t g_a6, uint64_t g_a7)
{
	if ((scause & 0xff) == 8) {
		uint64_t a0 = g_a0, a1 = g_a1, a6 = g_a6, a7 = g_a7;
		if (a7 == EID_NPA && a6 == FID_ASCEND) {
			uart_puts("[S] ASCEND reason=");
			uart_puthex(a0);
			uart_puts(" x=");
			uart_puthex(a1);
			uart_puts(" id=");
			uart_puthex(3);
			uart_puts("\n");
			asm volatile("csrw sepc, %0" :: "r"(parent_cont));
			uint64_t s;
			asm volatile("csrr %0, sstatus" : "=r"(s));
			s |= (1UL << 8);
			asm volatile("csrw sstatus, %0" :: "r"(s));
			return;
		}
	}
	uart_puts("[S] trap cause=");
	uart_puthex(scause);
	uart_puts(" sepc=");
	uart_puthex(sepc);
	uart_puts("\n");
	asm volatile("csrw sepc, %0" :: "r"(sepc + 4));
}

__attribute__((aligned(4), naked)) void npa_trap_entry(void)
{
	asm volatile(
		"addi sp, sp, -128\n"
		"sd ra, 0(sp)\n"
		"sd t0, 8(sp)\n"
		"sd t1, 16(sp)\n"
		"sd a0, 32(sp)\n"
		"sd a1, 40(sp)\n"
		"sd a6, 80(sp)\n"
		"sd a7, 88(sp)\n"
		"csrr t0, scause\n"
		"csrr t1, sepc\n"
		"ld a2, 32(sp)\n"
		"ld a3, 40(sp)\n"
		"ld a4, 80(sp)\n"
		"ld a5, 88(sp)\n"
		"mv a0, t0\n"
		"mv a1, t1\n"
		"jal ra, npa_c_handler\n"
		"ld ra, 0(sp)\n"
		"ld t0, 8(sp)\n"
		"ld t1, 16(sp)\n"
		"ld a0, 32(sp)\n"
		"ld a1, 40(sp)\n"
		"ld a6, 80(sp)\n"
		"ld a7, 88(sp)\n"
		"addi sp, sp, 128\n"
		"sret\n"
	);
}

static void vmb_entry(void)
{
	volatile uint8_t *u = (volatile uint8_t *)UART0;
	const char *s = "[vmB] U-mode ecall ascend\n";
	while (*s) {
		char c = *s++;
		if (c == '\n')
			*u = '\r';
		*u = (uint8_t)c;
	}
	register uint64_t a0 asm("a0") = REASON_SERVICE;
	register uint64_t a1 asm("a1") = 0x6869626dUL;
	register uint64_t a6 asm("a6") = FID_ASCEND;
	register uint64_t a7 asm("a7") = EID_NPA;
	asm volatile("ecall" : "+r"(a0), "+r"(a1) : "r"(a6), "r"(a7) : "memory");
	for (;;)
		asm volatile("nop");
}

static void enter_umode(uint64_t entry)
{
	parent_cont = (uint64_t)(uintptr_t)&&parent_out;
	asm volatile(
		"li t0, 0x100\n"
		"csrc sstatus, t0\n"
		"csrw sepc, %0\n"
		"sret\n"
		:
		: "r"(entry)
		: "t0", "memory"
	);
parent_out:
	uart_puts("[S] parent continuation (software policy)\n");
}

void npa_root_main(void)
{
	uart_puts("[S] NPA root v0.6 deprivileged_call\n");
	uint64_t tvec = (uint64_t)(uintptr_t)npa_trap_entry;
	asm volatile("csrw stvec, %0" :: "r"(tvec));
	uart_puts("[S] stvec set; sret U-mode vmB\n");
	cur = 1;
	enter_umode((uint64_t)(uintptr_t)vmb_entry);
	uart_puts("[S] sequence done\n");
	for (;;)
		asm volatile("nop");
}

__attribute__((section(".text._start"))) void _start(void)
{
	asm volatile("lla sp, _stack_top");
	npa_root_main();
}
