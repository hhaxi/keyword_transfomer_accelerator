// Bench-only transport for validating the PL datapath independently of UART.
#include "kwt_infer.h"

#define MAILBOX ((volatile uint32_t *)0x11200000u)
#define PACKET ((uint8_t *)0x11200010u)
#define TIMER_CTL (*(volatile uint32_t *)0xf8f00208u)

static void progress(unsigned layer, void *context)
{
    (void)context;
    MAILBOX[1] = layer;
}

int main(void)
{
    TIMER_CTL = 1;
    MAILBOX[0] = 0;
    for (;;) {
        if (MAILBOX[0] == 1) {
            MAILBOX[1] = 0;
            MAILBOX[2] = kwt_infer(PACKET, MAILBOX[3] != 0, progress, 0);
            __asm__ volatile ("dsb sy" ::: "memory");
            MAILBOX[0] = 2;
        }
    }
}
