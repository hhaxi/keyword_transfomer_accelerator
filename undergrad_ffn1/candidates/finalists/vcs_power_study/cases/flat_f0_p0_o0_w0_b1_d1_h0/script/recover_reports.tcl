# Usage (Bash): KWT_RECOVER_DDC=/absolute/path/design_compiled.ddc dc_shell -f script/recover_reports.tcl
# Restores the DDC's existing constraints. Never sources current constraints or compiles RTL.
set backend_root [file normalize [file join [file dirname [info script]] ..]]
if {[info exists env(KWT_RECOVER_BACKEND_ROOT)]} {
    set backend_root [file normalize $env(KWT_RECOVER_BACKEND_ROOT)]
}
set sh_continue_on_error false
if {[catch {
    source [file join $backend_root script common.tcl]
    source [file join $backend_root config library_config.tcl]
    resolve_and_validate
    if {![info exists env(KWT_RECOVER_DDC)]} { fail "set KWT_RECOVER_DDC to an existing compiled DDC" }
    set ddc [require_file $env(KWT_RECOVER_DDC) "saved DDC"]
    set_app_var target_library [list $std_db]
    set recovery_libs [list * $std_db]
    foreach name $required_sram_db_names { lappend recovery_libs [set $name] }
    set_app_var link_library $recovery_libs
    read_ddc $ddc
    set restored [get_object_name [current_design]]
    if {$restored ne $top_design && ![string match "${top_design}_*" $restored]} {
        fail "saved design '$restored' does not match requested scope=$synthesis_scope ($top_design)"
    }
    if {![link]} { fail "saved DDC link failed" }
    if {[sizeof_collection [get_clocks -quiet *]]==0} { fail "saved DDC has no clocks; restore its original SDC first" }
    set recovered [file join [file dirname [file dirname $ddc]] report_recovered_[clock format [clock seconds] -format %Y%m%d_%H%M%S]_[pid]]
    if {[info exists env(KWT_RECOVER_REPORT_DIR)]} {
        set recovered [file normalize $env(KWT_RECOVER_REPORT_DIR)]
    }
    file mkdir $recovered
    redirect -file [file join $recovered timing_setup.rpt] { report_timing -delay_type max -max_paths 50 -nworst 2 -input_pins -nets -transition_time -capacitance -nosplit }
    redirect -file [file join $recovered timing_hold_ss_only.rpt] { report_timing -delay_type min -max_paths 50 -nosplit }
    redirect -file [file join $recovered clocks.rpt] { report_clock }
    redirect -file [file join $recovered constraints.rpt] { report_constraint -all_violators -verbose }
    redirect -file [file join $recovered check_timing.rpt] { check_timing }
    redirect -file [file join $recovered area.rpt] { report_area -hierarchy }
    redirect -file [file join $recovered qor.rpt] { report_qor }
    redirect -file [file join $recovered units.rpt] { report_units }
    redirect -file [file join $recovered references.rpt] { report_reference -hierarchy }
    redirect -file [file join $recovered check_design.rpt] { set recovered_design_valid [check_design] }
    redirect -file [file join $recovered power_vectorless_NOT_OFFICIAL.rpt] { report_power -hierarchy }
    set inventory_valid 1
    set inventory [open [file join $recovered sram_inventory.rpt] w]
    foreach macro {RAMSP128X16 RAMSP1024X16 RAMSP4096X16} {
        set expected 0
        foreach spec $expected_macros {
            lassign $spec candidate count
            if {$candidate eq $macro} { set expected $count }
        }
        set actual [sizeof_collection [get_cells -hierarchical -quiet -filter "ref_name == $macro"]]
        if {$actual!=$expected} { set inventory_valid 0 }
        puts $inventory "$macro count=$actual expected=$expected"
    }
    close $inventory
    set meta [open [file join $recovered recovery_metadata.rpt] w]
    puts $meta "scope=$synthesis_scope"
    puts $meta "design=$restored"
    puts $meta "source_ddc=$ddc"
    puts $meta "check_design_valid=$recovered_design_valid"
    puts $meta "inventory_valid=$inventory_valid"
    puts $meta "area_method=exact_constant_pseudo_zero_other_unknown_fail"
    foreach_in_collection clock_object [get_clocks -quiet *] {
        puts $meta "clock=[get_object_name $clock_object]\tperiod=[get_attribute $clock_object period]"
    }
    puts $meta "power_method=vectorless_NOT_OFFICIAL"
    puts $meta "hold_corner=SS_only_NOT_fast_corner_signoff"
    close $meta
    set library_sources [open [file join $recovered library_sources.rpt] w]
    puts $library_sources "path=$std_db"
    foreach name $required_sram_db_names { puts $library_sources "path=[set $name]" }
    close $library_sources
    set area_scope_valid 1
    if {[string match "kwt_ffn1_soc*" $restored]} {
        source [file join $backend_root script area_scope.tcl]
        set area_scope_valid [kwt_write_scope_area_report [file join $recovered area_scope.rpt]]
    }
    if {!$area_scope_valid} { fail "area scope incomplete; other recovered reports have been saved" }
    if {!$recovered_design_valid} { fail "saved design failed check_design; inspect recovered reports" }
    if {!$inventory_valid} { fail "saved SRAM inventory does not match selected case; inspect sram_inventory.rpt" }
    puts "KWT_REPORTS_RECOVERED: design=$restored source=$ddc reports=$recovered"
} message]} { puts stderr "KWT_RECOVERY_FAILED: $message"; exit 1 }
exit 0
