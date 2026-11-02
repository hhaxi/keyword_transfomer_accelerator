# Recover saved DC sweep reports implementation plan

User-authorized scope: uniformly patch constant pseudo-cell area handling and
summarize the completed server sweep without rerunning synthesis. The server DDCs
are not present locally; deliver a source-only update and one Bash entry point.

Architecture: preserve dc_status.json and original run/report directories. Select
the recorded source run (including reused results), otherwise select the latest
run directory for each case/scope. Never silently use an older successful run.
Read the saved DDC with its embedded constraints and the configured libraries;
write new reports and SHA receipts. Cache only the exact same source DDC, not
independent runs of equivalent hardware. Aggregate long/16-row-wide CSV/JSON and
a human-readable Markdown table with explicit unknowns and provenance.

Tech stack: Python 3.6+ standard library, Bash 4.2+, Tcl/DC. Local tests emulate DC
report output and collections; only server execution produces actual PPA numbers.

- [x] Add failing tests for report parsing, SI units, partial reports, selection
  freshness, reused runs, failed-case isolation, receipts and aggregation.
- [x] Implement focused ppa_metrics.py and recover_sweep.py; preserve original
  records, never compile/analyze/elaborate, never treat missing values as zero.
- [x] Extend recover_reports.tcl with QoR, units, clocks, macro inventory and
  provenance reports; restore saved clocks without applying current constraints.
- [x] Add run_recover_compare.sh, server instructions and a small update archive
  that excludes RTL, local configs, libraries and old server results.
- [x] Verify Python 3.6 grammar, Bash 4.3 syntax/help (script uses Bash 4.2 features), Tcl recovery flow,
  exact constant-area handling, unchanged parent/baseline, archive closure, and
  fresh review before delivery. Full numerical RTL rerun is unnecessary because
  this change only reads existing designs and creates reports.

Important fields: total/comb/sequential/macro area, added/CPU/shared scope area,
setup WNS/TNS/violating paths, SS-only hold WNS, saved clocks and units, dynamic/
leakage/total vectorless power, constant pseudo counts, native macro counts,
constraint violations, mapped-design validity, original DDC/report paths and
hashes. Task cycles come from existing verified simulation evidence and are
separate from synthesis. Vectorless power must not be labelled task energy.

Evidence: 15 parser/driver tests, 4 area helper tests, and one Tcl control-flow
test passed. Tests include 32 requested rows with 20 actual fixture DDC sources,
changed-source/report receipts, original reused results, rounded violated slack,
hold/setup QoR separation and cross-scope resume. Independent review blockers
were fixed. Parent129/baseline204 hashes remained unchanged. The small update
archive has 11 reviewed source files and no server results, PDK files or RTL.
Actual DC execution and actual PPA numbers require running the update on server.

User scope correction: only 16 SoC runs completed; standalone accelerator runs
were stopped. Default recovery scope is now soc. Summary/detail tables filter to
the requested scope while retaining other-scope receipts if any exist. Two added
regressions verify default CLI scope and 16 SoC recoveries despite failed/missing
accelerator records; current driver/parser suite has 17 tests.
