# Q128 FFN1 local verification

## Upstream E203 ICB splitter

The SoC uses `sirv_icb1to8_bus` from E203 HBirdv2 revision `9f3e34f337f5d0a1236a285871ffa2032491617a`. The KWT arbiter still selects the requesting CPU, Host or DMA master and tracks response ownership. The same firmware, twelve layer parameter sets and strict task windows were used for both builds.

| Bus | Mean cycles/task | Tasks/s at 150 MHz |
|---|---:|---:|
| Custom bus baseline | 32,006.83 | 4,686.50 |
| E203 ICB splitter | 32,012.83 | 4,685.62 |

Each layer took six additional cycles in both the reset-per-task and continuous runs. Each mode passed the comparison of 304,128 output values. Yosys verified 128 MACs and the local inventory of 36 RAMSP128X16 and 16 RAMSP1024X16 macros. The new bus has local RTL verification. The linked server PPA results describe the custom-bus baseline.

The E203 buffer counter declarations now use `OUTS_CNT_W` for both signals. Icarus reproduced the two port-width warnings before this fix and compiled the bus without diagnostics afterward. A fresh Verilator build passed all twelve tasks in both reset modes, with the same output comparisons and an identical `functional.json`. The SpyGlass setup loads one lint waiver for the intentional low-phase `enb` latch in `e203_clkgate`. Tcl setup and waiver arguments were checked locally; rerun SpyGlass on the server to confirm its lint report.

## Original custom-bus comparison with the polling reference

| Mode | Polling cycles/task | IRQ/WFI cycles/task | IRQ/WFI task/s at 150 MHz |
|---|---:|---:|---:|
| Reset each task | 31,820.00 | 32,006.83 | 4,686.50 |
| Continuous | 31,794.25 | 32,006.83 | 4,686.50 |

Both modes checked 12 real layer tasks with 304,128 INT40 results and 304,128 INT16 writebacks per mode. The strict task00 window grew from 32,737.5 to 32,959.5 cycles. The slowest task was 34,929.5 cycles. All 120 vector files, including all 72 frozen tensors, and all 12 generated INT16 expected output files match the polling reference. The 128 signed 16×16 multipliers and the local inventory of 36 RAMSP128X16 plus 16 RAMSP1024X16 macros were reproduced with Yosys.

Mean strict-window activity per task was 31,460 WFI cycles, 32,007 source clock edges, 547 IFU edges and 31,993 EXU edges. The IFU spends most of the interval without clock edges. The EXU still sees nearly the entire source clock. The actual E203 audit exercised eight interrupt race rounds, all 32 GPRs, DMA watchdog wake, 70,000 clocks of idle wait, error, timeout, retry and delayed final-response signaling.

The strict Slang SoC frontend passed with zero errors and warnings. See the separate [server comparison](reports/RESULTS.md) for VCS/DC and RTL-SAIF results. Use the same power window, PDK, clock-gating options and constraints as the polling reference when reproducing the server run.
