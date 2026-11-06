# Real ICG mapping only. Called after read_db, before analyze; never alter CPU/SRAM.
proc kwt_cg_attr {object attribute {default ""}} {
    if {[catch {get_attribute -quiet $object $attribute} value]} { return $default }
    if {$value eq ""} { return $default }
    return $value
}
proc kwt_cg_true {value} { return [expr {$value eq "true" || $value eq "1"}] }
proc kwt_cg_mapping {cell} {
    set kind [kwt_cg_attr $cell clock_gating_integrated_cell]
    if {$kind ni {latch_posedge latch_posedge_precontrol latch_posedge_postcontrol}} { return {} }
    if {[kwt_cg_true [kwt_cg_attr $cell dont_use false]]} { return {} }
    set map [dict create cell [get_object_name $cell] kind $kind]
    foreach_in_collection pin [get_lib_pins -quiet [get_object_name $cell]/*] {
        set role ""
        foreach {attribute label} {clock_gate_clock_pin clk clock_gate_enable_pin en clock_gate_out_pin out clock_gate_test_pin test} {
            if {[kwt_cg_true [kwt_cg_attr $pin $attribute false]]} { set role $label }
        }
        if {$role eq "" || [dict exists $map $role]} { return {} }
        set name [file tail [get_object_name $pin]]
        if {![regexp {^[A-Za-z_][A-Za-z0-9_$]*$} $name]} { return {} }
        set direction [kwt_cg_attr $pin direction]
        if {$role eq "out"} {
            if {$direction ni {out output}} { return {} }
        } elseif {$direction ni {in input}} { return {} }
        dict set map $role $name
    }
    foreach required {clk en out} { if {![dict exists $map $required]} { return {} } }
    set area [kwt_cg_attr $cell area]
    if {![string is double -strict $area] || $area<=0} { return {} }
    dict set map area $area
    return $map
}
proc kwt_cg_prepare {} {
    global backend_root run_dir rpt_path env kwt_cg_expected kwt_cg_selected
    source [file join $backend_root config clock_gating_config.tcl]
    set kwt_cg_selected {}
    if {$kwt_cg_expected==0} { return }
    set candidates {}
    set requested ""
    if {[info exists env(KWT_ICG_LIB_CELL)]} { set requested $env(KWT_ICG_LIB_CELL) }
    # Library attributes, not guessed foundry pin names. Optional exact-cell override.
    foreach_in_collection cell [get_lib_cells -quiet */*] {
        set name [get_object_name $cell]
        if {$requested ne "" && $name ne $requested && [file tail $name] ne $requested} { continue }
        set mapping [kwt_cg_mapping $cell]
        if {[dict size $mapping]} { lappend candidates [list [dict get $mapping area] $name $mapping] }
    }
    if {![llength $candidates]} {
        fail "No compatible latch_posedge ICG with clock_gate_* pin attributes. Inspect report_lib; select KWT_ICG_LIB_CELL. No behavioral gate fallback is allowed."
    }
    if {$requested ne "" && [llength $candidates]!=1} { fail "Ambiguous KWT_ICG_LIB_CELL" }
    set selected [lindex [lsort -real -index 0 $candidates] 0]
    set kwt_cg_selected [lindex $selected 2]
    set module_name [file tail [dict get $kwt_cg_selected cell]]
    if {![regexp {^[A-Za-z_][A-Za-z0-9_$]*$} $module_name]} { fail "Unsupported ICG HDL identifier" }
    set ports {}
    foreach {role signal} {clk clk en en out gclk test test_en} {
        if {[dict exists $kwt_cg_selected $role]} { lappend ports [format {.%s(%s)} [dict get $kwt_cg_selected $role] $signal] }
    }
    set header [open [file join $run_dir generated kwt_icg_instance.vh] w]
    puts $header "$module_name u_icg([join $ports {, }]);"
    close $header
    set receipt [open [file join $rpt_path icg_library_mapping.rpt] w]
    puts $receipt $kwt_cg_selected
    puts $receipt "Expected_new_ICGs=$kwt_cg_expected; CPU gates unchanged; test_en tied inactive in functional SoC."
    close $receipt
}
proc kwt_cg_validate {stage} {
    global kwt_cg_expected kwt_cg_selected rpt_path
    set wrappers [get_cells -hierarchical -quiet -filter {ref_name =~ kwt_clock_gate*}]
    if {[sizeof_collection $wrappers]!=$kwt_cg_expected} { fail "ICG wrapper count mismatch at $stage" }
    if {$kwt_cg_expected==0} { return }
    set reference [file tail [dict get $kwt_cg_selected cell]]
    set found 0
    set receipt [open [file join $rpt_path icg_instances_${stage}.rpt] w]
    foreach_in_collection wrapper $wrappers {
        set name [get_object_name $wrapper]
        set instance [get_cells -quiet $name/u_icg]
        if {[sizeof_collection $instance]!=1 || [get_attribute $instance ref_name] ne $reference} {
            close $receipt; fail "Expected mapped ICG missing at $name"
        }
        incr found
        puts $receipt "$name/u_icg -> $reference"
    }
    puts $receipt "mapped_ICGs=$found expected=$kwt_cg_expected"
    close $receipt
    # Preserve intended clock partitions and fixed cell mapping; data logic still optimizes.
    set_dont_touch $wrappers true
}
proc kwt_cg_report {} {
    global kwt_cg_expected rpt_path
    kwt_cg_validate final
    if {$kwt_cg_expected==0} { return }
    if {![llength [info commands report_clock_gating]]} { fail "report_clock_gating unavailable" }
    redirect -file [file join $rpt_path clock_gating.rpt] { report_clock_gating }
    set out [open [file join $rpt_path CLOCK_GATING_ACCEPTANCE_REQUIRED.txt] w]
    puts $out "Mapping count verified, not PPA acceptance. Review gating setup/hold, pulse width, transitions and fanout."
    puts $out "Check actual ICG output clock activity in every measured task; unannotated clocks cannot be treated as zero."
    puts $out "Run postmapping functional equivalence or gate simulation with actual standard-cell/ICG models."
    close $out
}
