# Reuse the automatic insertion settings from the earlier low-power study.
proc kwt_compile_design {} {
    global kwt_gate_clock
    set options {-no_autoungroup}
    if {$kwt_gate_clock} {
        set_clock_gating_style -minimum_bitwidth 8 -max_fanout 64
        set options [linsert $options 0 -gate_clock]
    }
    if {![compile_ultra {*}$options]} { fail "compile_ultra returned failure" }
}

proc kwt_write_clock_gating_reports {} {
    global kwt_gate_clock rpt_path
    set summary [file join $rpt_path clock_gating.rpt]
    identify_clock_gating
    redirect -file $summary { report_clock_gating }
    redirect -file [file join $rpt_path clock_gating_elements.rpt] {
        report_clock_gating -gating_elements
    }
    if {$kwt_gate_clock} {
        set file [open $summary r]
        set report [read $file]
        close $file
        if {![regexp -nocase {Number of tool-inserted clock gating elements[ \t]*\|[ \t]*([0-9]+)} $report -> inserted]} {
            fail "cannot read tool-inserted clock-gate count; inspect $summary"
        }
        if {$inserted == 0} {
            fail "clock gating requested but no tool-inserted gates were reported; inspect $summary"
        }
        puts "KWT_CLOCK_GATING_INSERTED: $inserted"
    }
}
