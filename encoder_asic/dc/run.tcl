# Run: dc_shell -f encoder_asic/dc/run.tcl (from repository root or any cwd).
set project [file normalize [file join [file dirname [info script]] ..]]
set output [file join $project output dc]
file mkdir $output
set std_db {};set sram_dbs {};set saif_file {};set saif_instance {}
if {[info exists ::env(KWT_DC_STDLIB)]} {set std_db $::env(KWT_DC_STDLIB)}
if {[info exists ::env(KWT_DC_SRAM_DBS)]} {set sram_dbs $::env(KWT_DC_SRAM_DBS)}
if {[file exists [file join $project config local.tcl]]} {source [file join $project config local.tcl]}
if {$std_db eq {} || [llength $sram_dbs]==0} {error "Configure std_db and sram_dbs in encoder_asic/config/local.tcl"}
foreach f [concat [list $std_db] $sram_dbs] {if {![file exists $f]} {error "Missing technology DB: $f"}}
set_app_var target_library [list $std_db]
set_app_var link_library [concat [list * $std_db] $sram_dbs]
set_app_var search_path [concat [list [file join $project rtl]] $search_path]
define_design_lib WORK -path [file join $output work]
set_svf [file join $output encoder.svf]
set fh [open [file join $project sources.f] r];set files {}
foreach f [split [read $fh] \n] {if {[string trim $f] ne {}} {lappend files [file join $project [string trim $f]]}}
close $fh
lappend files [file join $project dc kwt_sram16.sv]
analyze -format sverilog -define SYNTHESIS $files
elaborate kwt_encoder_dc_top
current_design kwt_encoder_dc_top
if {![link]} {error "Link failed; check native SRAM DB names and ports"}
redirect -file [file join $output check_design.rpt] {check_design}
if {![check_design]} {error "check_design failed"}
source [file join $project dc constraints.sdc]
set_clock_gating_style -minimum_bitwidth 8 -max_fanout 64
if {![compile_ultra -no_autoungroup -gate_clock]} {error "DC compile failed"}
if {![check_design]} {error "Mapped check_design failed"}
redirect -file [file join $output area.rpt] {report_area -hierarchy}
redirect -file [file join $output timing_setup.rpt] {report_timing -delay_type max -max_paths 20}
redirect -file [file join $output timing_hold.rpt] {report_timing -delay_type min -max_paths 20}
redirect -file [file join $output constraints.rpt] {report_constraint -all_violators}
redirect -file [file join $output clock_gating.rpt] {report_clock_gating}
redirect -file [file join $output references.rpt] {report_reference -hierarchy}
redirect -file [file join $output clocks.rpt] {report_clock}
if {$saif_file ne {}} {
 if {$saif_instance eq {}} {error "Set saif_instance for real workload SAIF"}
 read_saif -input $saif_file -instance_name $saif_instance
 redirect -file [file join $output activity.rpt] {report_saif}
 redirect -file [file join $output power.rpt] {report_power -hierarchy}
}
change_names -rules verilog -hierarchy
write -format verilog -hierarchy -output [file join $output encoder_netlist.v]
write -format ddc -hierarchy -output [file join $output encoder.ddc]
write_sdc [file join $output encoder.sdc]
write_sdf [file join $output encoder.sdf]
puts "KWT_ENCODER_DC_COMPLETE: $output"
quit
