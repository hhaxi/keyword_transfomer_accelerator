# Classic sg_shell. Keep the full SoC source list aligned with VCS and DC.
set root [file normalize [file join [file dirname [info script]] ..]]

proc readable_file {path} {
    set path [file normalize $path]
    if {![file isfile $path] || ![file readable $path]} { error "Cannot read $path" }
    return $path
}

if {[catch {
    set run_dir [file normalize $env(KWT_SG_RUN)]
    set mode $env(KWT_SG_MODE)
    set goal [dict get {lint lint/lint_rtl gating power/power_reduction_adv profile power/power_est_profiling} $mode]
    if {[info exists env(KWT_SPYGLASS_GOAL)] && $env(KWT_SPYGLASS_GOAL) ne ""} {
        set goal $env(KWT_SPYGLASS_GOAL)
    }
    set sources {}
    set fd [open [file join $root filelists soc.f] r]
    foreach line [split [read $fd] \n] {
        set line [string trim $line]
        if {$line ne "" && ![string match #* $line]} {
            lappend sources [readable_file [file join $root $line]]
        }
    }
    close $fd
    lappend sources [readable_file [file join $root tests sram_blackboxes.sv]]
    set sgdc [file join $root config spyglass.sgdc]
    if {[info exists env(KWT_SPYGLASS_SGDC)] && $env(KWT_SPYGLASS_SGDC) ne ""} {
        set sgdc $env(KWT_SPYGLASS_SGDC)
    }
    set sgdc [readable_file $sgdc]
    if {$mode ne "lint" && [info exists env(KWT_SPYGLASS_SAIF)] && $env(KWT_SPYGLASS_SAIF) ne ""} {
        if {[info exists env(KWT_SPYGLASS_SGDC)] && $env(KWT_SPYGLASS_SGDC) ne ""} {
            error "Supply either KWT_SPYGLASS_SAIF or an activity SGDC, not both"
        }
        set saif [readable_file $env(KWT_SPYGLASS_SAIF)]
        set activity_sgdc [file join $run_dir activity.sgdc]
        file copy $sgdc $activity_sgdc
        set fd [open $activity_sgdc a]
        puts $fd [list activity_data -format SAIF -file $saif -sim_topname tb_soc.dut]
        close $fd
        set sgdc $activity_sgdc
    }
    set liberty ""
    if {[info exists env(KWT_SPYGLASS_LIB)] && $env(KWT_SPYGLASS_LIB) ne ""} {
        set liberty [readable_file $env(KWT_SPYGLASS_LIB)]
    }
    set sglib ""
    if {[info exists env(KWT_SPYGLASS_SGLIB)] && $env(KWT_SPYGLASS_SGLIB) ne ""} {
        set sglib [readable_file $env(KWT_SPYGLASS_SGLIB)]
    }
    if {$mode ne "lint" && $liberty eq "" && $sglib eq ""} {
        error "Set KWT_SPYGLASS_LIB to standard-cell Liberty (.lib) or KWT_SPYGLASS_SGLIB to a compiled .sglib"
    }
    cd $run_dir
    new_project q128_ffn1 -projectwdir $run_dir
    set_option top kwt_ffn1_soc
    set_option enableSV yes
    set_option define {SYNTHESIS DISABLE_SV_ASSERTION}
    set_option incdir [list [file join $root rtl] [file join $root vendor e203 rtl e203 core] [file join $root tests]]
    read_file -type verilog {*}$sources
    read_file -type sgdc $sgdc
    if {$mode eq "lint"} {
        read_file -type waiver [readable_file [file join $root config spyglass_lint.swl]]
    }
    if {$liberty ne ""} {
        set_option enable_gateslib_autocompile yes
        read_file -type gateslib $liberty
    }
    if {$sglib ne ""} { read_file -type sglib $sglib }
    if {[info exists env(KWT_SPYGLASS_METHODOLOGY)] && $env(KWT_SPYGLASS_METHODOLOGY) ne ""} {
        current_methodology $env(KWT_SPYGLASS_METHODOLOGY)
    }
    puts "Q128_SPYGLASS_GOAL $goal top=kwt_ffn1_soc sgdc=$sgdc"
    current_goal $goal -top kwt_ffn1_soc
    write_report goal_setup > [file join $run_dir goal_setup.rpt]
    run_goal
    write_report moresimple > [file join $run_dir messages.rpt]
    save_project
    puts Q128_SPYGLASS_REPORT_WRITTEN
} message]} {
    puts stderr "Q128_SPYGLASS_FAILED: $message"
}
exit -force
