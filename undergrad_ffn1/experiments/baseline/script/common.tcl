# Pure Tcl helpers; can be exercised without a Synopsys license.
proc fail {message} { error "KWT: $message" }
proc require_file {path label} {
    if {[string match *__EDIT_* $path] || ![file isfile $path] || ![file readable $path]} {
        fail "$label is missing/unreadable: $path; edit config/library_config.tcl"
    }
    return [file normalize $path]
}
proc find_basename {dir basename} {
    if {![file isdirectory $dir]} { return {} }
    set found [glob -nocomplain -types f -directory $dir $basename]
    foreach child [glob -nocomplain -types d -directory $dir *] {
        if {[file type $child] ne "link"} {
            set found [concat $found [find_basename $child $basename]]
        }
    }
    return $found
}
proc resolve_and_validate {} {
    global std_db std_root std_basename sram_db_128 sram_db_1024 sram_db_4096
    global sram_ema sram_emaw sram_controls_confirmed
    global max_cores dma_burst host_burst clock_period_ns backend_root
    global synthesis_scope top_design design_filelist expected_macros expected_macro_total expected_sram_bytes
    global clock_setup_uncertainty_ns clock_hold_uncertainty_ns
    global clock_uncertainty_ns clock_transition_ns input_transition_ns
    global io_input_max_ns io_input_min_ns io_output_max_ns io_output_min_ns
    global shared_read_max_ns shared_read_min_ns shared_setup_ns shared_hold_ns output_load_pf
    if {$synthesis_scope eq "soc"} {
        set top_design kwt_ffn1_soc
        set expected_macros {{RAMSP1024X16 18} {RAMSP4096X16 82}}
        set expected_macro_total 100
        set expected_sram_bytes 708608
    } elseif {$synthesis_scope eq "accelerator"} {
        set top_design kwt_ffn1_top
        set expected_macros {{RAMSP1024X16 18} {RAMSP4096X16 2}}
        set expected_macro_total 20
        set expected_sram_bytes 53248
    } else { fail "synthesis_scope must be soc or accelerator" }
    set design_filelist [file join $backend_root filelists [expr {$synthesis_scope eq "soc" ? "soc.f" : "accelerator.f"}]]
    if {$std_db eq ""} {
        set matches [find_basename $std_root $std_basename]
        if {[llength $matches]!=1} { fail "expected exactly one $std_basename below $std_root; found [llength $matches]. Set std_db explicitly." }
        set std_db [lindex $matches 0]
    }
    set std_db [require_file $std_db "RVT SS standard-cell DB"]
    foreach name {sram_db_1024 sram_db_4096} {
        upvar #0 $name value
        set value [require_file $value $name]
    }
    foreach spec {{sram_ema 7} {sram_emaw 3}} {
        lassign $spec name maximum
        upvar #0 $name value
        if {![string is integer -strict $value] || $value<0 || $value>$maximum} {
            fail "$name must be an integer from 0 to $maximum, matching the SP control width"
        }
    }
    if {$sram_controls_confirmed ne "1"} {
        fail "confirm SP EMA/EMAW and set sram_controls_confirmed to 1"
    }
    foreach name {max_cores dma_burst host_burst} {
        upvar #0 $name value
        if {![string is integer -strict $value] || $value<0} { fail "invalid $name" }
    }
    if {$max_cores<1 || $dma_burst<1 || $dma_burst>32 || $host_burst>32} { fail "invalid core/burst configuration" }
    foreach name {clock_period_ns clock_uncertainty_ns clock_setup_uncertainty_ns clock_hold_uncertainty_ns clock_transition_ns input_transition_ns io_input_max_ns io_input_min_ns io_output_max_ns io_output_min_ns shared_read_max_ns shared_read_min_ns shared_setup_ns shared_hold_ns output_load_pf} {
        upvar #0 $name value
        if {![string is double -strict $value]} { fail "invalid $name" }
        if {$name ni {io_input_min_ns io_output_min_ns shared_read_min_ns} && $value<0} {
            fail "invalid $name"
        }
    }
    if {$clock_period_ns<=0 || $io_input_min_ns>$io_input_max_ns || $io_output_min_ns>$io_output_max_ns || $shared_read_min_ns>$shared_read_max_ns} { fail "inconsistent timing budgets" }
    set filelist [open $design_filelist r]
    set entries [split [read $filelist] \n]; close $filelist
    foreach line $entries {
        set line [string trim $line]
        if {$line ne "" && ![string match #* $line]} {
            require_file [file join $backend_root $line] "RTL source"
        }
    }
}
proc write_sram_header {path} {
    global sram_ema sram_emaw
    set out [open $path w]
    puts $out "// Generated from confirmed server configuration; do not edit."
    puts $out "`define KWT_SRAM_EMA 3'd$sram_ema"
    puts $out "`define KWT_SRAM_EMAW 2'd$sram_emaw"
    close $out
}

