set comparison_root [file normalize [file join [file dirname [info script]] ..]]
if {![info exists env(KWT_GLOBAL_LOCAL_CONFIG)]} {
    set env(KWT_GLOBAL_LOCAL_CONFIG) [file join $comparison_root config local_config.tcl]
}
source [file join $comparison_root experiments cases i0_h1_x0_b0 script run_all.tcl]
