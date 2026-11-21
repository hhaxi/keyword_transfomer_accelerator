# Run in the same DC process that compiled the RTL and tracked name changes.
set activity_dir [file join $rpt_path rtl_activity task_00]
file mkdir $activity_dir
redirect -file [file join $activity_dir saif_mapping.rpt] { saif_map -report }
reset_switching_activity
redirect -file [file join $activity_dir annotation.rpt] {
    set annotated [read_saif -auto_map_names -input $rtl_saif -instance_name tb_soc/dut -verbose]
}
if {![string is boolean -strict $annotated] || !$annotated} {
    fail "RTL SAIF annotation failed; inspect $activity_dir/annotation.rpt"
}
set coverage_report [file join $activity_dir coverage.rpt]
redirect -file $coverage_report { report_saif -hierarchy -rtl_saif }
set coverage_file [open $coverage_report r]
set coverage [read $coverage_file]
close $coverage_file
if {![regexp -nocase -line {^[ \t]*Seq Cells[ \t]+[1-9][0-9]*[ \t]*\(} $coverage]} {
    fail "no sequential cells received RTL activity; inspect $coverage_report"
}
source [file join $backend_root script power_diagnostics.tcl]
kwt_diag::activity [file join $activity_dir diagnostics annotated_before_power] before_power 0
redirect -file [file join $activity_dir power.rpt] { report_power -hierarchy }
redirect -file [file join $activity_dir coverage_after_power.rpt] { report_saif -hierarchy }
kwt_diag::activity [file join $activity_dir diagnostics annotated_after_power] after_power 1
puts "KWT_RTL_SAIF_POWER_COMPLETED: $activity_dir"
