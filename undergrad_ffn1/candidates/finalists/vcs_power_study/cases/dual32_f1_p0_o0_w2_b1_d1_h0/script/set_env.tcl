# -----------------------------------------------------------------------------
# Paths, logical libraries and tool settings. Standard cells are mapping targets;
# native SRAM macros are link references, never synthetic/target libraries.
# -----------------------------------------------------------------------------
remove_design -all
set_host_options -max_cores $max_cores
define_design_lib WORK -path [file join $run_dir work]
set_svf [file join $run_dir svf ${top_design}.svf]
write_sram_header [file join $run_dir generated sram_config.vh]

set sram_dbs {}
foreach name $required_sram_db_names { lappend sram_dbs [set $name] }
set sram_dbs [lsort -unique $sram_dbs]
set_app_var target_library [list $std_db]
set_app_var synthetic_library {}
if {$use_designware} { set_app_var synthetic_library [list dw_foundation.sldb] }
set_app_var link_library [concat [list *] $target_library $sram_dbs $synthetic_library]
set_app_var search_path [concat [list [file join $run_dir generated] \
    [file join $backend_root rtl] [file join $backend_root tech] \
    [file join $backend_root vendor e203 rtl e203 core]] $search_path]
set_app_var sh_output_log_file [file join $run_dir log dc_output.log]
set_app_var sh_command_log_file [file join $run_dir log dc_commands.log]
set_app_var verilogout_no_tri true
set_app_var verilogout_single_bit false

foreach db [concat [list $std_db] $sram_dbs] { read_db $db }
set settings [open [file join $rpt_path run_settings.txt] w]
foreach name {synthesis_scope top_design backend_root std_db sram_root sram_corner sram_db_128 sram_db_1024 sram_db_4096 sram_ema sram_emaw dma_burst host_burst clock_period_ns clock_setup_uncertainty_ns clock_hold_uncertainty_ns std_operating_condition wire_load_model io_input_max_ns io_input_min_ns io_output_max_ns io_output_min_ns shared_read_max_ns shared_read_min_ns shared_setup_ns shared_hold_ns output_load_pf} {
    puts $settings "$name = [set $name]"
}
puts $settings "Scope=$synthesis_scope; SoC includes E203 + accelerator/interfaces + shared SRAM + ITCM/DTCM."
puts $settings "SoC is the project reference integration; official fixed peripheral platform is not supplied."
puts $settings "Interface budgets are provisional; no activity-based power data loaded."
foreach name {opt_itcm opt_host_continuous opt_small_x opt_small_bias} { puts $settings "$name = [set $name]" }
close $settings
foreach_in_collection library [get_libs *] {
    set library_name [get_object_name $library]
    # Keep library report filenames portable even if the library name has '/'.
    set safe_name [string map {/ _ : _} $library_name]
    redirect -file [file join $rpt_path library_${safe_name}.rpt] { report_lib $library_name }
}

# Validate actual .db macro interfaces, including all bits of each bus.
foreach spec $expected_macros {
    lassign $spec macro count
    set aw [dict get {RAMSP128X16 7 RAMSP1024X16 10 RAMSP4096X16 12} $macro]
    set cells [get_lib_cells -quiet */$macro]
    if {[sizeof_collection $cells]!=1} { fail "expected one linked library cell named $macro" }
    set cell [get_object_name $cells]
    set actual_pins {}
    foreach_in_collection pin [get_lib_pins -quiet $cell/*] {
        lappend actual_pins [file tail [get_object_name $pin]]
    }
    foreach pin {CLK CEN GWEN RET1N} {
        if {[lsearch -exact $actual_pins $pin]<0} {
            fail "$macro lacks expected scalar pin $pin"
        }
    }
    foreach pair [list [list Q 16] [list D 16] [list WEN 16] [list A $aw] [list EMA 3] [list EMAW 2]] {
        lassign $pair bus width
        for {set bit 0} {$bit<$width} {incr bit} {
            # Compare names literally; avoid version-dependent bus glob rules.
            set pin_name [format {%s[%d]} $bus $bit]
            if {[lsearch -exact $actual_pins $pin_name]<0} {
                fail "$macro lacks expected pin $bus bit $bit; check native wrapper ports"
            }
        }
    }
    set_dont_use $cells
}
