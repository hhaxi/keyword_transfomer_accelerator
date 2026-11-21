# Run the twelve FFN layer configurations against the repository's frozen vectors.
set source_dir [file dirname [file normalize [info script]]]
set repo [file normalize [file join $source_dir ../..]]
set build [file join $repo output z100 sim-ffn]
if {[info exists ::env(Z100_BUILD)]} {set build [file join $::env(Z100_BUILD) sim-ffn]}
file mkdir $build
set vector_source [file join $repo output encoder-vectors]
for {set i 0} {$i < 12} {incr i} {
    set layer [format layer_%02d $i]
    foreach {subdir names} [list $layer {w1 b1 w2 b2 config} \
        [file join task_00 $layer] {ffn_input ffn}] {
        set destination [file join $build vectors $subdir]
        file mkdir $destination
        foreach name $names {
            file copy -force [file join $vector_source $subdir $name.hex] $destination
        }
    }
    foreach name {ffn1 gelu} {
        file copy -force [file join [file dirname $build] ffn-traces $layer $name.hex] \
            [file join $build vectors task_00 $layer]
    }
}
set vivado_bin [file join $::env(XILINX_VIVADO) bin]
set tools [dict create]
foreach tool {xvlog xelab xsim} {
    set executable [file join $vivado_bin $tool]
    if {$::tcl_platform(platform) eq "windows"} {append executable .bat}
    dict set tools $tool $executable
}
set student [file join $repo rtl ffn1_row]
set sources [list [file join $student kwt_ffn1_core.sv]]
foreach name {kwt_sram16 kwt_gelu kwt_mac40} {
    lappend sources [file join $repo rtl $name.sv]
}
foreach name {z100_ffn2 z100_ffn tb_z100_ffn} {
    lappend sources [file join $source_dir $name.sv]
}
set prior [pwd]
cd $build
try {
    puts [exec [dict get $tools xvlog] -sv -i $student {*}$sources 2>@1]
    puts [exec [dict get $tools xelab] tb_z100_ffn -s z100_ffn_snapshot 2>@1]
    set output [exec [dict get $tools xsim] z100_ffn_snapshot --runall 2>@1]
    puts $output
    if {[regexp -all {Z100_FFN_PASS layer=} $output] != 12} {
        error "XSim did not pass all twelve FFN configurations"
    }
} finally {
    cd $prior
}
