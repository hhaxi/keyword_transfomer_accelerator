# FFN1 reference with IRQ/WFI

This single case uses the published `reference` tensor streams, DMA schedule, INT40 accumulation and shift-15 INT16 writeback. It enables the existing interrupt controller and builds the existing ITCM firmware with wait mode 2. It includes the published VCS `xq` declaration fix and strict-window activity counters.

Use this directory from a repository checkout in a short server path. Load the same VCS and Design Compiler environment and use the same libraries and constraints as the previous five-case study. If the previous run used a private `local_config.tcl`, use the same settings here.

```bash
cd undergrad_ffn1/candidates/q128_reference_sleep
sha256sum -c --quiet SHA256SUMS
bash run_combined.sh --resume
bash run_combined.sh --report-only
```

The runner captures real nonzero `task00` through VCS, exports the same strict RTL SAIF window, and runs the clock-gated 150 MHz DC flow. The result table is `comparison.md`. Compare with the previous `reference` and `dense_sleep` rows. Read `report/clock_gating.rpt` for register gating and `report/rtl_activity/task_00/coverage.rpt` for activity annotation. The CPU and ITCM rows in `report/rtl_activity/task_00/power.rpt` give the corresponding hierarchy estimates. Use the report path shown by the runner.

The task window starts at the first Host data request and ends at the last DMA write response. Functional simulation also waits for the real E203 to wake and signal completion through the mailbox. Before selecting a final design, check setup and hold separately and confirm the energy comparison on another real sample if the task00 advantage is small.
