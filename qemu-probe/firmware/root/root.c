/* NPA root firmware — DCB + lifecycle + descend/ascend (probe ABI).
 *
 * Software model of NPA semantics for QEMU bring-up. Maps to
 * SPEC_NPA_CORE I1–I20 and qemu-probe/SPEC_ABI.md.
 */
#include <stdint.h>
#include <stddef.h>

#define UART0 0x10000000UL

#define EID_NPA 0x4E504100UL
#define FID_DESCEND 0
#define FID_ASCEND  1
#define FID_REAP    2

#define OK 0
#define EBADDCB (-1)
#define ETERM   (-2)
#define ENOROOT (-3)
#define ENOTCHILD (-4)
#define EPERM   (-5)

#define REASON_SERVICE   0
#define REASON_RESULT    1
#define REASON_EXCEPTION 2
#define REASON_EXIT      3

#define LIFE_FREE 0
#define LIFE_LIVE 1
#define LIFE_TERM 2

#define MAX_DOM 8

typedef struct {
	uint32_t sz;      /* 0x00 */
	uint32_t id;      /* 0x04 */
	uint32_t entry;   /* 0x08 */
	uint32_t edel;    /* 0x0C */
	uint32_t exc;     /* 0x10 */
	uint32_t irq;     /* 0x14 */
	uint32_t ipa;     /* 0x18 */
	uint32_t ptb;     /* 0x1C */
	uint32_t child;   /* 0x20 */
	uint32_t sec;     /* 0x24 */
} dcb_t;

typedef struct {
	uint64_t pc;   /* resume/return point (Context, not Spec) */
	uint64_t sp;
	uint64_t x[4]; /* probe arg/ret slots */
} ctx_t;

typedef struct {
	int used;
	int life;          /* FREE / LIVE / TERM */
	uint32_t dcb_pa;
	dcb_t dcb;
	ctx_t ctx;
	int parent;        /* index or -1 */
} domain_t;

static domain_t doms[MAX_DOM];
static int cur = -1;          /* current domain index */
static uint32_t next_id = 1;

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

static void uart_hex(uint64_t v)
{
	static const char *h = "0123456789abcdef";
	uart_puts("0x");
	for (int i = 60; i >= 0; i -= 4)
		uart_putc(h[(v >> i) & 0xf]);
}

static int find_by_dcb(uint32_t pa)
{
	for (int i = 0; i < MAX_DOM; i++)
		if (doms[i].used && doms[i].dcb_pa == pa)
			return i;
	return -1;
}

static int alloc_dom(void)
{
	for (int i = 0; i < MAX_DOM; i++)
		if (!doms[i].used)
			return i;
	return -1;
}

/* ---- NPA core (software executable semantics) ---- */

static int npa_reap_core(int parent_idx, uint32_t dcb_pa)
{
	int i = find_by_dcb(dcb_pa);
	if (i < 0)
		return ENOTCHILD;
	if (doms[i].parent != parent_idx)
		return EPERM;
	if (doms[i].life == LIFE_FREE)
		return ENOTCHILD;
	doms[i].life = LIFE_FREE;
	doms[i].ctx = (ctx_t){0};
	doms[i].used = 0;
	if (parent_idx >= 0 && doms[parent_idx].dcb.child == dcb_pa)
		doms[parent_idx].dcb.child = 0;
	uart_puts("[root] reap id=");
	uart_hex(doms[i].dcb.id);
	uart_puts(" lifecycle->FREE\n");
	return OK;
}

/* Called when child wants to leave. Returns to parent's descend site. */
static void npa_ascend_core(uint32_t reason, uint64_t x)
{
	int c = cur;
	if (c < 0)
		return;
	int p = doms[c].parent;
	if (p < 0) {
		uart_puts("[root] ENOROOT ascend\n");
		for (;;)
			asm volatile("wfi");
	}

	/* Save child Context (pc after ecall / probe call). */
	/* In call-model, parent resume is C return; child stays LIVE unless EXIT. */
	if (reason == REASON_EXIT) {
		doms[c].life = LIFE_TERM;
		doms[p].dcb.child = 0;
		uart_puts("[root] EXIT id=");
		uart_hex(doms[c].dcb.id);
		uart_puts(" -> TERM\n");
	}

	uart_puts("[root] ascend reason=");
	uart_hex(reason);
	uart_puts(" x=");
	uart_hex(x);
	uart_puts(" from id=");
	uart_hex(doms[c].dcb.id);
	uart_puts(" -> parent id=");
	uart_hex(doms[p].dcb.id);
	uart_puts("\n");

	/* parent sees reason/x in its probe slots */
	doms[p].ctx.x[0] = reason;
	doms[p].ctx.x[1] = x;
	cur = p;
}

