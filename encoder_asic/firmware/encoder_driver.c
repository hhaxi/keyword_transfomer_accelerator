#include "encoder_driver.h"
#define ENC ((volatile uint32_t *)(uintptr_t)0x40010000u)
#define FFN ((volatile uint32_t *)(uintptr_t)0x40000000u)
static void fence_io(void) {
#if defined(__riscv)
 __asm__ volatile("fence iorw,iorw" ::: "memory");
#else
 __asm__ volatile("" ::: "memory");
#endif
}
static void store(uint32_t address,const uint32_t *source,uint32_t words) {
 volatile uint32_t *dest=(volatile uint32_t *)(uintptr_t)address;
 for(uint32_t i=0;i<words;i++) dest[i]=source[i];
 fence_io();
}
static int wait_engine(volatile uint32_t *engine,uint32_t timeout) {
 for(uint32_t i=0;i<timeout;i++) {
  uint32_t status=engine[1];
  if(!(status&1u)) return (status&31u)==2u ? 0 : -2;
 }
 return -1;
}
int encoder_dc_run(const uint32_t *parameters,const int32_t *input,int32_t *output,uint32_t timeout) {
 if((ENC[1]&1u)||(FFN[1]&1u)) return -3;
 store(0xa0010000u,(const uint32_t *)input,6336);
 ENC[0]=4;ENC[0x20/4]=0xa0010000u;ENC[0x24/4]=0xa0050000u;
 ENC[0x28/4]=0xa0018000u;ENC[0x2c/4]=0xa0030000u;ENC[0x30/4]=0xa0064000u;
 for(uint32_t layer=0;layer<12;layer++) {
  const uint32_t *p=parameters+layer*33410u;
  store(0xa0050000u,p,16704);p+=16704;
  store(0xa0020000u,p,8192);p+=8192;
  store(0xa0028000u,p,256);p+=256;
  store(0xa0040000u,p,8192);p+=8192;
  store(0xa0048000u,p,64);p+=64;
  FFN[0x3c/4]=p[0];ENC[0x34/4]=p[1]|24u|(layer?1u:0u)|(layer<11?2u:0u);
  ENC[0x38/4]=0;fence_io();FFN[0]=1;fence_io();ENC[0]=1;fence_io();
  if(wait_engine(ENC,timeout)||wait_engine(FFN,timeout)) goto failed;
  ENC[0x38/4]=1;fence_io();ENC[0]=1;fence_io();
  if(wait_engine(ENC,timeout)) goto failed;
 }
 for(uint32_t i=0;i<6336;i++) output[i]=((volatile int32_t *)(uintptr_t)0xa0064000u)[i];
 fence_io();return 0;
failed:
 ENC[0]=2;FFN[0]=2;fence_io();
 /* Do not reuse buffers until both DMA masters are idle. */
 for(uint32_t i=0;i<timeout;i++) if(!((ENC[1]|FFN[1])&1u)) return -2;
 return -4;
}
