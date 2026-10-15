#include "kwt_driver.h"
static inline void fence(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static inline volatile uint32_t *reg(uint32_t offset) {
    return (volatile uint32_t *)(uintptr_t)(KWT_BASE+offset);
}
int kwt_linear(const volatile int32_t *x, const volatile int32_t *w,
               const volatile int32_t *b, volatile uint32_t *output) {
    *reg(0)=2; /* Invalidate previous task; every task reloads X/W/b. */
    for (uint32_t i=0;i<KWT_ROWS*KWT_INNER;i++) *reg(0x10000+4*i)=(uint32_t)x[i];
    for (uint32_t i=0;i<KWT_INNER*KWT_COLS;i++) *reg(0x20000+4*i)=(uint32_t)w[i];
    for (uint32_t i=0;i<KWT_COLS;i++) *reg(0x30000+4*i)=(uint32_t)b[i];
    fence(); *reg(0)=1;
    for (uint32_t i=0;i<KWT_ROWS*KWT_COLS;i++) {
        uint32_t timeout=100000;
        uint32_t status;
        do {
            status=*reg(4);
            if (status&8) return -1;
            if (!--timeout) return -2;
        } while (!(status&4));
        output[2*i]=*reg(0x10);
        output[2*i+1]=*reg(0x14); /* Pop only after reading the low half. */
    }
    fence();
    return ((*reg(4)&0xf)==2)?0:-3;
}
