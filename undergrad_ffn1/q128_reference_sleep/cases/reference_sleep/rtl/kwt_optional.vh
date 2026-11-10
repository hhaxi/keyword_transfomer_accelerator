// 128-MAC experiment with paired INT16 output words.
`define KWT_USE_TILE 1
`define KWT_TILE_ROWS 8
`define KWT_TILE_COLS 8
`define KWT_TILE_KPAR 2
`define KWT_FUSE 1
`define KWT_PRODUCT_PIPE 0
`define KWT_OUTPUT_FORMAT 2
`define KWT_IRQ 1
`define KWT_DMA_BURST 1
`define KWT_HOST_BURST 0
`define KWT_OUTPUT_WORDS 12672
`define KWT_EXPECTED_MAC_CYCLES 13312

`define KWT_X_DELTA 1
`define KWT_TAIL_FIRST 1
