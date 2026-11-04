# Fresh synthesis + postcompile per-task activity. No activity-driven compile.
# Environment paths are supplied by tools/power_server.py; existing case scripts
# and previous DDC/vectorless reports are never changed.
set sh_continue_on_error false
if {[catch {
    foreach variable {KWT_POWER_CASE_ROOT KWT_POWER_RUN_DIR KWT_POWER_TASKS KWT_POWER_PYTHON} {
        if {![info exists env($variable)]} { error "missing $variable" }
    }
    set backend_root [file normalize $env(KWT_POWER_CASE_ROOT)]
    set run_dir [file normalize $env(KWT_POWER_RUN_DIR)]
    source [file join $backend_root script common.tcl]
    source [file join $backend_root config library_config.tcl]
    resolve_and_validate
    if {$synthesis_scope ne "soc"} { fail "activity capture requires SoC scope" }
    if {abs($clock_period_ns-6.666667)>0.000000001} { fail "capture requires 6.666667 ns clock" }
    foreach subdir {work report netlist sdc sdf svf generated log} {
        file mkdir [file join $run_dir $subdir]
    }
    # Bind actual resolved .db contents, without copying PDK data into package.
    proc power_hash {path} {
        global env
        return [string trim [exec $env(KWT_POWER_PYTHON) -c {import hashlib,sys; h=hashlib.sha256(); f=open(sys.argv[1],'rb'); [h.update(b) for b in iter(lambda:f.read(1048576),b'')]; print(h.hexdigest())} $path]]
    }
    set library_hashes {}
    set libraries [list $std_db]
    foreach name $required_sram_db_names { lappend libraries [set $name] }
    set library_receipt [open [file join $run_dir library_signatures.tsv] w]
    foreach path [lsort -unique $libraries] {
        set digest [power_hash $path]
        lappend library_hashes [list $path $digest]
        puts $library_receipt "$digest\t$path"
    }
    close $library_receipt
    cd $run_dir
    set rpt_path [file join $run_dir report]
    foreach command {saif_map read_saif report_saif reset_switching_activity} {
        if {![llength [info commands $command]]} { fail "Power Compiler command unavailable: $command" }
    }
    source [file join $backend_root script set_env.tcl]
    # Start tracking BEFORE analyze/elaborate; preserve through change_names.
    saif_map -start
    source [file join $backend_root script read_file.tcl]
    source [file join $backend_root script set_constraint.tcl]
    source [file join $backend_root script compile.tcl]
    source [file join $backend_root script write_file.tcl]
    # Save the mapping report for diagnosis. This is not an annotation pass.
    redirect -file [file join $rpt_path saif_mapping.rpt] { saif_map -report }
    source $env(KWT_POWER_TASKS)
    if {[llength $power_tasks]!=12} { fail "expected twelve task SAIF files" }
    set seen {}
    foreach task $power_tasks {
        lassign $task task_id saif
        if {![string is integer -strict $task_id] || $task_id<0 || $task_id>11 || $task_id in $seen} {
            fail "invalid/duplicate task id $task_id"
        }
        lappend seen $task_id
        require_file $saif "task SAIF"
        set task_dir [file join $rpt_path activity [format task_%02d $task_id]]
        file mkdir $task_dir
        reset_switching_activity
        redirect -file [file join $task_dir annotation.rpt] {
            set annotated [read_saif -auto_map_names -input $saif -instance_name tb_soc/dut -verbose]
        }
        if {![string is boolean -strict $annotated] || !$annotated} {
            fail "task $task_id read_saif failed; inspect annotation.rpt (no vectorless fallback)"
        }
        # Use bare report_saif for compatibility, preserving original coverage.
        # The installed tool may accept richer options; no fabricated percentage.
        redirect -file [file join $task_dir coverage.rpt] { report_saif }
        redirect -file [file join $task_dir power.rpt] { report_power -hierarchy }
        set marker [open [file join $task_dir annotated.ok] w]
        puts $marker "read_saif returned success; coverage requires human review"
        close $marker
    }
    foreach pair $library_hashes {
        lassign $pair path digest
        if {[power_hash $path] ne $digest} { fail "library changed during analysis: $path" }
    }
    set marker [open [file join $run_dir dc_complete.ok] w]
    puts $marker "12 postcompile RTL activity tasks; coverage and PPA acceptance not implied"
    close $marker
} message]} {
    puts stderr "KWT_POWER_FAILED: $message"
    if {[info exists errorInfo]} { puts stderr $errorInfo }
    exit 1
}
puts "KWT_POWER_COMPLETED: $run_dir"
exit 0
