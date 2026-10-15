#include "kwt_driver.h"
static inline void fence(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static inline volatile uint32_t *reg(uint32_t offset) {
    return (volatile uint32_t *)(uintptr_t)(KWT_BASE+offset);
}
static void load_words(uint32_t offset, const volatile int32_t *src, uint32_t count) {
    volatile uint32_t *dst=reg(offset);
    // All three fixed tensor lengths are multiples of four.
    for (uint32_t i=0;i<count;i+=4) {
        dst[i]=(uint32_t)src[i]; dst[i+1]=(uint32_t)src[i+1];
        dst[i+2]=(uint32_t)src[i+2]; dst[i+3]=(uint32_t)src[i+3];
    }
}
int kwt_linear(const volatile int32_t *x, const volatile int32_t *w,
               const volatile int32_t *b, volatile uint32_t *output) {
    *reg(0)=2; /* Invalidate previous task; every task reloads X/W/b. */
    load_words(0x10000,x,KWT_ROWS*KWT_INNER);
    load_words(0x20000,w,KWT_INNER*KWT_COLS);
    load_words(0x30000,b,KWT_COLS);
    fence(); *reg(0)=1;
    for (uint32_t i=0;i<KWT_ROWS*KWT_COLS;i+=4) {
        uint32_t timeout=100000;
        uint32_t status;
        do {
            status=*reg(4);
            if (status&8) return -1;
            if (!--timeout) return -2;
        } while (!(status&16)); // Four results are guaranteed until consumed.
        output[2*i]=*reg(0x10);
        output[2*i+1]=*reg(0x14); /* Pop only after reading the low half. */
        output[2*i+2]=*reg(0x10); output[2*i+3]=*reg(0x14);
        output[2*i+4]=*reg(0x10); output[2*i+5]=*reg(0x14);
        output[2*i+6]=*reg(0x10); output[2*i+7]=*reg(0x14);
    }
    fence();
    return ((*reg(4)&0xf)==2)?0:-3;
}
