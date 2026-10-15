#include "kwt_driver.h"
/* Host loads one layer at a time via shared SRAM. No expected answers in firmware. */
int main(void) {
    volatile uint32_t *mail=(volatile uint32_t *)0xa000f000u;
    for (;;) {
        uint32_t request;
        do { request=mail[0]; } while (request!=1 && request!=3);
        if (request==3) {
            // Host requests statistics only after stopping its task timer.
            kwt_profile(mail+8);
            __asm__ volatile("fence iorw,iorw" ::: "memory");
            mail[0]=4;
            continue;
        }
        int rc=kwt_linear((const volatile int32_t *)0xa0010000u,
                          (const volatile int32_t *)0xa0018000u,
                          (const volatile int32_t *)0xa0028000u,
                          (volatile uint32_t *)0xa0030000u);
        mail[1]=(uint32_t)rc;
        __asm__ volatile("fence iorw,iorw" ::: "memory");
        mail[0]=rc?0xdead:2;
    }
}
