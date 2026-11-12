#ifndef ENCODER_DC_DRIVER_H
#define ENCODER_DC_DRIVER_H
#include <stdint.h>
/* Frozen parameter array: 12 x 33410 words, no file header or classifier. */
/* Caller supplies a timeout in status polls. Returns 0 on completion. */
int encoder_dc_run(const uint32_t *parameters, const int32_t *input, int32_t *output, uint32_t timeout);
#endif
