# Configuration/path checks only: the dummy files are NOT usable technology DBs.
set backend_root [file normalize [file join [file dirname [info script]] ..]]
source [file join $backend_root script common.tcl]
source [file join $backend_root config library_config.tcl]
set stub [file join $backend_root tmp preflight-lib]
file mkdir $stub
foreach n {std.db ram128.db ram1024.db ram4096.db} {
    set f [open [file join $stub $n] w];puts $f "NOT A REAL LIBRARY";close $f
}
set std_db [file join $stub std.db]
set sram_db_128 [file join $stub ram128.db]
set sram_db_1024 [file join $stub ram1024.db]
set sram_db_4096 [file join $stub ram4096.db]
foreach scope {soc accelerator} {
    set synthesis_scope $scope
    resolve_and_validate
    set accelerator_bytes [expr {53248-15360*$opt_small_x-3072*$opt_small_bias}]
    set accelerator_macros [expr {20+2*$opt_small_x+2*$opt_small_bias}]
    if {$scope eq "soc" && ($top_design ne "kwt_ffn1_soc" || $expected_macro_total!=$accelerator_macros+80 || $expected_sram_bytes!=$accelerator_bytes+655360)} {error "Wrong SoC scope"}
    if {$scope eq "accelerator" && ($top_design ne "kwt_ffn1_top" || $expected_macro_total!=$accelerator_macros || $expected_sram_bytes!=$accelerator_bytes)} {error "Wrong accelerator scope"}
}
puts "FFN1_PREFLIGHT_STUB_PASS: config/path checks only; no DB contents or DC tested"
