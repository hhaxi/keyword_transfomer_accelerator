# Full encoder + existing FFN + E203 integration. Provisional I/O budgets.
create_clock -name core_clk -period 6.666667 [get_ports clk]
set_clock_uncertainty 0.100 [get_clocks core_clk]
set_clock_transition 0.050 [get_clocks core_clk]
set_input_delay -clock core_clk -max 1.000 [get_ports {rst_n boot_hold h_valid h_addr* h_wdata* h_read h_mask* h_rsp_ready}]
set_input_delay -clock core_clk -min 0.000 [get_ports {rst_n boot_hold h_valid h_addr* h_wdata* h_read h_mask* h_rsp_ready}]
set_output_delay -clock core_clk -max 1.000 [get_ports {h_ready h_rsp_valid h_rdata* h_err inspect_pc*}]
set_output_delay -clock core_clk -min 0.000 [get_ports {h_ready h_rsp_valid h_rdata* h_err inspect_pc*}]
# No timing exceptions; SRAM timing/power/area models must be supplied officially.
