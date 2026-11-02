# Usage (Bash): KWT_RECOVER_DDC=/absolute/path/design_compiled.ddc dc_shell -f script/recover_reports.tcl
# Restores the DDC's existing constraints. Never sources current constraints or compiles RTL.
set backend_root [file normalize [file join [file dirname [info script]] ..]]
set sh_continue_on_error false
if {[catch {
    source [file join $backend_root script common.tcl]
    source [file join $backend_root config library_config.tcl]
    resolve_and_validate
    if {![info exists env(KWT_RECOVER_DDC)]} { fail "set KWT_RECOVER_DDC to an existing compiled DDC" }
    set ddc [require_file $env(KWT_RECOVER_DDC) "saved DDC"]
    set_app_var target_library [list $std_db]
    set_app_var link_library [list * $std_db $sram_db_1024 $sram_db_4096]
    read_ddc $ddc
    set restored [get_object_name [current_design]]
    if {![link]} { fail "saved DDC link failed" }
    if {[sizeof_collection [get_clocks -quiet *]]==0} { fail "saved DDC has no clocks; restore its original SDC first" }
    set recovered [file join [file dirname [file dirname $ddc]] report_recovered_[clock format [clock seconds] -format %Y%m%d_%H%M%S]_[pid]]
    file mkdir $recovered
    redirect -file [file join $recovered timing_setup.rpt] { report_timing -delay_type max -max_paths 50 -nworst 2 -input_pins -nets -transition_time -capacitance -nosplit }
    redirect -file [file join $recovered timing_hold_ss_only.rpt] { report_timing -delay_type min -max_paths 50 -nosplit }
    redirect -file [file join $recovered clocks.rpt] { report_clock }
    redirect -file [file join $recovered constraints.rpt] { report_constraint -all_violators -verbose }
    redirect -file [file join $recovered check_timing.rpt] { check_timing }
    redirect -file [file join $recovered area.rpt] { report_area -hierarchy }
    redirect -file [file join $recovered power_vectorless_NOT_OFFICIAL.rpt] { report_power -hierarchy }
    set area_scope_valid 1
    if {[string match "kwt_ffn1_soc*" $restored]} {
        source [file join $backend_root script area_scope.tcl]
        set area_scope_valid [kwt_write_scope_area_report [file join $recovered area_scope.rpt]]
    }
    puts "KWT_REPORTS_RECOVERED: design=$restored source=$ddc reports=$recovered"
    if {!$area_scope_valid} { fail "area scope incomplete; other recovered reports have been saved" }
} message]} { puts stderr "KWT_RECOVERY_FAILED: $message"; exit 1 }
exit 0
