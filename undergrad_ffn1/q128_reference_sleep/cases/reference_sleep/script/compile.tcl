# Optimize user hierarchy; keep linked native SRAM cells intact.
kwt_compile_design
# Save the optimized design BEFORE acceptance checks/reporting, so a later
# failure does not discard the expensive compile result.
write -format ddc -hierarchy -output [file join $run_dir netlist ${top_design}_compiled.ddc]
write_sdc [file join $run_dir sdc ${top_design}_compiled.sdc]
redirect -file [file join $rpt_path check_design_after.rpt] { set valid [check_design] }
if {!$valid} { fail "check_design failed after compile" }
set unmapped [get_cells -hierarchical -quiet -filter {is_unmapped == true}]
if {[sizeof_collection $unmapped]!=0} {
    redirect -file [file join $rpt_path unmapped.rpt] { report_cell $unmapped }
    fail "unmapped cells remain after compile"
}
check_macro_inventory
