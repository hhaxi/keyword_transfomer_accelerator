# Run in XSDB after extracting ps7_init.tcl from z100-smoke.xsa.
set build_dir [file normalize [file join [file dirname [info script]] ../../output/z100]]
if {[info exists ::env(Z100_BUILD)]} {
    set build_dir [file normalize $::env(Z100_BUILD)]
}
set image [expr {[llength $argv] >= 1 ? [lindex $argv 0] : "z100-smoke"}]
set firmware [expr {[llength $argv] >= 2 ? [lindex $argv 1] : $image}]
set model_source [expr {[llength $argv] >= 3 ? [lindex $argv 2] : "jtag"}]
connect -url tcp:127.0.0.1:3121
puts [targets]
targets -set -filter {name =~ "ARM Cortex-A9*#0"}
rst -system
after 1500
targets -set -filter {name =~ "ARM Cortex-A9*#0"}
catch {stop}
source [file join $build_dir $image ps7_init.tcl]
ps7_init
fpga -file [file join $build_dir $image.bit]
ps7_post_config
puts "AXI test address: [mrd -force 0x43c00000]"
set cycle [lindex [mrd -force -value 0x43c0000c] 0]
foreach word {0x55aa55aa 0xaa55aa55} {
    mwr -force 0x43c00008 $word
    if {[lindex [mrd -force -value 0x43c00008] 0] != $word} {
        error "PL scratch failed for $word"
    }
}
if {[lindex [mrd -force -value 0x43c0000c] 0] == $cycle} {error "PL cycle counter did not advance"}
puts "JTAG_PL_REGS_PASS"
if {$image ne "z100-smoke"} {
    puts "Encoder ID: [mrd -force 0x43c1200c]"
    puts "FFN ID: [mrd -force 0x43c1100c]"
    if {$model_source eq "sd"} {
        mwr 0x11000000 0
    } else {
        dow -data [file join $build_dir kwt.bin] 0x11000000
        puts "KWT parameters loaded into DDR"
    }
}
dow [file join $build_dir $firmware.elf]
puts [rrd pc]
con
puts "Cortex-A9 started"
