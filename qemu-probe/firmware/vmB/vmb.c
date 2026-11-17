/* NPA vmB guest firmware (1 vCPU) — bare-metal probe. */
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

void npa_vmb_main(void)
{
	uart_puts("[vmB] NPA firmware guest v0.3\n");
	uart_puts("[vmB] ascend(SERVICE, hello-from-vmB)\n");
	register unsigned long a0 asm("a0") = 0; /* SERVICE */
	register unsigned long a1 asm("a1") = 0x6869626dUL; /* 'mbhi' tag */
	register unsigned long a6 asm("a6") = 2;
	register unsigned long a7 asm("a7") = 0x4E504100UL;
	asm volatile("ecall" : "+r"(a0) : "r"(a1), "r"(a6), "r"(a7) : "memory");
	uart_puts("[vmB] back from ascend; loop\n");
	for (;;)
		asm volatile("wfi");
}
