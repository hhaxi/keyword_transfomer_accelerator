# -----------------------------------------------------------------------------
# Read only synthesizable design sources. Do not analyze vendor behavioral
# models, test fixtures, the old kwt_sram16, or KWT_SRAM_BLACKBOX declarations.
# -----------------------------------------------------------------------------
set sources {}
set input [open $design_filelist r]
foreach line [split [read $input] \n] {
    set line [string trim $line]
    if {$line ne "" && ![string match #* $line]} {
        lappend sources [file join $backend_root $line]
    }
}
close $input
if {![analyze -format sverilog -library WORK -define {SYNTHESIS DISABLE_SV_ASSERTION} $sources]} {
    fail "analyze failed; fix the first HDL compiler error above before elaboration"
}
set elaboration_status [elaborate $top_design -library WORK -parameters "DMA_BURST=$dma_burst,HOST_BURST=$host_burst"]
if {$elaboration_status eq "0" || $elaboration_status eq ""} {
    fail "elaborate failed for $top_design; see the first elaboration error above"
}
# Parameter overrides can make DC name the design TOP_PARAMvalue instead of TOP.
# elaborate sets the current design; query it rather than guessing the suffix.
set elaborated_top [get_object_name [current_design]]
if {$elaborated_top ne $top_design && ![string match "${top_design}_*" $elaborated_top]} {
    fail "unexpected elaborated top '$elaborated_top'; expected $top_design or its parameterized variant"
}
if {$elaborated_top ne $top_design} {
    if {![rename_design $elaborated_top $top_design]} {
        fail "cannot rename elaborated top '$elaborated_top' to '$top_design'"
    }
}
if {[sizeof_collection [get_designs -quiet $top_design]]!=1} {
    fail "expected exactly one elaborated design named $top_design"
}
current_design $top_design
puts "KWT_TOP_SELECTED: elaborated=$elaborated_top selected=$top_design"
redirect -file [file join $rpt_path link.rpt] { set linked [link] }
if {!$linked} { fail "link failed; see link.rpt" }
uniquify
redirect -file [file join $rpt_path check_design_before.rpt] { set valid [check_design] }
if {!$valid} { fail "check_design failed before compile" }

proc check_macro_inventory {} {
    global rpt_path expected_macros expected_macro_total expected_sram_bytes
    set out [open [file join $rpt_path sram_inventory.rpt] w]
    set total_area 0.0
    foreach spec $expected_macros {
        lassign $spec macro expected
        set instances [get_cells -hierarchical -quiet -filter "ref_name == $macro"]
        set count [sizeof_collection $instances]
        if {$count!=$expected} {
            close $out
            fail "$macro count is $count, expected $expected (missing/pruned/replaced macro)"
        }
        set cells [get_lib_cells -quiet */$macro]
        set area [get_attribute $cells area]
        if {![string is double -strict $area] || $area<=0} {
            close $out; fail "$macro has missing/nonpositive .db area"
        }
        set sum [expr {$count*$area}]
        set total_area [expr {$total_area+$sum}]
        puts $out "$macro count=$count area_per_macro=$area subtotal=$sum"
        set_dont_touch $instances true
    }
    puts $out "Total=$expected_macro_total macros; payload=$expected_sram_bytes bytes; .db macro area sum=$total_area"
    puts $out "Area units follow .db; verify against official macro area data."
    close $out
}
check_macro_inventory
