# Frontend FFN1 candidate experiment, 2026-11-05

User authorized new frontend candidates and functional/performance simulations.
Scope: E203 + existing shared SRAM/TCMs + FFN1 only. Keep INT16/INT32/INT40
arithmetic, all 12 existing layer vectors, real Host traffic, and final DMA
write-response timing. No synthesis/PPA claims from this workstation.
The frozen baseline and four original finalists are read-only references.

## Experiments, in dependency order

1. Reproduce the fastest existing dual32 packed40/pause64 candidate unchanged.
2. Output queue: old formatter serializes group assembly and word transmission.
   Separate partial assembly and a two-entry completed-group FIFO, allowing
   assembly and transmission together. Expected: fewer FIFO stalls and cycles.
   Cost/risk: extra payload/index registers, muxes, switching, full/empty and
   simultaneous enqueue/dequeue correctness. External packed format unchanged.
3. Fusion: enable existing first-product/previous-result overlap on experiment 2.
   Expected: fewer group transition bubbles. Risk: more timing pressure and FIFO
   backpressure, so measure separately rather than add predicted savings.
4. WFI: use existing interrupt wait firmware with packed40 on experiment 3.
   Expected: less CPU activity; not assumed to improve time. Risk: wake latency,
   races, and clock gating must be checked on server. Recompile only this firmware;
   polling candidates retain the original fixed image for clean RTL comparisons.
5. Quad64: extend the existing row-broadcast tile from two to four rows, keeping
   8 columns and 2 k products per PE. Same weight bank/precision and output format.
   Expected: halve arithmetic cycles, amortize weight reads. Cost: twice the
   multipliers/accumulators versus dual32, 2 KiB more local X SRAM, greater fanout,
   output bottleneck, and a 3-row tail. Compare first with identical pause firmware.
6. Independently compare WFI and product pipelining on quad64. Pipeline can add
   cycles; keep only as an explicitly labeled timing-oriented candidate if justified.

## Qualification and handoff

Measure reset and continuous execution across all 12 vectors, exact output bits,
MAC and DMA counts, strict cycles, legacy notification cycles, and FIFO/bus stalls.
Exercise the changed formatter independently with random data, backpressure,
clear/reset and invalid packed index sequences using a four-state simulator.
Bind firmware, vectors, RTL, logs and scripts by SHA256; reject stale results.
Package self-contained cases plus the existing VCS/SAIF/DC flow (adapted only for
new candidate configuration), a human report and CSV/JSON. No PDK or local tools.
Area/timing/power/energy stay unknown until real server runs.
