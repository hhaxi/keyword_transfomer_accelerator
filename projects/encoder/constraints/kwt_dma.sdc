# Complete DMA+compute engine boundary. Provisional official-platform I/O budget.
create_clock -name core_clk -period 6.666667 [get_ports clk]
set_clock_uncertainty 0.100 [get_clocks core_clk]
set_clock_transition 0.050 [get_clocks core_clk]
set_input_delay -clock core_clk -max 1.000 [get_ports {rst_n cmd_valid cmd_addr* cmd_read cmd_wdata* cmd_wmask* rsp_ready m_ready m_rsp_valid m_rdata* m_err}]
set_input_delay -clock core_clk -min 0.000 [get_ports {rst_n cmd_valid cmd_addr* cmd_read cmd_wdata* cmd_wmask* rsp_ready m_ready m_rsp_valid m_rdata* m_err}]
set_output_delay -clock core_clk -max 1.000 [get_ports {cmd_ready rsp_valid rsp_rdata* rsp_err m_valid m_addr* m_wdata* m_read m_mask* m_rsp_ready}]
set_output_delay -clock core_clk -min 0.000 [get_ports {cmd_ready rsp_valid rsp_rdata* rsp_err m_valid m_addr* m_wdata* m_read m_mask* m_rsp_ready}]
# No false-path or multicycle exceptions. SRAM timing/area/power require official models.