static int npa_descend_core(int pidx, uint32_t dcb_pa)
{
	if (pidx < 0)
		return ENOROOT;
	dcb_t tmp;
	/* caller must have filled dcb in table; validate */
	int i = find_by_dcb(dcb_pa);
	if (i < 0)
		return EBADDCB;
	dcb_t *d = &doms[i].dcb;
	if (d->sz < 10)
		return EBADDCB;

	if (doms[i].life == LIFE_TERM)
		return ETERM;

	if (doms[pidx].dcb.child != 0 && doms[pidx].dcb.child != dcb_pa)
		return EPERM; /* C1: one current child */

	/* first vs resume (I18) */
	if (doms[i].life == LIFE_FREE) {
		if (d->entry == 0)
			return EBADDCB;
		doms[i].ctx.pc = d->entry;
		doms[i].life = LIFE_LIVE;
		uart_puts("[root] descend first id=");
		uart_hex(d->id);
		uart_puts(" entry=");
		uart_hex(d->entry);
		uart_puts("\n");
	} else {
		uart_puts("[root] descend resume id=");
		uart_hex(d->id);
		uart_puts(" pc=");
		uart_hex(doms[i].ctx.pc);
		uart_puts("\n");
	}

	doms[pidx].dcb.child = dcb_pa;
	doms[i].parent = pidx;
	cur = i;
	return OK;
}

/* ---- ecall ABI (guest) ---- */
/* Minimal: not wired to real S-mode yet; root uses direct API. */

/* ---- domain payloads ---- */

static void setup_dcb(dcb_t *d, uint32_t id, uint32_t entry, uint32_t edel)
{
	d->sz = 10;
	d->id = id;
	d->entry = entry;
	d->edel = edel;
	d->exc = 0;
	d->irq = 0;
	d->ipa = 0;
	d->ptb = 0;
	d->child = 0;
	d->sec = 0;
}

/* vmB guest body (runs as call-model child) */
static int vmb_body(void)
{
	uart_puts("[vmB] start (call-model domain)\n");
	uart_puts("[vmB] ascend(SERVICE)\n");
	/* This function cannot directly npa_ascend without a return path;
	 * root simulates by calling npa_ascend_core after we return reason.
	 * Real ecall path comes when trap vector is wired (next step).
	 */
	return REASON_SERVICE;
}

void npa_root_main(void)
{
	uart_puts("[root] NPA root firmware v0.3 (DCB+lifecycle)\n");

	/* root domain */
	doms[0].used = 1;
	doms[0].life = LIFE_LIVE;
	doms[0].dcb_pa = 0x82000000UL;
	setup_dcb(&doms[0].dcb, 0, 0, 0);
	doms[0].parent = -1;
	cur = 0;

	/* vmB */
	int b = alloc_dom();
	doms[b].used = 1;
	doms[b].life = LIFE_FREE;
	doms[b].dcb_pa = 0x82001000UL;
	setup_dcb(&doms[b].dcb, 3, (uint32_t)(uintptr_t)vmb_body, 0);
	/* write DCB to "memory image" too for future ecall */
	*(volatile dcb_t *)0x82001000UL = doms[b].dcb;

	int r = npa_descend_core(0, 0x82001000UL);
	if (r != OK) {
		uart_puts("[root] descend failed r=");
		uart_hex((uint64_t)(int64_t)r);
		uart_puts("\n");
		goto halt;
	}

	/* Call-model run of vmB until it returns SERVICE. */
	int rr = vmb_body();
	uart_puts("[root] vmB returned reason=");
	uart_hex((uint64_t)rr);
	uart_puts(" (call-model)\n");
	npa_ascend_core(rr, 0x6869626dUL);

	/* resume vmB */
	r = npa_descend_core(0, 0x82001000UL);
	uart_puts("[root] after resume, cur id=");
	uart_hex(doms[cur].dcb.id);
	uart_puts("\n");

	/* EXIT + reap */
	npa_ascend_core(REASON_EXIT, 0);
	npa_reap_core(0, 0x82001000UL);
	npa_reap_core(0, 0x82001000UL); /* double reap -> ENOTCHILD or FREE */

	uart_puts("[root] probe sequence done\n");

halt:
	for (;;)
		asm volatile("wfi");
}

__attribute__((section(".text._start"))) void _start(void)
{
	asm volatile("lla sp, _stack_top" ::: "sp");
	npa_root_main();
	for (;;)
		asm volatile("wfi");
}
