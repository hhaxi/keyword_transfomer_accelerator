# Boot z100-kwt-25-jtag.elf first. Argument is a prepared verification directory.
set directory [file normalize [lindex $argv 0]]
set verify [expr {[file exists [file join $directory 000.expected]] ? 1 : 0}]
connect -url tcp:127.0.0.1:3121
targets -set -filter {name =~ "ARM Cortex-A9*#0"}
foreach input [lsort [glob -directory $directory *.input]] {
    set output [file rootname $input].reply
    dow -data $input 0x11200010
    mwr 0x1120000c $verify
    mwr 0x11200000 1
    set deadline [expr {[clock milliseconds] + 15000}]
    set reported 0
    while {1} {
        lassign [mrd -value 0x11200000 2] status layer
        if {$status == 2} {break}
        if {$layer > $reported && $layer <= 12} {
            puts "JTAG_LAYER $layer"
            flush stdout
            set reported $layer
        }
        if {[clock milliseconds] > $deadline} {
            error "JTAG inference timeout on $input, status [mrd 0x11200000 4]"
        }
        after 30
    }
    set count [lindex [mrd -value 0x11200008] 0]
    if {$count != ($verify ? 25402 : 58)} {
        error "Unexpected result length $count on $input, status [mrd 0x11200010 2]"
    }
    mrd -bin -file $output -size b 0x11200010 $count
    puts "JTAG_RESULT [file tail $output] $count bytes"
}
