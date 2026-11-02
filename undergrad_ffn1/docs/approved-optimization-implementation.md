# Approved FFN1 optimizations implementation plan

User authorization: implement ITCM, continuous Host, small-X DMA ping-pong,
and bias downsizing. No interrupts, packed40, PE-array, arithmetic, polling-rate
or arbitration changes. Preserve original parent workspace and immutable baseline.

Architecture: keep a self-contained original at experiments/baseline, add two
compile-time hardware switches and independently selectable firmware/Host modes.
Materialize 16 self-contained cases and five cumulative checkpoints. Four unique
hardware configurations share DC results across software-only duplicates unless
the user requests repeated synthesis. Use the same constraints/library corner.

- [x] Freeze original sources/evidence and hashes before implementation.
- [x] Add failing checks for ITCM execution, continuous requests, streamed row
  release/ownership and native 128 macro counts; run against old behavior.
- [x] ITCM: legal CPU copy from shared boot image to 0x80000000, fence.i, run hot
  code there; report bootstrap separately and preserve task-load timing interval.
- [x] Host: remove blocking-driver bubbles using accepted request/response counts;
  keep old driver as an independent selectable comparison and obey backpressure.
- [x] Small X: retain W/b, load rows through A/B parity banks. Track row readiness,
  reserve pending responses, release only after all 256 outputs of a row. Preserve
  offered commands, fault/abort drain, final-write-response completion and INT40.
- [x] Bias: four 128x16 macros, address-depth selection and registered read mux;
  retain bias prefetch and native synchronous read latency.
- [x] Extend functional/component/structure checks for all options. All 12 tasks
  reset and resetless, plus prolonged stalls/faults/abort/late final response.
- [x] DC: per-case entry points, dynamic macro/DB inventory (128 needed only for
  compact cases), settings provenance, machine-readable timing/area/power summary.
- [x] Batch: all 16 modes, baseline and checkpoints, unique-hardware deduplication,
  failure isolation, comparison CSV/JSON, server Desktop-relative paths and docs.
- [x] Re-run meaningful checks, verify frozen baseline and unchanged parent, build
  upload tar/zip; do not claim actual PDK mapping/timing/power without server runs.

Acceptance: 16 MACs, bit-exact 12-layer FFN1 outputs, 11616 input words and 50688
output words per task. Compact X=4x128x16 (1KiB); compact bias=4x128x16 (1KiB).
SRAM scope: accelerator 52→34KiB, SoC 692→674KiB; capacity is not physical area.
No repeated weight loading across the 99 input rows. In-flight response ownership
must not be inferred from the mutable compute-bank selector.

Delivery evidence: verification/optimization_matrix.json and delivery-audit.json.
All 16 modes passed 12 reset tasks plus 12 continuous tasks (384 total).
The 129 parent fingerprints and all 204 frozen baseline files are unchanged.
Pure Tcl preflight passed for 17 source packages in both scopes; Bash syntax and
help passed under the current Bash and Bash 4.3. Upload archives are checked
byte-for-byte against their source manifest. Actual DC/PDK results remain pending.
