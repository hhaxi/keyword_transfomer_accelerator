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
    if {[string match "z100-contest-*" $image]} {
        puts "Contest loader ID: [mrd -force 0x43d80004]"
        if {[lindex [mrd -force -value 0x43d80004] 0] != 0x4b575443} {
            error "Unexpected contest loader ID"
        }
        mwr -force 0x43d00000 0x55aa55aa
        mwr -force 0x43d7fffc 0xaa55aa55
        if {([lindex [mrd -force -value 0x43d00000] 0] & 0xffffffff) != 0x55aa55aa ||
            ([lindex [mrd -force -value 0x43d7fffc] 0] & 0xffffffff) != 0xaa55aa55} {
            error "Shared SRAM endpoint readback failed"
        }
        puts "CONTEST_SHARED_SRAM_ENDPOINTS_PASS"
        set rv_firmware [open [file join $build_dir encoder.bin] rb]
        set rv_bytes [read $rv_firmware]
        close $rv_firmware
        append rv_bytes [string repeat \x00 [expr {(4 - [string length $rv_bytes] % 4) % 4}]]
        binary scan $rv_bytes i* rv_words
        set rv_addr 0x43d00000
        foreach word $rv_words {
            mwr -force $rv_addr [format 0x%08x [expr {$word & 0xffffffff}]]
            incr rv_addr 4
        }
        if {[lindex [mrd -force -value 0x43d00000] 0] != ([lindex $rv_words 0] & 0xffffffff)} {
            error "E203 boot SRAM readback failed"
        }
        puts "E203 firmware loaded into 512 KiB shared SRAM"
    } else {
        puts "Encoder ID: [mrd -force 0x43c1200c]"
        puts "FFN ID: [mrd -force 0x43c1100c]"
    }
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
