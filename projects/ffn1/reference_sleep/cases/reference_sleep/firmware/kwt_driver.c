#include "kwt_driver.h"
static inline void fence(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static inline volatile uint32_t *reg(uint32_t offset) {
    return (volatile uint32_t *)(uintptr_t)(KWT_BASE+offset);
}
static int abort_wait(void) {
    *reg(0)=2;
#if FFN1_WAIT_MODE == 0
    for (uint32_t n=0;n<100000;n++) if (!(*reg(4)&1)) return 0;
#else
    uint32_t start=kwt_cycles();
#if FFN1_WAIT_MODE == 2
    kwt_irq_dma_wait(1);
#endif
    for (;;) {
#if FFN1_WAIT_MODE == 2
        uint32_t state=kwt_irq_lock();
#endif
        uint32_t status=*reg(4);
        int done=!(status&1);
        int expired=(uint32_t)(kwt_cycles()-start)>=FFN1_DRAIN_TIMEOUT_CYCLES;
#if FFN1_WAIT_MODE == 2
        kwt_irq_unlock(state,!done && !expired);
#endif
        if(done) {
#if FFN1_WAIT_MODE == 2
            kwt_irq_dma_wait(0);
#endif
            return 0;
        }
        if(expired) break;
        kwt_poll_pause();
    }
#if FFN1_WAIT_MODE == 2
    kwt_irq_dma_wait(0);
#endif
#endif
    return -4; /* Bus did not drain: memory must not be reused before reset. */
}
static int configure(const volatile uint32_t *x, const volatile uint32_t *w,
               const volatile int32_t *b, volatile uint32_t *output) {
    if (*reg(0x0c)!=0x4b575438u) return -3;
    int rc=abort_wait();
    if (rc) return rc;
    *reg(0x20)=(uint32_t)(uintptr_t)x;
    *reg(0x24)=(uint32_t)(uintptr_t)w;
    *reg(0x28)=(uint32_t)(uintptr_t)b;
    *reg(0x2c)=(uint32_t)(uintptr_t)output;
    return 0;
}
static int execute(void) {
    int rc;
    fence();*reg(0)=1;
#if FFN1_WAIT_MODE == 0
    for (uint32_t n=0;n<1000000;n++) {
        uint32_t status=*reg(4);
        if (status&0x1c) { rc=abort_wait();return rc?rc:-1; }
        if ((status&3)==2) { fence();return 0; }
    }
#else
    uint32_t start=kwt_cycles();
#if FFN1_WAIT_MODE == 2
    kwt_irq_dma_wait(1);
#endif
    for (;;) {
#if FFN1_WAIT_MODE == 2
        uint32_t state=kwt_irq_lock();
#endif
        uint32_t status=*reg(4);
        int terminal=(status&0x1c) || ((status&3)==2);
        int expired=(uint32_t)(kwt_cycles()-start)>=FFN1_DMA_TIMEOUT_CYCLES;
#if FFN1_WAIT_MODE == 2
        kwt_irq_unlock(state,!terminal && !expired);
#endif
        if(terminal || expired) {
#if FFN1_WAIT_MODE == 2
            kwt_irq_dma_wait(0);
#endif
            if(status&0x1c) { rc=abort_wait();return rc?rc:-1; }
            if((status&3)==2) { fence();return 0; }
            break;
        }
        kwt_poll_pause();
    }
#endif
    rc=abort_wait();return rc?rc:-2;
}
int kwt_linear(const volatile uint32_t *x, const volatile uint32_t *w,
               const volatile int32_t *b, volatile uint32_t *output) {
    int rc=configure(x,w,b,output);
    if(rc) return rc;
    *reg(0x38)=FFN1_OUTPUT_FORMAT;
    return execute();
}
void kwt_profile(volatile uint32_t *out) {
    for (uint32_t i=0;i<15;i++) out[i]=*reg(0x40+4*i);
    fence();out[15]=0x50524633u; /* Publish only after all counters were copied. */
}
