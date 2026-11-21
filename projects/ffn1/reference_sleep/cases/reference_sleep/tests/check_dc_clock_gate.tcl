# Exercise the DC command selection and coverage check without a DC license.
set project [file normalize [file join [file dirname [info script]] ..]]
source [file join $project script clock_gating.tcl]
set rpt_path [file join $project tmp clock_gate_tcl_check]
file mkdir $rpt_path
set inserted 0
proc fail {message} { error $message }
proc compile_ultra {args} { set ::compile_args $args; return 1 }
proc set_clock_gating_style {args} { set ::gating_style $args }
proc identify_clock_gating {} {}
proc redirect {option path script} {
    set out [open $path w]
    puts $out [uplevel 1 $script]
    close $out
}
proc report_clock_gating {args} {
    return "| Number of tool-inserted clock gating elements | $::inserted (100.00%) |"
}
proc verify {condition} {
    if {![uplevel 1 [list expr $condition]]} { error "failed: $condition" }
}

set kwt_gate_clock 0
kwt_compile_design
verify {$compile_args eq {-no_autoungroup}}
verify {![info exists gating_style]}
kwt_write_clock_gating_reports

set kwt_gate_clock 1
kwt_compile_design
verify {$compile_args eq {-gate_clock -no_autoungroup}}
verify {$gating_style eq {-minimum_bitwidth 8 -max_fanout 64}}
verify {[catch {kwt_write_clock_gating_reports} msg]}
verify {[string match {*no tool-inserted*} $msg]}
verify {[file isfile [file join $rpt_path clock_gating_elements.rpt]]}
set inserted 7
kwt_write_clock_gating_reports
puts "Q128_DC_CLOCK_GATE_TCL_PASS"
