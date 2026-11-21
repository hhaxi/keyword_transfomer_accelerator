# Local comparison with the polling reference

| Mode | Polling cycles/task | IRQ/WFI cycles/task | IRQ/WFI task/s at 150 MHz |
|---|---:|---:|---:|
| Reset each task | 31,820.00 | 32,006.83 | 4,686.50 |
| Continuous | 31,794.25 | 32,006.83 | 4,686.50 |

Both modes checked 12 real layer tasks with 304,128 INT40 results and 304,128 INT16 writebacks per mode. The strict task00 window grew from 32,737.5 to 32,959.5 cycles. The slowest task was 34,929.5 cycles. All 120 vector files, including all 72 frozen tensors, and all 12 generated INT16 expected output files match the polling reference. The 128 signed 16×16 multipliers and the local inventory of 36 RAMSP128X16 plus 16 RAMSP1024X16 macros were reproduced with Yosys.

Mean strict-window activity per task was 31,460 WFI cycles, 32,007 source clock edges, 547 IFU edges and 31,993 EXU edges. The IFU spends most of the interval without clock edges. The EXU still sees nearly the entire source clock. The actual E203 audit exercised eight interrupt race rounds, all 32 GPRs, DMA watchdog wake, 70,000 clocks of idle wait, error, timeout, retry and delayed final-response signaling.

The strict Slang SoC frontend passed with zero errors and warnings. See the separate [server comparison](reports/RESULTS.md) for VCS/DC and RTL-SAIF results. Use the same power window, PDK, clock-gating options and constraints as the polling reference when reproducing the server run.
