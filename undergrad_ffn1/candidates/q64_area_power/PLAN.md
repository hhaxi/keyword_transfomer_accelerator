# Q64 area/power frontend experiment — 2026-11-06

User selected q64_fused_pause and authorized new frontend area/power candidates,
functional simulation, server packaging and remote push. Frozen reference is the
qualified q64_fused_pause inside the previous committed handoff archive. Keep
all original references, real E203, shared SRAM/TCMs, Host traffic, arithmetic
values, packed40 protocol, fixed pause64 firmware and twelve layer vectors.
No local foundry mapping, frequency, area or power claim.

## Controlled experiments

1. **Sequence addresses**: old core stores a 15-bit address beside each of 64
   output values. Generate addresses from the fixed 4-row/8-column traversal on
   each accepted result instead. Expected: remove 960 address storage bits and
   parallel index write/read selection. Risk: row/column boundaries, the 99-row
   tail, clear and stalls must preserve exact order. No throughput change intended.
2. **Two group banks**: old core writes 32 results through dynamic circular FIFO
   indices. Use two 32-value banks with constant lane wiring and a shared bank
   write enable, plus the sequence generator. Expected: simpler routing/muxes;
   same 64-value capacity. Risk: tail group uses 24 values; full/pop/push ordering.
3. **One group bank**: compute next group in accumulators while the previous
   group drains from a single 32-value bank. Allow overwrite on the edge accepting
   the old last result. Expected: remove another 1280 payload bits; maintain the
   output-limited throughput. Risk: reduced elasticity may expose bubbles.
4. **Exact narrow arithmetic**, independently on one-bank core: two INT16
   products require a signed 33-bit pair sum; the sum of 64 products plus INT32
   bias fits signed 38 bits. Replace internal 40-bit accumulator with 38 bits and
   sign-extend to the unchanged INT40 interface. This is lossless range-based
   implementation, not new quantization. Risk: sign/first/clear handling and
   extreme positive sums; validate against 64-bit mathematical arithmetic.
5. **Single completed formatter group**: retain independent assembly of three
   incoming values, but reduce the completed 160-bit group queue from two to one.
   Permit publish on the edge retiring the current final word. Expected: fewer
   payload/address registers and bank muxes. Risk: reduced elasticity may add cycles.
6. **Combined**: one-bank + exact narrow arithmetic + single formatter group.
7. **Early tile release**, independently on combined: current X bank remains
   occupied until the last column group's results can enter the result queue.
   Release it on LAST, when the final old-tile operands have been consumed;
   retain the completed results in the accumulators while output is stalled.
   Remove the old EMIT release to avoid clearing a newly refilled bank twice.
   Expected: hide DMA refill behind output drain, recover boundary cycles with
   no added data storage. Risk: read/write lifetime and final/continuous tasks.

Idle operand masking was not selected: SRAM outputs already hold without reads,
so extra masks may add transitions and gates without useful idle power reduction.

All candidates keep 64 physical multipliers and the existing SRAM geometry.
Compare one change per edge of the experiment tree, not sums of predicted gains.

## Qualification

- Fresh reference and candidates: twelve reset and twelve continuous tasks,
  25,344 outputs/task, exact DMA/MAC counts, integer-fs strict task windows.
- Four-state component tests: random long stalls, simultaneous last-pop/push,
  all output indices including the final three rows, mid-stream clear/reset;
  MAC extrema, random groups, stalls, adjacent first-product seeds and clear.
- Yosys frontend elaboration/check only; report generic sequential/mux bits and
  actual SRAM/MAC instance counts separately from physical area.
- Reuse byte-identical previously tested VCS/SAIF/DC drivers; verify seed binding
  and source hashes. Retain inherited driver test provenance without claiming a
  new commercial-tool run. Package independent cases, logs, CSV/JSON and scripts.
