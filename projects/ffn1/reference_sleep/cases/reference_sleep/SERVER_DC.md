For this X-delta/tail-first reference with IRQ/WFI, follow ../../SERVER.md. Run `bash run_combined.sh --resume` from the archive root for one real-task00 VCS RTL SAIF plus clock-gated DC run. Hardware ID 0x4b575438 matches the included firmware and vectors. The case enables KWT_IRQ=1 and builds firmware with FFN1_WAIT_MODE=2.

128 signed16x16 multipliers and36 RAMSP128X16+16 RAMSP1024X16 local single-port macros are retained. Four-lane local restoration uses distinct existing SRAM macros. Shared SRAM remains the unchanged single32-bit command reference implementation, using macro stitching for capacity; physical capacity stitching is allowed by the user-confirmed rule. No shared bank concurrency is used.

Actual mapped area, workload power and STA require the server run. Read `report/clock_gating.rpt` for gating coverage and `report/diagnostics/mapped` for SRAM gate and fanout evidence. See ../../SERVER.md for the full commands.
