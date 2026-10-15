#ifndef KWT_DRIVER_H
#define KWT_DRIVER_H
#include <stdint.h>
#define KWT_BASE 0x40000000u
#define KWT_ROWS 99u
#define KWT_INNER 64u
#define KWT_COLS 256u
/* Inputs/weights: two signed int16 per uint32, first in low bits; W column-major.
 * X has 3168 words, W 8192 words; both buffers must be 4-byte aligned.
 * Output: sign-extended int40 carried in int64, row-major. */
int kwt_linear(const volatile uint32_t *x, const volatile uint32_t *w,
               const volatile int32_t *b, volatile uint32_t *output);
/* Full FFN output has 99*64 signed int40 values in int64 containers.
 * gelu_config: input right shift in bits 4:0, output right shift in 12:8.
 * W2 is packed column-major (8192 words); b2 has 64 int32 words. */
int kwt_ffn(const volatile uint32_t *x, const volatile uint32_t *w,
            const volatile int32_t *b, const volatile uint32_t *w2,
            const volatile int32_t *b2, volatile uint32_t *output, uint32_t gelu_config);
/* Profile destination must hold 19 words (word 15 is publication magic). */
void kwt_profile(volatile uint32_t *out);
#endif
