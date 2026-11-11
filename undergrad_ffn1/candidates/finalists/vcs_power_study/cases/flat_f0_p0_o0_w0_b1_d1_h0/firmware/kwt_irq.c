#include "kwt_driver.h"
#if FFN1_WAIT_MODE == 2
#define EVT_ENABLE (*(volatile uint32_t *)(KWT_BASE+0x80u))
#define EVT_PENDING (*(volatile uint32_t *)(KWT_BASE+0x84u))
static inline void fence(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
void kwt_irq_init(void) {
    __asm__ volatile("csrci mstatus,8" ::: "memory");
    EVT_ENABLE=0;EVT_PENDING=7;fence();
    __asm__ volatile("csrw mie,%0" :: "r"(0x800u) : "memory");
    EVT_ENABLE=1;fence();
    __asm__ volatile("csrsi mstatus,8" ::: "memory");
}
void kwt_irq_dma_wait(int active) {
    EVT_ENABLE=active?7:1;fence();
}
uint32_t kwt_irq_lock(void) {
    uint32_t state;
    __asm__ volatile("csrrci %0,mstatus,8" : "=r"(state) :: "memory");
    // Clear stale notifications BEFORE the authoritative status/mailbox read.
    EVT_PENDING=7;fence();
    return state;
}
void kwt_irq_unlock(uint32_t state,int sleep) {
    // Pinned E203 e203_exu_excp: WFI wake ignores mstatus.MIE, honors mie.MEIE.
    // An event between the protected status read and WFI stays pending and wakes.
    if(sleep) __asm__ volatile("wfi" ::: "memory");
    if(state&8) __asm__ volatile("csrsi mstatus,8" ::: "memory");
}
void kwt_trap_handler(void) {
    uint32_t cause,pc;
    __asm__ volatile("csrr %0,mcause" : "=r"(cause));
    if(cause==0x8000000bu) { EVT_PENDING=7;fence();return; }
    __asm__ volatile("csrr %0,mepc" : "=r"(pc));
    volatile uint32_t *mail=(volatile uint32_t *)0xa000f000u;
    mail[2]=cause;mail[3]=pc;fence();mail[0]=0xbad;fence();
    for(;;) __asm__ volatile("nop");
}
#endif
