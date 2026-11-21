# Annotate the saved design that produced the exact Verilog simulated in VCS.
set sh_continue_on_error false
if {[catch {
    set backend_root [file normalize [file join [file dirname [info script]] ..]]
    source [file join $backend_root script common.tcl]
    source [file join $backend_root config library_config.tcl]
    resolve_and_validate
    if {$synthesis_scope ne "soc"} { fail "gate activity requires SoC scope" }
    set ddc [require_file $env(KWT_ACTIVITY_DDC) "mapped DDC"]
    set saif [require_file $env(KWT_ACTIVITY_SAIF) "gate-level SAIF"]
    set settings_file [open [file join [file dirname [file dirname $ddc]] report run_settings.txt] r]
    set settings [split [read $settings_file] \n]
    close $settings_file
    foreach name [linsert $required_sram_db_names 0 std_db] {
        if {[lsearch -exact $settings "$name = [set $name]"]<0} {
            fail "$name does not match the saved synthesis run"
        }
    }
    cd $env(KWT_ACTIVITY_REPORT)
    set_app_var target_library [list $std_db]
    set libs [list * $std_db]
    foreach name $required_sram_db_names { lappend libs [set $name] }
    set_app_var link_library $libs
    read_ddc $ddc
    current_design $top_design
    if {![link]} { fail "mapped DDC link failed" }
    set clocks [get_clocks -quiet core_clk]
    if {[sizeof_collection $clocks]!=1 ||
        abs([get_attribute $clocks period]-6.666667)>0.000001} {
        fail "saved core_clk must match VCS 6.666667 ns"
    }
    source [file join $backend_root script power_diagnostics.tcl]
    kwt_diag::structure [file join $env(KWT_ACTIVITY_REPORT) diagnostics mapped]
    reset_switching_activity
    redirect -file annotation.rpt {
        set annotated [read_saif -input $saif -instance_name tb_soc/dut -verbose]
    }
    if {![string is boolean -strict $annotated] || !$annotated} {
        fail "gate-level SAIF annotation failed; inspect annotation.rpt"
    }
    redirect -file coverage.rpt { report_saif -hierarchy }
    set coverage_file [open coverage.rpt r]
    set coverage [read $coverage_file]
    close $coverage_file
    if {![regexp -nocase -line {^[ \t]*(Nets|Seq Cells)[ \t]+[1-9][0-9]*\(} $coverage]} {
        fail "no annotated nets or sequential cells reported; inspect coverage.rpt"
    }
    kwt_diag::activity [file join $env(KWT_ACTIVITY_REPORT) diagnostics annotated_before_power] before_power 0
    redirect -file power.rpt { report_power -hierarchy }
    redirect -file coverage_after_power.rpt { report_saif -hierarchy }
    kwt_diag::activity [file join $env(KWT_ACTIVITY_REPORT) diagnostics annotated_after_power] after_power 1
} message]} {
    puts stderr "KWT_GATE_ACTIVITY_FAILED: $message"
    if {[info exists errorInfo]} { puts stderr $errorInfo }
    exit 1
}
puts "KWT_GATE_ACTIVITY_COMPLETED"
exit 0
