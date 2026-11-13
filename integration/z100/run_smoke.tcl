set script_dir [file dirname [file normalize [info script]]]
source [file join $script_dir create_smoke.tcl]
if {[info exists ::env(Z100_IN_PROCESS)] && $::env(Z100_IN_PROCESS) eq "1"} {
    synth_design -top z100_wrapper -part xc7z035ffg900-2
    opt_design
    if {!$contest} {power_opt_design}
    place_design
    phys_opt_design
    route_design
} else {
    launch_runs impl_1 -to_step write_bitstream -jobs 1
    wait_on_run impl_1
    if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
        error "Z100 implementation failed: [get_property STATUS [get_runs impl_1]]"
    }
}
source [file join $script_dir finish_smoke.tcl]
