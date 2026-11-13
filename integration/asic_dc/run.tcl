# Run from any directory with: dc_shell -f integration/asic_dc/run.tcl
proc require_env {name} {
    if {![info exists ::env($name)] || $::env($name) eq ""} { error "Set $name before running DC" }
    return $::env($name)
}

proc check_macro_pins {macro width} {
    set cells [get_lib_cells -quiet */$macro]
    if {[sizeof_collection $cells] != 1} { error "Expected one library cell $macro" }
    set actual {}
    foreach_in_collection pin [get_lib_pins -quiet [get_object_name $cells]/*] {
        lappend actual [file tail [get_object_name $pin]]
    }
    set expected {CLK CEN GWEN RET1N}
    foreach {bus bits} [list Q 16 D 16 WEN 16 EMA 3 EMAW 2 A $width] {
        for {set i 0} {$i < $bits} {incr i} { lappend expected [format {%s[%d]} $bus $i] }
    }
    foreach pin $expected {
        if {$pin ni $actual} { error "$macro has no expected pin $pin" }
    }
}

proc macro_inventory {path protect} {
    set report [open $path w]
    puts $report "scope,reference,count,area_per_macro,subtotal"
    foreach {macro total expected_added} {
        RAMSP128X16 654 654 RAMSP1024X16 36 36 RAMSP4096X16 82 2
    } {
        set reference [get_lib_cells -quiet */$macro]
        if {[sizeof_collection $reference] != 1} { error "Expected one library cell $macro" }
        set area [get_attribute $reference area]
        if {![string is double -strict $area] || $area <= 0 || $area >= Inf} {
            error "Missing positive area for $macro"
        }
        set instances [get_cells -hierarchical -quiet -filter "ref_name == $macro"]
        set count [sizeof_collection $instances]
        if {$count != $total} { error "$macro count $count differs from expected $total" }
        array set observed {added 0 cpu 0 shared 0}
        foreach_in_collection cell $instances {
            set name [get_object_name $cell]
            if {[string match cpu/* $name]} {
                incr observed(cpu)
            } elseif {[string match bus/shared/* $name]} {
                incr observed(shared)
            } else {
                incr observed(added)
            }
        }
        set expected_cpu [expr {$macro eq "RAMSP4096X16" ? 16 : 0}]
        set expected_shared [expr {$macro eq "RAMSP4096X16" ? 64 : 0}]
        if {$observed(added) != $expected_added || $observed(cpu) != $expected_cpu ||
            $observed(shared) != $expected_shared} { error "Wrong hierarchy partition for $macro" }
        foreach scope {added cpu shared} {
            puts $report "$scope,$macro,$observed($scope),$area,[expr {$area*$observed($scope)}]"
        }
        if {$protect} { set_dont_touch $instances true }
    }
    close $report
}

proc run_encoder_dc {here} {
    set root [file normalize [file join $here ../..]]
    set output [file join $root output encoder-dc dc]
    if {[info exists ::env(KWT_DC_OUTPUT)]} { set output [file normalize $::env(KWT_DC_OUTPUT)] }
    set std_db [file normalize [require_env KWT_STD_DB]]
    set libraries [list $std_db]
    foreach depth {128 1024 4096} {
        lappend libraries [file normalize [require_env KWT_SRAM_DB_$depth]]
    }
    foreach lib $libraries {
        if {![file isfile $lib]} { error "Library does not exist: $lib" }
    }
    set ema [require_env KWT_SRAM_EMA]
    set emaw [require_env KWT_SRAM_EMAW]
    if {![regexp {^[0-7]$} $ema] || ![regexp {^[0-3]$} $emaw]} { error "Invalid EMA/EMAW" }

    set e203 [file join $root assets references e203_hbirdv2-9f3e34f337f5d0a1236a285871ffa2032491617a rtl e203]
    if {![file isfile [file join $e203 core e203_cpu_top.v]]} {
        error "Pinned E203 is missing. Run scripts/download_competition_assets.py first."
    }
    file mkdir $output [file join $output work] [file join $output include]
    set header [open [file join $output include sram_config.vh] w]
    puts $header "`define KWT_SRAM_EMA 3'd$ema\n`define KWT_SRAM_EMAW 2'd$emaw"
    close $header
    define_design_lib WORK -path [file join $output work]
    set_app_var target_library [list $std_db]
    set_app_var synthetic_library {}
    set_app_var link_library [concat [list *] $libraries]
    set_app_var search_path [concat [list [file join $e203 core] [file join $output include]] [get_app_var search_path]]
    set_app_var verilogout_no_tri true
    foreach lib $libraries { read_db $lib }
    foreach {depth width} {128 7 1024 10 4096 12} { check_macro_pins RAMSP${depth}X16 $width }
    set_svf [file join $output encoder.svf]

    set sources {}
    foreach file [lsort [glob -directory [file join $e203 core] *.v]] { lappend sources $file }
    foreach file [lsort [glob -directory [file join $e203 general] *.v]] {
        if {[file tail $file] ne "sirv_gnrl_ram.v"} { lappend sources $file }
    }
    lappend sources [file join $e203 subsys e203_subsys_nice_core.v]
    set listfile [open [file join $here encoder.f] r]
    foreach path [split [read $listfile] \n] {
        set path [string trim $path]
        if {$path ne ""} { lappend sources [file join $root $path] }
    }
    close $listfile
    foreach module {kwt_sram16 kwt_banked_sram kwt_shared_sram sirv_gnrl_ram} {
        lappend sources [file join $root undergrad_ffn1 tech $module.sv]
    }
    lappend sources [file join $root integration kwt_encoder_soc.sv]
    if {![analyze -format sverilog -library WORK -define {SYNTHESIS DISABLE_SV_ASSERTION} $sources]} {
        error "RTL analyze failed"
    }
    if {[elaborate kwt_encoder_soc -library WORK -parameters "PROJECTION_K4=1,WIDE_MACRO=1"] in {0 {}}} {
        error "RTL elaborate failed"
    }
    set top [get_object_name [current_design]]
    if {$top ne "kwt_encoder_soc" && ![rename_design $top kwt_encoder_soc]} {
        error "Cannot rename elaborated top $top"
    }
    current_design kwt_encoder_soc
    redirect -file [file join $output link.rpt] { set linked [link] }
    if {!$linked} { error "Link failed. Inspect link.rpt" }
    uniquify
    redirect -file [file join $output check-design-before.rpt] { set valid [check_design] }
    if {!$valid} { error "Pre-compile check_design failed" }
    macro_inventory [file join $output sram-before.csv] 1
    source [file join $here encoder.sdc]
    set_fix_multiple_port_nets -all -buffer_constants
    if {![compile_ultra -no_autoungroup -no_boundary_optimization]} { error "compile_ultra failed" }
    write -format ddc -hierarchy -output [file join $output encoder.ddc]
    write -format verilog -hierarchy -output [file join $output encoder.v]
    write_sdc [file join $output encoder.mapped.sdc]
    redirect -file [file join $output area.rpt] { report_area -hierarchy }
    redirect -file [file join $output setup.rpt] { report_timing -delay_type max -max_paths 20 }
    redirect -file [file join $output hold.rpt] { report_timing -delay_type min -max_paths 20 }
    redirect -file [file join $output constraints.rpt] { report_constraint -all_violators }
    redirect -file [file join $output check-timing.rpt] { check_timing }
    redirect -file [file join $output check-design.rpt] { set valid [check_design] }
    if {!$valid} { error "Post-compile check_design failed" }
    macro_inventory [file join $output sram-mapped.csv] 0
    source [file join $root undergrad_ffn1 script area_scope.tcl]
    if {![kwt_write_scope_area_report [file join $output area-by-scope.rpt]]} {
        error "Incomplete area. Inspect area-by-scope.rpt"
    }
    set_svf -off
    puts "KWT_DC_COMPLETE $output"
}

set script_dir [file dirname [file normalize [info script]]]
if {[catch {run_encoder_dc $script_dir} message]} {
    puts stderr "KWT_DC_ERROR $message"
    exit 1
}
exit 0
