# FFN1 clock gating experiment — 2026-11-06

Frozen reference: q64_bank1_fmt1 from the previous SHA256-qualified handoff.
User authorized one reference plus four clock-gated candidates, identical
throughput and functional outputs, then backend comparison. All work is local
to undergrad_ffn1. Original cases remain immutable. No numerical, firmware,
SRAM, MAC, scheduling or queue-depth changes.

## Changes and risks, recorded before implementation

- fmt1_ref: exact original RTL and fixed firmware. Fresh measurements.
- fmt1_cg_result: the 1280-bit result bank previously holds data with a write
  enable but receives every clock edge. Four gates each feed eight 40-bit
  lanes, enabled only on group publication. No payload reset is introduced.
- fmt1_cg_mac: four gates each feed eight 40-bit accumulators. Enable includes
  valid product (MAC, LAST and fused EMIT) OR synchronous clear/start. Control,
  operand SRAM and combinational multipliers remain on their original paths.
- fmt1_cg_formatter: independent gates for three 40-bit partial slices (first
  slice also clocks its 15-bit index) and the 160+16-bit completed group.
  Enable is the exact original write condition OR clear. Control runs ungated.
- fmt1_cg_combined: only the above three changes combined.

Expected benefit is fewer clock edges at data registers, possibly fewer enable
muxes. Risks are gate area/buffering, enable-path timing/hold, clock skew and
power annotation. No numerical power/area improvement is promised. Never use
a raw combinational enable AND clock. RTL uses a low-level enable latch;
backend must replace it with a real positive-edge integrated clock-gating cell
identified by library attributes. Fail if no compatible ICG is available.
No whole-SoC automatic gating, no CPU or SRAM changes, no new wakeup cycle.

## Acceptance

1. Five cases, each 12 reset + 12 continuous tasks, 25344 exact outputs/task.
2. Every task's strict integer-fs duration AND performance counter profile must
   equal fmt1_ref, separately for reset/continuous. Reference must reproduce
   55416.5 reset cycles and the previously qualified continuous task windows.
3. Four-state gate tests cover changes during high/low clock phases, test
   override, disabled operation, clear/reset and resumed writes. Component
   scoreboards cover long backpressure and simultaneous final-pop/publication.
4. Per-task monitors count actual gated edges inside POWER_BEGIN..POWER_END,
   check no extra/missing edges against enables at root edges, and report
   register-clock-edge opportunities. Counts are not mW estimates.
5. Yosys elaboration checks 64 signed 16x16 multipliers, unchanged SRAM and
   register capacity, and intended gate sinks. This is not foundry mapping.
6. Backend uses the same clock/constraints/library/macro count, explicitly
   validates ICG mapping, reports clock-gating/timing/activity, and keeps
   coverage/hold acceptance pending until reviewed. New ICG clocks must not
   become unannotated zero-activity nets. Postmapping functional equivalence or
   gate simulation is required before accepting PPA. No backend is available
   on this host; package runnable server jobs and their checks.

Legacy verification/baseline.json remains historical only; all new deltas are
against the same frozen fmt1_ref. Server target is 150 MHz with no cycle loss.
