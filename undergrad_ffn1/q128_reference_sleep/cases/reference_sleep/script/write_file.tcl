# -----------------------------------------------------------------------------
# Portable deliverables and reports. No deletion of prior runs.
# -----------------------------------------------------------------------------
change_names -rules verilog -hierarchy
write -format ddc -hierarchy -output [file join $run_dir netlist ${top_design}.ddc]
write -format verilog -hierarchy -output [file join $run_dir netlist ${top_design}.v]
write_sdc [file join $run_dir sdc ${top_design}.sdc]
write_sdf [file join $run_dir sdf ${top_design}.sdf]
redirect -file [file join $rpt_path area.rpt] { report_area -hierarchy }
redirect -file [file join $rpt_path qor.rpt] { report_qor }
redirect -file [file join $rpt_path timing_setup.rpt] { report_timing -delay_type max -max_paths 50 -nworst 2 -input_pins -nets -transition_time -capacitance -nosplit }
redirect -file [file join $rpt_path timing_hold_ss_only.rpt] { report_timing -delay_type min -max_paths 50 -nworst 2 -nosplit }
redirect -file [file join $rpt_path constraints.rpt] { report_constraint -all_violators -verbose }
redirect -file [file join $rpt_path clocks.rpt] { report_clock }
redirect -file [file join $rpt_path ports.rpt] { report_port -verbose }
redirect -file [file join $rpt_path check_timing_after.rpt] { check_timing }
redirect -file [file join $rpt_path references.rpt] { report_reference -hierarchy }
redirect -file [file join $rpt_path units.rpt] { report_units }
# Machine-readable actual saved clock periods; report_units supplies time units.
set metadata [open [file join $rpt_path recovery_metadata.rpt] w]
puts $metadata "scope=$synthesis_scope"
puts $metadata "power_method=vectorless_NOT_OFFICIAL"
puts $metadata "hold_corner=SS_only_NOT_fast_corner_signoff"
foreach_in_collection clock_object [get_clocks -quiet *] {
    puts $metadata "clock=[get_object_name $clock_object]\tperiod=[get_attribute $clock_object period]"
}
close $metadata
set area_scope_valid 1
if {$synthesis_scope eq "soc"} {
    source [file join [file dirname [info script]] area_scope.tcl]
    set area_scope_valid [kwt_write_scope_area_report [file join $rpt_path area_scope.rpt]]
}
set latches [all_registers -level_sensitive]
redirect -file [file join $rpt_path latches.rpt] {
    if {[sizeof_collection $latches]} { report_cell $latches } else { puts "No level-sensitive registers." }
}
redirect -file [file join $rpt_path power_vectorless_NOT_OFFICIAL.rpt] { report_power -hierarchy }
set_svf -off
set summary [open [file join $rpt_path READ_FIRST.txt] w]
puts $summary "Inspect setup slack and all constraint violations. Script completion does not imply timing closure."
puts $summary "SS-only min-delay report is NOT a fast-corner hold signoff."
puts $summary "No placed/routed parasitics; inspect wire-load and external SRAM budgets."
puts $summary "Vectorless power is a tool estimate, NOT competition task-average power/energy."
puts $summary "Area includes linked internal RAMSP macros; compare units/areas with official data."
puts $summary "Synthesis scope=$synthesis_scope. SoC contains E203/TCMs/shared SRAM; accelerator scope excludes them."
puts $summary "Reference integration is not the official fixed peripheral platform. Task-activity power is still pending."
puts $summary "Expected native SRAM inventory=$expected_macros; bytes=$expected_sram_bytes"
puts $summary "Parameters: DMA_BURST=$dma_burst HOST_BURST=$host_burst"
puts $summary "Area scope complete=$area_scope_valid; UNKNOWN areas are not zero."
close $summary
source [file join $backend_root script power_diagnostics.tcl]
kwt_diag::structure [file join $rpt_path diagnostics mapped]
kwt_write_clock_gating_reports
if {!$area_scope_valid} {
    fail "area scope incomplete; inspect area_scope.rpt; other reports have been saved"
}
