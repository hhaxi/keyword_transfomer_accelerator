# KWT DC entry point. Resolve all paths from this script, not the caller's cwd.
set backend_root [file normalize [file join [file dirname [info script]] ..]]
# Do not let the server's startup configuration continue sourced scripts after
# errors. Stage return values are checked as well; a failed analyze must not link.
set sh_continue_on_error false
if {[catch {
    source [file join $backend_root script common.tcl]
    source [file join $backend_root config library_config.tcl]
    set kwt_gate_clock 0
    if {[info exists env(KWT_GATE_CLOCK)]} { set kwt_gate_clock $env(KWT_GATE_CLOCK) }
    if {$kwt_gate_clock ni {0 1}} { fail "KWT_GATE_CLOCK must be 0 or 1" }
    set gate_mode [expr {$kwt_gate_clock ? "clock_gate" : "baseline"}]
    resolve_and_validate
    set rtl_saif ""
    if {[info exists env(KWT_RTL_SAIF)]} {
        set rtl_saif [require_file $env(KWT_RTL_SAIF) "RTL task SAIF"]
        if {$synthesis_scope ne "soc" || abs($clock_period_ns-6.666667)>0.000001} {
            fail "RTL activity requires SoC scope and a 6.666667 ns clock"
        }
    }
    set run_id "[clock format [clock seconds] -format %Y%m%d_%H%M%S]_[pid]_${gate_mode}_${synthesis_scope}"
    set run_dir [file join $backend_root run $run_id]
    foreach subdir {work report netlist sdc sdf svf generated log} {
        file mkdir [file join $run_dir $subdir]
    }
    cd $run_dir
    set rpt_path [file join $run_dir report]
    source [file join $backend_root script set_env.tcl]
    if {$rtl_saif ne ""} { saif_map -start }
    source [file join $backend_root script read_file.tcl]
    source [file join $backend_root script set_constraint.tcl]
    source [file join $backend_root script compile.tcl]
    source [file join $backend_root script write_file.tcl]
    if {$rtl_saif ne ""} { source [file join $backend_root script rtl_activity_power.tcl] }
} message]} {
    puts stderr "KWT_DC_FAILED: $message"
    if {[info exists errorInfo]} { puts stderr $errorInfo }
    exit 1
}
puts "KWT_DC_COMPLETED: $run_dir"
puts "Completion is NOT a claim of timing/area acceptance; inspect reports."
exit 0
