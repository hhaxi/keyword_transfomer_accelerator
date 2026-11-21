#ifndef Z100_KWT_INFER_H
#define Z100_KWT_INFER_H
#include <stdint.h>

enum { KWT_FEATURE_BYTES = 6336 * 4, KWT_REPLY_BYTES = 58 };
typedef void (*kwt_progress)(unsigned completed, void *context);
unsigned kwt_infer(uint8_t *packet, int verify, kwt_progress progress, void *context);
#endif
