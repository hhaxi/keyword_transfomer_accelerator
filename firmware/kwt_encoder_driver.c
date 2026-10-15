#include "kwt_encoder_driver.h"
#include "kwt_driver.h"
static volatile uint32_t *const enc=(volatile uint32_t *)0x40080000u;
static inline void fence(void) { __asm__ volatile("fence iorw,iorw" ::: "memory"); }
static int abort_encoder(void) {
    enc[0]=2;
    for(uint32_t n=0;n<100000;n++) if(!(enc[1]&1)) return 0;
    return -4;
}
static int execute(uint32_t operation) {
    enc[0x38/4]=operation;fence();enc[0]=1;
    for(uint32_t n=0;n<2000000;n++) {
        uint32_t s=enc[1];
        if(s&0x1c) { int r=abort_encoder();return r?r:-1; }
        if((s&3)==2) { fence();return 0; }
    }
    int r=abort_encoder();return r?r:-2;
}
int kwt_encoder_layer(uint32_t layer,uint32_t gelu_config,uint32_t encoder_config,
                      volatile uint32_t *statistics) {
    if(layer>=12 || enc[3]!=0x454e4331u || (enc[1]&1)) return -3;
    if(layer==0) {
        if(encoder_config&1u) return -3;
        enc[0]=4; /* Invalidate task data; payload SRAM is never reset. */
    }
    if(layer==11 && (encoder_config&2u)) return -3; /* Final results must be written. */
    enc[0x20/4]=(layer && !(encoder_config&1u)) ? 0xa0064000u : 0xa0010000u;
    enc[0x24/4]=0xa0050000u;enc[0x28/4]=0xa0018000u;
    enc[0x2c/4]=0xa0030000u;enc[0x30/4]=0xa0064000u;enc[0x34/4]=encoder_config;
    int rc=execute(0);if(rc) return rc;
    statistics[0]=enc[0x40/4];
    for(uint32_t n=0;n<5;n++) statistics[3+n]=enc[0x48/4+n];
    rc=kwt_ffn((const volatile uint32_t *)0xa0018000u,
               (const volatile uint32_t *)0xa0020000u,(const volatile int32_t *)0xa0028000u,
               (const volatile uint32_t *)0xa0040000u,(const volatile int32_t *)0xa0048000u,
               (volatile uint32_t *)0xa0030000u,gelu_config);
    if(rc) { abort_encoder();return rc; }
    statistics[2]=*(volatile uint32_t *)0x40000040u;
    rc=execute(1);if(rc) return rc;
    statistics[1]=enc[0x40/4];
    for(uint32_t n=0;n<5;n++) statistics[3+n]+=enc[0x48/4+n];
    fence();return 0;
}
