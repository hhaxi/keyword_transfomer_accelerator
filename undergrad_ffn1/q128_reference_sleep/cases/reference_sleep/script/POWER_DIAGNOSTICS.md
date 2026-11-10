# DC fanout, clock-gating and activity diagnostics

The high-fanout warning alone does not establish that DC power estimation is broken. A high-fanout approximation can affect estimated capacitance/delay and therefore the estimate needs inspection. Earlier activity with zero X switching versus 6335/6336 nonzero X points is also a material change in the power input; it can explain much of the 17.922 to 38.58 mW increase. Those two reports cannot isolate the effect of fanout. These are existing observations, not new results from this combined candidate.

Generic Yosys weighted bit loads (clock 6409, reset 3757, push 2577) are structural indicators. They are not actual technology-mapped DC sink counts or capacitances. No electrical constraints, wire-load models, ideal networks, or toggle rates are changed by the diagnostics.

## New synthesis and same-process RTL SAIF

The normal candidate run automatically writes `report/diagnostics/mapped/`. If RTL SAIF is loaded, it also writes `report/rtl_activity/task_00/diagnostics/annotated_before_power/` and `annotated_after_power/`. Existing `power.rpt` and coverage reports keep their names. The clock-gating compile remains `compile_ultra -gate_clock -no_autoungroup` with minimum bitwidth 8 and maximum fanout 64.

Read `availability.tsv` in every diagnostics directory first. `COMPLETED_INSPECT_TEXT` means the command completed; the original report text still needs review. `UNAVAILABLE` and `.unavailable.txt` preserve command/attribute failure rather than replacing missing values with zero. Installed command help and application attribute inventories are retained. No local DC/VCS result is asserted by this package.

For a before/after architecture comparison, run the same saved-run helper on the original tile8x8 run and the combined candidate. Keep task 00, clock, libraries, constraint budgets and activity window identical. Pre-compile generic net fanout must not be presented as mapped fanout.

## Saved DDC inspection, with no synthesis

Run from this case directory after loading the original EDA environment:

```bash
python3 tools/diagnose_power.py --run /absolute/original/DC/run \
  --saif /absolute/task_00.saif --saif-kind rtl
```

This prepares a unique folder under `run/power_diagnostics/` and prints its path. It copies diagnostics scripts and original report evidence, records DDC/SDC/SAIF/library hashes, and writes raw SAIF clock/control statistics. It does not need DC to prepare the folder. Missing inputs are explicit in `READ_FIRST.txt` and prevent replay.

To execute analysis immediately, append `--replay`. For an exact mapped-netlist SAIF, use `--saif-kind gate`. With no `--saif`, the flow is explicitly vectorless; it cannot qualify task power. `--ddc`/`--sdc` can select the saved compiled checkpoint. If the original SRAM inventory is unavailable, pass each actual original SRAM DB as a separate `--library`; the original standard-cell target remains the one recorded in `run_settings.txt`.

The replay reads the original library paths recorded in the saved run and does not source current library configuration or timing constraints. SDC is restored only if the DDC lacks clocks. It never recompiles. Every invocation creates a new directory outside the original run, verifies inputs did not change, and marks power acceptance `NOT_CERTIFIED`. Fresh DDC replay may lack the original RTL SAIF name mapping: compare its coverage/power against the original same-process reports before using it. A successful replay marker does not establish annotation equivalence.

## Actual fanout and capacitance

`mapped/mapped_net_loads.tsv` counts input/inout leaf pin loads and output port loads obtained from `all_connected -leaf`, with drivers and unknown endpoints separately. `count_status=LOWER_BOUND_unknown_endpoint_types` is a lower bound; `UNAVAILABLE_actual_leaf_connections` is not a count. Hierarchical aliases may expose the same electrical leaf endpoints in multiple rows; do not sum net rows. Fanout attributes are separate from actual endpoint counts.

`high_fanout_loads.tsv` retains nets with at least 64 counted loads plus named clock/reset/push/enable/chip-select nets. `top_net_*.rpt` uses native `report_net -connections -verbose`; matching endpoint TSVs list the actual loads. Capacitance attributes that exist are kept in native units; `report_units` and native net reports supply interpretation. Unknown attributes remain `UNAVAILABLE`. `constraints.rpt`, `current_settings.tsv`, `design.rpt`, `ideal_networks.rpt`, and `original_warnings.txt` retain electrical limits, current high-fanout approximation settings, ideal status and original warnings. Do not remove warnings or idealize nets to improve the estimate.

## Two different coverage metrics

Inside an already linked DDC session, the direct commands are:

```tcl
identify_clock_gating
report_clock_gating
report_clock_gating -gating_elements
report_saif -hierarchy -rtl_saif
```

`report_clock_gating` defines the tool's recognized clock-gated register numerator/denominator and reports inserted/recognized gate elements. Preserve that report's definitions. `report_saif` Seq Cells coverage is the fraction receiving activity annotation; it does not measure clock-gating coverage. The existing 69.89% Seq SAIF figure therefore cannot be called 69.89% clock-gating coverage.

The local SRAM gate is a handwritten low-level latch plus AND under `gated_clock/clock_gate`, driving wrapper `macro_clk` and macro `CLK`. It may remain discrete logic and may not appear as an integrated/recognized clock-gating cell. `macro_gate_inventory.tsv` records actual references and recognized attributes if available. Its `clock_report_index` maps each SRAM to `macro_NNN_clock_cone.rpt` and `macro_NNN_clock_net.rpt`. These inspect actual mapped upstream cells and clock connections without assuming ICG conversion. The default shared SRAM/TCM wrappers remain part of the diagnostic inventory so their activity can be compared.

## Gated macro clock activity and power groups

Compare `clock_macro_activity.tsv` before and after power evaluation. Each row links to a raw `get_switching_activity object -related_clock` record. Points include the root clock, register clocks, every native macro CLK/CEN/GWEN/RET1N, mapped macro-clock driver pins, and named gate/latch pins. `report_activity -driver`/`-verbose`, per-pin source attributes, `report_saif -hierarchy -rtl_saif -missing`, and the original annotation log provide complementary evidence of user annotation, propagation, defaults and missing points. The source-text hints are search hints, not a source certification; if the installed tool does not expose a source, it remains unavailable.

`raw_saif_controls.tsv`/JSON provides captured CLK/CEN/macro_clk/cs/enable_latched records, transition count, unknown fraction and transitions per ns. Two transitions occur per full clock cycle. Raw SAIF presence establishes capture only, not successful mapping to a DC pin. A captured `macro_clk` with low TC does not establish low mapped CLK activity if DC uses a default clock rate. Conversely a full-rate root clock is expected while an idle local bank clock should show fewer transitions. Check CEN active-low duty and CLK together, and compare before/after propagation. Do not use `set_switching_activity` to force the expected answer. If direct mapped source coverage cannot be demonstrated with RTL SAIF, simulate the exact saved gate netlist and repeat with gate SAIF.

`annotated_after_power/power_hierarchy.rpt` retains hierarchy to six levels. Separate CPU, shared SRAM and accelerator root reports use disjoint roots; macro-only power overlaps those roots and is diagnostic detail, so do not add it to them. Hierarchy totals also include their descendants. Report power is an estimate without routed RC; clock-gate recognition, activity coverage and timing acceptance require independent review. SS-only hold remains incomplete for fast-corner signoff.