# Source in a new Vivado session. Optional environment variable Z100_BUILD.
set source_dir [file normalize [file dirname [info script]]]
set repo [file normalize [file join $source_dir ../..]]
set build_dir [file join $repo output z100]
if {[info exists ::env(Z100_BUILD)]} {
    set build_dir [file normalize $::env(Z100_BUILD)]
}
set_param general.maxThreads 2
set full [expr {[info exists ::env(Z100_KWT)] && $::env(Z100_KWT) eq "1"}]
set variant [expr {$full ? "kwt" : "smoke"}]
set profile [expr {$full ? "ps_profile_sd.tcl" : "ps_profile.tcl"}]
if {$full && [info exists ::env(Z100_ETHERNET)] && $::env(Z100_ETHERNET) eq "1"} {
    set profile ps_profile_ethernet.tcl
}
source [file join $build_dir vendor $profile]
set frequency 25
if {$full && [info exists ::env(Z100_FCLK_MHZ)]} {
    set frequency $::env(Z100_FCLK_MHZ)
}
if {![string is integer -strict $frequency] || $frequency < 20 || $frequency > 100} {
    error "PL clock must be an integer between 20 and 100 MHz"
}
set project_dir [file join $build_dir $variant-$frequency-[clock seconds]]
create_project z100_$variant $project_dir -part xc7z035ffg900-2
add_files -norecurse [file join $source_dir z100_regs.v]
if {$full} {
    foreach name {z100_axi_mmio.sv z100_axi_ddr.sv z100_kwt.v z100_ffn.sv z100_ffn2.sv z100_ffn_rows.sv} {
        add_files -norecurse [file join $source_dir $name]
    }
    foreach name {kwt_encoder.sv kwt_vecmem32.sv kwt_udiv64.sv kwt_isqrt64.sv kwt_sram16.sv
        kwt_gelu.sv kwt_mac40.sv kwt_exp_negative.sv} {
        add_files -norecurse [file join $repo rtl $name]
    }
    add_files -norecurse [file join $repo integration kwt_dma_arbiter.sv]
    add_files -norecurse [file join $repo undergrad_ffn1 rtl kwt_ffn1_core.sv]
    add_files -norecurse [file join $repo undergrad_ffn1 rtl kwt_options.vh]
    set_property include_dirs [list [file join $repo undergrad_ffn1 rtl]] [current_fileset]
}
create_bd_design z100

set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps]
set_property -dict $z100_ps_config $ps
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_EN_CLK0_PORT {1} \
    CONFIG.PCW_EN_RST0_PORT {1} CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $frequency] $ps
if {$full} {
    set_property -dict [list CONFIG.PCW_USE_S_AXI_HP0 {1} CONFIG.PCW_S_AXI_HP0_DATA_WIDTH {32}] $ps
}
make_bd_intf_pins_external [get_bd_intf_pins ps/DDR]
make_bd_intf_pins_external [get_bd_intf_pins ps/FIXED_IO]

set bus [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_ctrl]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $bus
set reset [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 reset]
set_property CONFIG.C_EXT_RESET_HIGH {0} $reset
set locked [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 locked]
set_property CONFIG.CONST_VAL {1} $locked
create_bd_cell -type module -reference z100_regs regs

connect_bd_net [get_bd_pins ps/FCLK_CLK0] [get_bd_pins ps/M_AXI_GP0_ACLK] \
    [get_bd_pins axi_ctrl/aclk] [get_bd_pins reset/slowest_sync_clk] [get_bd_pins regs/aclk]
connect_bd_net [get_bd_pins ps/FCLK_RESET0_N] [get_bd_pins reset/ext_reset_in]
connect_bd_net [get_bd_pins locked/dout] [get_bd_pins reset/dcm_locked]
connect_bd_net [get_bd_pins reset/peripheral_aresetn] [get_bd_pins axi_ctrl/aresetn] [get_bd_pins regs/aresetn]
connect_bd_intf_net [get_bd_intf_pins ps/M_AXI_GP0] [get_bd_intf_pins axi_ctrl/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_ctrl/M00_AXI] [get_bd_intf_pins regs/s_axi]
assign_bd_address -offset 0x43C00000 -range 4K -target_address_space [get_bd_addr_spaces ps/Data] \
    [get_bd_addr_segs -of_objects [get_bd_intf_pins regs/s_axi]]
if {$full} {
    set_property CONFIG.NUM_MI {2} $bus
    create_bd_cell -type module -reference z100_kwt kwt
    if {[info exists ::env(Z100_FAST_PROJECTION)] && $::env(Z100_FAST_PROJECTION) eq "1"} {
        set_property CONFIG.FAST_PROJECTION {1} [get_bd_cells kwt]
    }
    if {[info exists ::env(Z100_FAST_ATTENTION)] && $::env(Z100_FAST_ATTENTION) eq "1"} {
        set_property CONFIG.FAST_ATTENTION {1} [get_bd_cells kwt]
    }
    if {[info exists ::env(Z100_WIDE_ENCODER)] && $::env(Z100_WIDE_ENCODER) eq "1"} {
        set_property CONFIG.FAST_PROJECTION {2} [get_bd_cells kwt]
        set_property CONFIG.FAST_ATTENTION {2} [get_bd_cells kwt]
    }
    if {[info exists ::env(Z100_FAST_FFN_ROWS)] && $::env(Z100_FAST_FFN_ROWS) eq "1"} {
        set_property CONFIG.FAST_FFN_ROWS {1} [get_bd_cells kwt]
        if {[info exists ::env(Z100_FAST_HANDOFF)] && $::env(Z100_FAST_HANDOFF) eq "1"} {
            set_property CONFIG.FAST_HANDOFF {1} [get_bd_cells kwt]
        }
        if {[info exists ::env(Z100_HELD_GELU)] && $::env(Z100_HELD_GELU) eq "1"} {
            set_property CONFIG.GELU_CYCLES {2} [get_bd_cells kwt]
            set gelu_xdc [file join $source_dir held_gelu.xdc]
            add_files -fileset constrs_1 -norecurse $gelu_xdc
            set_property USED_IN_SYNTHESIS false [get_files $gelu_xdc]
        }
    }
    set hp [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_ddr]
    set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $hp
    connect_bd_net [get_bd_pins ps/FCLK_CLK0] [get_bd_pins ps/S_AXI_HP0_ACLK] \
        [get_bd_pins kwt/aclk] [get_bd_pins axi_ddr/aclk]
    connect_bd_net [get_bd_pins reset/peripheral_aresetn] \
        [get_bd_pins kwt/aresetn] [get_bd_pins axi_ddr/aresetn]
    connect_bd_intf_net [get_bd_intf_pins axi_ctrl/M01_AXI] [get_bd_intf_pins kwt/s_axi]
    connect_bd_intf_net [get_bd_intf_pins kwt/m_axi] [get_bd_intf_pins axi_ddr/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins axi_ddr/M00_AXI] [get_bd_intf_pins ps/S_AXI_HP0]
    assign_bd_address -offset 0x43C10000 -range 64K -target_address_space [get_bd_addr_spaces ps/Data] \
        [get_bd_addr_segs -of_objects [get_bd_intf_pins kwt/s_axi]]
    assign_bd_address [get_bd_addr_segs ps/S_AXI_HP0/HP0_DDR_LOWOCM] \
        -target_address_space [get_bd_addr_spaces kwt/m_axi]
}
validate_bd_design
save_bd_design
set bd [get_files z100.bd]
set_property synth_checkpoint_mode None $bd
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property top z100_wrapper [current_fileset]
update_compile_order -fileset sources_1
