#ifndef KWT_DRIVER_H
#define KWT_DRIVER_H
#include <stdint.h>
#define KWT_BASE 0x40000000u
#define KWT_ROWS 99u
#define KWT_INNER 64u
#define KWT_COLS 256u
/* Inputs/weights: sign-extended int16 in int32 words; W is column-major.
 * Output: sign-extended int40 carried in int64, row-major. */
int kwt_linear(const volatile int32_t *x, const volatile int32_t *w,
               const volatile int32_t *b, volatile uint32_t *output);
#endif
