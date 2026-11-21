#ifndef KWT_DRIVER_H
#define KWT_DRIVER_H
#include <stdint.h>
#ifndef FFN1_WAIT_MODE
#define FFN1_WAIT_MODE 0
#endif
#define FFN1_OUTPUT_FORMAT 2u
#ifndef FFN1_POLL_PAUSE
#define FFN1_POLL_PAUSE 64u
#endif
#ifndef FFN1_DMA_TIMEOUT_CYCLES
#define FFN1_DMA_TIMEOUT_CYCLES 100000000u
#endif
#ifndef FFN1_DRAIN_TIMEOUT_CYCLES
#define FFN1_DRAIN_TIMEOUT_CYCLES 10000000u
#endif
#if FFN1_WAIT_MODE < 0 || FFN1_WAIT_MODE > 2
#error "FFN1_WAIT_MODE must be 0, 1 or 2"
#endif
#if FFN1_DMA_TIMEOUT_CYCLES >= 0x80000000u || FFN1_DRAIN_TIMEOUT_CYCLES >= 0x80000000u
#error "cycle deadlines must be below 2^31"
#endif
static inline uint32_t kwt_cycles(void) {
    uint32_t value;
    __asm__ volatile("csrr %0,mcycle" : "=r"(value));
    return value;
}
static inline void kwt_poll_pause(void) {
#if FFN1_WAIT_MODE == 1
    for (uint32_t n=0;n<FFN1_POLL_PAUSE;n++) __asm__ volatile("nop");
#endif
}
#if FFN1_WAIT_MODE == 2
void kwt_irq_init(void);
void kwt_irq_dma_wait(int active);
uint32_t kwt_irq_lock(void);
void kwt_irq_unlock(uint32_t state, int sleep);
#endif
#define KWT_BASE 0x40000000u
#define KWT_ROWS 99u
#define KWT_INNER 64u
#define KWT_COLS 256u
/* Inputs/weights: two signed int16 per uint32, first in low bits; W column-major.
 * X uses exact row_delta8_quad_v1:16 header words +2*sum(row widths),
 * with every8-row tile independently predicted and ordered per the hardware configuration.
 * Reconstructed X remains6336 original signed16 values. W uses signed_dual_column_width_v1: 32 header words
 * plus 2*sum(column_widths) payload words (544..8224 total); both buffers must be 4-byte aligned.
 * Output: 12672 row-major words. Each holds two signed int16 values, first in
 * low bits, rounded to nearest-even after dividing the int40 sum by 32768. */
int kwt_linear(const volatile uint32_t *x, const volatile uint32_t *w,
               const volatile int32_t *b, volatile uint32_t *output);
/* Profile destination must hold 16 words (word 15 is publication magic). */
void kwt_profile(volatile uint32_t *out);
#endif
