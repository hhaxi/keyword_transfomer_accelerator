#include "kwt_encoder_driver.h"
/* The host supplies one layer's weights at a time. Only controls/telemetry in C. */
int main(void) {
    volatile uint32_t *mail=(volatile uint32_t *)0xa000f000u;
    uint32_t expected_layer=0;
    for(;;) {
        while(mail[0]!=11) {}
        uint32_t layer=mail[4];
        int rc=-5;
        if(layer==0 || layer==expected_layer) {
            rc=kwt_encoder_layer(layer,mail[2],mail[3],mail+64+8*layer);
        }
        expected_layer=rc || layer==11 ? 0 : layer+1;
        mail[1]=(uint32_t)rc;
        __asm__ volatile("fence iorw,iorw" ::: "memory");
        mail[0]=rc?0xdead:2;
    }
}
