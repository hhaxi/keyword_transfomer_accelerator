# FFN1 reference with IRQ/WFI

This case uses the E203 `sirv_icb1to8_bus` splitter and KWT master arbitration. It uses the published `reference` tensor streams, DMA schedule, INT40 accumulation, shift-15 INT16 writeback, and ITCM firmware with IRQ/WFI. The reports in `reports/RESULTS.md` came from the earlier custom-bus version.

Use this directory from a repository checkout in a short server path. Load the same VCS and Design Compiler environment and use the same libraries and constraints as the previous five-case study. If the previous run used a private `local_config.tcl`, use the same settings here.

```bash
cd undergrad_ffn1/q128_reference_sleep
sha256sum -c --quiet SHA256SUMS
bash run_combined.sh --resume
bash run_combined.sh --report-only
```

The runner captures one real task through VCS, exports the strict RTL SAIF window, and runs clock-gated DC at 150 MHz. The result table is `comparison.md`. Read `report/clock_gating.rpt` for inserted clock gates and gated registers, and `report/rtl_activity/task_00/coverage.rpt` for SAIF annotation. See the CPU and ITCM rows in `report/rtl_activity/task_00/power.rpt` for the corresponding hierarchy estimates.

The task window starts at the first Host data request and ends at the last DMA write response. Functional simulation also waits for the real E203 to wake and signal completion through the mailbox. Before selecting a final design, check setup and hold separately and confirm the energy comparison on another real sample if the task00 advantage is small.

## Direct synthesis and verification commands

Run from `cases/reference_sleep/` with the Synopsys tools on `PATH`.

| Command | Result |
|---|---|
| `bash run_dc.sh both` | SoC synthesis with and without DC clock-gate insertion, including area, setup and hold timing, and clock-gating reports. |
| `bash run_vcs_rtl_power.sh both` | Capture a single strict RTL SAIF window and use it for the two DC runs. The launcher prints paths to the DC reports and to the activity capture. |
| `bash run_coverage.sh` | VCS runs all 12 FFN1 tasks in both reset modes, then URG writes its dashboard. `--tasks 1` is a shorter check. |
| `bash run_spyglass.sh lint` | Classic SpyGlass RTL lint on `kwt_ffn1_soc`. |
| `bash run_spyglass.sh gating` | SpyGlass Power reduction analysis for register enables and clock-gating opportunities. |
| `bash run_spyglass.sh profile` | SpyGlass Power profiling with task activity for clock gating ratio and efficiency. |

The coverage launcher prints `Q128_COVERAGE_RUN`. Open `urg_report/dashboard.html` for code coverage and `functional.md` for counts of observed bus scenarios. A zero count marks a scenario absent from the run. Source hierarchy starts at `tb_soc.dut`. The testbench additionally checks bus response ownership, stability during backpressure, byte-mask write behavior, denied Host MMIO, and dropping an in-flight response on reset. Coverage runs leave wave dumping disabled.

SpyGlass prints `Q128_SPYGLASS_REPORTS`. Start with `messages.rpt` and use `report_files.txt` to locate detailed reports from the requested goal. Gating suggestions require review of affected registers, enable conditions, reset behavior and timing before any RTL change. Compare those suggestions with DC's inserted gates in `clock_gating.rpt`.

The vendored `sirv_gnrl_icbs.v` matches the outstanding counter signals to `OUTS_CNT_W` to fix both `W110` diagnostics. The lint waiver in `config/spyglass_lint.swl` covers only the `InferLatch` message for `enb` in `e203_clkgate`. The low-phase latch is part of the upstream clock gate implementation. Review remaining warnings and any unmatched waiver messages in the new report.

If the advanced reduction goal reports `PECHECK28`, its `adv_power_rednso` / `power_cge_regr` license checkout failed. The launcher keeps reports for diagnosis and exits nonzero on a fatal goal summary. To check whether the installation can offer basic guidance, use `KWT_SPYGLASS_GOAL=power/power_guidance` with the same library and `run_spyglass.sh gating`. This goal reports RTL guidance if its license is available. For activity profiling, supply the task SAIF and run `run_spyglass.sh profile` to inspect inefficient or ungated blocks.

For the Power goals, provide the server's standard-cell Liberty `.lib` through `KWT_SPYGLASS_LIB`. The script enables SpyGlass automatic compilation to `.sglib`. You can also pass a precompiled library from the same SpyGlass release through `KWT_SPYGLASS_SGLIB`. Use `KWT_SPYGLASS_SAIF` to pass the strict task SAIF from the same RTL snapshot. The script maps it to `tb_soc.dut`. Alternatively, set `KWT_SPYGLASS_SGDC` to a site-specific SGDC with clock and activity mapping. The provided SGDC sets `clk` to 6.666667 ns. Static elaboration uses SRAM port declarations and fixture control constants. For installation-specific GuideWare setup, use `KWT_SPYGLASS_METHODOLOGY` and `KWT_SPYGLASS_GOAL`. Defaults are `lint/lint_rtl`, `power/power_reduction_adv` and `power/power_est_profiling`. The launcher uses classic `sg_shell` and accepts an absolute executable path through `KWT_SG_SHELL`.
