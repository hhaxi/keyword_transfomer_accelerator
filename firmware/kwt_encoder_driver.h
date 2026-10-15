#ifndef KWT_ENCODER_DRIVER_H
#define KWT_ENCODER_DRIVER_H
#include <stdint.h>
/* Calls control real hardware; no dot products, nonlinear math or rescaling in C. */
int kwt_encoder_layer(uint32_t layer, uint32_t gelu_config, uint32_t encoder_config,
                      volatile uint32_t *statistics);
#endif
