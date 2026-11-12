# Source after impl_1 completes through write_bitstream.
set source_dir [file normalize [file dirname [info script]]]
set build_dir [file normalize [file join $source_dir ../../output/z100]]
if {[info exists ::env(Z100_BUILD)]} {
    set build_dir [file normalize $::env(Z100_BUILD)]
}
set in_process [expr {[info exists ::env(Z100_IN_PROCESS)] && $::env(Z100_IN_PROCESS) eq "1"}]
if {!$in_process} {open_run impl_1}
set variant smoke
if {[get_property NAME [current_project]] eq "z100_kwt"} {
    set frequency 25
    if {[info exists ::env(Z100_FCLK_MHZ)]} {set frequency $::env(Z100_FCLK_MHZ)}
    set variant kwt-$frequency
}
report_timing_summary -report_unconstrained -file [file join $build_dir $variant-timing.rpt]
report_drc -file [file join $build_dir $variant-drc.rpt]
report_utilization -file [file join $build_dir $variant-utilization.rpt]
if {$in_process} {
    report_methodology -file [file join $build_dir $variant-methodology.rpt]
    write_checkpoint -force [file join $build_dir $variant-routed.dcp]
    set setup [get_property SLACK [lindex [get_timing_paths -delay_type max -max_paths 1] 0]]
    set hold [get_property SLACK [lindex [get_timing_paths -delay_type min -max_paths 1] 0]]
    if {$setup < 0 || $hold < 0} {error "Timing failed WNS=$setup WHS=$hold"}
}
set bitstream [file join $build_dir z100-$variant.bit]
write_bitstream -force $bitstream
if {![info exists ::env(Z100_BIT_ONLY)] || $::env(Z100_BIT_ONLY) ne "1"} {
    if {$in_process} {
        # The platform exporter looks up the bitstream in the project's run directory.
        set impl_dir [get_property DIRECTORY [get_runs impl_1]]
        file mkdir $impl_dir
        file copy -force $bitstream [file join $impl_dir z100_wrapper.bit]
    }
    write_hw_platform -fixed -include_bit -force -file [file join $build_dir z100-$variant.xsa]
}
