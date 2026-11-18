/* NPA root firmware (minimal) — RISC-V virt, bare-metal.
 * Role: root domain (id=0). Creates hyp DCB, descend(hyp), handles ascend.
 * Console: 8250 at QEMU virt UART0 (0x10000000).
 */
#include <stdint.h>

#define UART0 0x10000000UL

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

/* DCB Spec Field offsets (NPA v0.3) */
#define DCB_SZ      0x00
#define DCB_ID      0x04
#define DCB_ENTRY   0x08
#define DCB_EDEL    0x0C
#define DCB_EXC     0x10
#define DCB_IRQ     0x14
#define DCB_IPA     0x18
#define DCB_PTB     0x1C
#define DCB_CHILD   0x20
#define DCB_SEC     0x24

#define HYP_DCB_PADDR 0x82000000UL
#define VMA_DCB_PADDR 0x82001000UL
#define VMB_DCB_PADDR 0x82002000UL

static inline void w32(unsigned long a, uint32_t v)
{
	*(volatile uint32_t *)a = v;
}

static void dcb_init(unsigned long paddr, uint32_t id, uint32_t entry,
		     uint32_t edel, uint32_t ipa, uint32_t ptb)
{
	w32(paddr + DCB_SZ, 10);          /* 10 words Spec */
	w32(paddr + DCB_ID, id);
	w32(paddr + DCB_ENTRY, entry);
	w32(paddr + DCB_EDEL, edel);
	w32(paddr + DCB_EXC, 0);
	w32(paddr + DCB_IRQ, 0);
	w32(paddr + DCB_IPA, ipa);
	w32(paddr + DCB_PTB, ptb);
	w32(paddr + DCB_CHILD, 0);
	w32(paddr + DCB_SEC, 0);
}

/* Phase-1 stub: ecall-based descend/ascend (SBI-like probe ABI). */
static void npa_descend(unsigned long dcb)
{
	register unsigned long a0 asm("a0") = dcb;
	/* custom SBI-like: eid=0x4E504100 'NPA\\0', fid=1 */
	register unsigned long a7 asm("a7") = 0x4E504100UL;
	asm volatile("ecall" : "+r"(a0) : "r"(a7) : "memory");
}

static void npa_ascend(uint32_t reason, unsigned long x)
{
	register unsigned long a0 asm("a0") = reason;
	register unsigned long a1 asm("a1") = x;
	register unsigned long a7 asm("a7") = 0x4E504100UL;
	register unsigned long a6 asm("a6") = 2; /* fid ascend */
	asm volatile("ecall" : "+r"(a0) : "r"(a1), "r"(a6), "r"(a7) : "memory");
}

void npa_root_main(void)
{
	uart_puts("[root] NPA root firmware v0.3 (probe)\n");

	/* Hyp DCB: id=1, entry filled by hyp payload or placeholder */
	dcb_init(HYP_DCB_PADDR, 1, 0x80200000UL, 0, 0, 0);
	/* Child DCBs prepared by root; hyp may rebind */
	dcb_init(VMA_DCB_PADDR, 2, 0x80200000UL, 1, 0, 0);
	dcb_init(VMB_DCB_PADDR, 3, 0x80201000UL, 0, 0, 0);

	uart_puts("[root] DCBs ready; descend(hyp)\n");
	npa_descend(HYP_DCB_PADDR);

	/* If ascend returns here, service loop */
	for (;;) {
		uart_puts("[root] ascend from child (stub)\n");
		npa_ascend(3 /* EXIT */, 0); /* not used if root — loop */
		for (;;)
			asm volatile("wfi");
	}
}

__attribute__((section(".text._start"))) void _start(void)
{
	asm volatile("lla sp, _stack_top");
	npa_root_main();
	for (;;)
		asm volatile("wfi");
}
