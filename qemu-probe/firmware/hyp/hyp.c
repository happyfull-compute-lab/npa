/* NPA hyp stub — HS-layer probe (phase 1).
 * Creates child DCB links, loops on ascend; later real HS mapping.
 */
#include <stdint.h>

#define UART0 0x10000000UL
#define UART1 0x10000000UL /* same virt UART until multi-console */

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

/* Probe: while ecall ABI is not in QEMU, hyp logs intent only. */
void npa_hyp_main(void)
{
	uart_puts("[hyp] NPA hyp stub v0.3 (layer on all harts)\n");
	uart_puts("[hyp] schedule: rebind child + descend (C1)\n");
	uart_puts("[hyp] waiting for ecall ascend from vmA/vmB\n");
	for (;;)
		asm volatile("wfi");
}
